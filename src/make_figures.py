"""Draw the tuning and PVT charts from outputs/ into reports/figures/.

Usage: .venv\\Scripts\\python.exe src/make_figures.py
Needs outputs/train from run_rules.py --period train. PVT charts are drawn
only when outputs/test exists.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter, NullFormatter  # noqa: E402

from db import OUTPUT_DIR, REPO_ROOT  # noqa: E402

FIGURE_DIR = REPO_ROOT / "reports" / "figures"
ALERT_BUDGET_PER_DAY = 50

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_MUTED = "#52514e"
GRID = "#e4e3df"
OTHER_POINT = "#b9b8b2"
V2_BLUE = "#2a78d6"
V1_ORANGE = "#eb6834"
# Aqua is below 3:1 contrast on the light surface, so it is always direct-labelled.
CASES_AQUA = "#1baf7a"

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": GRID,
    "axes.labelcolor": TEXT_MUTED,
    "axes.titlecolor": TEXT,
    "axes.titlesize": 11,
    "axes.labelsize": 9,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "xtick.color": TEXT_MUTED,
    "ytick.color": TEXT_MUTED,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "font.size": 9,
    "legend.frameon": False,
    "legend.fontsize": 8,
})


def read(period, name):
    return pd.read_csv(OUTPUT_DIR / period / f"{name}.csv")


def save(fig, name):
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE_DIR / name, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote reports/figures/{name}")


def plain_log_x(ax):
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    ax.xaxis.set_minor_formatter(NullFormatter())


def mark_point(ax, row, color, label):
    ax.scatter(row["alerts_per_day"], row["txn_recall_pct"], s=55, color=color, zorder=3,
               edgecolors=SURFACE, linewidths=2, label=label)
    ax.annotate(label, (row["alerts_per_day"], row["txn_recall_pct"]), xytext=(6, 4),
                textcoords="offset points", fontsize=8, color=TEXT)


# Each sweep, with how to pick out the v1 and v2 rows.
SWEEPS = [
    ("R1 velocity (window min x count)", "r1_sweep",
     lambda d: (d.window_min == 60) & (d.min_count == 5), None),
    ("R2 amount spike (multiple x floor)", "r2_sweep",
     lambda d: (d.multiple == 5) & (d.min_amt == 0), None),
    ("R3 late night (amount)", "r3_sweep",
     lambda d: d.min_amt == 500, lambda d: d.min_amt == 600),
    ("R5 distance (km)", "r5_sweep",
     lambda d: d.min_km == 100, None),
    ("R6 new merchant (N x amount)", "r6_sweep",
     lambda d: (d.min_prior_txns == 10) & (d.min_amt == 300),
     lambda d: (d.min_prior_txns == 10) & (d.min_amt == 750)),
    ("R7 spend burst (window x multiple x floor x days)", "r7_sweep",
     lambda d: (d.window_hours == 24) & (d.multiple == 3) & (d.min_spend == 0) & (d.min_active_days == 7),
     lambda d: (d.window_hours == 48) & (d.multiple == 5) & (d.min_spend == 0) & (d.min_active_days == 7)),
]


def tuning_tradeoffs():
    fig, axes = plt.subplots(2, 3, figsize=(12, 7))
    for ax, (title, name, is_v1, is_v2) in zip(axes.flat, SWEEPS):
        sweep = read("train", name)
        ax.scatter(sweep["alerts_per_day"], sweep["txn_recall_pct"], s=30, color=OTHER_POINT,
                   label="other settings tested", zorder=2)
        mark_point(ax, sweep[is_v1(sweep)].iloc[0], V1_ORANGE, "v1")
        if is_v2 is not None:
            mark_point(ax, sweep[is_v2(sweep)].iloc[0], V2_BLUE, "v2")
        ax.set_title(title, loc="left")
        ax.set_xlabel("alerts per day")
        ax.set_ylabel("transaction recall (%)")
        plain_log_x(ax)
    handles, labels = axes.flat[-1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", ncol=3)
    fig.suptitle("Threshold sweeps on train: workload vs recall (log x axis)", x=0.01, ha="left",
                 color=TEXT, fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    save(fig, "tuning_sweep_tradeoffs.png")


def r4_by_category():
    sweep = read("train", "r4_sweep")
    v1 = {"shopping_net": 500, "misc_net": 500, "shopping_pos": 500, "grocery_pos": 300}
    v2 = {"shopping_net": 600, "misc_net": 600, "shopping_pos": 600, "grocery_pos": 250}
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.6), sharey=True)
    for ax, category in zip(axes, v1):
        rows = sweep[sweep.category == category].sort_values("min_amt")
        ax.plot(rows["min_amt"], rows["txn_recall_pct"], color=OTHER_POINT, linewidth=2, zorder=1)
        ax.scatter(rows["min_amt"], rows["txn_recall_pct"], s=30, color=OTHER_POINT, zorder=2)
        # v1 labels sit below their point and v2 labels above, so neighbours never collide.
        for amounts, color, label, dy in ((v1, V1_ORANGE, "v1", -14), (v2, V2_BLUE, "v2", 8)):
            row = rows[rows.min_amt == amounts[category]].iloc[0]
            ax.scatter(row["min_amt"], row["txn_recall_pct"], s=55, color=color, zorder=3,
                       edgecolors=SURFACE, linewidths=2, label=label)
            ax.annotate(f"{label}: {row['alerts_per_day']:.1f}/day", (row["min_amt"], row["txn_recall_pct"]),
                        xytext=(0, dy), textcoords="offset points", ha="center", fontsize=8, color=TEXT)
        ax.set_title(category, loc="left")
        ax.set_xlabel("amount threshold ($)")
    axes[0].set_ylabel("recall within all fraud (%)")
    axes[0].set_ylim(-1, 27)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", ncol=2)
    fig.suptitle("R4 per-category thresholds on train", x=0.01, ha="left", color=TEXT, fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    save(fig, "tuning_r4_by_category.png")


def r5_precision():
    # 150 km fires on 2 transactions only; too few to show a rate.
    sweep = read("train", "r5_sweep").sort_values("min_km")
    sweep = sweep[sweep.alerts >= 100].reset_index(drop=True)
    row_counts = pd.read_csv(OUTPUT_DIR / "dq" / "dq_row_counts.csv")
    base_rate = row_counts.loc[row_counts.file == "train", "fraud_rate_pct"].iloc[0]
    fig, ax = plt.subplots(figsize=(6, 3.4))
    ax.bar(sweep["min_km"].astype(str) + " km", sweep["precision_pct"], color=V2_BLUE, width=0.55)
    ax.axhline(base_rate, color=TEXT_MUTED, linewidth=1.5, linestyle="--")
    ax.annotate(f"train fraud rate {base_rate:.3f}%", (len(sweep) - 0.6, base_rate), xytext=(0, 6),
                textcoords="offset points", ha="right", fontsize=8, color=TEXT_MUTED)
    for x, row in sweep.iterrows():
        ax.annotate(f"{row['precision_pct']:.2f}%\n{row['alerts_per_day']:.0f}/day", (x, row["precision_pct"]),
                    xytext=(0, -26), textcoords="offset points", ha="center", fontsize=8, color=SURFACE)
    ax.grid(axis="x", visible=False)
    ax.set_ylabel("precision (%)")
    ax.set_title("R5 precision stays at or below the base rate", loc="left")
    save(fig, "tuning_r5_precision.png")


def candidate_sets():
    sets = read("train", "candidate_set_comparison").sort_values("set_name", ascending=False).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(9, 3.4))
    for y, row in sets.iterrows():
        color = V2_BLUE if row["set_name"].startswith("5 ") else OTHER_POINT
        ax.scatter(row["alerts_per_day"], y, s=70, color=color, zorder=3, edgecolors=SURFACE, linewidths=2)
        ax.text(1.03, y, f"{row['alerts_per_day']:.1f}/day   recall {row['txn_recall_pct']:.1f}%   "
                f"precision {row['precision_pct']:.1f}%", transform=ax.get_yaxis_transform(),
                va="center", fontsize=8, color=TEXT)
    ax.set_yticks(range(len(sets)), sets["set_name"].str[2:])
    ax.axvline(ALERT_BUDGET_PER_DAY, color=TEXT_MUTED, linewidth=1.5, linestyle="--", zorder=1)
    ax.text(ALERT_BUDGET_PER_DAY * 1.04, len(sets) - 0.55, f"budget {ALERT_BUDGET_PER_DAY}/day",
            fontsize=8, color=TEXT_MUTED)
    ax.set_ylim(-0.6, len(sets) - 0.3)
    plain_log_x(ax)
    ax.set_xlim(25, 1200)
    ax.set_xlabel("alerts per day (log scale)")
    ax.set_title("Combined rule sets on train", loc="left")
    ax.grid(axis="y", visible=False)
    save(fig, "tuning_candidate_sets.png")


def monthly_budget(period, title, filename):
    monthly = read(period, "monthly_active")
    monthly["month"] = pd.to_datetime(monthly["month"])
    fig, ax = plt.subplots(figsize=(8.5, 3.6))
    for column, color, label in (("alerts_per_day", V2_BLUE, "alerts per day"),
                                 ("cases_per_day", CASES_AQUA, "cases per day")):
        ax.plot(monthly["month"], monthly[column], color=color, linewidth=2, marker="o", markersize=5,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label=label)
        last = monthly.iloc[-1]
        ax.annotate(label, (last["month"], last[column]), xytext=(8, 0), textcoords="offset points",
                    va="center", fontsize=8, color=TEXT)
    ax.axhline(ALERT_BUDGET_PER_DAY, color=TEXT_MUTED, linewidth=1.5, linestyle="--")
    ax.annotate(f"budget {ALERT_BUDGET_PER_DAY}/day", (monthly["month"].iloc[0], ALERT_BUDGET_PER_DAY),
                xytext=(0, 5), textcoords="offset points", fontsize=8, color=TEXT_MUTED)
    peak = monthly.loc[monthly["alerts_per_day"].idxmax()]
    ax.annotate(f"{peak['month']:%b %Y}: {peak['alerts_per_day']:.1f} alerts, {peak['cases_per_day']:.1f} cases",
                (peak["month"], peak["alerts_per_day"]), xytext=(-8, 0), textcoords="offset points",
                ha="right", va="center", fontsize=8, color=TEXT)
    ax.set_ylim(0, max(monthly["alerts_per_day"].max(), ALERT_BUDGET_PER_DAY) * 1.15)
    ax.set_ylabel("per day")
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.12), ncol=2)
    ax.set_title(title, loc="left")
    save(fig, filename)


def main():
    tuning_tradeoffs()
    r4_by_category()
    r5_precision()
    candidate_sets()
    monthly_budget("train", "v2 active rule set on train: alerts and cases per day by month", "tuning_monthly_alerts_train.png")


if __name__ == "__main__":
    main()
