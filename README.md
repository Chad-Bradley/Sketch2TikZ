# Sketch2TikZ

Hand-drawn sketch → TikZ vector code → compiled PDF. Multi-model LLM pipeline with vision-based evaluation.

## Structure

```
train/                   # Development — freely modify
├── contract.py          # Interface definition (test calls this)
├── llm_caller.py        # Multi-platform API wrapper
├── pipeline.py          # image → vision desc → code gen → compile
└── data/
    ├── easy/            50 PNG + 50 TikZ code
    ├── medium/          50 PNG + 50 TikZ code
    └── difficult/       50 PNG + 50 TikZ code

test/                    # Sealed — do not modify
├── judge.py             # temp=0 Qwen3-VL-235B-A22B-Instruct, fixed prompt
├── runner.py            # Loads test PNGs, calls train.pipeline.generate(), judges
└── data/
    ├── easy/            50 PNG only (no code)
    ├── medium/          50 PNG only (no code)
    └── difficult/       50 PNG only (no code)
```

Train and test data come from non-overlapping parquet sources. Test has no code access — evaluation is purely visual comparison.

## Setup

```bash
conda create -n tikz_agent python=3.10 -y && conda activate tikz_agent
pip install -r requirements.txt
```

TeX Live with required packages:

```bash
tlmgr option repository https://mirrors.tuna.tsinghua.edu.cn/CTAN/systems/texlive/tlnet
tlmgr install pgf standalone xecjk ctex fontspec pgfplots subfigure bbm-macros revtex
```

Ghostscript:

```bash
conda install -c conda-forge -y ghostscript
```

## Usage

```bash
python -m test.runner --difficulty easy --num-samples 10
python -m test.runner --difficulty medium --num-samples 5 --skip-judge
python -m test.runner --difficulty difficult --num-samples 10
```

| Flag | Effect |
|------|--------|
| `--difficulty {easy,medium,difficult}` | Test set to evaluate |
| `--num-samples N` | Number of samples (default 10, max 50) |
| `--skip-judge` | Skip vision judge, compile-only mode |

## API Keys

Copy `.env.example` to `.env` and fill in keys. Four platforms supported with automatic fallback:

| Platform | Vision | Code |
|----------|--------|------|
| ModelScope | Qwen3-VL-235B | Qwen3-Coder-480B |
| DeepSeek | — | deepseek-chat |
| ZhipuAI | glm-4v-flash | glm-4.7-flash |
| SiliconFlow | — | Qwen3-8B |

Vision priority: ModelScope → ZhipuAI
Code priority: DeepSeek → ModelScope → SiliconFlow → ZhipuAI

## Judge

Single temp=0 Qwen3-VL-235B-A22B-Instruct with hard score caps:

- Missing elements → ≤ 1.0
- Position/color diffs → 1.0–2.0
- Naked-eye differences → ≤ 3.0
- Minor differences only → 2.0–5.0
