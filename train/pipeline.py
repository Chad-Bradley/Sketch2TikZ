"""
Pipeline with dual feedback loops:
  N2↔N3: Compile self-heal (max 2 retries, .log errors fed back)
  N4↔N5: Visual self-heal (max 1 retry, vision critic diagnosis fed back)
"""
import os, re, subprocess, time, json, base64, shutil

from dotenv import load_dotenv
load_dotenv(override=True)

from train.llm_caller import image_to_text, text_to_text, _create
from train.llm_caller import CODE_MODELS, VISION_MODELS, VISION_PLATFORMS, CODE_PLATFORMS
from train.contract import SampleResult

XELATEX = os.getenv("XELATEX_PATH", "xelatex")

# ── Prompts ──────────────────────────────────────────
VISION_PROMPT = (
    "Describe all geometric shapes, text labels, arrows, colors, and layout "
    "in this diagram in detail. Include relative positions, sizes, and "
    "connections. Output a structured description suitable for generating TikZ."
)

CODE_SYSTEM = (
    "You are a TikZ LaTeX expert. Generate correct, compilable TikZ code.\n"
    "RULES:\n"
    "1) First line: \\documentclass[tikz, border=2pt]{standalone}\n"
    "2) Output ONLY raw LaTeX. No markdown, no explanation.\n"
    "3) No \\usepackage{inputenc}, \\usepackage{fontenc}, or [pdftex] driver.\n"
    "4) No \\ensuremath in node styles.\n"
    "5) All node text in valid LaTeX math ($...$ or \\(...\\)).\n"
    "6) \\draw[->] for arrows, \\node[draw,circle] for circled nodes.\n"
    "7) No unused packages, no commented-out blocks.\n"
    "EXAMPLE:\n"
    "\\documentclass[tikz, border=2pt]{standalone}\n"
    "\\begin{document}\n"
    "\\begin{tikzpicture}\n"
    "  \\node[draw, circle] (A) at (0,0) {A};\n"
    "  \\node[draw, circle] (B) at (2,1) {B};\n"
    "  \\draw[->] (A) -- (B);\n"
    "\\end{tikzpicture}\n"
    "\\end{document}"
)

CRITIC_PROMPT = (
    "Compare these two images. Image 1 is the REFERENCE, Image 2 is the GENERATED output. "
    "Output ONLY a JSON object:\n"
    '{"score": <float 1.0-5.0>, "is_pass": <true/false>, '
    '"diagnosis": "<specific: what shapes are wrong, missing, misplaced, wrong color/size>"}\n'
    "is_pass = score >= 3.0. Be strict — if key elements are missing, score <= 1.0."
)

# ── Platform priority (imported from llm_caller) ──────

# ── Helpers ──────────────────────────────────────────
def _fix(code: str) -> str:
    code = re.sub(r'\\usepackage\[pdftex\]', r'\\usepackage', code)
    code = re.sub(r'\\usepackage\[pdftex,\s*', r'\\usepackage[', code)
    code = re.sub(r',\s*pdftex\]', r']', code)
    for pkg in ["MnSymbol", "mathrsfs"]:
        code = code.replace(r"\usepackage{" + pkg + "}", r"% removed")
        code = code.replace("," + pkg, "").replace(pkg + ",", "")
    return code


def _clean(raw: str) -> str:
    c = raw.strip()
    for p in ["```latex", "```tex", "```tikz", "```"]:
        if c.startswith(p): c = c[len(p):].strip()
    if c.endswith("```"): c = c[:-3].strip()
    return c


def _compile(tex_path: str, pdf_path: str) -> tuple:
    """Returns (ok: bool, errors: str)"""
    tex_abs = os.path.abspath(tex_path)
    log_abs = tex_abs.replace(".tex", ".log")
    try:
        subprocess.run([XELATEX, "-interaction=nonstopmode", tex_abs],
                       capture_output=True, text=True, timeout=60,
                       cwd=os.path.dirname(tex_abs) or ".")
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
            return True, ""
        if os.path.exists(log_abs):
            with open(log_abs, "r", encoding="utf-8", errors="replace") as f:
                lines = [l.strip() for l in f if l.startswith("! ")]
                return False, "\n".join(lines[-10:])
        return False, "(no log)"
    except subprocess.TimeoutExpired:
        return False, "Compile timeout"
    except FileNotFoundError:
        return False, f"XeLaTeX not found: {XELATEX}"


def _gs() -> str:
    for name in ["gs", "gswin64c", "gswin64"]:
        f = shutil.which(name)
        if f: return f
    root = os.path.dirname(os.path.dirname(os.getenv("CONDA_PREFIX", "")))
    for sub in ["Library/bin/gs.exe", "Library/bin/gswin64c.exe"]:
        p = os.path.join(root, sub)
        if os.path.exists(p): return p
    raise FileNotFoundError("Ghostscript not found")


def _pdf_to_png(pdf_path: str, png_path: str) -> bool:
    try:
        subprocess.run([_gs(), "-dNOPAUSE", "-dBATCH", "-dSAFER",
                        "-sDEVICE=png16m", "-r150", "-dFirstPage=1", "-dLastPage=1",
                        f"-sOutputFile={png_path}", pdf_path],
                       capture_output=True, text=True, timeout=30)
        return os.path.exists(png_path) and os.path.getsize(png_path) > 0
    except Exception:
        return False


