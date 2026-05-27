"""
Multi-platform LLM API wrapper with fallback, named-model callers, and key rotation.

Provides:
  - image_to_text():     image -> structured description (vision model, fallback)
  - text_to_text():      text -> text/code (LLM, fallback)
  - _create():           low-level SSE streaming call for a specific platform+model
  - call_vision_model(): call a specific vision model by name
  - call_text_model():   call a specific text model by name

Supported platforms: modelscope, siliconflow, zhipu, deepseek, nvidia, openrouter, default_choice

Multi-key support:
  Set comma-separated keys in .env (e.g. NVIDIA_API_KEY=key1,key2)
  or use numbered suffixes (NVIDIA_API_KEY_1=..., NVIDIA_API_KEY_2=...).
  Rate-limited / quota-exhausted keys are automatically cooled down and rotated.
"""
import os
import time
import threading
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
    "default_choice":"default_url"  # Placeholder, replace with actual URL
}

PLATFORM_ENV_KEY = {
    "modelscope":   "MODELSCOPE_API_KEY",
    "siliconflow":  "SILICONFLOW_API_KEY",
    "zhipu":        "ZHIPU_API_KEY",
    "deepseek":     "DEEPSEEK_API_KEY",
    "nvidia":       "NVIDIA_API_KEY",
    "openrouter":   "OPENROUTER_API_KEY",
    "default_choice":"DEFAULT_CHOICE_API_KEY",
}

# Per-platform default vision models
_VISION_MODELS = {
    "modelscope":   os.getenv("VISION_MODEL", "Qwen/Qwen3-VL-235B-A22B-Instruct"),
    "zhipu":        "glm-4v-flash",
    "nvidia":       "mistralai/mistral-large-3-675b-instruct-2512",
    "openrouter":   "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "default_choice":os.getenv("DEFAULT_CHOICE_VISION_MODEL", "gpt-4o"),
}

# Per-platform default code/text models
_CODE_MODELS = {
    "deepseek":     os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    "modelscope":   os.getenv("MODELSCOPE_CODE_MODEL", os.getenv("CODE_MODEL", "Qwen/Qwen3-Coder-480B-A35B-Instruct")),
    "siliconflow":  os.getenv("SILICONFLOW_CODE_MODEL", os.getenv("CODE_MODEL", "Qwen/Qwen3-8B")),
    "zhipu":        os.getenv("ZHIPU_CODE_MODEL", "glm-4.7-flash"),
    "nvidia":       os.getenv("NVIDIA_CODE_MODEL", "qwen/qwen3-coder-480b-a35b-instruct"),
    "openrouter":   os.getenv("OPENROUTER_CODE_MODEL", "deepseek/deepseek-v4-flash:free"),
    "default_choice":os.getenv("DEFAULT_CHOICE_CODE_MODEL", "deepseek-v4-pro"),
}

# ── Backward-compatible aliases (used by pipeline.py) ──
VISION_MODELS = _VISION_MODELS
CODE_MODELS = _CODE_MODELS
VISION_PLATFORMS = ["modelscope", "zhipu", "nvidia", "openrouter", "default_choice"]
CODE_PLATFORMS = ["deepseek", "modelscope", "siliconflow", "zhipu", "nvidia", "openrouter", "default_choice"]

