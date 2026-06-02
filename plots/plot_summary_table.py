"""
绘制汇总表：所有任务 × 所有 epoch 的 Pass Rate 和 Avg/Median Score
"""

import json
import os
import matplotlib.pyplot as plt
import numpy as np

# ── 配置 ──────────────────────────────────────────────
PLOTS_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PLOTS_DIR, "data")
OUTPUT_DIR = os.path.join(PLOTS_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

OUTPUT_PATH = os.path.join(OUTPUT_DIR, "summary_table.png")

ALL_TASKS = ["easy", "medium", "difficult", "chart_plot", "pure_drawing",
             "math_formula", "math_geometry"]
EPOCHS = [0, 1, 2]

TASK_LABELS = {
    "easy":         "Easy",
    "medium":       "Medium",
    "difficult":    "Difficult",
    "chart_plot":   "Chart/Plot",
    "pure_drawing": "Pure Drawing",
    "math_formula": "Math Formula",
    "math_geometry":"Math Geometry",
}


def load_metrics(task: str, epoch: int) -> dict | None:
    """加载单个 JSON 并计算指标"""
    fname = f"{task}{epoch}.json"
    fpath = os.path.join(DATA_DIR, fname)
    if not os.path.exists(fpath):
        return None
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)

    samples = data.get("samples", [])
    if not samples:
        return None

    n = len(samples)
    compile_ok = sum(1 for s in samples if s.get("compile_ok", False))
    compile_rate = compile_ok / n * 100

    judged = [s for s in samples if s.get("score") is not None and s.get("compile_ok")]
    if judged:
        scores = [s["score"] for s in judged]
        avg_score = np.mean(scores)
        median_score = np.median(scores)
        pass_count = sum(1 for s in scores if s >= 3.0)
        pass_rate = pass_count / len(scores) * 100
    else:
        avg_score = median_score = pass_rate = 0.0

    return {
        "n": n,
        "compile_rate": compile_rate,
        "avg_score": avg_score,
        "median_score": median_score,
        "pass_rate": pass_rate,
    }


def main():
    # ── 收集数据 ──
    all_metrics = {}
    for task in ALL_TASKS:
        all_metrics[task] = {}
        for ep in EPOCHS:
            m = load_metrics(task, ep)
            if m:
                all_metrics[task][ep] = m
                print(f"  {TASK_LABELS[task]} ep{ep}: pass={m['pass_rate']:.2f}%, "
                      f"avg={m['avg_score']:.2f}, n={m['n']}")
            else:
                all_metrics[task][ep] = None

    # ── 构建表格数据 ──
    col_labels = ["Task", "n",
                  "E0 Pass%", "E0 Avg", "E0 Med",
                  "E1 Pass%", "E1 Avg", "E1 Med",
                  "E2 Pass%", "E2 Avg", "E2 Med"]

    table_data = []
    for task in ALL_TASKS:
        row = [TASK_LABELS[task]]
        first_ep = next((ep for ep in EPOCHS if all_metrics[task][ep] is not None), None)
        if first_ep is not None:
            row.append(str(all_metrics[task][first_ep]["n"]))
        else:
            row.append("—")

        for ep in EPOCHS:
            m = all_metrics[task][ep]
            if m:
                row.append(f"{m['pass_rate']:.2f}%")
                row.append(f"{m['avg_score']:.2f}")
                row.append(f"{m['median_score']:.1f}")
            else:
                row.extend(["—", "—", "—"])
        table_data.append(row)

    # ── 绘图 ──
    fig, ax = plt.subplots(figsize=(16, 6.5))
    ax.axis("off")

    table = ax.table(
        cellText=table_data,
        colLabels=col_labels,
        cellLoc="center",
        loc="center",
    )

    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.6)

    # 颜色
    header_color = "#2C3E50"
    header_text_color = "white"
    epoch_colors = ["#E8F0FE", "#FFF3E0", "#FDE0DD"]

    n_rows = len(table_data) + 1
    n_cols = len(col_labels)

    for i in range(n_rows):
        for j in range(n_cols):
            cell = table[i, j]
            cell.set_linewidth(0.5)
            cell.set_edgecolor("#D5D8DC")

            if i == 0:
                cell.set_facecolor(header_color)
                cell.set_text_props(color=header_text_color, fontweight="bold", fontsize=11)
            else:
                if j == 0 or j == 1:
                    cell.set_facecolor("#F8F9FA")
                    if j == 0:
                        cell.set_text_props(fontweight="bold", fontsize=10)
                else:
                    col_group = (j - 2) // 3
                    if col_group < len(epoch_colors):
                        cell.set_facecolor(epoch_colors[col_group])

            if j == 0 and i > 0:
                cell.get_text().set_horizontalalignment("left")

    # 列宽
    col_widths = [0.10, 0.04] + [0.06, 0.06, 0.06] * 3
    for j, w in enumerate(col_widths):
        for i in range(n_rows):
            table[i, j].set_width(w)

    ax.set_title("Summary Table — All Tasks × All Epochs",
                 fontsize=16, fontweight="bold", pad=30)

    fig.text(0.5, 0.06,
             "Pass% = score ≥ 3.0 / total judged (compile_ok) samples    Avg = mean score    Med = median score",
             ha="center", fontsize=9, color="gray", fontstyle="italic")

    plt.tight_layout()
    plt.savefig(OUTPUT_PATH, dpi=200, bbox_inches="tight")
    print(f"\n表已保存: {OUTPUT_PATH}")
    plt.close()


if __name__ == "__main__":
    main()