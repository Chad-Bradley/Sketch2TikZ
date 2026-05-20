# -*- coding: utf-8 -*-
"""
Sketch2TikZ unified evaluation framework.

Pipeline per sample:
  1. Image -> vision model -> structured description
  2. Description -> code model -> TikZ code
  3. XeLaTeX compile -> PDF generation (compile pass/fail)
  4. Vision Critic -> quality score (1.0–5.0) + is_pass

Usage:
    python evaluate.py --difficulty easy --num_samples 10
    python evaluate.py --difficulty medium --num_samples 5
    python evaluate.py --difficulty hard --num_samples 5 --skip-critic
"""
import os
import sys
import json
import time
import argparse
import subprocess
import shutil
import tempfile
from pathlib import Path

# Unicode safety on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from src.llm_caller import image_to_text, text_to_text
from src.pipeline import safe_print, fix_for_xelatex, clean_tikz_output, compile_latex

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

# ==================== Prompts ====================

VISION_PROMPT = (
    "Please describe all geometric shapes, text labels, arrow connections, "
    "colors, and layout in this image in detail. Output a structured "
    "description suitable for generating complete TikZ code. "
    "Do not miss any details."
)

CODE_SYSTEM_PROMPT = (
    "You are a TikZ LaTeX expert. Generate correct, compilable TikZ code from an "
    "image description.\n\n"
    "CRITICAL RULES:\n"
    "1) Output ONLY raw LaTeX code. No markdown fences, no explanations.\n"
    "2) First line MUST be: \\documentclass[tikz, border=2pt]{standalone}\n"
    "3) Do NOT use \\usepackage{inputenc}, \\usepackage{fontenc}, or driver options like [pdftex].\n"
    "4) Do NOT use \\ensuremath in node font styles — use font=\\small or omit.\n"
    "5) Every tikzpicture node with text content must have valid LaTeX. Math inside $...$ or \\(...\\).\n"
    "6) When using \\usetikzlibrary, only load libraries you actually use.\n"
    "7) Use \\draw[->] for arrows, \\node[draw,circle] for circled nodes, \\node[draw,rectangle] for boxes.\n"
    "8) Coordinates: use relative positioning with above/below/left/right, or absolute (x,y) in cm.\n"
    "9) Colors: red, blue, green, orange, purple, gray, black, white.\n"
    "10) Keep code clean — no commented-out blocks, no unused packages.\n\n"
    "EXAMPLE of correct output format:\n"
    "\\documentclass[tikz, border=2pt]{standalone}\n"
    "\\usetikzlibrary{arrows.meta}\n"
    "\\begin{document}\n"
    "\\begin{tikzpicture}\n"
    "  \\node[draw, circle] (A) at (0,0) {A};\n"
    "  \\node[draw, circle] (B) at (2,1) {B};\n"
    "  \\draw[->] (A) -- (B);\n"
    "\\end{tikzpicture}\n"
    "\\end{document}\n"
)

def _find_gs() -> str:
    """Auto-discover Ghostscript executable."""
    # Check env var first
    env = os.getenv("GS_PATH")
    if env and os.path.exists(env):
        return env
    # Check PATH
    for name in ["gs", "gswin64c", "gswin64"]:
        found = shutil.which(name)
        if found:
            return found
    # Check common install locations
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\gs\*\bin\gs.exe"),
        r"C:\Program Files\gs\*\bin\gs.exe",
    ]
    # Also check conda base path (3 levels up from env python: base/envs/tikz_agent/python.exe)
    conda_base = os.getenv("CONDA_PREFIX")  # active env
    if conda_base:
        # env is base/envs/tikz_agent, conda root is two levels up
        root = os.path.dirname(os.path.dirname(conda_base))
        for sub in ["Library/bin/gs.exe", "Library/bin/gswin64c.exe"]:
            p = os.path.join(root, sub)
            if os.path.exists(p):
                return p
    for pattern in candidates:
        import glob
        hits = sorted(glob.glob(pattern), reverse=True)
        if hits:
            return hits[0]
    raise FileNotFoundError(
        "Ghostscript not found. Set GS_PATH in .env or install: conda install -c conda-forge ghostscript"
    )

GS_EXE = _find_gs()

CRITIC_PROMPT = (
    "You are evaluating how well a generated TikZ figure matches an original "
    "reference image. Image 1 is the ORIGINAL, Image 2 is the GENERATED output. "
    "Compare them on: layout structure, shapes, labels, relative positions, "
    "and overall visual similarity. "
    "Score from 1.0 (no resemblance) to 5.0 (nearly identical). "
    "Output ONLY a JSON object:\n"
    '  {"score": <float 1.0-5.0>, "is_pass": <true/false>}\n'
    "is_pass should be true if score >= 3.0."
)


