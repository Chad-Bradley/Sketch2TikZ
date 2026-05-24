"""
Multi-platform LLM API wrapper with fallback and named-model callers.

Provides:
  - image_to_text():     image -> structured description (vision model, fallback)
  - text_to_text():      text -> text/code (LLM, fallback)
  - _create():           low-level SSE streaming call for a specific platform+model
  - call_vision_model(): call a specific vision model by name
  - call_text_model():   call a specific text model by name

Supported platforms: modelscope, siliconflow, zhipu, deepseek, nvidia, openrouter
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
    "nvidia":       "https://integrate.api.nvidia.com/v1",
    "openrouter":   "https://openrouter.ai/api/v1",
}

PLATFORM_ENV_KEY = {
    "modelscope":   "MODELSCOPE_API_KEY",
    "siliconflow":  "SILICONFLOW_API_KEY",
    "zhipu":        "ZHIPU_API_KEY",
    "deepseek":     "DEEPSEEK_API_KEY",
    "nvidia":       "NVIDIA_API_KEY",
    "openrouter":   "OPENROUTER_API_KEY",
}

# Per-platform default vision models
_VISION_MODELS = {
    "modelscope":   os.getenv("VISION_MODEL", "Qwen/Qwen3-VL-235B-A22B-Instruct"),
    "zhipu":        "glm-4v-flash",
    "nvidia":       "mistralai/mistral-large-3-675b-instruct-2512",
    "openrouter":   "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
}

# Per-platform default code/text models
_CODE_MODELS = {
    "deepseek":     os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    "modelscope":   os.getenv("MODELSCOPE_CODE_MODEL", os.getenv("CODE_MODEL", "Qwen/Qwen3-Coder-480B-A35B-Instruct")),
    "siliconflow":  os.getenv("SILICONFLOW_CODE_MODEL", os.getenv("CODE_MODEL", "Qwen/Qwen3-8B")),
    "zhipu":        os.getenv("ZHIPU_CODE_MODEL", "glm-4.7-flash"),
    "nvidia":       os.getenv("NVIDIA_CODE_MODEL", "qwen/qwen3-coder-480b-a35b-instruct"),
    "openrouter":   os.getenv("OPENROUTER_CODE_MODEL", "deepseek/deepseek-v4-flash:free"),
}

# ── Backward-compatible aliases (used by pipeline.py) ──
VISION_MODELS = _VISION_MODELS
CODE_MODELS = _CODE_MODELS
VISION_PLATFORMS = ["modelscope", "zhipu", "nvidia", "openrouter"]
CODE_PLATFORMS = ["deepseek", "modelscope", "siliconflow", "zhipu", "nvidia", "openrouter"]

# Extra known models beyond defaults
_EXTRA_MODELS: Dict[str, Dict[str, List[str]]] = {
    "nvidia": {
        "code": [
            "google/gemma-2-2b-it",
            "google/gemma-3n-e2b-it",
            "minimaxai/minimax-m2.7",
            "mistralai/mistral-nemotron",
            "google/gemma-3n-e4b-it",
        ],
        "vision": [],
    },
    "openrouter": {
        "code": [
            "openrouter/free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "poolside/laguna-m.1:free",
            "openai/gpt-oss-120b:free",
            "z-ai/glm-4.5-air:free",
            "arcee-ai/trinity-large-thinking:free",
            "poolside/laguna-xs.2:free",
            "baidu/cobuddy:free",
        ],
        "vision": [
            "google/gemma-4-31b-it:free",
            "nvidia/nemotron-nano-12b-v2-vl:free",
            "google/gemma-4-26b-a4b-it:free",
        ],
    },
}

_SPECIAL_BASE_URL: Dict[str, str] = {}


# ── Model index: model_name → [(platform, call_type), …] ──

def _build_model_index() -> Dict[str, List[tuple]]:
    index: Dict[str, List[tuple]] = {}

    def _add(platform: str, model: str, call_type: str) -> None:
        entry = (platform, call_type)
        existing = index.get(model)
        if existing is None:
            index[model] = [entry]
        elif entry not in existing:
            existing.append(entry)

    for p, m in _VISION_MODELS.items():
        _add(p, m, "vision")
    for p, m in _CODE_MODELS.items():
        _add(p, m, "code")
    for p, types in _EXTRA_MODELS.items():
        for call_type, models in types.items():
            for m in models:
                _add(p, m, call_type)
    return index

_MODEL_INDEX = _build_model_index()


def _resolve_model(model_name: str, call_type: Optional[str] = None) -> List[str]:
    entries = _MODEL_INDEX.get(model_name)
    if not entries:
        raise ValueError(
            f"Unknown model '{model_name}'. "
            f"Known models: {sorted(_MODEL_INDEX.keys())}"
        )
    if call_type:
        entries = [e for e in entries if e[1] == call_type]
    if not entries:
        raise ValueError(
            f"Model '{model_name}' is not registered for call_type='{call_type}'."
        )
    return [e[0] for e in entries]


def list_models(call_type: Optional[str] = None) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    if call_type in (None, "vision"):
        for p, m in _VISION_MODELS.items():
            result.setdefault(p, []).append(m)
        for p, types in _EXTRA_MODELS.items():
            for m in types.get("vision", []):
                if m not in result.get(p, []):
                    result.setdefault(p, []).append(m)
    if call_type in (None, "code"):
        for p, m in _CODE_MODELS.items():
            result.setdefault(p, []).append(m)
        for p, types in _EXTRA_MODELS.items():
            for m in types.get("code", []):
                if m not in result.get(p, []):
                    result.setdefault(p, []).append(m)
    return result


def iter_models(platform: Optional[str] = None) -> List[tuple]:
    result: List[tuple] = []
    seen: set = set()
    for p, m in _VISION_MODELS.items():
        if platform is None or p == platform:
            key = (p, m, "vision")
            if key not in seen:
                seen.add(key)
                result.append(key)
    for p, m in _CODE_MODELS.items():
        if platform is None or p == platform:
            key = (p, m, "code")
            if key not in seen:
                seen.add(key)
                result.append(key)
    for p, types in _EXTRA_MODELS.items():
        if platform is None or p == platform:
            for call_type, models in types.items():
                for m in models:
                    key = (p, m, call_type)
                    if key not in seen:
                        seen.add(key)
                        result.append(key)
    return result


# ==================== Client helpers ====================

def _get_client(platform: str, api_key: Optional[str] = None,
                timeout: Optional[float] = None) -> OpenAI:
    key = api_key or os.getenv(PLATFORM_ENV_KEY.get(platform, ""))
    if not key:
        raise ValueError(
            f"Missing API key for '{platform}'. "
            f"Set {PLATFORM_ENV_KEY[platform]} in .env"
        )
    kwargs = dict(api_key=key, base_url=PLATFORM_BASE_URL[platform])
    if timeout is not None:
        kwargs["timeout"] = timeout
    return OpenAI(**kwargs)


def _get_client_for_model(model_name: str, api_key: Optional[str] = None,
                          timeout: Optional[float] = None) -> OpenAI:
    platform = _resolve_model(model_name)[0]
    base_url = _SPECIAL_BASE_URL.get(model_name, PLATFORM_BASE_URL[platform])
    key = api_key or os.getenv(PLATFORM_ENV_KEY.get(platform, ""))
    if not key:
        raise ValueError(
            f"Missing API key for '{platform}'. "
            f"Set {PLATFORM_ENV_KEY[platform]} in .env"
        )
    kwargs = dict(api_key=key, base_url=base_url)
    if timeout is not None:
        kwargs["timeout"] = timeout
    return OpenAI(**kwargs)


def _encode_image(image_path: str) -> str:
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


# ==================== Low-level SSE streaming ====================

def _create(platform: str, model: str, messages: list,
            temperature: float, max_tokens: int) -> str:
    """Call API with SSE streaming for all platforms.

    Kept for backward compatibility — pipeline.py calls this directly.
    """
    client = _get_client(platform)
    stream = client.chat.completions.create(
        model=model, messages=messages,
        temperature=temperature, max_tokens=max_tokens, stream=True,
    )
    content = ""
    for chunk in stream:
        if chunk.choices[0].delta.content:
            content += chunk.choices[0].delta.content
    return content


# ==================== Fallback engine ====================

def _try_platforms(platforms: List[str], call_fn, call_name: str) -> str:
    errors = []
    for p in platforms:
        try:
            return call_fn(p)
        except Exception as e:
            msg = f"[{p}] {type(e).__name__}: {e}"
            errors.append(msg)
            try:
                print(f"  [WARN] {call_name} failed on {p}: {type(e).__name__}: {str(e)[:300]}")
            except Exception:
                pass
    raise RuntimeError(
        f"All {len(platforms)} platform(s) failed for '{call_name}'.\n"
        + "\n".join(f"  - {e}" for e in errors)
        + "\n\nPlease check your API keys in .env and ensure at least one is valid."
    )


# ==================== Named-model callers ====================

def call_vision_model(
    model_name: str,
    image_input: str,
    prompt: str = "Please describe this image in detail.",
    api_key: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    timeout: Optional[float] = None,
) -> str:
    """Call a specific vision model by name (no fallback)."""
    _resolve_model(model_name, "vision")

    if image_input.startswith(("http://", "https://")):
        image_url = image_input
    else:
        image_url = _encode_image(image_input)

    client = _get_client_for_model(model_name, api_key, timeout=timeout)
    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": prompt},
        ],
    }]
    resp = client.chat.completions.create(
        model=model_name, messages=messages,
        temperature=temperature, max_tokens=max_tokens,
    )
    result = resp.choices[0].message.content
    if result is None:
        finish = resp.choices[0].finish_reason
        msg = f"Model '{model_name}' returned empty content — finish_reason={finish}"
        if finish == "length":
            msg += ". Hint: increase max_tokens (current value may be too low for reasoning/thinking models)"
        raise RuntimeError(msg)
    return result


def call_text_model(
    model_name: str,
    messages: List[Dict[str, str]],
    api_key: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 8192,
    timeout: Optional[float] = None,
) -> str:
    """Call a specific text/code model by name (no fallback)."""
    _resolve_model(model_name, "code")

    client = _get_client_for_model(model_name, api_key, timeout=timeout)
    resp = client.chat.completions.create(
        model=model_name, messages=messages,
        temperature=temperature, max_tokens=max_tokens,
    )
    result = resp.choices[0].message.content
    if result is None:
        finish = resp.choices[0].finish_reason
        msg = f"Model '{model_name}' returned empty content — finish_reason={finish}"
        if finish == "length":
            msg += ". Hint: increase max_tokens (current value may be too low for reasoning/thinking models)"
        raise RuntimeError(msg)
    return result


# ==================== Fallback callers ====================

def image_to_text(
    image_input: str,
    prompt: str = "Please describe this image in detail.",
    platforms: Optional[List[str]] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    timeout: Optional[float] = None,
) -> str:
    """Call a vision model to convert an image into a text description.

    Tries platforms in order. If all fail, raises RuntimeError.

    Args:
        image_input: Local file path or http/https URL.
        prompt: Text prompt about the image.
        platforms: List of platforms to try. Default: all registered vision platforms.
        model: Override model name. When given, only platforms hosting this model
               are tried. When None, each platform's default vision model is used.
    """
    if image_input.startswith(("http://", "https://")):
        image_url = image_input
    else:
        image_url = _encode_image(image_input)

    if model is not None:
        resolved = [p for p in _resolve_model(model, "vision")
                    if p in VISION_PLATFORMS]
        if not resolved:
            raise ValueError(
                f"Vision model '{model}' has no vision-capable platforms."
            )
        target_platforms = resolved
    elif platforms is not None:
        target_platforms = platforms
    else:
        target_platforms = list(VISION_PLATFORMS)

    def _call(p):
        m = model or _VISION_MODELS.get(p, _VISION_MODELS["modelscope"])
        client = _get_client(p, api_key, timeout=timeout)
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
        result = resp.choices[0].message.content
        if result is None:
            finish = resp.choices[0].finish_reason
            msg = f"Model '{m}' returned empty content — finish_reason={finish}"
            if finish == "length":
                msg += ". Hint: increase max_tokens (current value may be too low for reasoning/thinking models)"
            raise RuntimeError(msg)
        return result

    return _try_platforms(target_platforms, _call, "image_to_text")


def text_to_text(
    messages: List[Dict[str, str]],
    platforms: Optional[List[str]] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 8192,
    timeout: Optional[float] = None,
) -> str:
    """Call a text model for text-to-text or code generation.

    Tries platforms in order. If all fail, raises RuntimeError.

    Args:
        messages: Standard chat message list.
        platforms: List of platforms to try. Default: CODE_PLATFORMS.
        model: Override model name. When given, only platforms hosting this model
               are tried. When None, each platform's default code model is used.
    """
    if model is not None:
        resolved = _resolve_model(model, "code")
        target_platforms = resolved
    elif platforms is not None:
        target_platforms = platforms
    else:
        target_platforms = list(CODE_PLATFORMS)

    def _call(p):
        m = model or _CODE_MODELS.get(p, _CODE_MODELS["modelscope"])
        client = _get_client(p, api_key, timeout=timeout)
        resp = client.chat.completions.create(
            model=m, messages=messages,
            temperature=temperature, max_tokens=max_tokens,
        )
        result = resp.choices[0].message.content
        if result is None:
            finish = resp.choices[0].finish_reason
            msg = f"Model '{m}' returned empty content — finish_reason={finish}"
            if finish == "length":
                msg += ". Hint: increase max_tokens (current value may be too low for reasoning/thinking models)"
            raise RuntimeError(msg)
        return result

    return _try_platforms(target_platforms, _call, "text_to_text")
