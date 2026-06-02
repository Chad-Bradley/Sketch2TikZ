# Plots 目录说明

本目录包含 **Sketch2TikZ-v2** 项目训练/评测结果的可视化图表及其数据源。

---

## 目录结构

```
plots/
├── data/                        # 评测原始数据（JSON）
│   ├── easy0.json ~ easy2.json
│   ├── medium0.json ~ medium3.json
│   ├── difficult0.json ~ difficult2.json
│   ├── chart_plot0.json ~ chart_plot2.json
│   ├── pure_drawing0.json ~ pure_drawing2.json
│   ├── math_formula0.json ~ math_formula3.json
│   └── math_geometry0.json ~ math_geometry2.json
├── iter*3/                      # 自迭代实验日志
│   ├── iter_014/
│   ├── iter_015/
│   └── iter_016/
├── output/                      # 生成的图片
│   ├── metrics_trend.png
│   ├── gen_metrics_trend_0.pdf
│   ├── gen_metrics_trend_1.pdf
│   ├── gen_metrics_trend_2.pdf
│   ├── score_distribution_fig1.png
│   ├── score_distribution_fig2.png
│   └── summary_table.png
├── plot_distribution.py         # 绘制分数分布图（箱线图+散点）
├── plot_metrics.py              # 绘制指标趋势图（折线图）
├── plot_summary_table.py        # 绘制汇总表格图
└── explanation.md               # 本文件
```

---

## 数据来源

`data/` 下的 JSON 文件命名规则为 `{task}{epoch}.json`，例如 `easy0.json` 表示 **Easy 任务的 Epoch 0** 评测结果。

每个 sample 的字段：

| 字段 | 说明 |
|------|------|
| `sample` | 原始图片文件名 |
| `compile_ok` | TikZ 代码是否编译通过 |
| `compile_attempts` | 编译尝试次数 |
| `score` | AI 视觉裁判评分（1.0~5.0），≥3.0 为 pass |
| `diagnosis` | 裁判给出的具体差异描述 |
| `vision_time` / `codegen_time` | 各阶段耗时（秒） |

支持的 7 个任务类型：

| 任务 key | 说明 |
|---------|------|
| `easy` | 简单图形 |
| `medium` | 中等难度图形 |
| `difficult` | 困难图形 |
| `chart_plot` | 图表/折线图 |
| `pure_drawing` | 纯手绘图 |
| `math_formula` | 数学公式 |
| `math_geometry` | 几何图形 |

每个任务有多个 epoch，对应多轮迭代优化后的评测结果。

---

## 生成的图表

### 1. `output/metrics_trend.png`

由 `plot_metrics.py` 生成。

**内容**：所有 7 个任务在 3 个 epoch 上的两个核心指标变化趋势，分左右两张子图：

- **左图 — Critic Pass Rate (score ≥ 3.0)**：通过率的变化趋势
- **右图 — Average Fidelity Score (1.0–5.0)**：平均视觉相似度得分变化

虚线表示 pass 阈值（3.0 分），每个数据点旁标注具体数值。

**用途**：总体观察多轮迭代的优化趋势，判断哪些任务在提升、哪些停滞或下降。

---

### 2. `output/score_distribution_fig1.png`

由 `plot_distribution.py` 生成。

**内容**：Easy / Medium / Difficult 三个难度级别的分数分布。

- 2×2 子图布局，右下角为 epoch 颜色图例
- 每个子图为一个任务的 3 个 epoch 箱线图（boxplot）
- 叠加散点（strip plot）展示每个样本的实际分数
- 箱体颜色按 epoch 渐变：浅蓝(E0)→橙(E1)→红(E2)
- 虚线为 pass 阈值（3.0 分）
- 每个 epoch 上方标注均值

**用途**：观察不同难度下分数的分布形态、离散程度、异常值和中位数变化。

---

### 3. `output/score_distribution_fig2.png`

由 `plot_distribution.py` 生成。

**内容**：Chart/Plot / Pure Drawing / Math Formula / Math Geometry 四个专项类型的分数分布。

布局和配色与 Figure 1 相同，图例放在右侧外部。

**用途**：与 Figure 1 互补，覆盖剩下的四个专项任务。

---

### 4. `output/summary_table.png`

由 `plot_summary_table.py` 生成。

**内容**：所有 7 个任务 × 3 个 epoch 的汇总指标表格：

| 列 | 说明 |
|----|------|
| Task | 任务名称 |
| n | 样本数（固定为 50） |
| E0 / E1 / E2 Pass% | 各 epoch 的通过率（score ≥ 3.0） |
| E0 / E1 / E2 Avg | 各 epoch 的平均分 |
| E0 / E1 / E2 Med | 各 epoch 的中位数 |

列按 epoch 分组着色（蓝/橙/红），便于横向对比。

**用途**：以最紧凑的形式呈现所有任务的完整评测结果，适合做最终报告。

---

## 完整评测结果

### 全面优化结果（每轮一次 dev_loop）

