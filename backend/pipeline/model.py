"""XGBoost outbreak-risk model: train, evaluate out-of-time, score and persist."""

from __future__ import annotations

import json
import logging
import time

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import load
from .features import FEATURE_LABELS, FEATURES, build_panel
from .settings import HORIZON_WEEKS, MODEL_DIR, RISK_LEVELS, SURGE_RATIO, TRAIN_END

log = logging.getLogger(__name__)

PARAMS = {
    "n_estimators": 1500,
    "learning_rate": 0.03,
    "max_depth": 5,
    "min_child_weight": 10,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_lambda": 2.0,
    "tree_method": "hist",
    "eval_metric": "aucpr",
    "random_state": 42,
    "n_jobs": 4,
}
EARLY_STOPPING_ROUNDS = 100
VALIDATION_WEEKS = 26
ROLLING_YEARS = [2021, 2022, 2023, 2024, 2025]


# -------------------------------------------------------------------------- data
def read_inputs(engine: Engine) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with engine.connect() as conn:
        cases = pd.read_sql(text("SELECT disease, iso3, week_start, new_cases, new_deaths, reported FROM case_reports"), conn)
        countries = pd.read_sql(text("SELECT iso3, name, population, lat, subregion FROM countries"), conn)
        neighbours = pd.read_sql(text("SELECT iso3, neighbour_iso3 FROM country_neighbours"), conn)
    for frame in (cases, countries, neighbours):
        for col in ("iso3", "neighbour_iso3"):
            if col in frame:
                frame[col] = frame[col].str.strip()
    return cases, countries, neighbours


def risk_level(probability: np.ndarray) -> np.ndarray:
    out = np.full(len(probability), RISK_LEVELS[-1][0], dtype=object)
    for name, floor in reversed(RISK_LEVELS):
        out[probability >= floor] = name
    return out


# -------------------------------------------------------------------- evaluation
def classification_metrics(y: np.ndarray, score: np.ndarray, probability: bool = True) -> dict:
    if len(y) == 0 or y.min() == y.max():
        return {"n": int(len(y)), "positives": int(y.sum())}
    out = {
        "n": int(len(y)),
        "positives": int(y.sum()),
        "prevalence": float(y.mean()),
        "roc_auc": float(roc_auc_score(y, score)),
        "pr_auc": float(average_precision_score(y, score)),
    }
    k = max(1, int(round(0.10 * len(y))))
    top = np.argsort(-score, kind="stable")[:k]
    out["capture_top_10pct"] = float(y[top].sum() / y.sum())
    out["precision_top_10pct"] = float(y[top].mean())
    if probability:
        out["brier"] = float(brier_score_loss(y, score))
        for name, floor in RISK_LEVELS[:3]:
            flagged = score >= floor
            out[f"precision_at_{name.lower()}"] = float(y[flagged].mean()) if flagged.any() else None
            out[f"recall_at_{name.lower()}"] = float(y[flagged].sum() / y.sum())
    return out


def fit_xgb(train: pd.DataFrame, n_estimators: int | None = None) -> xgb.XGBClassifier:
    """Fit with early stopping on the most recent ``VALIDATION_WEEKS`` of the training period."""
    params = dict(PARAMS)
    if n_estimators is not None:              # tree count already chosen: use all the data
        params["n_estimators"] = n_estimators
        return xgb.XGBClassifier(**params).fit(train[FEATURES], train["label"])
    cut = train["week_start"].max() - pd.Timedelta(weeks=VALIDATION_WEEKS)
    fit, val = train[train["week_start"] <= cut], train[train["week_start"] > cut]
    model = xgb.XGBClassifier(**params, early_stopping_rounds=EARLY_STOPPING_ROUNDS)
    model.fit(fit[FEATURES], fit["label"], eval_set=[(val[FEATURES], val["label"])], verbose=False)
    return model


def rolling_origin(labelled: pd.DataFrame, n_estimators: int) -> list[dict]:
    """Re-train before each year and test on that year: is performance stable over time?"""
    folds = []
    for year in ROLLING_YEARS:
        start = pd.Timestamp(year=year, month=1, day=1)
        train = labelled[labelled["week_start"] < start - pd.Timedelta(weeks=HORIZON_WEEKS)]
        test = labelled[(labelled["week_start"] >= start) & (labelled["week_start"] < start + pd.DateOffset(years=1))]
        if len(train) < 5000 or test["label"].sum() < 20:
            continue
        model = fit_xgb(train, n_estimators=n_estimators)
        proba = model.predict_proba(test[FEATURES])[:, 1]
        m = classification_metrics(test["label"].to_numpy(), proba)
        folds.append({"test_year": year, "train_rows": int(len(train)), **{k: m[k] for k in ("n", "positives", "roc_auc", "pr_auc")}})
    return folds


def top_drivers(model: xgb.XGBClassifier, X: pd.DataFrame, k: int = 3) -> list[list[dict]]:
    """The k features pushing each prediction furthest from the base rate (SHAP values)."""
    contrib = model.get_booster().predict(xgb.DMatrix(X, feature_names=FEATURES), pred_contribs=True)[:, :-1]
    order = np.argsort(-np.abs(contrib), axis=1)[:, :k]
    values = X.to_numpy(dtype=float)
    out = []
    for i, idx in enumerate(order):
        out.append(
            [
                {
                    "feature": FEATURES[j],
                    "label": FEATURE_LABELS[FEATURES[j]],
                    "effect": "raises" if contrib[i, j] > 0 else "lowers",
                    "shap": round(float(contrib[i, j]), 3),
                    "value": None if np.isnan(values[i, j]) else round(float(values[i, j]), 3),
                }
                for j in idx
            ]
        )
    return out


