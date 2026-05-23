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
VISION_MODELS = {"modelscope": "Qwen/Qwen3-VL-235B-A22B-Instruct", "zhipu": "glm-4v-flash"}
CODE_MODELS = {
    "deepseek": "deepseek-chat", "modelscope": "Qwen/Qwen3-Coder-480B-A35B-Instruct",
    "siliconflow": "Qwen/Qwen3-8B", "zhipu": "glm-4.7-flash",
}


def _client(platform: str) -> OpenAI:
    key = os.getenv(ENV_KEY.get(platform, ""))
    if not key: raise ValueError(f"Missing key for {platform}")
    return OpenAI(api_key=key, base_url=BASE_URL[platform])


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
    if platforms is None: platforms = ["modelscope", "zhipu"]
    b64 = _encode(path)
    def _call(p):
        r = _client(p).chat.completions.create(
            model=VISION_MODELS[p],
            messages=[{"role":"user","content":[{"type":"image_url","image_url":{"url":b64}},{"type":"text","text":prompt}]}],
            temperature=kw.get("temperature",0.1), max_tokens=kw.get("max_tokens",1024))
        return r.choices[0].message.content
    return _try(platforms, _call, "vision")


def text_to_text(messages: list, platforms=None, **kw) -> str:
    if platforms is None: platforms = ["deepseek", "modelscope", "siliconflow", "zhipu"]
    def _call(p):
        r = _client(p).chat.completions.create(
            model=CODE_MODELS[p], messages=messages,
            temperature=kw.get("temperature",0.1), max_tokens=kw.get("max_tokens",4096))
        return r.choices[0].message.content
    return _try(platforms, _call, "code")
