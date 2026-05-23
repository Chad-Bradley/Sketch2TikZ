"""
Sealed vision judge. temp=0, single model, fixed prompt.
Does NOT touch train data. Compares generated figure against original.
"""
import base64, json, os, subprocess, shutil
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

MODEL = "Qwen/Qwen3-VL-235B-A22B-Instruct"
BASE_URL = "https://api-inference.modelscope.cn/v1"

PROMPT = (
    "You are evaluating how well a generated figure matches a reference image. "
    "Image 1 is the REFERENCE (ground truth). Image 2 is the GENERATED output. "
    "Compare them on: shapes, line styles, colors, topology, connections, "
    "relative positions, spatial layout, and aspect ratio. "
    "CRITICAL: If shapes are severely stretched, squashed, or distorted vs "
    "the reference, assign score = 0.0. "
    "If key elements from the reference are entirely missing, score <= 1.0. "
    "If all elements present but positions/colors differ, score 1.0-2.0. "
    "If minor differences only, score 2.0-5.0. "
    "If there are any differences that are easily discernible to the naked eye—such as the absence of visually prominent lines—the score should not exceed 3.0."
	"Output ONLY a JSON object, no markdown, no explanation:\n"
    '{"score": <float 1.0-5.0>, "is_pass": <true/false>, '
    '"diagnosis": "<one sentence describing the main difference>"}'
)


def _find_gs() -> str:
    env = os.getenv("GS_PATH")
    if env and os.path.exists(env): return env
    for name in ["gs", "gswin64c", "gswin64"]:
        found = shutil.which(name)
        if found: return found
    conda_base = os.getenv("CONDA_PREFIX")
    if conda_base:
        root = os.path.dirname(os.path.dirname(conda_base))
        for sub in ["Library/bin/gs.exe", "Library/bin/gswin64c.exe"]:
            p = os.path.join(root, sub)
            if os.path.exists(p): return p
    raise FileNotFoundError("Ghostscript not found. Set GS_PATH in .env")


def _encode(path: str) -> str:
    with open(path, "rb") as f: data = base64.b64encode(f.read()).decode("utf-8")
    ext = os.path.splitext(path)[1].lower()
    return f"data:{'image/png' if ext=='.png' else 'image/jpeg'};base64,{data}"


def evaluate(original_path: str, generated_pdf_path: str, render_dir: str) -> dict:
    """Render PDF -> PNG, compare with vision model."""
    gs = _find_gs()
    render_path = os.path.join(render_dir, "critic_render.png")

    subprocess.run(
        [gs, "-dNOPAUSE", "-dBATCH", "-dSAFER",
         "-sDEVICE=png16m", "-r150", "-dFirstPage=1", "-dLastPage=1",
         f"-sOutputFile={render_path}", generated_pdf_path],
        capture_output=True, text=True, timeout=30,
    )
    if not os.path.exists(render_path) or os.path.getsize(render_path) == 0:
        return {"score": 0.0, "is_pass": False, "diagnosis": "PDF rendering failed"}

    # Resize images that exceed 2048 on any side (ModelScope limit)
    from PIL import Image as PILImage
    orig_path = original_path
    rend_path = render_path
    for label, p in [("orig", orig_path), ("rend", rend_path)]:
        im = PILImage.open(p)
        if max(im.size) > 2048:
            ratio = 2048 / max(im.size)
            new_size = (int(im.width * ratio), int(im.height * ratio))
            im = im.resize(new_size, PILImage.LANCZOS)
            new_p = os.path.join(os.path.dirname(p), f"resized_{label}.png")
            im.save(new_p)
            if label == "orig": orig_path = new_p
            else: rend_path = new_p

    b64_orig = _encode(orig_path)
    b64_gen = _encode(rend_path)

    key = os.getenv("MODELSCOPE_API_KEY")
    if not key: raise RuntimeError("MODELSCOPE_API_KEY not set")

    client = OpenAI(api_key=key, base_url=BASE_URL)
    resp = client.chat.completions.create(
        model=MODEL, temperature=0.0, max_tokens=256,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "Image 1 (REFERENCE):"},
            {"type": "image_url", "image_url": {"url": b64_orig}},
            {"type": "text", "text": "Image 2 (GENERATED):"},
            {"type": "image_url", "image_url": {"url": b64_gen}},
            {"type": "text", "text": PROMPT},
        ]}],
    )

    raw = resp.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"): raw = raw[:-3]
        raw = raw.strip()

    try:
        r = json.loads(raw)
        return {"score": float(r.get("score", 0)), "is_pass": bool(r.get("is_pass", False)),
                "diagnosis": str(r.get("diagnosis", ""))}
    except (json.JSONDecodeError, ValueError):
        return {"score": 0.0, "is_pass": False, "diagnosis": f"JSON parse failed: {raw[:100]}"}
