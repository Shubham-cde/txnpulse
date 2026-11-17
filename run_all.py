"""Reproduce every table, chart and report section from the raw Kaggle CSVs.

Usage: .venv\\Scripts\\python.exe run_all.py
Needs data/fraudTrain.csv and data/fraudTest.csv. Stops at the first failing step.
"""

import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

STEPS = [
    ("data quality checks and train-only EDA", ["src/profile_data.py"]),
    ("R8 merchant risk list from train", ["src/build_risk_list.py"]),
    ("rules, metrics and sweeps on train", ["src/run_rules.py", "--period", "train"]),
    ("frozen rules on test (PVT)", ["src/run_rules.py", "--period", "test"]),
    ("train vs test comparison", ["src/compare_pvt.py"]),
    ("charts", ["src/make_figures.py"]),
    ("ML alert ranker (validation inside train, test scored once)", ["ml/train_ranker.py"]),
    ("threshold-gaming test", ["ml/gaming_test.py"]),
    ("ML charts", ["ml/make_ml_figures.py"]),
    ("Power BI extracts", ["dashboards/build_extracts.py"]),
    ("example Excel MIS (test, 2020-12-24)", ["mis/build_mis.py", "--period", "test", "--date", "2020-12-24"]),
    ("UAT cases and report table", ["src/run_uat.py"]),
    ("pytest suite", ["-m", "pytest", "tests", "-q"]),
]


def check_data():
    missing = [name for name in ("fraudTrain.csv", "fraudTest.csv") if not (REPO_ROOT / "data" / name).exists()]
    if missing:
        sys.exit(f"missing in data/: {', '.join(missing)} (download the Kaggle files first)")


def main():
    check_data()
    started = time.perf_counter()
    for number, (label, args) in enumerate(STEPS, start=1):
        print(f"[{number}/{len(STEPS)}] {label}", flush=True)
        result = subprocess.run([sys.executable, *args], cwd=REPO_ROOT)
        if result.returncode != 0:
            sys.exit(f"step failed: {label}")
    print(f"done in {time.perf_counter() - started:.0f} s; results in outputs/ (including outputs/mis/), dashboards/extracts/, reports/figures/, ml/figures/ and reports/uat_report.md")


if __name__ == "__main__":
    main()
