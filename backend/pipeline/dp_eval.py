"""What does differential privacy cost the outbreak-risk model?

For each epsilon the weekly counts are released with the Laplace mechanism
(``privacy.release_case_counts``) and the model is evaluated two ways:

* **retrain** - a data user who only has the noisy release builds the features, the
  training labels and the XGBoost model from it. Everything is derived from the DP output,
  so the whole result is epsilon-DP.
* **rescore** - the existing model (trained on the true counts) scores features built from
  the noisy counts. This shows how sensitive the model is to noisy inputs, but the model
  itself saw the true data, so this path is *not* private end to end.

In both cases the test labels come from the true counts: the question is how well the
model predicts the outbreaks that really happened. Each epsilon is repeated with several
noise seeds because one draw of noise can be lucky or unlucky.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import load
from .dp_release import PRIVACY_UNIT
from .features import FEATURES, build_panel
from .model import classification_metrics, fit_xgb, read_inputs
from .privacy import L1_SENSITIVITY, release_case_counts
from .settings import BACKEND_ROOT, HORIZON_WEEKS, TRAIN_END

log = logging.getLogger(__name__)

EPSILONS = [0.1, 0.25, 0.5, 1.0, 2.0, 4.0]
SEEDS = [0, 1, 2]
KEY = ["disease", "iso3", "week_start"]
OUT_DIR = BACKEND_ROOT.parent / "docs" / "dp"


def split(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Same out-of-time split as ``model.run``: train up to TRAIN_END, test after it."""
    train_end = pd.Timestamp(TRAIN_END)
    labelled = panel[panel["label_valid"]]
    train = labelled[labelled["week_start"] <= train_end - pd.Timedelta(weeks=HORIZON_WEEKS)]
    test = labelled[labelled["week_start"] > train_end]
    return train, test


def scores(test: pd.DataFrame, true_label: pd.Series, proba: np.ndarray) -> dict:
    """ROC-AUC and average precision, overall and for mpox, against the true labels."""
    y = true_label.to_numpy()
    mpox = (test["disease"] == "mpox").to_numpy()
    overall, small = classification_metrics(y, proba), classification_metrics(y[mpox], proba[mpox])
    return {"roc_auc": overall["roc_auc"], "pr_auc": overall["pr_auc"], "mpox_roc_auc": small["roc_auc"], "mpox_pr_auc": small["pr_auc"]}


def count_error(true_cases: pd.DataFrame, noisy_cases: pd.DataFrame) -> dict:
    """How far the released counts are from the truth, per disease (reported weeks only)."""
    reported = true_cases["reported"].to_numpy(dtype=bool)
    diff = (noisy_cases["new_cases"] - true_cases["new_cases"]).abs()[reported]
    out = {}
    for disease, err in diff.groupby(true_cases.loc[reported, "disease"]):
        truth = true_cases.loc[err.index, "new_cases"]
        out[disease] = {
            "median_true_count": float(truth.median()),
            "mean_abs_error": round(float(err.mean()), 2),
            # true zero weeks that the release shows as having cases
            "share_zero_weeks_shown_nonzero": round(float((noisy_cases.loc[err.index, "new_cases"][truth == 0] > 0).mean()), 3),
        }
    return out


