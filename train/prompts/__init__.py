"""Load and manage per-difficulty prompts for the pipeline."""
import os

_PROMPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_prompts(difficulty: str = "easy") -> dict:
    """Load vision_prompt and code_system for a given difficulty.
    
    Falls back to 'easy' if the specific file doesn't exist.
    Returns {"vision_prompt": str, "code_system": str}
    """
    # Try the requested difficulty first, fall back to easy
    for name in [difficulty, "easy"]:
        vision_path = os.path.join(_PROMPT_DIR, f"{name}.vision.txt")
        code_path = os.path.join(_PROMPT_DIR, f"{name}.code.txt")
        
        if os.path.exists(vision_path) and os.path.exists(code_path):
            with open(vision_path, "r", encoding="utf-8") as f:
                vision_prompt = f.read()
            with open(code_path, "r", encoding="utf-8") as f:
                code_system = f.read()
            return {"vision_prompt": vision_prompt, "code_system": code_system}
    
    raise FileNotFoundError(
        f"No prompt files found for '{difficulty}' (tried {difficulty}, easy) "
        f"in {_PROMPT_DIR}"
    )
