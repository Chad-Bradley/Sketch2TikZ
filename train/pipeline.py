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
    "Output a TikZ-like specification that maps directly to draw commands. "
    "Use ONLY these notations. No natural-language narration.\n\n"
    "\\def\\R{3cm}                          %% define radius/dimensions\n"
    "\\coordinate (A) at (90:\\R);          %% node positions (polar or cartesian)\n"
    "\\draw[red, thick] (A) -- (B)          %% line segment, color, style\n"
    "  node[midway, above] {$x$};          %% label on segment\n"
    "\\draw[->, blue, thick] (A) arc (90:0:\\R)  %% arc with arrow\n"
    "  node[midway, right] {$f(x)$};       %% label on arc\n"
    "\\node[circle, draw, fill=black!50] at (O) {O};  %% labelled point\n"
    "\\definecolor{myRed}{HTML}{C2504B}     %% custom colors\n\n"
    "RULES:\n"
    "- Every formula in LaTeX: $\\sum$, $\\alpha$, $\\rightarrow$, etc.\n"
    "- Every segment: specify from/to, color, style (solid/dashed/dotted), arrow tip\n"
    "- Every label: specify which segment it's on, position (midway/above/right)\n"
    "- Every arc: specify angles (polar), radius, direction\n"
    "- Count elements. The code generator needs exact numbers.\n"
    "- Use polar coords for circular diagrams: (angle:radius)\n"
    "- Use cartesian for grid/bar/flowchart: (x,y)\n"
    "- For graphs: specify vertex symbols ($*$ vs filled dot vs circle). "
    "For self-loops: specify angular position (top/bottom/left/right) and relative size\n"
    "- For symmetric arc-cutout shapes: describe arc centers, radii, "
    "and the resulting central shape (e.g. '4 quarter-circles at corners create central star')\n"
    "- For 3D isometric views: state projection type and viewing angles "
    "(e.g. 'tdplot_main_coords theta=60 phi=120'), describe which axes are tilted\n"
    "- For fractal/recursive patterns: state depth/order, branch colors, "
    "and whether structure is symmetric or asymmetric\n"
    "- For divided circles/wedges: state dividing line angles from center, "
    "whether lines are double-stroked (gap), and relative wedge sizes"
)

CODE_SYSTEM = (
    "You are a TikZ LaTeX expert. Generate correct, compilable TikZ code.\n"
    "RULES:\n"
    "1) First line: \\documentclass[tikz, border=2pt]{standalone}\n"
    "2) Output ONLY raw LaTeX. No markdown, no explanation.\n"
    "3) No \\usepackage{inputenc}, \\usepackage{fontenc}, or [pdftex] driver.\n"
    "4) No \\ensuremath in node styles.\n"
    "5) Every formula in the description MUST appear verbatim in LaTeX math mode.\n"
    "6) \\draw[->, <color>] for colored arrows, \\node[draw,circle] for circled nodes, "
    "\\node[draw,rectangle] for boxes. Every color in the description must "
    "appear as an explicit draw/fill color.\n"
    "7) Every shape in the description MUST be rendered. Count them: if the "
    "description says N circles, your code must have N circles.\n"
    "8) ARC AND LINE LABELS: place labels via 'node[midway, above] {label}' directly "
    "on the \\draw command. NEVER place labels at separate unconnected coordinates.\n"
    "9) POLAR COORDINATES: for circular/radial diagrams, use (angle:radius) — "
    "e.g. (90:\\R), (180:3cm). Define \\def\\R{2cm} for radius, use \\coordinate.\n"
    "10) COLORS: use \\definecolor{name}{HTML}{hex} for precise colors. "
    "Match the description's colors exactly — don't substitute generic 'red' for 'myRed'.\n"
    "11) SELF-LOOPS: use `edge [in=<angle>,out=<angle>,loop]` with explicit angles "
    "matching the described position (top=70/110, right=0/30, bottom=270/290, left=150/180). "
    "Render vertex symbols literally: $*$ for asterisk, $\\bullet$ for filled dot.\n"
    "12) SYMMETRIC ARCS: for shapes built from quarter-circle cutouts, chain arc "
    "commands with `--` connectors (e.g. `arc (0:90:r) arc (-90:0:r) -- cycle`). "
    "Ensure arcs share endpoints at edge midpoints to form a closed region.\n"
    "13) Lines: -- (straight), .. controls .. (curved), -| or |- (right-angle).\n"
    "14) 3D PROJECTIONS: use \\usepackage{tikz-3dplot} + \\tdplotsetmaincoords{60}{120} "
    "+ [tdplot_main_coords]. Include dashed projection wireframe from vector tip "
    "to all three coordinate planes.\n"
    "15) FRACTAL/RECURSIVE: use \\usetikzlibrary{lindenmayersystems} + "
    "\\pgfdeclarelindenmayersystem with production rules, not manual drawing.\n"
    "16) DIVIDED CIRCLES: use `double, double distance=2mm` for parallel-line "
    "cut edges. Draw sectors with \\clip on the circle + radial lines at specified angles.\n"
    "17) Match the description's layout: row, column, grid, tree, radial, 3D, or fractal.\n"
    "18) No unused packages, no commented-out blocks.\n"
    "EXAMPLE:\n"
    "\\documentclass[tikz, border=2pt]{standalone}\n"
    "\\usetikzlibrary{arrows.meta}\n"
    "\\begin{document}\n"
    "\\begin{tikzpicture}\n"
    "  \\def\\R{2cm}\n"
    "  \\coordinate (A) at (90:\\R);\n"
    "  \\draw[red, thick] (A) arc (90:-30:\\R) node[midway, right] {$x$};\n"
    "\\end{tikzpicture}\n"
    "\\end{document}"
)

