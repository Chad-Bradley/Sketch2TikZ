"""Multi-platform LLM API wrapper."""
import os, base64
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

BASE_URL = {
    "modelscope":  "https://api-inference.modelscope.cn/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "zhipu":       "https://open.bigmodel.cn/api/paas/v4",
    "deepseek":    "https://api.deepseek.com",
}
ENV_KEY = {
    "modelscope":  "MODELSCOPE_API_KEY", "siliconflow": "SILICONFLOW_API_KEY",
    "zhipu":       "ZHIPU_API_KEY",       "deepseek":    "DEEPSEEK_API_KEY",
}
VISION_MODELS = {
    "modelscope": "Qwen/Qwen3-VL-235B-A22B-Instruct",
    "zhipu":      "glm-4v-flash",
}
CODE_MODELS = {
    "deepseek":   "deepseek-chat",
    "modelscope": "Qwen/Qwen3-Coder-480B-A35B-Instruct",
    "siliconflow": "Qwen/Qwen3-8B",
    "zhipu":      "glm-4.7-flash",
}

VISION_PLATFORMS = ["modelscope", "zhipu"]
CODE_PLATFORMS = ["deepseek", "modelscope", "siliconflow", "zhipu"]


def _create(platform: str, model: str, messages: list, temperature: float, max_tokens: int) -> str:
    """Call API with SSE streaming for all platforms."""
    key_env = ENV_KEY.get(platform)
    key = os.getenv(key_env, "")
    client = OpenAI(api_key=key, base_url=BASE_URL[platform])

    stream = client.chat.completions.create(
        model=model, messages=messages,
        temperature=temperature, max_tokens=max_tokens, stream=True,
    )
    content = ""
    for chunk in stream:
        if chunk.choices[0].delta.content:
            content += chunk.choices[0].delta.content
    return content


def _encode(path: str) -> str:
    with open(path, "rb") as f: data = base64.b64encode(f.read()).decode("utf-8")
    ext = os.path.splitext(path)[1].lower()
    return f"data:{'image/png' if ext=='.png' else 'image/jpeg'};base64,{data}"


def _try(platforms, fn, name):
    errors = []
    for p in platforms:
        try: return fn(p)
        except Exception as e:
            errors.append(f"[{p}] {type(e).__name__}: {e}")
            print(f"  [WARN] {name} {p}: {type(e).__name__}: {str(e)[:120]}")
    raise RuntimeError(f"All platforms failed for '{name}':\n" + "\n".join(errors))


def image_to_text(path: str, prompt: str, platforms=None, **kw) -> str:
    if platforms is None: platforms = list(VISION_PLATFORMS)
    b64 = _encode(path)
    def _call(p):
        return _create(p, VISION_MODELS[p],
                       [{"role":"user","content":[{"type":"image_url","image_url":{"url":b64}},{"type":"text","text":prompt}]}],
                       kw.get("temperature",0.1), kw.get("max_tokens",1024))
    return _try(platforms, _call, "vision")


def text_to_text(messages: list, platforms=None, **kw) -> str:
    if platforms is None: platforms = list(CODE_PLATFORMS)
    def _call(p):
        return _create(p, CODE_MODELS[p], messages,
                       kw.get("temperature",0.1), kw.get("max_tokens",4096))
    return _try(platforms, _call, "code")