# Platforms whose API only supports SSE streaming
_STREAMING_ONLY = {"default_choice"}

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
    "default_choice": {
        "code": [
            "gpt-4o",
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-opus-4-6",
            "claude-opus-4-5",
            "claude-opus-4-1",
            "claude-sonnet-4",
            "claude-opus-4",
            "claude-3-7-sonnet-v2",
            "claude-3-5-sonnet-v2",
            "gpt-5-5",
            "gpt-5-4",
            "gpt-5-3",
            "gpt-5-1",
            "gpt-5",
            "gpt-5-online",
            "gpt-5-nano",
            "gpt-5-mini",
            "gpt-4o-mini",
            "gpt-o4-mini",
            "gpt-4-1-mini",
            "gpt-4-1-nano",
            "google-2.5-pro",
            "gemini-2.5-flash",
            "gemini-3-1-pro",
            "gemini-3-pro",
            "gemini-2-5-flash-image",
            "grok-4",
            "grok-3",
            "qwen-3-max",
            "deepseek-v3",
            "deepseek-r1",
            "gpt-o1",
            "gpt-o3",
            "gpt-o3-mini",
            "llama-3-3-70b-versatile",
            "deepinfra-kimi-k2",
            "qwen-qwq-32b",
        ],
        "vision": [
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-opus-4-6",
            "claude-opus-4-5",
            "claude-opus-4-1",
            "claude-sonnet-4",
            "claude-opus-4",
            "claude-3-7-sonnet-v2",
            "claude-3-5-sonnet-v2",
            "gpt-5-5",
            "gpt-5-4",
            "gpt-5-3",
            "gpt-5-1",
            "gpt-5",
            "gpt-5-online",
            "gpt-5-nano",
            "gpt-5-mini",
            "gpt-4o-mini",
            "gpt-o4-mini",
            "gpt-4-1-mini",
            "gpt-4-1-nano",
            "google-2.5-pro",
            "gemini-2.5-flash",
            "gemini-3-1-pro",
            "gemini-3-pro-image",
            "gemini-3-pro",
            "gemini-2-5-flash-image",
            "grok-4",
            "grok-3",
            "qwen-3-max",
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
    """Return (platform, model_name, call_type) tuples grouped by platform.

    Each platform's models appear together: defaults first (vision, then code),
    then extras. Within each group, insertion order is preserved.
    """
    grouped: Dict[str, List[tuple]] = {}
    platform_order: List[str] = []
    seen: set = set()

    def _add(p: str, m: str, ct: str) -> None:
        if platform is not None and p != platform:
            return
        key = (p, m, ct)
        if key not in seen:
            seen.add(key)
            if p not in grouped:
                grouped[p] = []
                platform_order.append(p)
            grouped[p].append(key)

    for p, m in _VISION_MODELS.items():
        _add(p, m, "vision")
    for p, m in _CODE_MODELS.items():
        _add(p, m, "code")
    for p, types in _EXTRA_MODELS.items():
        for call_type, models in types.items():
            for m in models:
                _add(p, m, call_type)

    result: List[tuple] = []
    for p in platform_order:
        result.extend(grouped[p])
    return result


# ==================== API Key Pool with rotation ====================

def _is_rate_limited(error: Exception) -> bool:
    """Detect rate-limit, quota, billing, or overload errors from any provider."""
    msg = str(error).lower()
    # HTTP status codes embedded in error message
    for code in ["429", "402"]:
        if any(pat.format(code) in msg for pat in [
            " {} ", "error code: {}", "status {}",
            "status_code: {}", "status_code={}",
            "http status: {}", "status={}",
        ]):
            return True
    # Known rate-limit / quota / billing keywords
    for pat in [
        "rate limit", "rate_limit", "ratelimit",
        "too many requests",
        "quota exceeded", "quota", "insufficient_quota",
        "billing", "insufficient_balance", "balance",
        "throttle", "throttled",
        "overloaded", "overload", "capacity",
        "limit exceeded", "exceeded limit",
        "try again later", "please retry",
        "server is busy", "busy",
    ]:
        if pat in msg:
            return True
    return False


class ApiKeyPool:
    """Thread-safe rotating pool of API keys with rate-limit cooldown.

    Reads keys from environment variables. Supports two formats:
      - Comma-separated:  NVIDIA_API_KEY=key1,key2,key3
      - Numbered suffix:  NVIDIA_API_KEY_1=key1, NVIDIA_API_KEY_2=key2
    """

    def __init__(self, platform: str):
        self.platform = platform
        self._lock = threading.Lock()
        self._cooldown_until: Dict[str, float] = {}
        self._index = 0

    def _read_keys(self) -> List[str]:
        """Read all keys for this platform from environment."""
        env_key = PLATFORM_ENV_KEY.get(self.platform, "")
        keys: List[str] = []

        raw = os.getenv(env_key, "")
        if raw:
            for k in raw.split(","):
                k = k.strip()
                if k:
                    keys.append(k)

        i = 1
        while True:
            extra = os.getenv(f"{env_key}_{i}", "")
            if not extra:
                break
            extra = extra.strip()
            if extra and extra not in keys:
                keys.append(extra)
            i += 1

        return keys

    def get_key(self) -> str:
        """Return the next available key, skipping those in cooldown.

        Raises RuntimeError if no keys are configured or all are cooling down.
        """
        with self._lock:
            keys = self._read_keys()
            if not keys:
                raise RuntimeError(
                    f"No API keys configured for '{self.platform}'. "
                    f"Set {PLATFORM_ENV_KEY[self.platform]} in .env "
                    f"(comma-separated for multiple keys)."
                )

            now = time.time()
            for offset in range(len(keys)):
                idx = (self._index + offset) % len(keys)
                key = keys[idx]
                if self._cooldown_until.get(key, 0) <= now:
                    self._index = (idx + 1) % len(keys)
                    return key

            earliest_key = min(keys, key=lambda k: self._cooldown_until.get(k, 0))
            wait = max(0, self._cooldown_until.get(earliest_key, 0) - now)
            raise RuntimeError(
                f"All {len(keys)} key(s) for '{self.platform}' are rate-limited. "
                f"Earliest recovery in ~{wait:.0f}s."
            )

    def cool_down(self, key: str, seconds: float = 30.0) -> None:
        """Put a key into cooldown after a rate-limit error."""
        with self._lock:
            self._cooldown_until[key] = time.time() + seconds

    def cool_down_long(self, key: str, seconds: float = 300.0) -> None:
        """Longer cooldown for quota-exhaustion errors."""
        self.cool_down(key, seconds)

    def key_count(self) -> int:
        """Return the total number of configured keys."""
        return len(self._read_keys())


# Global pool registry
_POOLS: Dict[str, ApiKeyPool] = {}
_POOLS_LOCK = threading.Lock()


def _get_pool(platform: str) -> ApiKeyPool:
    """Get or create the key pool for a platform."""
    with _POOLS_LOCK:
        if platform not in _POOLS:
            _POOLS[platform] = ApiKeyPool(platform)
        return _POOLS[platform]


# ==================== Client helpers ====================

def _get_client(platform: str, api_key: Optional[str] = None,
                timeout: Optional[float] = None) -> OpenAI:
    """Create an OpenAI client for *platform*.

    When *api_key* is None, a key is drawn from the platform's rotating pool.
    """
    if api_key is not None:
        key = api_key
    else:
        key = _get_pool(platform).get_key()

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
    """Create an OpenAI client for a specific model."""
    platform = _resolve_model(model_name)[0]
    base_url = _SPECIAL_BASE_URL.get(model_name, PLATFORM_BASE_URL[platform])

    if api_key is not None:
        key = api_key
    else:
        key = _get_pool(platform).get_key()

    if not key:
        raise ValueError(
            f"Missing API key for '{platform}'. "
            f"Set {PLATFORM_ENV_KEY[platform]} in .env"
        )
    kwargs = dict(api_key=key, base_url=base_url)
    if timeout is not None:
        kwargs["timeout"] = timeout
    return OpenAI(**kwargs)


def _mark_key_rate_limited(platform: str, client: OpenAI, long_cooldown: bool = False) -> None:
    """Mark the key embedded in *client* as rate-limited."""
    key = getattr(client, "api_key", None)
    if key is None:
        return
    pool = _get_pool(platform)
    if long_cooldown:
        pool.cool_down_long(key)
    else:
        pool.cool_down(key)


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


# ==================== Unified chat completion ====================

def _chat_completion(client, model: str, messages: list,
                     temperature: float, max_tokens: int,
                     platform: str = "") -> str:
    """Call chat completion, using streaming for platforms that require it.

    Some servers (default_choice) always return SSE chunks even when stream=False,
    which breaks the standard OpenAI client. This wrapper uses streaming
    transparently for those platforms.
    """
    if platform in _STREAMING_ONLY:
        stream = client.chat.completions.create(
            model=model, messages=messages,
            temperature=temperature, max_tokens=max_tokens, stream=True,
        )
        chunks = []
        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                chunks.append(content)
        result = "".join(chunks)
        if not result:
            raise RuntimeError(f"Model '{model}' returned empty streaming content")
        return result

    resp = client.chat.completions.create(
        model=model, messages=messages,
        temperature=temperature, max_tokens=max_tokens,
    )
    result = resp.choices[0].message.content
    if result is None:
        finish = resp.choices[0].finish_reason
        msg = f"Model '{model}' returned empty content — finish_reason={finish}"
        if finish == "length":
            msg += ". Hint: increase max_tokens (current value may be too low for reasoning/thinking models)"
        raise RuntimeError(msg)
    return result


# ==================== Low-level SSE streaming ====================

def _create(platform: str, model: str, messages: list,
            temperature: float, max_tokens: int) -> str:
    """Call API with SSE streaming for all platforms.

    Kept for backward compatibility — pipeline.py calls this directly.
    Keys are automatically rotated on rate-limit errors.
    """
    pool = _get_pool(platform)
    key_count = max(pool.key_count(), 1)

    for attempt in range(key_count):
        client = _get_client(platform)
        try:
            stream = client.chat.completions.create(
                model=model, messages=messages,
                temperature=temperature, max_tokens=max_tokens, stream=True,
            )
            content = ""
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    content += chunk.choices[0].delta.content
            return content
        except Exception as e:
            if _is_rate_limited(e) and attempt + 1 < key_count:
                _mark_key_rate_limited(platform, client)
                try:
                    print(f"  [WARN] Key rotation on {platform}: {type(e).__name__}: {str(e)[:200]}")
                except Exception:
                    pass
                continue
            raise


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
    """Call a specific vision model by name.

    When *api_key* is not provided, keys are rotated automatically on rate-limit errors.
    """
    platform = _resolve_model(model_name, "vision")[0]

    if image_input.startswith(("http://", "https://")):
        image_url = image_input
    else:
        image_url = _encode_image(image_input)

    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": prompt},
        ],
    }]

    # When the caller provides an explicit key, don't rotate
    if api_key is not None:
        client = _get_client_for_model(model_name, api_key, timeout=timeout)
        return _chat_completion(
            client, model_name, messages,
            temperature=temperature, max_tokens=max_tokens,
            platform=platform,
        )

    # Key rotation loop
    pool = _get_pool(platform)
    key_count = max(pool.key_count(), 1)
    for attempt in range(key_count):
        client = _get_client_for_model(model_name, timeout=timeout)
        try:
            return _chat_completion(
                client, model_name, messages,
                temperature=temperature, max_tokens=max_tokens,
                platform=platform,
            )
        except Exception as e:
            if _is_rate_limited(e) and attempt + 1 < key_count:
                _mark_key_rate_limited(platform, client, long_cooldown=True)
                try:
                    print(f"  [WARN] Key rotation on {platform}: {type(e).__name__}: {str(e)[:200]}")
                except Exception:
                    pass
                continue
            raise


