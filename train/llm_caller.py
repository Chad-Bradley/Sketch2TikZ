"""Multi-platform LLM API wrapper."""
import os, base64
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

BASE_URL = {
    "modelscope":  "https://api-inference.modelscope.cn/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "zhipu":       "https://open.bigmodel.cn/api/paas/v4",
    "nvidia":      "https://integrate.api.nvidia.com/v1",
    "openrouter":  "https://openrouter.ai/api/v1",
    "siliconflow2":"https://api.siliconflow.cn/v1",
    "modelscope2": "https://api-inference.modelscope.cn/v1",
    "nvidia2":     "https://integrate.api.nvidia.com/v1",
}
ENV_KEY = {
    "modelscope":  "MODELSCOPE_API_KEY",  "modelscope2":  "MODELSCOPE2_API_KEY",
    "siliconflow": "SILICONFLOW_API_KEY", "siliconflow2": "SILICONFLOW2_API_KEY",
    "zhipu":       "ZHIPU_API_KEY",
    "nvidia":      "NVIDIA_API_KEY",       "nvidia2":      "NVIDIA2_API_KEY",
    "openrouter":  "OPENROUTER_API_KEY",
}
VISION_MODELS = {
    "modelscope":  "Qwen/Qwen3-VL-235B-A22B-Instruct",
    "modelscope2": "Qwen/Qwen3-VL-235B-A22B-Instruct",
    "zhipu":       "glm-4v-flash",
    "nvidia":      "mistralai/mistral-large-3-675b-instruct-2512",
}
CODE_MODELS = {
    "modelscope":  "Qwen/Qwen3-Coder-480B-A35B-Instruct",
    "modelscope2": "Qwen/Qwen3-Coder-480B-A35B-Instruct",
    "zhipu":       "glm-4.7-flash",
    "nvidia":      "qwen/qwen3-coder-480b-a35b-instruct",
    "nvidia2":     "qwen/qwen3-coder-480b-a35b-instruct",
    "openrouter":  "nvidia/nemotron-3-super-120b-a12b:free",
    "siliconflow": "Qwen/Qwen3-8B",
    "siliconflow2":"Qwen/Qwen3-8B",
}

VISION_PLATFORMS = ["modelscope", "modelscope2", "zhipu", "nvidia"]
CODE_PLATFORMS = ["modelscope", "modelscope2", "nvidia", "nvidia2", "zhipu", "openrouter", "siliconflow", "siliconflow2"]


def _create(platform: str, model: str, messages: list, temperature: float, max_tokens: int) -> str:
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
    for i, p in enumerate(platforms):
        try:
            result = fn(p)
            if i > 0:
                print(f"  [OK]   {name} fell back to #{i+1} {p}")
            return result
        except Exception as e:
            err = f"[{p}] {type(e).__name__}: {str(e)[:100]}"
            errors.append(err)
            print(f"  [FAIL] {name} #{i+1} {p}: {type(e).__name__}")
    raise RuntimeError(f"All {len(platforms)} platforms failed for '{name}':\n" + "\n".join(errors))


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
