"""
Plot: 5 tasks × 3 epochs 的 Critic Pass Rate 和 Avg Fidelity Score
从各 JSON 文件中读取样本数据，计算两个指标，画在一张图上（双轴/双子图）。
"""

import json
import os
import matplotlib.pyplot as plt
import numpy as np

# ── 配置 ──────────────────────────────────────────────
PLOTS_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(PLOTS_DIR, "metrics_trend.png")

TASKS = ["easy", "medium", "difficult", "chart_plot", "pure_drawing",
          "math_formula", "math_geometry"]
EPOCHS = [0, 1, 2]

# 任务显示名 & 颜色
TASK_CONFIG = {
    "easy":         {"label": "Easy",           "color": "#2E86AB", "marker": "o"},
    "medium":       {"label": "Medium",         "color": "#A23B72", "marker": "s"},
    "difficult":    {"label": "Difficult",      "color": "#F18F01", "marker": "^"},
    "chart_plot":   {"label": "Chart/Plot",     "color": "#1B998B", "marker": "D"},
    "pure_drawing": {"label": "Pure Drawing",   "color": "#C73E1D", "marker": "v"},
    "math_formula": {"label": "Math Formula",   "color": "#6A4C93", "marker": "P"},
    "math_geometry":{"label": "Math Geometry",  "color": "#1982C4", "marker": "X"},
}


def load_metrics(task: str, epoch: int) -> dict:
    """从 JSON 文件加载并计算指标"""
    fname = f"{task}{epoch}.json"
    fpath = os.path.join(PLOTS_DIR, "data", fname)
    if not os.path.exists(fpath):
        print(f"  [WARN] 文件不存在: {fname}")
        return None

    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)

    samples = data.get("samples", [])
    n_total = len(samples)
    if n_total == 0:
        return None

    # Compile rate
    compile_ok = sum(1 for s in samples if s.get("compile_ok", False))
    compile_rate = compile_ok / n_total * 100

    # Avg compile attempts
    attempts = [s.get("compile_attempts", 0) for s in samples]
    avg_attempts = np.mean(attempts)

    # Critic pass rate (score >= 3.0 才算 pass)
    judged = [s for s in samples if s.get("score") is not None]
    critic_pass = sum(1 for s in judged if s.get("score", 0) >= 3.0)
    critic_pass_rate = critic_pass / len(judged) * 100 if judged else 0.0

    # Avg fidelity score
    scores = [s["score"] for s in judged if s["score"] is not None]
    avg_fidelity = np.mean(scores) if scores else 0.0

    return {
        "compile_rate": compile_rate,
        "avg_compile_attempts": avg_attempts,
        "critic_pass_rate": critic_pass_rate,
        "avg_fidelity_score": avg_fidelity,
        "n_total": n_total,
        "n_judged": len(judged),
    }


def main():
    # 收集数据
    all_data = {}  # task -> {epoch -> metrics}
    for task in TASKS:
        all_data[task] = {}
        for ep in EPOCHS:
            m = load_metrics(task, ep)
            if m is not None:
                all_data[task][ep] = m

    # ── 绘图 ──────────────────────────────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))
    fig.suptitle("Full Optimisation Results — Multi-task Trend",
                 fontsize=15, fontweight="bold", y=1.02)

    x = EPOCHS  # [0, 1, 2]

    # ── 左图: Critic Pass Rate ──
    ax1.set_title("Critic Pass Rate (score ≥ 3.0)", fontsize=12, pad=10)
    ax1.set_xlabel("Epoch", fontsize=11)
    ax1.set_ylabel("Critic Pass Rate (%)", fontsize=11)
    ax1.set_xticks(x)
    ax1.set_ylim(40, 100)
    ax1.grid(True, linestyle="--", alpha=0.4)

    for task in TASKS:
        cfg = TASK_CONFIG[task]
        epochs_data = all_data[task]
        y_vals = [epochs_data[ep]["critic_pass_rate"] for ep in EPOCHS if ep in epochs_data]
        x_vals = [ep for ep in EPOCHS if ep in epochs_data]
        if y_vals:
            ax1.plot(x_vals, y_vals, color=cfg["color"], marker=cfg["marker"],
                     linewidth=2.2, markersize=7, label=cfg["label"])
            # 在数据点旁标注数值
            for ep, val in zip(x_vals, y_vals):
                ax1.annotate(f"{val:.0f}%", (ep, val),
                             textcoords="offset points", xytext=(0, 12),
                             ha="center", fontsize=8, color=cfg["color"],
                             fontweight="bold")

    ax1.legend(fontsize=10, loc="upper left")

    # ── 右图: Avg Fidelity Score ──
    ax2.set_title("Average Fidelity Score (1.0 – 5.0)", fontsize=12, pad=10)
    ax2.set_xlabel("Epoch", fontsize=11)
    ax2.set_ylabel("Avg Fidelity Score", fontsize=11)
    ax2.set_xticks(x)
    ax2.set_ylim(2.4, 3.8)
    ax2.grid(True, linestyle="--", alpha=0.4)

    # 及格线
    ax2.axhline(y=3.0, color="gray", linestyle=":", linewidth=1.2, alpha=0.7)
    ax2.text(2.05, 3.02, "pass threshold (3.0)", fontsize=10, color="gray",
             fontstyle="italic")

    for task in TASKS:
        cfg = TASK_CONFIG[task]
        epochs_data = all_data[task]
        y_vals = [epochs_data[ep]["avg_fidelity_score"] for ep in EPOCHS if ep in epochs_data]
        x_vals = [ep for ep in EPOCHS if ep in epochs_data]
        if y_vals:
            ax2.plot(x_vals, y_vals, color=cfg["color"], marker=cfg["marker"],
                     linewidth=2.2, markersize=7, label=cfg["label"])
            for ep, val in zip(x_vals, y_vals):
                ax2.annotate(f"{val:.2f}", (ep, val),
                             textcoords="offset points", xytext=(0, 12),
                             ha="center", fontsize=8, color=cfg["color"],
                             fontweight="bold")

    ax2.legend(fontsize=10, loc="upper left")

    # ── 底部信息 ──
    fig.text(0.5, -0.02,
             "Data source: plots/data/*.json | Critic: Qwen3-VL (score ≥ 3.0 = pass)",
             ha="center", fontsize=9, color="gray", fontstyle="italic")

    plt.tight_layout()
    plt.savefig(OUTPUT_PATH, dpi=200, bbox_inches="tight")
    print(f"图已保存: {OUTPUT_PATH}")
    plt.close()

    # ── 打印汇总表 ──
    print()
    print("=" * 80)
    print(f"{'Task':<15} {'Epoch':<8} {'Compile%':<10} {'CriticPass%':<15} {'AvgScore':<10} {'n':<6}")
    print("-" * 80)
    for task in TASKS:
        for ep in EPOCHS:
            if ep in all_data[task]:
                d = all_data[task][ep]
                print(f"{TASK_CONFIG[task]['label']:<15} {ep:<8} "
                      f"{d['compile_rate']:<10.1f} {d['critic_pass_rate']:<15.1f} "
                      f"{d['avg_fidelity_score']:<10.2f} {d['n_total']:<6}")
    print("=" * 80)


if __name__ == "__main__":
    main()
