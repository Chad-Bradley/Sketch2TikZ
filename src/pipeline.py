"""
Sketch2TikZ compile pipeline — LaTeX compilation and preprocessing utilities.
"""
import os
import re
import sys
import subprocess

from dotenv import load_dotenv

load_dotenv(override=True)

XELATEX = os.getenv("XELATEX_PATH", "xelatex")

# ==================== Unicode-safe print ====================

def safe_print(*args, **kwargs):
    """Wrapper around print that survives Windows GBK encoding crashes."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", errors="replace").decode("ascii") for a in args), **kwargs)


# ==================== LaTeX preprocessing ====================

def fix_for_xelatex(code: str) -> str:
    """Preprocess LaTeX code for XeLaTeX compatibility.

    - Removes pdftex-specific driver options (e.g. \\usepackage[pdftex]{color})
    - Comments out packages known to be unavailable in TeX Live
    """
    # Strip [pdftex] driver option
    code = re.sub(r'\\usepackage\[pdftex\]', r'\\usepackage', code)
    code = re.sub(r'\\usepackage\[pdftex,\s*', r'\\usepackage[', code)
    code = re.sub(r',\s*pdftex\]', r']', code)

    # Packages known to be unavailable in TeX Live (non-free or removed)
    unavailable = ["MnSymbol", "mathrsfs"]
    for pkg in unavailable:
        code = code.replace(r"\usepackage{" + pkg + "}", r"% removed (not in TL)")
        code = code.replace("," + pkg, "")
        code = code.replace(pkg + ",", "")

    return code


def clean_tikz_output(raw: str) -> str:
    """Strip markdown code fences and whitespace from LLM output."""
    code = raw.strip()
    for prefix in ["```latex", "```tex", "```"]:
        if code.startswith(prefix):
            code = code[len(prefix):].strip()
    if code.endswith("```"):
        code = code[:-3].strip()
    return code


# ==================== Compilation ====================

def compile_latex(tex_path: str, workdir: str = ".") -> tuple:
    """Compile a .tex file with XeLaTeX.

    Success is determined by PDF existence (not exit code), since XeLaTeX
    may return non-zero on warnings but still produce valid output.

    Args:
        tex_path: Path to the .tex file.
        workdir: Working directory for compilation (for relative paths in .tex).

    Returns:
        (success: bool, log_summary: str)
    """
    tex_abs = os.path.abspath(tex_path)
    log_path = tex_abs.replace(".tex", ".log")
    pdf_path = tex_abs.replace(".tex", ".pdf")
    try:
        result = subprocess.run(
            [XELATEX, "-interaction=nonstopmode", tex_abs],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.path.dirname(tex_abs) or ".",
        )
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
            return True, "Compile OK"
        else:
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                    last_lines = lines[-50:] if len(lines) >= 50 else lines
                    log_tail = "".join(last_lines)
            else:
                log_tail = result.stderr[-2000:] if result.stderr else "(no log file)"
            return False, log_tail
    except subprocess.TimeoutExpired:
        return False, "Compile timeout (60s)"
    except FileNotFoundError:
        return False, f"XeLaTeX not found: {XELATEX}"
