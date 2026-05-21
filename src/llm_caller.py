"""
Sketch2TikZ LLM caller — OpenAI-compatible multi-platform API wrapper.

Provides:
  - image_to_text(): image -> structured description (vision model)
  - text_to_text():  text -> text/code (LLM)

Both functions accept a list of platforms and try them in order.
If ALL platforms fail, a RuntimeError is raised with diagnostic info.
"""
import os
import base64
from typing import Optional, List, Dict

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

# ==================== Platform registry ====================

PLATFORM_BASE_URL = {
    "modelscope":   "https://api-inference.modelscope.cn/v1",
    "siliconflow":  "https://api.siliconflow.cn/v1",
    "zhipu":        "https://open.bigmodel.cn/api/paas/v4",
    "deepseek":     "https://api.deepseek.com",
}

PLATFORM_ENV_KEY = {
    "modelscope":   "MODELSCOPE_API_KEY",
    "siliconflow":  "SILICONFLOW_API_KEY",
    "zhipu":        "ZHIPU_API_KEY",
    "deepseek":     "DEEPSEEK_API_KEY",
}

# Per-platform default models
# Note: SiliconFlow does NOT provide vision models.
_VISION_MODELS = {
    "modelscope":   os.getenv("VISION_MODEL", "Qwen/Qwen3-VL-235B-A22B-Instruct"),
    "zhipu":        "glm-4v-flash",
}

_CODE_MODELS = {
    "deepseek":     os.getenv("CODE_MODEL", "deepseek-chat"),
    "modelscope":   "Qwen/Qwen3-Coder-480B-A35B-Instruct",
    "siliconflow":  "Qwen/Qwen3-8B",
    "zhipu":        "glm-4.7-flash",
}

# Platforms that support vision calls (image_url in messages)
_VISION_PLATFORMS = ["modelscope", "zhipu"]


def _get_client(platform: str, api_key: Optional[str] = None) -> OpenAI:
    """Create an OpenAI-compatible client for the given platform."""
    key = api_key or os.getenv(PLATFORM_ENV_KEY.get(platform, ""))
    if not key:
        raise ValueError(
            f"Missing API key for '{platform}'. "
            f"Set {PLATFORM_ENV_KEY[platform]} in .env"
        )
    base_url = PLATFORM_BASE_URL.get(platform)
    if not base_url:
        raise ValueError(f"Unsupported platform: {platform}")
    return OpenAI(api_key=key, base_url=base_url)


def _encode_image(image_path: str) -> str:
    """Encode a local image to base64 data URI."""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif",
    }
    mime = mime_map.get(ext, "image/png")
    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{data}"


# ==================== Fallback engine ====================

def _try_platforms(platforms: List[str], call_fn, call_name: str) -> str:
    """Try calling `call_fn(platform)` for each platform in order.
    If all fail, raise RuntimeError with a summary of every failure.
    """
    errors = []
    for p in platforms:
        try:
            return call_fn(p)
        except Exception as e:
            msg = f"[{p}] {type(e).__name__}: {e}"
            errors.append(msg)
            # Print warning so the user sees which platforms are dying
            try:
                print(f"  [WARN] {call_name} failed on {p}: {type(e).__name__}: {str(e)[:120]}")
            except Exception:
                pass

    raise RuntimeError(
        f"All {len(platforms)} platform(s) failed for '{call_name}'.\n"
        + "\n".join(f"  - {e}" for e in errors)
        + "\n\nPlease check your API keys in .env and ensure at least one is valid."
    )


# ==================== Public API ====================

def image_to_text(
    image_input: str,
    prompt: str = "Please describe this image in detail.",
    platforms: Optional[List[str]] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 1024,
) -> str:
    """Call a vision model to convert an image into a text description.

    Tries platforms in order. If all fail, raises RuntimeError.

    Args:
        image_input: Local file path or http/https URL.
        prompt: Text prompt about the image.
        platforms: List of platforms to try, e.g. ["modelscope", "zhipu"].
                   Default: ["modelscope", "zhipu", "siliconflow"].
        model: Override model name (otherwise uses platform default).
        api_key: Override API key.
        temperature: Sampling temperature.
        max_tokens: Maximum output tokens.

    Returns:
        The model-generated text description.

    Raises:
        RuntimeError: If all platforms fail.
    """
    if platforms is None:
        platforms = list(_VISION_PLATFORMS)

    if image_input.startswith(("http://", "https://")):
        image_url = image_input
    else:
        image_url = _encode_image(image_input)

    def _call(p):
        m = model or _VISION_MODELS.get(p, _VISION_MODELS["modelscope"])
        client = _get_client(p, api_key)
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": prompt},
            ],
        }]
        resp = client.chat.completions.create(
            model=m, messages=messages,
            temperature=temperature, max_tokens=max_tokens,
        )
        return resp.choices[0].message.content

    return _try_platforms(platforms, _call, "image_to_text")


def text_to_text(
    messages: List[Dict[str, str]],
    platforms: Optional[List[str]] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 8192,
) -> str:
    """Call a text model for text-to-text or code generation.

    Tries platforms in order. If all fail, raises RuntimeError.

    Args:
        messages: Standard chat message list.
        platforms: List of platforms to try, e.g. ["modelscope", "siliconflow"].
                   Default: ["modelscope", "siliconflow", "zhipu"].
        model: Override model name (otherwise uses platform default).
        api_key: Override API key.
        temperature: Sampling temperature.
        max_tokens: Maximum output tokens.

    Returns:
        The model-generated text.

    Raises:
        RuntimeError: If all platforms fail.
    """
    if platforms is None:
        platforms = ["deepseek", "modelscope", "siliconflow", "zhipu"]

    def _call(p):
        m = model or _CODE_MODELS.get(p, _CODE_MODELS["modelscope"])
        client = _get_client(p, api_key)
        resp = client.chat.completions.create(
            model=m, messages=messages,
            temperature=temperature, max_tokens=max_tokens,
        )
        return resp.choices[0].message.content

    return _try_platforms(platforms, _call, "text_to_text")