CRITIC_PROMPT = (
    "Compare the two images. Score 1.0-5.0. Be brutally honest.\n"
    "This is NOT a checklist of what elements exist.\n"
    "It is about whether the two images LOOK THE SAME visually.\n"
    "- 1.0: completely different, unrecognizable\n"
    "- 2.0: recognizable attempt but major structural or shape differences\n"
    "- 3.0: same type of diagram but significant layout/shape/color differences\n"
    "- 4.0: very similar, only minor shape/size/position differences\n"
    "- 5.0: near-identical, no discernible differences\n"
    "CRITICAL: identical element count does NOT mean identical appearance.\n"
    "If shapes differ in proportion, aspect ratio, or curvature, score <= 2.0.\n"
    "If placement differs noticeably from reference, score <= 3.0.\n"
    'Output ONLY JSON: {"score": <float>, "is_pass": <bool>, '
    '"diagnosis": "<specific visual differences>"}'
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
    critic_msgs = [{"role": "user", "content": [
        {"type": "text", "text": "Image 1 (REFERENCE):"},
        {"type": "image_url", "image_url": {"url": b64_orig}},
        {"type": "text", "text": "Image 2 (GENERATED):"},
        {"type": "image_url", "image_url": {"url": b64_gen}},
        {"type": "text", "text": CRITIC_PROMPT},
    ]}]

    # Try vision platforms in order via fallback
    raw = None
    for p in VISION_PLATFORMS:
        try:
            raw = _create(p, VISION_MODELS[p], critic_msgs, temperature=0.0, max_tokens=300)
            break
        except Exception:
            continue
    if raw is None:
        return {"score": 0.0, "is_pass": False, "diagnosis": "All critic platforms failed"}
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
                         platforms=VISION_PLATFORMS, temperature=0.0, max_tokens=1024)
    vision_time = round(time.time() - t_start, 1)

    base_name = os.path.splitext(os.path.basename(image_path))[0]
    tag = f"{base_name}_{index:04d}"
    tex_path = os.path.join(output_dir, f"gen_{tag}.tex")
    pdf_path = os.path.join(output_dir, f"gen_{tag}.pdf")

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
                           temperature=0.0, max_tokens=4096)
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
                                temperature=0.0, max_tokens=4096)
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