|task|epoch| Compile rate | Avg compile attempts|Critic pass rate | Avg fidelity score |
|-----|----|----|--|--|--|
easy|0|100%|1.0|84.0%|3.24/5.0|
easy|1|100%|1.0|84.0%|3.39/5.0|
easy|2|100%|1.0|94.0%|3.50/5.0|
medium|0|100%|1.0|60.0%|2.69/5.0|
medium|1|100%|1.0|96.0%|3.04/5.0|
medium|2|100%|1.0|84.0%|2.89/5.0|
difficult|0|100%|1.0|58.0%|2.91/5.0|
difficult|1|100%|1.0|78.0%|2.70/5.0|
difficult|2|100%|1.0|48.0%|2.67/5.0|
chart_plot|0|100%|1.0|84.0%|2.92/5.0|
chart_plot|1|100%|1.0|72.0%|3.21/5.0|
chart_plot|2|100%|1.0|86.0%|3.22/5.0|
pure_drawing|0|100%|1.0|76.9%|2.85/5.0|
pure_drawing|1|100%|1.0|53.8%|2.77/5.0|
pure_drawing|1|100%|1.0|69.2%|2.88/5.0|
math_geometry|0|100%|1.0|64.0%|2.55/5.0|
math_geometry|1|100%|1.0|78.0%|2.75/5.0|
math_geometry|2|100%|1.0|50.0%|2.66/5.0
math_formula|0|100%|1.0|89.3%|2.89/5.0|
math_formula|1|100%|1.0|82.1%|2.84/5.0|
math_formula|2|100%|1.0|82.1%|2.84/5.0|
math_formula|3|100%|1.0|92.9%|3.09/5.0|

**说明**：所有任务均 100% 编译通过，平均编译尝试次数均为 1.0（一次通过）。Easy 和 Chart/Plot 表现最好，Critic Pass Rate 最高达 94% 和 86%；Difficult 和 Pure Drawing 波动较大，Diffcult 在第 2 轮反而下降至 48%；Math Formula 经过额外一轮优化后达到 E3 的 92.9%/3.09。

---

### 针对 Medium 的专项优化

将评测结果记录发给 DeepSeek 进行手动 prompt 优化，得到以下改进：

| task | epoch | Compile rate | Avg compile attempts | Critic pass rate | Avg fidelity score |
|------|-------|-------------|---------------------|-----------------|-------------------|
| medium | 0 | 100% | 1.0 | 60.0% | 2.69/5.0 |
| medium | 1 | 100% | 1.0 | 68.0% | 2.88/5.0 |
| medium | 2 | 100% | 1.0 | 66.0% | 2.95/5.0 |
| medium | 3 | 100% | 1.0 | **86.0%** | **2.95/5.0** |

经过针对性 prompt 优化后，Medium 的 Critic Pass Rate 和Avg fidelity score均有提升。

### 跨域迁移实验：Medium prompt → Easy 数据

| task | epoch | Compile rate | Avg compile attempts | Critic pass rate | Avg fidelity score |
|------|-------|-------------|---------------------|-----------------|-------------------|
| easy | 0 | 100% | 1.0 | 74.0% | 3.37/5.0 |

用 Medium 的 prompt 去跑 Easy 数据，得到 74.0%/3.37 的成绩。

---

## 图表自迭代实验

除了上述标准任务的评测外，本项目还进行了一个 **自引用迭代实验**：

### 实验设计

将 `output/metrics_trend.png`（由 `plot_metrics.py` 生成的趋势图本身）作为输入图片，使用 **chart_plot** 类 prompt，通过 `dev_loop_focused.py` 进行 3 轮迭代优化，目标是让模型生成的 TikZ 代码重新绘制出与原始趋势图高度相似的图表。

### 迭代过程

| 轮次 | 路径 | Score | 关键差异 |
|------|------|-------|---------|
| 第 1 轮 | `iter*3/iter_014/` | 3.5 | 图例位置、标记样式、线条粗细与参考图有差异 |
| 第 2 轮 | `iter*3/iter_015/` | 3.5 | 图例仍与 x 轴标签重叠，数据标签有重叠 |
| 第 3 轮 | `iter*3/iter_016/` | **4.0** ✅ | 布局和数据系列高度一致，仅字体渲染和比例略有不同 |

### 输出文件

| 文件 | 说明 |
|------|------|
| `iter*3/iter_014/` ~ `iter*3/iter_016/` | 每轮迭代的完整日志（prompt、samples、review、summary） |
| `output/gen_metrics_trend_0.pdf` | 第 1 轮生成的 PDF |
| `output/gen_metrics_trend_1.pdf` | 第 2 轮生成的 PDF |
| `output/gen_metrics_trend_2.pdf` | 第 3 轮生成的 PDF（最终版，score = 4.0） |

### 意义

这个实验验证了 pipeline 对 **自身输出图表的重构能力**：经过 3 轮 prompt 优化，模型成功将一幅带双轴、多数据系列、数据标签的复杂趋势图还原到 4.0 分水平，说明 chart_plot 类 prompt 对图表类图片有较好的泛化效果。

---

## 如何使用

### 重新生成所有图表

```bash
cd Sketch2TikZ-v2
python plots/plot_metrics.py           # 生成 metrics_trend.png
python plots/plot_distribution.py      # 生成 score_distribution_fig1.png + fig2.png
python plots/plot_summary_table.py     # 生成 summary_table.png
```