def call_text_model(
    model_name: str,
    messages: List[Dict[str, str]],
    api_key: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 8192,
    timeout: Optional[float] = None,
) -> str:
    """Call a specific text/code model by name.

    When *api_key* is not provided, keys are rotated automatically on rate-limit errors.
    """
    platform = _resolve_model(model_name, "code")[0]

    # When the caller provides an explicit key, don't rotate
    if api_key is not None:
        client = _get_client_for_model(model_name, api_key, timeout=timeout)
        return _chat_completion(
            client, model_name, messages,
            temperature=temperature, max_tokens=max_tokens,
            platform=platform,
        )

    # Key rotation loop
    pool = _get_pool(platform)
    key_count = max(pool.key_count(), 1)
    for attempt in range(key_count):
        client = _get_client_for_model(model_name, timeout=timeout)
        try:
            return _chat_completion(
                client, model_name, messages,
                temperature=temperature, max_tokens=max_tokens,
                platform=platform,
            )
        except Exception as e:
            if _is_rate_limited(e) and attempt + 1 < key_count:
                _mark_key_rate_limited(platform, client, long_cooldown=True)
                try:
                    print(f"  [WARN] Key rotation on {platform}: {type(e).__name__}: {str(e)[:200]}")
                except Exception:
                    pass
                continue
            raise


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

    Tries platforms in order. Within each platform, keys are rotated on rate-limit errors.
    If all platforms fail, raises RuntimeError.

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
        """Call platform *p* with key rotation."""
        m = model or _VISION_MODELS.get(p, _VISION_MODELS["modelscope"])
        pool = _get_pool(p)
        key_count = max(pool.key_count(), 1)

        for attempt in range(key_count):
            client = _get_client(p, api_key, timeout=timeout)
            try:
                messages = [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {"type": "text", "text": prompt},
                    ],
                }]
                return _chat_completion(
                    client, m, messages,
                    temperature=temperature, max_tokens=max_tokens,
                    platform=p,
                )
            except Exception as e:
                if _is_rate_limited(e) and attempt + 1 < key_count:
                    _mark_key_rate_limited(p, client)
                    try:
                        print(f"  [WARN] Key rotation on {p}: {type(e).__name__}: {str(e)[:200]}")
                    except Exception:
                        pass
                    continue
                raise

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

    Tries platforms in order. Within each platform, keys are rotated on rate-limit errors.
    If all platforms fail, raises RuntimeError.

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
        """Call platform *p* with key rotation."""
        m = model or _CODE_MODELS.get(p, _CODE_MODELS["modelscope"])
        pool = _get_pool(p)
        key_count = max(pool.key_count(), 1)

        for attempt in range(key_count):
            client = _get_client(p, api_key, timeout=timeout)
            try:
                return _chat_completion(
                    client, m, messages,
                    temperature=temperature, max_tokens=max_tokens,
                    platform=p,
                )
            except Exception as e:
                if _is_rate_limited(e) and attempt + 1 < key_count:
                    _mark_key_rate_limited(p, client)
                    try:
                        print(f"  [WARN] Key rotation on {p}: {type(e).__name__}: {str(e)[:200]}")
                    except Exception:
                        pass
                    continue
                raise

    return _try_platforms(target_platforms, _call, "text_to_text")