def load_data(difficulty: str):
    """Load parquet data for a given difficulty level.

    Parquet files are named {difficulty}1.parquet (e.g. easy1.parquet).
    """
    parquet_name = f"{difficulty}1.parquet"
    parquet_path = DATA_DIR / difficulty / parquet_name
    if not parquet_path.exists():
        raise FileNotFoundError(
            f"Dataset not found: {parquet_path}\n"
            f"Run 'python scripts/setup_data.py' first to extract the data."
        )
    return pd.read_parquet(parquet_path)


def pdf_to_png(pdf_path: str, png_path: str) -> bool:
    """Convert first page of PDF to PNG using Ghostscript."""
    try:
        result = subprocess.run(
            [GS_EXE, "-dNOPAUSE", "-dBATCH", "-dSAFER",
             "-sDEVICE=png16m", "-r150", "-dFirstPage=1", "-dLastPage=1",
             f"-sOutputFile={png_path}", pdf_path],
            capture_output=True, text=True, timeout=30,
        )
        return os.path.exists(png_path) and os.path.getsize(png_path) > 0
    except Exception:
        return False


def critic_evaluate(original_img_path: str, output_pdf_path: str, workdir: str) -> dict:
    """Vision-based critic: render PDF to PNG, then feed BOTH original image
    and generated rendering to a vision model for comparison.

    Returns: {"score": float, "is_pass": bool}

    If PDF->PNG conversion fails, returns score=0.
    Raises RuntimeError if all vision API platforms fail.
    """
    render_path = os.path.join(workdir, "critic_render.png")
    if not pdf_to_png(output_pdf_path, render_path):
        safe_print("  [CRITIC] PDF->PNG conversion failed, score=0")
        return {"score": 0.0, "is_pass": False}

    # Build message with TWO images: original + generated rendering
    from src.llm_caller import _encode_image, _get_client, _VISION_MODELS, _VISION_PLATFORMS

    b64_orig = _encode_image(original_img_path)
    b64_render = _encode_image(render_path)

    errors = []
    for p in _VISION_PLATFORMS:
        try:
            model = _VISION_MODELS[p]
            client = _get_client(p)
            resp = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Image 1 (ORIGINAL reference):"},
                        {"type": "image_url", "image_url": {"url": b64_orig}},
                        {"type": "text", "text": "Image 2 (GENERATED output to evaluate):"},
                        {"type": "image_url", "image_url": {"url": b64_render}},
                        {"type": "text", "text": CRITIC_PROMPT},
                    ],
                }],
                temperature=0.0, max_tokens=256,
            )
            raw = resp.choices[0].message.content.strip()
            break
        except Exception as e:
            errors.append(f"[{p}] {type(e).__name__}: {str(e)[:120]}")
    else:
        raise RuntimeError(
            f"Critic: all platforms failed.\n" +
            "\n".join(errors) +
            "\nCheck your API keys in .env."
        )

    # Parse JSON
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    try:
        result = json.loads(raw)
        return {
            "score": float(result.get("score", 0)),
            "is_pass": bool(result.get("is_pass", False)),
        }
    except (json.JSONDecodeError, ValueError):
        safe_print(f"  [CRITIC] Failed to parse JSON, score=0. Raw: {raw[:120]}")
        return {"score": 0.0, "is_pass": False}


