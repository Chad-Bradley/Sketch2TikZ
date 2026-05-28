# Sketch2TikZ

Hand-drawn sketch → TikZ vector code → compiled PDF.
Multi-model LLM pipeline with self-improving prompt optimization.

## Architecture

```
train/                   # Development — freely modify
├── contract.py          # SampleResult interface (test calls this)
├── llm_caller.py        # Multi-platform API wrapper with key rotation
├── pipeline.py          # Generation + dual feedback + critic
├── dev_loop.py          # Iterative prompt optimizer with AI review
├── _ask_ai.py           # Ad-hoc visual quality audit tool
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
```

Train and test data come from non-overlapping sources. Test has no code access — evaluation is purely visual.

## Self-Improving Pipeline

The system evolves its own prompts through a closed optimization loop:

```
                      ┌──────────────────────────┐
                      │   train/dev_loop.py       │
                      │                           │
Random train sample → │ 1. Generate TikZ + compile │
                      │ 2. Internal critic scores  │
                      │ 3. If score < 4.0:         │
                      │    AI reviews GT vs gen    │
                      │    Outputs concrete fixes  │
                      │ 4. Apply fixes to prompts  │
                      │ 5. Re-test same batch      │
                      └──────────────────────────┘
```

Each iteration produces copy-pasteable prompt fixes — specific rules, pattern descriptions, and code conventions — validated against ground truth code. The critic enforces strict visual fidelity scoring (1.0–5.0) with explicit score caps for shape distortion, missing elements, and placement errors.

The final evaluation runs through `test/runner.py` against unseen test images. The sealed judge (temp=0, single model, fixed prompt) ensures no score inflation.

### Pipeline per sample

```
Image → Vision model (TikZ-like specification) → Code model (LaTeX) → XeLaTeX compile
    ↓
Compile self-heal (max 3 retries, .log feedback)
    ↓
Internal visual critic (diagnosis + honest score)
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
# Benchmark on sealed test set
python -m test.runner --difficulty easy --num-samples 10

# Iterative prompt optimization (uses train data with GT code)
python -m train.dev_loop

# Ad-hoc visual quality check on a specific sample
python -m train._ask_ai
```

| Flag | Effect |
|------|--------|
| `--difficulty {easy,medium,difficult}` | Test set (default: easy) |
| `--num-samples N` | Samples to test (default: 10, max 50) |
| `--skip-judge` | Compile-only mode, skip vision judge |

## Platforms

Multi-platform architecture with a configurable primary endpoint. Additional providers serve as fallback chain.

| Priority | Vision | Code |
|----------|--------|------|
| 1 | default_choice (configurable) | default_choice (configurable) |
| 2 | ModelScope (Qwen3-VL-235B) | ModelScope (Qwen3-Coder-480B) |
| 3 | ZhipuAI (glm-4v-flash) | NVIDIA (qwen3-coder-480b) |
| 4 | NVIDIA (mistral-large-3) | ZhipuAI (glm-4.7-flash) |
| 5 | — | OpenRouter (nemotron-3-super-120b) |
| 6 | — | SiliconFlow (Qwen3-8B) |

Platforms support comma-separated keys in `.env` for automatic quota rotation. Empty content from the primary platform triggers automatic retry before fallback.

## Judge

`test/judge.py` is sealed. Single temp=0 Qwen3-VL-235B-A22B-Instruct on ModelScope. Multi-key rotation. Scoring:

- Missing elements → ≤ 1.0
- Position/color diffs → 1.0–2.0
- Naked-eye differences → ≤ 3.0
- Minor differences → 2.0–5.0
