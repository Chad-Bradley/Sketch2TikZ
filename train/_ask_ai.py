"""Ask default_choice to honestly judge a generated sample vs original."""
import json, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from train.llm_caller import _create, VISION_MODELS, _encode
from train.pipeline import generate

IMAGE = "train/data/easy/0016.png"
JUDGE_PROMPT = (
    "Compare the two images. Score 1.0-5.0. Be brutally honest. "
    "This is NOT a checklist of what elements exist. "
    "It is about whether the two images LOOK THE SAME visually. "
    "1.0=completely different, 2.0=recognizable but major differences, "
    "3.0=same diagram type but significant layout/shape differences, "
    "4.0=very similar minor differences only, 5.0=near-identical. "
    "CRITICAL: same element count != same appearance. "
    "If shapes differ in proportion or curvature, score <= 2.0. "
    "If placement differs noticeably, score <= 3.0. "
    'Output ONLY JSON: {"score": <float>, "is_pass": <bool>, "diagnosis": "..."}'
)

# Generate
print(f"Generating {IMAGE}...")
r = generate(IMAGE, 0, output_dir="output")
print(f"Compile: {r.compile_ok}")

if not r.compile_ok:
    print("FAILED")
    sys.exit(1)

# Render PDF to PNG
from train.pipeline import _pdf_to_png, _encode_img
render_path = "output/_ask_render.png"
_pdf_to_png(r.gen_pdf_path, render_path)

# Judge with default_choice
print(f"Judging with default_choice...")
b64_orig = _encode(IMAGE)
b64_gen = _encode(render_path)

raw = _create("default_choice", VISION_MODELS["default_choice"],
    [{"role": "user", "content": [
        {"type": "text", "text": "Image 1 (REFERENCE):"},
        {"type": "image_url", "image_url": {"url": b64_orig}},
        {"type": "text", "text": "Image 2 (GENERATED):"},
        {"type": "image_url", "image_url": {"url": b64_gen}},
        {"type": "text", "text": JUDGE_PROMPT},
    ]}],
    temperature=0.0, max_tokens=300)

raw = raw.strip()
if raw.startswith("```"):
    raw = raw.split("\n", 1)[-1].replace("```", "").strip()
j = json.loads(raw)
print(f"Score: {j['score']}  Pass: {j['is_pass']}")
print(f"Diagnosis: {j['diagnosis']}")