def run_sample(row, idx: int, workdir: str, skip_critic: bool = False) -> dict:
    """Run the full AI pipeline on a single data row.

    No fallback to Ground Truth — if any API call fails across all platforms,
    a RuntimeError is raised and the program exits.

    Returns a dict with all metrics for this sample.
    """
    result = {
        "idx": idx,
        "uri": row.get("uri", ""),
        "compile_ok": False,
        "vision_time": 0.0,
        "codegen_time": 0.0,
        "critic_score": 0.0,
        "critic_pass": False,
        "gen_code_len": 0,
    }

    # ---- Decode image ----
    img_bytes = row["image"]["bytes"]
    img_path = os.path.join(workdir, f"eval_input_{idx}.png")
    with open(img_path, "wb") as f:
        f.write(img_bytes)

    # ---- Step 1: Vision -> description ----
    t0 = time.time()
    description = image_to_text(
        image_input=img_path,
        prompt=VISION_PROMPT,
        platforms=["modelscope", "zhipu"],
        temperature=0.1,
        max_tokens=1024,
    )
    result["vision_time"] = round(time.time() - t0, 1)

    # ---- Step 2: Code model -> TikZ ----
    t0 = time.time()
    tikz_raw = text_to_text(
        messages=[
            {"role": "system", "content": CODE_SYSTEM_PROMPT},
            {"role": "user",
             "content": f"Generate TikZ code based on this description:\n{description}"},
        ],
        platforms=["modelscope", "siliconflow", "zhipu"],
        temperature=0.05,
        max_tokens=4096,
    )
    result["codegen_time"] = round(time.time() - t0, 1)

    tikz_code = clean_tikz_output(tikz_raw)
    tikz_code = fix_for_xelatex(tikz_code)
    result["gen_code_len"] = len(tikz_code)

    # ---- Step 3: Compile ----
    tex_path = os.path.join(workdir, f"eval_output_{idx}.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tikz_code)

    compile_ok, _ = compile_latex(tex_path, workdir)
    result["compile_ok"] = compile_ok

    # ---- Step 4: Critic (only if compile passed) ----
    if compile_ok and not skip_critic:
        pdf_path = tex_path.replace(".tex", ".pdf")
        critic = critic_evaluate(img_path, pdf_path, workdir)
        result["critic_score"] = critic["score"]
        result["critic_pass"] = critic["is_pass"]
    # If compile failed, score stays 0.0 — code that can't compile is worthless.

    return result


def print_dashboard(results: list, difficulty: str):
    """Print a statistics dashboard."""
    n = len(results)
    if n == 0:
        safe_print("No results to display.")
        return

    compile_pass = sum(1 for r in results if r["compile_ok"])
    critic_pass = sum(1 for r in results if r["critic_pass"])
    scores = [r["critic_score"] for r in results if r["critic_score"] > 0]
    avg_score = sum(scores) / len(scores) if scores else 0.0
    avg_vision = sum(r["vision_time"] for r in results) / n
    avg_codegen = sum(r["codegen_time"] for r in results) / n

    safe_print(f"\n{'=' * 55}")
    safe_print(f"  Evaluation Dashboard — {difficulty.upper()}")
    safe_print(f"{'=' * 55}")
    safe_print(f"  Samples tested:        {n}")
    safe_print(f"  Compile pass rate:     {compile_pass}/{n}  ({100*compile_pass/n:.1f}%)")
    safe_print(f"  Critic pass rate:      {critic_pass}/{n}  ({100*critic_pass/n:.1f}%)")
    safe_print(f"  Avg fidelity score:    {avg_score:.2f} / 5.0")
    safe_print(f"  Avg vision time:       {avg_vision:.1f}s")
    safe_print(f"  Avg codegen time:      {avg_codegen:.1f}s")
    safe_print(f"{'=' * 55}")


def main():
    parser = argparse.ArgumentParser(
        description="Sketch2TikZ unified evaluation benchmark"
    )
    parser.add_argument(
        "--difficulty", choices=["easy", "medium", "hard"], default="easy",
        help="Difficulty level to evaluate (default: easy)"
    )
    parser.add_argument(
        "--num_samples", type=int, default=10,
        help="Number of samples to test (default: 10)"
    )
    parser.add_argument(
        "--skip-critic", action="store_true",
        help="Skip the critic scoring step (faster, but no quality scores)"
    )
    args = parser.parse_args()

    safe_print(f"Loading dataset: {args.difficulty} (max {args.num_samples} samples)")
    df = load_data(args.difficulty)
    samples = df.head(args.num_samples)

    safe_print(f"  Available: {len(df)} rows, testing: {len(samples)}")

    workdir = "output"
    os.makedirs(workdir, exist_ok=True)
    results = []
    for i, (_, row) in enumerate(samples.iterrows()):
        safe_print(f"\n[{i+1}/{len(samples)}] Processing {row.get('uri', 'N/A')}")
        try:
            r = run_sample(row, i + 1, workdir, skip_critic=args.skip_critic)
            results.append(r)
            status = "OK" if r["compile_ok"] else "FAIL"
            safe_print(
                f"  -> Compile: {status} | Critic: {r['critic_score']:.1f} | "
                f"Vision: {r['vision_time']}s | CodeGen: {r['codegen_time']}s"
            )
        except RuntimeError as e:
            safe_print(f"\n{'=' * 55}")
            safe_print(f"FATAL: All API platforms exhausted on sample {i+1}.")
            safe_print(f"{'=' * 55}")
            safe_print(str(e))
            safe_print(f"{'=' * 55}")
            safe_print("Action: update your API keys in .env and re-run.")
            sys.exit(1)

    print_dashboard(results, args.difficulty)


if __name__ == "__main__":
    main()
