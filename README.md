# Sketch2TikZ

Multi-model LLM pipeline: hand-drawn sketch → TikZ vector code → compiled PDF.
A vision model describes the image, a code model generates LaTeX/TikZ, then XeLaTeX compiles locally. A second vision pass (Critic) compares the rendered output against the original image to score fidelity (1.0–5.0).

> [中文摘要](#chinese)

---

## Project Structure

```
Sketch2TikZ/
├── src/
│   ├── llm_caller.py       # Multi-platform API wrapper (4 providers, auto-fallback)
│   ├── pipeline.py         # XeLaTeX compiler + preprocessor
│   └── academic_metrics.py # SciTikZ metrics: TED, CrystalBLEU, SSIM, LPIPS (opt-in)
├── scripts/
│   └── setup_data.py       # Extract difficulty-level zip datasets
├── evaluate.py             # Full benchmark: vision → code → compile → critic
├── output/                 # Generated .tex / .pdf / .png (auto-cleaned each run)
├── data/                   # Extracted parquet datasets (gitignored)
├── .env                    # API keys + XeLaTeX path (gitignored, NEVER commit)
├── .env.example            # Template for .env
├── .gitignore
└── requirements.txt
```

---

## Environment Setup

### 1. Python

```bash
conda create -n tikz_agent python=3.10 -y
conda activate tikz_agent
pip install -r requirements.txt
```

### 2. LaTeX (TeX Live) + Ghostscript

The pipeline compiles with **XeLaTeX** and uses **Ghostscript** to rasterize PDFs for visual comparison.

**Install TeX Live** via a fast CTAN mirror:

```bash
wget https://mirrors.tuna.tsinghua.edu.cn/CTAN/systems/texlive/tlnet/install-tl.zip
unzip install-tl.zip && cd install-tl-*/

# Linux/macOS
perl install-tl -no-gui -scheme=small

# Windows — create a profile file with TEXDIR set, then:
perl install-tl -no-gui -profile your_profile.txt
```

**Install required LaTeX packages:**

```bash
tlmgr option repository https://mirrors.tuna.tsinghua.edu.cn/CTAN/systems/texlive/tlnet
tlmgr install pgf standalone xecjk ctex fontspec pgfplots subfigure bbm-macros revtex
```

**Ghostscript** (for PDF→PNG conversion during Critic scoring):

```bash
conda install -c conda-forge -y ghostscript
```

### 3. API Keys

```bash
cp .env.example .env
# Edit .env — fill in keys for the platforms you intend to use
```

Four platforms are supported. The pipeline tries them **in order** and falls back automatically:

| Platform | Vision model | Code model | Priority |
|----------|-------------|------------|----------|
| DeepSeek | (not available) | `deepseek-chat` | Code #1 |
| ModelScope | `Qwen/Qwen3-VL-235B-A22B-Instruct` | `Qwen/Qwen3-Coder-480B-A35B-Instruct` | Vision #1, Code #2 |
| ZhipuAI | `glm-4v-flash` | `glm-4.7-flash` | Vision #2, Code #4 |
| SiliconFlow | (not available) | `Qwen/Qwen3-8B` | Code #3 |

`.env` is **gitignored** and must never be committed.

---

## Data Preparation

Three difficulty-level datasets are distributed as zip archives in the project root:

| File | Typical content | Approx. test rows |
|------|----------------|-------------------|
| `easy.zip` | Simple geometric diagrams, basic nodes | ~138 |
| `medium.zip` | Multi-node graphs, moderate structure | ~199 |
| `hard.zip` | pgfplots charts, custom shapes | ~224 |

```bash
python scripts/setup_data.py             # extract all three
python scripts/setup_data.py --level easy # extract one
```

Populates `data/easy/`, `data/medium/`, `data/hard/`.

---

## Usage

```bash
python evaluate.py --difficulty easy --num_samples 10
python evaluate.py --difficulty medium --num_samples 5 --skip-critic
python evaluate.py --difficulty hard --num_samples 10 --academic
```

| Flag | Effect |
|------|--------|
| `--difficulty {easy,medium,hard}` | Which dataset to evaluate (default: easy) |
| `--num_samples N` | How many rows to test (default: 10) |
| `--skip-critic` | Skip visual Critic scoring (faster, no fidelity scores) |
| `--academic` | Enable SciTikZ metrics: TED, CrystalBLEU, SSIM, LPIPS (off by default) |

All generated files are written to `output/`. The directory is **auto-cleaned** at the start of each run.

### Pipeline per sample

1. Vision model describes the image
2. Code model generates TikZ LaTeX
3. XeLaTeX compiles → PDF (pass/fail)
4. **Aspect-ratio gate**: if generated shapes are >2x or <0.5x the original aspect ratio, score = 0
5. Vision Critic scores visual similarity 1.0–5.0 (only if compile passed)

### Dashboard metrics

| Metric | Meaning |
|--------|---------|
| Compile pass rate | % of AI-generated TikZ that compiles to PDF |
| Critic pass rate | % rated ≥ 3.0 by vision-based comparison |
| Avg fidelity score | Mean score across ALL samples (failures count as 0) |
| Avg vision / codegen time | Latency per pipeline stage |

---

## API Fallback Behavior

Each API call accepts a **list** of platforms and tries them in order. If a platform returns 401/429/403, the next is tried immediately. If **all** platforms fail, the program exits with a diagnostic showing which platform failed and why.

---

## Notes

- XeLaTeX success is determined by **PDF file existence**, not exit code.
- Niche packages (`MnSymbol`, `mathrsfs`) are auto-stripped by the preprocessor.
- `--academic` metrics (LPIPS especially) are slow on CPU — GPU recommended.
- Ghostscript is auto-discovered from PATH, or set `GS_PATH` in `.env`.

---

## <a name="chinese">中文</a>

Sketch2TikZ 是一个多模型 LLM 流水线：手绘草图 → 视觉模型描述 → 代码模型生成 TikZ → XeLaTeX 编译 → 宽高比门禁 → 视觉 Critic 对比原图打分。

### 环境配置

1. 安装 TeX Live（推荐清华镜像）+ `tlmgr install pgf standalone xecjk ctex fontspec pgfplots subfigure bbm-macros revtex`
2. `conda install -c conda-forge -y ghostscript`
3. `cp .env.example .env` 并填入 API Key
4. `pip install -r requirements.txt`
5. `python scripts/setup_data.py` 解压数据集

### API 平台优先级

视觉模型：ModelScope → ZhipuAI
代码模型：DeepSeek → ModelScope → SiliconFlow → ZhipuAI

### 评估指标

编译通过率、Critic 通过率（1.0–5.0 分，含形变门禁）、平均保真度（编译失败 = 0 分）。
需要学术指标时加 `--academic`，输出 TED / CrystalBLEU / SSIM / LPIPS。