# -------------------------------------------------------------------------- main
def run(engine: Engine | None = None) -> dict:
    """Train on data up to TRAIN_END, evaluate on everything after, store scores for the dashboard."""
    engine = engine or load.get_engine()
    t0 = time.time()
    cases, countries, neighbours = read_inputs(engine)
    panel = build_panel(cases, countries, neighbours)
    log.info("panel: %d rows, %d series (%.0f s)", len(panel), panel.groupby(["disease", "iso3"]).ngroups, time.time() - t0)

    train_end = pd.Timestamp(TRAIN_END)
    labelled = panel[panel["label_valid"]]
    train = labelled[labelled["week_start"] <= train_end - pd.Timedelta(weeks=HORIZON_WEEKS)]
    test = labelled[labelled["week_start"] > train_end]
    log.info("train %d rows (%.1f%% positive) | test %d rows (%.1f%% positive)", len(train), 100 * train.label.mean(), len(test), 100 * test.label.mean())

    model = fit_xgb(train)
    y_test = test["label"].to_numpy()
    proba = model.predict_proba(test[FEATURES])[:, 1]

    # baselines on the same held-out period
    persistence = classification_metrics(y_test, test["growth_4w"].fillna(0).to_numpy(), probability=False)
    logit = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(max_iter=2000, C=0.5))
    logit.fit(train[FEATURES], train["label"])
    logit_metrics = classification_metrics(y_test, logit.predict_proba(test[FEATURES])[:, 1])

    metrics = {
        "definition": f"cases at least x{SURGE_RATIO:g} over the next {HORIZON_WEEKS} weeks and above a minimum size",
        "train_end": TRAIN_END,
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "test_period": [str(test["week_start"].min().date()), str(test["week_start"].max().date())],
        "best_iteration": int(model.best_iteration),
        "xgboost": classification_metrics(y_test, proba),
        "by_disease": {
            disease: classification_metrics(group["label"].to_numpy(), proba[(test["disease"] == disease).to_numpy()])
            for disease, group in test.groupby("disease")
        },
        "baseline_persistence": persistence,
        "baseline_logistic_regression": logit_metrics,
        "rolling_origin": rolling_origin(labelled, n_estimators=int(model.best_iteration) + 1),
    }
    log.info(
        "held-out %s..%s | XGBoost ROC-AUC %.3f PR-AUC %.3f | logistic PR-AUC %.3f | persistence PR-AUC %.3f | base rate %.3f",
        *metrics["test_period"],
        metrics["xgboost"]["roc_auc"],
        metrics["xgboost"]["pr_auc"],
        logit_metrics["pr_auc"],
        persistence["pr_auc"],
        metrics["xgboost"]["prevalence"],
    )

    booster = model.get_booster()
    gain = booster.get_score(importance_type="gain")
    total_gain = sum(gain.values()) or 1.0
    shap_abs = np.abs(booster.predict(xgb.DMatrix(test[FEATURES], feature_names=FEATURES), pred_contribs=True)[:, :-1]).mean(axis=0)
    importance = sorted(
        (
            {"feature": f, "label": FEATURE_LABELS[f], "gain": round(gain.get(f, 0.0) / total_gain, 4), "mean_abs_shap": round(float(s), 4)}
            for f, s in zip(FEATURES, shap_abs, strict=True)
        ),
        key=lambda r: -r["mean_abs_shap"],
    )

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(MODEL_DIR / "outbreak_xgb.json")
    metadata = {"features": FEATURES, "metrics": metrics, "feature_importance": importance}
    (MODEL_DIR / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    # ---- score every usable week after the training cut-off (all out-of-sample)
    to_score = panel[panel["feature_valid"] & (panel["week_start"] > train_end)].copy()
    to_score["risk_probability"] = model.predict_proba(to_score[FEATURES])[:, 1]
    to_score["risk_level"] = risk_level(to_score["risk_probability"].to_numpy())
    to_score["top_drivers"] = [json.dumps(d) for d in top_drivers(model, to_score[FEATURES])]
    to_score["outcome"] = to_score["label"].where(to_score["label_valid"]).astype("Int64")

    params = {k: v for k, v in PARAMS.items() if k != "n_jobs"} | {"best_iteration": int(model.best_iteration)}
    with engine.begin() as conn:
        conn.execute(text("UPDATE model_runs SET is_active = false"))
        run_id = conn.execute(
            text(
                """INSERT INTO model_runs (algorithm, horizon_weeks, train_end, params, metrics, feature_importance, is_active)
                   VALUES ('XGBoost (gradient-boosted trees)', :h, :te, CAST(:p AS jsonb), CAST(:m AS jsonb), CAST(:fi AS jsonb), true)
                   RETURNING run_id"""
            ),
            {"h": HORIZON_WEEKS, "te": TRAIN_END, "p": json.dumps(params), "m": json.dumps(metrics), "fi": json.dumps(importance)},
        ).scalar_one()

    scores = pd.DataFrame(
        {
            "run_id": run_id,
            "disease": to_score["disease"],
            "iso3": to_score["iso3"],
            "week_start": to_score["week_start"].dt.date,
            "risk_probability": to_score["risk_probability"].round(4),
            "risk_level": to_score["risk_level"],
            "cases_4w": to_score["cases_4w"].astype(int),
            "incidence_4w": to_score["incidence_4w"].round(3),
            "growth_4w": np.expm1(to_score["growth_4w"]).round(3) + 1,      # back to a plain ratio
            "top_drivers": to_score["top_drivers"],
            "outcome": to_score["outcome"],
        }
    )
    load.upsert(engine, "risk_scores", scores, ["run_id", "disease", "iso3", "week_start"])
    log.info("model run %d stored: %d risk scores, levels %s", run_id, len(scores), scores["risk_level"].value_counts().to_dict())
    return metrics
