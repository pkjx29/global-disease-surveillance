"""Differentially private release of the weekly case counts.

Unit of privacy: one reported case (or death). A single case is counted in exactly one
cell of ``case_reports``: one disease, one country, one week. Adding or removing that case
changes ``new_cases`` in that one cell by 1, and, if the patient died, ``new_deaths`` in the
same cell by 1. So:

* sensitivity of the whole table = 2 in L1 norm (1 for cases + 1 for deaths), and also
  sqrt(1^2 + 1^2) = sqrt(2) in L2 norm;
* every cell holds different people, so the noise added to all ~119,000 cells together
  costs epsilon once, not once per cell (parallel composition).

Rounding the noisy numbers and clipping them at zero happen after the noise, so they use
no extra privacy budget (post-processing).

Randomness: a real release (no ``seed``) draws its noise from the operating system's
cryptographically secure generator (``secrets.SystemRandom``), so nobody can predict or
replay it. A ``seed`` switches to NumPy's reproducible generator, which is only for
experiments and tests.

What this does not cover: a person reported more than once (e.g. a COVID-19 reinfection)
is protected at k * epsilon for k reports; and the shape of the table (which country-weeks
exist, the ``reported`` flag) is treated as public.
"""

from __future__ import annotations

import secrets

import numpy as np
import pandas as pd

COUNT_COLUMNS = ["new_cases", "new_deaths"]
L1_SENSITIVITY = 2.0              # one case adds 1 to new_cases and at most 1 to new_deaths
L2_SENSITIVITY = np.sqrt(2.0)


def laplace_scale(epsilon: float, sensitivity: float = L1_SENSITIVITY) -> float:
    """Laplace noise scale b = sensitivity / epsilon (pure epsilon-DP)."""
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    return sensitivity / epsilon


def gaussian_sigma(epsilon: float, delta: float, sensitivity: float = L2_SENSITIVITY) -> float:
    """Classic Gaussian-mechanism sigma for (epsilon, delta)-DP (Dwork & Roth, Thm A.1).

    The formula is only proven for epsilon < 1.
    """
    if not 0 < epsilon < 1:
        raise ValueError("the classic Gaussian mechanism needs 0 < epsilon < 1")
    if not 0 < delta < 1:
        raise ValueError("delta must be between 0 and 1")
    return np.sqrt(2 * np.log(1.25 / delta)) * sensitivity / epsilon


def secure_noise(mechanism: str, scale: float, shape: tuple[int, int]) -> np.ndarray:
    """Noise from the operating system's secure random generator (for real releases)."""
    rng = secrets.SystemRandom()
    n = shape[0] * shape[1]
    if mechanism == "laplace":
        draws = [rng.expovariate(1.0) - rng.expovariate(1.0) for _ in range(n)]     # Exp(1) - Exp(1) ~ Laplace(0, 1)
    else:
        draws = [rng.gauss(0.0, 1.0) for _ in range(n)]
    return scale * np.array(draws).reshape(shape)


def release_case_counts(
    cases: pd.DataFrame,
    epsilon: float,
    mechanism: str = "laplace",
    delta: float = 1e-6,
    seed: int | None = None,
) -> pd.DataFrame:
    """Return a copy of ``cases`` with noisy, rounded, non-negative weekly counts.

    Only weeks a country actually reported are noised; unreported weeks stay at zero
    with ``reported = False`` so they are still never mistaken for real zeros.
    ``seed = None`` (the default) uses secure randomness; a seed gives reproducible noise.
    """
    if mechanism == "laplace":
        scale = laplace_scale(epsilon)
    elif mechanism == "gaussian":
        scale = gaussian_sigma(epsilon, delta)
    else:
        raise ValueError(f"unknown mechanism '{mechanism}'")

    out = cases.copy()
    reported = out["reported"].to_numpy(dtype=bool)
    shape = (int(reported.sum()), len(COUNT_COLUMNS))
    if seed is None:
        noise = secure_noise(mechanism, scale, shape)
    else:
        rng = np.random.default_rng(seed)
        noise = rng.laplace(0.0, scale, size=shape) if mechanism == "laplace" else rng.normal(0.0, scale, size=shape)

    true_counts = out.loc[reported, COUNT_COLUMNS].to_numpy(dtype=float)
    noisy = np.clip(np.round(true_counts + noise), 0, None)       # post-processing: free
    out[COUNT_COLUMNS] = out[COUNT_COLUMNS].astype("int64")
    out.loc[reported, COUNT_COLUMNS] = noisy.astype("int64")
    return out
