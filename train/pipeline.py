"""
Pipeline: image -> vision desc -> code gen -> compile.
Develop using train/data/ only. This is the contract interface test calls.
"""
import os, re, subprocess, time

from dotenv import load_dotenv
load_dotenv(override=True)

from train.llm_caller import image_to_text, text_to_text
from train.contract import SampleResult

XELATEX = os.getenv("XELATEX_PATH", "xelatex")

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

CODE_PLATFORMS = ["deepseek", "modelscope", "siliconflow", "zhipu"]
VISION_PLATFORMS = ["modelscope", "zhipu"]


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


def generate(image_path: str, index: int) -> SampleResult:
    """Called by test runner. One image in, one result out."""
    t0 = time.time()

    desc = image_to_text(image_path, VISION_PROMPT,
                         platforms=VISION_PLATFORMS, temperature=0.1, max_tokens=1024)
    vision_time = round(time.time() - t0, 1)

    wd = os.path.dirname(os.path.abspath(image_path)) or "."
    tex_path = os.path.join(wd, f"gen_{index:04d}.tex")
    pdf_path = os.path.join(wd, f"gen_{index:04d}.pdf")

    msgs = [
        {"role": "system", "content": CODE_SYSTEM},
        {"role": "user", "content": f"Generate TikZ code for:\n{desc}"},
    ]

    t1 = time.time()
    tikz = ""
    for attempt in range(3):
        raw = text_to_text(msgs, platforms=CODE_PLATFORMS,
                           temperature=0.05 if attempt == 0 else 0.3, max_tokens=4096)
        tikz = _clean(raw)
        tikz = _fix(tikz)
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tikz)
        ok, errors = _compile(tex_path, pdf_path)
        if ok: break
        msgs.append({"role": "user", "content": f"Compile errors:\n{errors}\nFix and output complete code."})
    else:
        ok = False

    codegen_time = round(time.time() - t1, 1)

    return SampleResult(
        index=index, compile_ok=ok,
        compile_attempts=attempt + 1 if ok else 3,
        gen_pdf_path=pdf_path if ok else "",
        vision_time=vision_time, codegen_time=codegen_time,
        critic_score=0.0, critic_pass=False, diagnosis="",
    )
