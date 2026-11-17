"""Charts for the ML alert-ranking report, written to ml/figures/.

Usage: .venv\\Scripts\\python.exe ml/make_ml_figures.py   (after ml/train_ranker.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import json  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

import make_figures as style  # noqa: E402  (sets the shared chart style on import)
from db import OUTPUT_DIR  # noqa: E402

FIGURE_DIR = Path(__file__).resolve().parent / "figures"
ML_OUT = OUTPUT_DIR / "ml"

METHOD_LABELS = {
    "model_score": "model score",
    "rules_fired": "rules fired",
    "strongest_action": "strongest action",
    "amount": "amount",
}
# Fixed order and colours; aqua and yellow are below 3:1 contrast, so every bar is labelled.
METHOD_COLOURS = {
    "model_score": "#2a78d6",
    "rules_fired": "#eb6834",
    "strongest_action": "#1baf7a",
    "amount": "#eda100",
}


def save(fig, name):
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE_DIR / name, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote ml/figures/{name}")


def queue_comparison(level, filename, title):
    documented = json.loads((ML_OUT / "model_decision.json").read_text(encoding="utf-8"))["documented_model"]
    rankings = pd.read_csv(ML_OUT / f"test_rankings_{documented}.csv")
    rankings = rankings[rankings["level"] == level]
    queue_sizes = sorted(rankings["k"].unique())
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8))
    width = 0.2
    for ax, metric, label in ((axes[0], "precision_at_k_pct", "Precision@K (%)"),
                              (axes[1], "value_at_k_queue_pct", "Value@K: share of fraud value in the alert queue (%)")):
        for offset, method in enumerate(METHOD_LABELS):
            rows = rankings[rankings["method"] == method].set_index("k").loc[queue_sizes]
            xs = [i + (offset - 1.5) * width for i in range(len(queue_sizes))]
            bars = ax.bar(xs, rows[metric], width=width * 0.92, color=METHOD_COLOURS[method],
                          label=METHOD_LABELS[method])
            for bar, value in zip(bars, rows[metric]):
                ax.annotate(f"{value:.0f}", (bar.get_x() + bar.get_width() / 2, value), xytext=(0, 2),
                            textcoords="offset points", ha="center", fontsize=7, color=style.TEXT)
        ax.set_xticks(range(len(queue_sizes)), [f"K = {k} per day" for k in queue_sizes])
        ax.set_title(label, loc="left")
        ax.set_ylim(0, 108)
        ax.grid(axis="x", visible=False)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", ncol=4)
    fig.suptitle(title, x=0.01, ha="left", color=style.TEXT, fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    save(fig, filename)


def shap_importance():
    importance = pd.read_csv(ML_OUT / "shap_importance.csv", index_col=0)["mean_abs_shap"]
    importance = importance[importance > 0].sort_values()
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.barh(importance.index, importance.values, color=style.V2_BLUE, height=0.6)
    for y, value in enumerate(importance.values):
        ax.annotate(f"{value:.2f}", (value, y), xytext=(3, 0), textcoords="offset points",
                    va="center", fontsize=7, color=style.TEXT)
    ax.set_xlabel("mean |SHAP| on test alerts (log-odds)")
    ax.set_title("What the ranker relies on", loc="left")
    ax.grid(axis="y", visible=False)
    save(fig, "ml_shap_importance.png")


def main():
    queue_comparison("alert", "ml_queue_alert_level.png", "Test period: daily alert queue by ranking method")
    queue_comparison("case", "ml_queue_case_level.png",
                     "Test period: daily case queue by ranking method (ranked by each case's opening alert)")
    shap_importance()


if __name__ == "__main__":
    main()
