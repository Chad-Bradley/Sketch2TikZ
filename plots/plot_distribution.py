"""
Boxplot + Stripplot: 每个任务各 epoch 的 score 分布

分两组图:
  Figure 1 (2×2): easy, medium, difficult + 右下角图例
  Figure 2 (2×2): chart_plot, pure_drawing, math_formula, math_geometry + 右下角图例
"""

import json
import os
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

# ── 配置 ──────────────────────────────────────────────
PLOTS_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PLOTS_DIR, "data")

OUTPUT_DIR = os.path.join(PLOTS_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

OUTPUT_PATH1 = os.path.join(OUTPUT_DIR, "score_distribution_fig1.png")   # easy/medium/difficult
OUTPUT_PATH2 = os.path.join(OUTPUT_DIR, "score_distribution_fig2.png")   # 其余四项

ALL_TASKS = ["easy", "medium", "difficult", "chart_plot", "pure_drawing",
             "math_formula", "math_geometry"]
EPOCHS = [0, 1, 2]

TASK_CONFIG = {
    "easy":         {"label": "Easy",           "color": "#2E86AB"},
    "medium":       {"label": "Medium",         "color": "#A23B72"},
    "difficult":    {"label": "Difficult",      "color": "#F18F01"},
    "chart_plot":   {"label": "Chart/Plot",     "color": "#1B998B"},
    "pure_drawing": {"label": "Pure Drawing",   "color": "#C73E1D"},
    "math_formula": {"label": "Math Formula",   "color": "#6A4C93"},
    "math_geometry":{"label": "Math Geometry",  "color": "#1982C4"},
}

EPOCH_COLORS = ["#A8D0E6", "#F4A261", "#E76F51"]  # ep0, ep1, ep2 的颜色
EPOCH_LABELS = ["Epoch 0", "Epoch 1", "Epoch 2"]


def load_scores(task: str, epoch: int) -> list:
    """从 JSON 加载该任务该 epoch 的所有 score"""
    fname = f"{task}{epoch}.json"
    fpath = os.path.join(DATA_DIR, fname)
    if not os.path.exists(fpath):
        return []
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    samples = data.get("samples", [])
    scores = [s["score"] for s in samples if s.get("compile_ok") and s.get("score") is not None]
    return scores


def plot_task_axes(ax, task, cfg, all_scores):
    """在给定的 ax 上绘制该任务的 boxplot + stripplot"""
    # 准备数据
    data = []
    positions = []
    for i, ep in enumerate(EPOCHS):
        scores = all_scores[task].get(ep, [])
        if scores:
            data.append(scores)
            positions.append(i)

    if not data:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        return

    # ── 箱线图 ──
    bp = ax.boxplot(data, positions=positions, widths=0.55,
                    patch_artist=True, showmeans=True,
                    meanprops=dict(marker="D", markerfacecolor="white",
                                   markeredgecolor="black", markersize=5),
                    medianprops=dict(color="black", linewidth=1.8),
                    whiskerprops=dict(linewidth=1.2),
                    capprops=dict(linewidth=1.2),
                    flierprops=dict(marker="o", markerfacecolor=cfg["color"],
                                    markersize=4, alpha=0.4))

    # 箱体颜色 - epoch 渐变色
    for patch, color in zip(bp["boxes"], [EPOCH_COLORS[i] for i in positions]):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)

    # ── 叠加散点 (strip plot) ──
    for i, ep in enumerate(EPOCHS):
        scores = all_scores[task].get(ep, [])
        if not scores:
            continue
        jitter = np.random.normal(0, 0.04, size=len(scores))
        ax.scatter(i + jitter, scores,
                   alpha=0.3, s=12, color=EPOCH_COLORS[i],
                   edgecolors="none", zorder=3)

    # ── 及格线 ──
    ax.axhline(y=3.0, color="gray", linestyle=":", linewidth=1.0, alpha=0.6)

    # ── 标注均值 ──
    for i, ep in enumerate(EPOCHS):
        scores = all_scores[task].get(ep, [])
        if scores:
            mean_val = np.mean(scores)
            ax.annotate(f"{mean_val:.2f}",
                        (i, mean_val),
                        textcoords="offset points",
                        xytext=(0, -14),
                        ha="center", fontsize=8,
                        color="black", fontweight="bold")

    # ── 格式 ──
    ax.set_title(cfg["label"], fontsize=13, fontweight="bold", pad=8)
    ax.set_xticks(positions)
    ax.set_xticklabels([EPOCH_LABELS[i] for i in positions], fontsize=10)
    ax.set_ylim(-0.3, 5.3)
    ax.set_ylabel("Score", fontsize=10)
    ax.grid(True, axis="y", linestyle="--", alpha=0.3)


