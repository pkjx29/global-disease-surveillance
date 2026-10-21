"""Differentially private release: noise size, post-processing and the DP guarantee itself."""

import numpy as np
import pandas as pd
import pytest

from pipeline.privacy import L1_SENSITIVITY, gaussian_sigma, laplace_scale, release_case_counts


def make_cases(n: int, new_cases: int = 1000, reported: bool = True, new_deaths: int | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "disease": ["covid19"] * n,
            "iso3": "AAA",
            "week_start": pd.Timestamp("2022-01-03"),        # the release never looks at dates
            "new_cases": new_cases,
            "new_deaths": new_cases // 10 if new_deaths is None else new_deaths,
            "reported": reported,
        }
    )


def test_laplace_noise_has_the_documented_scale():
    cases = make_cases(50_000)                          # large counts: clipping at zero never happens
    noise = release_case_counts(cases, epsilon=1.0, seed=0)["new_cases"] - cases["new_cases"]
    b = laplace_scale(1.0)                              # 2 / 1 = 2
    assert b == L1_SENSITIVITY
    assert abs(noise.mean()) < 0.05
    assert noise.std() == pytest.approx(np.sqrt(2) * b, rel=0.03)   # Laplace(b) has sd sqrt(2) b


def test_smaller_epsilon_means_more_noise():
    cases = make_cases(20_000)
    err = {eps: (release_case_counts(cases, eps, seed=1)["new_cases"] - cases["new_cases"]).abs().mean() for eps in (0.1, 1.0, 10.0)}
    assert err[0.1] > err[1.0] > err[10.0]


def test_output_is_whole_non_negative_counts_and_input_is_untouched():
    cases = make_cases(5_000, new_cases=0)              # zero counts: half the noise draws are negative
    before = cases.copy()
    noisy = release_case_counts(cases, epsilon=0.5, seed=2)
    pd.testing.assert_frame_equal(cases, before)
    assert (noisy[["new_cases", "new_deaths"]] >= 0).all().all()
    assert noisy["new_cases"].dtype == "int64"
    assert (noisy["new_cases"] > 0).any()               # zeros are not always released as zeros


def test_unreported_weeks_stay_unreported_zeros():
    cases = pd.concat([make_cases(10), make_cases(10, new_cases=0, reported=False)], ignore_index=True)
    noisy = release_case_counts(cases, epsilon=0.1, seed=3)
    gap = noisy[~noisy["reported"]]
    assert len(gap) == 10 and (gap[["new_cases", "new_deaths"]] == 0).all().all()


def test_same_seed_reproduces_and_different_seed_does_not():
    cases = make_cases(100)
    a, b, c = (release_case_counts(cases, 1.0, seed=s) for s in (7, 7, 8))
    pd.testing.assert_frame_equal(a, b)
    assert not a.equals(c)


def test_neighbouring_tables_are_hard_to_tell_apart():
    """The DP definition, checked empirically on the worst-case neighbour: one extra case who also died.

    Every released (cases, deaths) pair must be at most e^epsilon times more likely with that
    person than without them.
    """
    epsilon, draws = 1.0, 400_000
    without = release_case_counts(make_cases(draws, new_cases=50, new_deaths=5), epsilon, seed=10)
    with_one = release_case_counts(make_cases(draws, new_cases=51, new_deaths=6), epsilon, seed=11)
    p = without.value_counts(["new_cases", "new_deaths"], normalize=True)
    q = with_one.value_counts(["new_cases", "new_deaths"], normalize=True)
    common = p.index.intersection(q.index)
    common = common[(p[common] > 0.002) & (q[common] > 0.002)]          # enough samples for a stable ratio
    ratio = np.maximum(p[common] / q[common], q[common] / p[common])
    assert len(common) > 20
    assert ratio.max() <= np.exp(epsilon) * 1.15                        # small allowance for sampling error


def test_gaussian_mechanism():
    sigma = gaussian_sigma(0.5, 1e-5)
    assert sigma == pytest.approx(np.sqrt(2 * np.log(1.25e5)) * np.sqrt(2) / 0.5)
    noise = release_case_counts(make_cases(50_000), 0.5, mechanism="gaussian", delta=1e-5, seed=4)["new_cases"] - 1000
    assert noise.std() == pytest.approx(sigma, rel=0.03)


@pytest.mark.parametrize(
    "kwargs",
    [{"epsilon": 0}, {"epsilon": -1}, {"epsilon": 1.0, "mechanism": "gaussian"}, {"epsilon": 1.0, "mechanism": "exponential"}],
)
def test_invalid_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        release_case_counts(make_cases(3), **kwargs)
