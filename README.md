# Sketch2TikZ

Hand-drawn sketch → TikZ vector code → compiled PDF. Multi-model LLM pipeline with vision-based evaluation.

## Structure

```
train/                   # Development — freely modify
├── contract.py          # SampleResult interface (test calls this)
├── llm_caller.py        # Multi-platform API wrapper (SSE + fallback + named-model)
├── pipeline.py          # Vision description → code gen → compile → critic
└── data/
    ├── easy/            50 PNG + 50 TikZ code
    ├── medium/          50 PNG + 50 TikZ code
    └── difficult/       50 PNG + 50 TikZ code

test/                    # Sealed — read-only
├── judge.py             # Single-model judge (Qwen3-VL-235B, temp=0)
├── runner.py            # Loads test PNGs, calls pipeline, reports
└── data/
    ├── easy/            50 PNG only (no code access)
    ├── medium/          50 PNG only
    └── difficult/       50 PNG only

test_apis.py             # API connectivity tester for all registered models
output/                  # Runtime artifacts (gitignored)
```

Train and test data come from non-overlapping parquet sources. Test has no access to ground-truth code — evaluation is purely visual.

## Pipeline

```
Image → Vision model (description) → Code model (TikZ) → XeLaTeX compile
    ↓
Compile self-heal (max 3 retries, .log feedback)
    ↓
Internal visual critic (diagnosis + score)
    ↓
Visual self-heal (1 pass, diagnosis-driven surgical fix)
    ↓
Sealed external judge (final score)
```

## Setup

```bash
conda create -n tikz_agent python=3.10 -y && conda activate tikz_agent
pip install -r requirements.txt
```

TeX Live:

```bash
tlmgr option repository https://mirrors.tuna.tsinghua.edu.cn/CTAN/systems/texlive/tlnet
tlmgr install pgf standalone xecjk ctex fontspec pgfplots subfigure bbm-macros revtex
```

Ghostscript:

```bash
conda install -c conda-forge -y ghostscript
```

API keys: copy `.env.example` to `.env`, fill in at least one platform.

## Usage

```bash
python -m test.runner --difficulty easy --num-samples 10
python -m test.runner --difficulty medium --num-samples 5 --skip-judge
```

| Flag | Effect |
|------|--------|
| `--difficulty {easy,medium,difficult}` | Test set (default: easy) |
| `--num-samples N` | Samples to test (default: 10, max 50) |
| `--skip-judge` | Compile-only mode, skip vision judge |

## Platforms

Six platforms with automatic fallback. Priority order:

| Priority | Vision | Code |
|----------|--------|------|
| 1 | ModelScope (Qwen3-VL-235B) | DeepSeek (deepseek-chat) |
| 2 | ZhipuAI (glm-4v-flash) | ModelScope (Qwen3-Coder-480B) |
| 3 | NVIDIA (mistral-large-3) | SiliconFlow (Qwen3-8B) |
| 4 | OpenRouter (nemotron-3-nano-omni) | ZhipuAI (glm-4.7-flash) |
| 5 | — | NVIDIA (qwen3-coder-480b) |
| 6 | — | OpenRouter (deepseek-v4-flash) |

If a platform returns 401/429/403, the next is tried immediately. All platforms fail → program exits with diagnostic.

Use `call_vision_model(name, ...)` / `call_text_model(name, ...)` to target a specific model.
Use `python test_apis.py` to check API key configuration and model availability.
Use `python test_apis.py --image path.jpg` to also test vision models.


  ### Multi-key API scheduling (train/llm_caller.py)

  Key pool (ApiKeyPool class, line ~175):
  - Thread-safe rotating pool of API keys per platform
  - Keys are read from env vars in two formats:
    - Comma-separated: NVIDIA_API_KEY=key1,key2,key3
    - Numbered suffix: NVIDIA_API_KEY_1=key1, NVIDIA_API_KEY_2=key2
  - Rate-limited keys are put into cooldown (30s default, 300s for quota exhaustion) and skipped on subsequent requests

  Rate-limit detection (_is_rate_limited, line ~157):
  - Detects HTTP 429/402 status codes in error messages
  - Matches keywords: rate limit, quota, insufficient_quota, billing, throttle, overloaded, etc.
  - Works across all providers (Nvidia, ModelScope, OpenRouter, etc.)

  Automatic key rotation:
  - _create() — rotates keys on rate-limit within the same platform
  - call_vision_model() / call_text_model() — rotates when no explicit api_key is passed
  - image_to_text() / text_to_text() — inner key rotation within each platform's fallback attempt
  - When an explicit api_key is provided, no rotation occurs (direct key usage)


## Judge

test/judge.py is sealed. Single temp=0 Qwen3-VL-235B-A22B-Instruct on ModelScope. Scoring:

- Missing elements → ≤ 1.0
- Position/color diffs → 1.0–2.0
- Naked-eye differences → ≤ 3.0
- Minor differences → 2.0–5.0