def draw_epoch_legend(ax):
    """在给定的 ax（通常关掉坐标轴）上绘制 epoch 颜色图例"""
    legend_elements = [
        Patch(facecolor=EPOCH_COLORS[0], alpha=0.6, label=EPOCH_LABELS[0]),
        Patch(facecolor=EPOCH_COLORS[1], alpha=0.6, label=EPOCH_LABELS[1]),
        Patch(facecolor=EPOCH_COLORS[2], alpha=0.6, label=EPOCH_LABELS[2]),
    ]
    ax.legend(handles=legend_elements, loc="center", fontsize=11,
              title="Epoch", title_fontsize=12, framealpha=0.9)
    ax.axis("off")


def main():
    # ── 收集数据 ──
    all_scores = {}
    for task in ALL_TASKS:
        all_scores[task] = {}
        for ep in EPOCHS:
            scores = load_scores(task, ep)
            if scores:
                all_scores[task][ep] = scores
                print(f"  {TASK_CONFIG[task]['label']} ep{ep}: n={len(scores)}, "
                      f"mean={np.mean(scores):.2f}, median={np.median(scores):.1f}")
            else:
                all_scores[task][ep] = []

    # ═══════════════════════════════════════════════
    # Figure 1: easy / medium / difficult (2×2)
    # ═══════════════════════════════════════════════
    fig1_tasks = ["easy", "medium", "difficult"]
    fig1, axes1 = plt.subplots(2, 2, figsize=(12, 10))
    fig1.suptitle("Score Distribution by Task and Epoch — Difficulty Levels",
                  fontsize=16, fontweight="bold", y=1.01)

    for idx, task in enumerate(fig1_tasks):
        row, col = divmod(idx, 2)
        plot_task_axes(axes1[row, col], task, TASK_CONFIG[task], all_scores)

    # 右下角放图例
    draw_epoch_legend(axes1[1, 1])

    plt.tight_layout()
    plt.savefig(OUTPUT_PATH1, dpi=200, bbox_inches="tight")
    print(f"\n图已保存: {OUTPUT_PATH1}")
    plt.close(fig1)

    # ═══════════════════════════════════════════════
    # Figure 2: chart_plot / pure_drawing / math_formula / math_geometry (2×2)
    # ═══════════════════════════════════════════════
    fig2_tasks = ["chart_plot", "pure_drawing", "math_formula", "math_geometry"]
    fig2, axes2 = plt.subplots(2, 2, figsize=(14, 10))
    fig2.suptitle("Score Distribution by Task and Epoch — Specialised Types",
                  fontsize=16, fontweight="bold", y=1.01)

    for idx, task in enumerate(fig2_tasks):
        row, col = divmod(idx, 2)
        plot_task_axes(axes2[row, col], task, TASK_CONFIG[task], all_scores)

    # 外部图例
    legend_elements = [
        Patch(facecolor=EPOCH_COLORS[0], alpha=0.6, label=EPOCH_LABELS[0]),
        Patch(facecolor=EPOCH_COLORS[1], alpha=0.6, label=EPOCH_LABELS[1]),
        Patch(facecolor=EPOCH_COLORS[2], alpha=0.6, label=EPOCH_LABELS[2]),
    ]
    fig2.legend(handles=legend_elements, loc="center right",
                fontsize=12, title="Epoch", title_fontsize=13,
                framealpha=0.9)

    plt.tight_layout(rect=[0, 0, 0.85, 1])
    plt.savefig(OUTPUT_PATH2, dpi=200, bbox_inches="tight")
    print(f"图已保存: {OUTPUT_PATH2}")
    plt.close(fig2)


if __name__ == "__main__":
    main()