def _encode_img(path: str) -> str:
    with open(path, "rb") as f: data = base64.b64encode(f.read()).decode("utf-8")
    ext = os.path.splitext(path)[1].lower()
    return f"data:{'image/png' if ext=='.png' else 'image/jpeg'};base64,{data}"


def _internal_critic(original_path: str, pdf_path: str, output_dir: str) -> dict:
    """Internal visual critic for feedback loop (not the sealed judge)."""
    png_path = os.path.join(output_dir, "critic_internal.png")
    if not _pdf_to_png(pdf_path, png_path):
        return {"score": 0.0, "is_pass": False, "diagnosis": "PDF render failed"}
    b64_orig = _encode_img(original_path)
    b64_gen = _encode_img(png_path)
    critic_platform = VISION_PLATFORMS[0]  # first available vision platform
    critic_model = VISION_MODELS[critic_platform]
    raw = _create(
        critic_platform, critic_model,
        [{"role": "user", "content": [
            {"type": "text", "text": "Image 1 (REFERENCE):"},
            {"type": "image_url", "image_url": {"url": b64_orig}},
            {"type": "text", "text": "Image 2 (GENERATED):"},
            {"type": "image_url", "image_url": {"url": b64_gen}},
            {"type": "text", "text": CRITIC_PROMPT},
        ]}],
        temperature=0.0, max_tokens=300,
    )
    raw = raw.strip()
    if raw.startswith("```"): raw = raw.split("\n", 1)[-1].replace("```", "").strip()
    try:
        j = json.loads(raw)
        return {"score": float(j.get("score", 0)), "is_pass": bool(j.get("is_pass", False)),
                "diagnosis": str(j.get("diagnosis", ""))}
    except (json.JSONDecodeError, ValueError):
        return {"score": 0.0, "is_pass": False, "diagnosis": f"Critic parse failed: {raw[:100]}"}


# ── Main pipeline ────────────────────────────────────
def generate(image_path: str, index: int, output_dir: str = "output") -> SampleResult:
    t_start = time.time()
    os.makedirs(output_dir, exist_ok=True)

    # N1: Vision description
    desc = image_to_text(image_path, VISION_PROMPT,
                         platforms=VISION_PLATFORMS, temperature=0.1, max_tokens=1024)
    vision_time = round(time.time() - t_start, 1)

    tex_path = os.path.join(output_dir, f"gen_{index:04d}.tex")
    pdf_path = os.path.join(output_dir, f"gen_{index:04d}.pdf")

    msgs = [
        {"role": "system", "content": CODE_SYSTEM},
        {"role": "user", "content": f"Generate TikZ code for:\n{desc}"},
    ]

    t_code = time.time()
    compile_ok = False
    compile_attempts = 0
    critic_first_score = 0.0
    critic_final_score = 0.0
    diagnosis = ""
    tikz = ""

    # ── N2↔N3 Compile self-heal loop (max 3 total attempts) ──
    for attempt in range(3):
        compile_attempts = attempt + 1
        raw = text_to_text(msgs, platforms=CODE_PLATFORMS,
                           temperature=0.05 if attempt == 0 else 0.3, max_tokens=4096)
        tikz = _clean(raw)
        tikz = _fix(tikz)
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tikz)
        ok, errors = _compile(tex_path, pdf_path)
        if ok:
            compile_ok = True
            break
        msgs.append({"role": "user",
                     "content": f"Compile errors:\n{errors}\nFix and output complete code."})
    else:
        compile_ok = False

    codegen_time = round(time.time() - t_code, 1)

    # ── N4↔N5 Visual self-heal (1 pass) ──
    if compile_ok:
        c1 = _internal_critic(image_path, pdf_path, output_dir)
        critic_first_score = c1["score"]
        diagnosis = c1["diagnosis"]

        if not c1["is_pass"]:
            msgs.append({"role": "user",
                         "content": f"Visual review found these differences from the reference:\n"
                                    f"{diagnosis}\n\nMake ONLY minimal targeted fixes to address these "
                                    f"specific issues. Do NOT change anything that is already correct."})
            raw2 = text_to_text(msgs, platforms=CODE_PLATFORMS,
                                temperature=0.1, max_tokens=4096)
            tikz2 = _clean(raw2)
            tikz2 = _fix(tikz2)
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(tikz2)
            ok2, _ = _compile(tex_path, pdf_path)
            if ok2:
                tikz = tikz2
                c2 = _internal_critic(image_path, pdf_path, output_dir)
                critic_final_score = c2["score"]
                diagnosis = c2["diagnosis"]
            else:
                critic_final_score = 0.0
        else:
            critic_final_score = c1["score"]

    return SampleResult(
        index=index,
        compile_ok=compile_ok,
        compile_attempts=compile_attempts,
        gen_pdf_path=pdf_path if compile_ok else "",
        vision_time=vision_time,
        codegen_time=codegen_time,
        critic_score=critic_first_score,   # will be overwritten by test runner
        critic_pass=critic_first_score >= 3.0,
        diagnosis=diagnosis,
    )