def run(engine=None, epsilons: list[float] = EPSILONS, seeds: list[int] = SEEDS, out_dir: Path = OUT_DIR) -> pd.DataFrame:
    engine = engine or load.get_engine()
    t0 = time.time()
    cases, countries, neighbours = read_inputs(engine)
    cases["week_start"] = pd.to_datetime(cases["week_start"])

    # non-private baseline: exactly what model.run trains
    train, test = split(build_panel(cases, countries, neighbours))
    baseline_model = fit_xgb(train)
    truth = test[KEY + ["label"]]
    rows = [{"epsilon": np.inf, "seed": None, "mode": "baseline", **scores(test, test["label"], baseline_model.predict_proba(test[FEATURES])[:, 1])}]
    log.info("baseline: ROC-AUC %.3f, AP %.3f", rows[0]["roc_auc"], rows[0]["pr_auc"])

    errors = {}
    for epsilon in epsilons:
        for seed in seeds:
            noisy_cases = release_case_counts(cases, epsilon, seed=seed)
            if seed == seeds[0]:
                errors[str(epsilon)] = count_error(cases, noisy_cases)
            noisy_train, noisy_test = split(build_panel(noisy_cases, countries, neighbours))
            # the validity flags depend only on the reported flag, so the rows match the baseline
            noisy_test = noisy_test.merge(truth.rename(columns={"label": "true_label"}), on=KEY, how="inner", validate="one_to_one")
            assert len(noisy_test) == len(test)

            rescored = baseline_model.predict_proba(noisy_test[FEATURES])[:, 1]
            rows.append({"epsilon": epsilon, "seed": seed, "mode": "rescore", **scores(noisy_test, noisy_test["true_label"], rescored)})
            retrained = fit_xgb(noisy_train).predict_proba(noisy_test[FEATURES])[:, 1]
            rows.append({"epsilon": epsilon, "seed": seed, "mode": "retrain", **scores(noisy_test, noisy_test["true_label"], retrained)})
            log.info("epsilon %-5g seed %d | rescore ROC-AUC %.3f | retrain ROC-AUC %.3f AP %.3f (%.0f s)",
                     epsilon, seed, rows[-2]["roc_auc"], rows[-1]["roc_auc"], rows[-1]["pr_auc"], time.time() - t0)

    results = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(out_dir / "dp_results.csv", index=False, float_format="%.4f")
    (out_dir / "count_error.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
    experiment = {
        "status": "experimental perturbation study of already-public aggregate counts, not a patient-level privacy release",
        "mechanism": "laplace",
        "epsilons": epsilons,
        "delta": 0.0,
        "seeds": seeds,
        "privacy_unit": PRIVACY_UNIT,
        "adjacency": "add or remove one reported case",
        "contribution_bound": "one cell; at most +1 new_cases and +1 new_deaths",
        "l1_sensitivity": L1_SENSITIVITY,
        "composition": "parallel across cells; each epsilon is a separate hypothetical release, so the grid itself is not one budget",
        "query_dimensions": {"cells": int(cases["reported"].sum()), "columns": ["new_cases", "new_deaths"]},
        "split": {
            "train_anchor_end": str((pd.Timestamp(TRAIN_END) - pd.Timedelta(weeks=HORIZON_WEEKS)).date()),
            "test_anchors": [str(test["week_start"].min().date()), str(test["week_start"].max().date())],
        },
        "test_rows": int(len(test)),
        "test_positives": int(test["label"].sum()),
        "test_mpox_rows": int((test["disease"] == "mpox").sum()),
        "test_mpox_positives": int(test.loc[test["disease"] == "mpox", "label"].sum()),
        "labels": "test labels always from the true counts",
    }
    (out_dir / "dp_experiment.json").write_text(json.dumps(experiment, indent=2), encoding="utf-8")
    summary = summarise(results)
    summary.to_csv(out_dir / "dp_summary.csv", index=False, float_format="%.3f")
    plot(summary, out_dir / "dp_accuracy.png")
    log.info("results written to %s\n%s", out_dir, summary.to_string(index=False))
    return results


def summarise(results: pd.DataFrame) -> pd.DataFrame:
    """Mean and standard deviation over the noise seeds, per epsilon and mode."""
    metrics = ["roc_auc", "pr_auc", "mpox_roc_auc", "mpox_pr_auc"]
    grouped = results.groupby(["mode", "epsilon"], sort=False)[metrics]
    summary = grouped.mean().join(grouped.std().fillna(0.0), rsuffix="_sd").reset_index()
    return summary.sort_values(["mode", "epsilon"]).reset_index(drop=True)


def plot(summary: pd.DataFrame, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    baseline = summary[summary["mode"] == "baseline"].iloc[0]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharex=True)
    panels = [("roc_auc", "mpox_roc_auc", "ROC-AUC"), ("pr_auc", "mpox_pr_auc", "Average precision")]
    for ax, (overall, mpox, title) in zip(axes, panels, strict=True):
        for mode, colour in (("retrain", "#1f6feb"), ("rescore", "#d29922")):
            part = summary[summary["mode"] == mode]
            ax.errorbar(part["epsilon"], part[overall], yerr=part[f"{overall}_sd"], color=colour, marker="o", capsize=3, label=f"all diseases, {mode}")
            ax.errorbar(part["epsilon"], part[mpox], yerr=part[f"{mpox}_sd"], color=colour, marker="s", linestyle=":", capsize=3, label=f"mpox only, {mode}")
        ax.axhline(baseline[overall], color="black", linestyle="--", linewidth=1, label="no privacy (all)")
        ax.axhline(baseline[mpox], color="grey", linestyle="--", linewidth=1, label="no privacy (mpox)")
        if overall == "roc_auc":
            ax.axhline(0.5, color="grey", linestyle=":", linewidth=1, label="random ranking")
        ax.set_xscale("log")
        ax.set_xlabel("privacy budget epsilon (log scale, smaller = more private)")
        ax.set_title(f"{title} on 2023-2026 (true outbreaks)")
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=7, loc="lower right")
    fig.suptitle("Outbreak-risk model trained on Laplace-noised weekly counts (mean +/- sd over 3 noise seeds)")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
