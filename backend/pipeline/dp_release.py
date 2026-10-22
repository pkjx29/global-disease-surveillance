"""Publish a differentially private copy of ``case_reports`` and keep a budget ledger.

Each release of the same counts leaks a little more, so the epsilons (and deltas) of all
releases add up (basic sequential composition). Before releasing, the ledger in
``dp_release_runs`` is summed; a release that would take the total over
``DP_TOTAL_EPSILON`` / ``DP_TOTAL_DELTA`` is refused before any noise is drawn.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .model import read_inputs
from .privacy import L1_SENSITIVITY, L2_SENSITIVITY, release_case_counts
from .settings import DP_TOTAL_DELTA, DP_TOTAL_EPSILON

log = logging.getLogger(__name__)

PRIVACY_UNIT = "one reported case (adds 1 to new_cases and at most 1 to new_deaths in one disease-country-week cell)"


class BudgetExceeded(RuntimeError):
    pass


def budget_spent(engine: Engine) -> tuple[float, float]:
    with engine.connect() as conn:
        eps, delta = conn.execute(text("SELECT coalesce(sum(epsilon), 0), coalesce(sum(delta), 0) FROM dp_release_runs")).one()
    return float(eps), float(delta)


def release(
    engine: Engine,
    epsilon: float,
    out_path: Path,
    mechanism: str = "laplace",
    delta: float = 1e-6,
    total_epsilon: float = DP_TOTAL_EPSILON,
    total_delta: float = DP_TOTAL_DELTA,
) -> dict:
    """Check the budget, write the noisy CSV plus a metadata file, and record the release."""
    delta = 0.0 if mechanism == "laplace" else delta           # Laplace is pure epsilon-DP
    spent_eps, spent_delta = budget_spent(engine)
    if spent_eps + epsilon > total_epsilon + 1e-12 or spent_delta + delta > total_delta + 1e-15:
        raise BudgetExceeded(
            f"release refused: epsilon {spent_eps:g} + {epsilon:g} > {total_epsilon:g} or delta {spent_delta:g} + {delta:g} > {total_delta:g}"
        )

    cases, _, _ = read_inputs(engine)
    released = release_case_counts(cases, epsilon, mechanism=mechanism, delta=delta or 1e-6)     # no seed: secure randomness
    out_path = Path(out_path)
    released.to_csv(out_path, index=False)
    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()

    meta = {
        "mechanism": mechanism,
        "epsilon": epsilon,
        "delta": delta,
        "privacy_unit": PRIVACY_UNIT,
        "adjacency": "add or remove one reported case",
        "sensitivity": L1_SENSITIVITY if mechanism == "laplace" else float(L2_SENSITIVITY),
        "sensitivity_norm": "L1" if mechanism == "laplace" else "L2",
        "composition": "parallel across cells (each case is in one cell); sequential (summed) across releases",
        "cells": int(cases["reported"].sum()),
        "data_through": str(pd.to_datetime(cases["week_start"]).max().date()),
        "output_sha256": digest,
        "budget_after_release": {"epsilon": spent_eps + epsilon, "delta": spent_delta + delta, "total_epsilon": total_epsilon, "total_delta": total_delta},
    }
    out_path.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    with engine.begin() as conn:
        meta["release_id"] = conn.execute(
            text(
                """INSERT INTO dp_release_runs (mechanism, epsilon, delta, privacy_unit, sensitivity, cells, data_through, output_sha256)
                   VALUES (:mechanism, :epsilon, :delta, :privacy_unit, :sensitivity, :cells, :data_through, :output_sha256)
                   RETURNING release_id"""
            ),
            {k: meta[k] for k in ("mechanism", "epsilon", "delta", "privacy_unit", "sensitivity", "cells", "data_through", "output_sha256")},
        ).scalar_one()
    log.info("release %d: %d cells, epsilon %g, total spent %g of %g", meta["release_id"], meta["cells"], epsilon, spent_eps + epsilon, total_epsilon)
    return meta
