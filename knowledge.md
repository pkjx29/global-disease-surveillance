# Design notes

Why the platform is built the way it is. Each section is a decision and the reason for it.

## Data

- **One row = one disease, one country, one ISO week starting Monday.** WHO dates a week by its
  closing Sunday, OpenDengue uses Sunday-to-Saturday epidemiological weeks and OWID mpox is daily, so
  each source is mapped to the ISO week that holds its midpoint (or summed from days for mpox).
- **A missing week is not zero.** Weeks a country skipped are kept with `reported = false`. Features
  that need complete windows require 75% reporting over 8 weeks, and labels need all four following
  weeks reported. Otherwise a reporting gap would look like a collapse and the next report like a surge.
- **Duplicates are not added.** When OpenDengue has two weekly records for the same country-week,
  the larger is kept. Adding them would double count overlapping reports.
- **Sources change.** The WHO file is revised after publication, so every download records its
  SHA-256 and retrieval time, and every report records a hash of the database contents it used.

## Model

- **Label.** At anchor week t: are cases in weeks t+1 to t+4 at least double those in t-3 to t, and
  above a minimum size (100 COVID-19, 50 dengue, 10 mpox cases)? The minimum stops 1 → 2 cases from
  counting as an outbreak.
- **No look-ahead.** Every feature is a function of weeks up to t, computed within one series sorted
  by time. A test changes future values and checks that earlier features do not move.
- **Purges.** A training row at week t has a label that reads weeks t+1 to t+4. So training anchors end
  four weeks before the test period, and the early-stopping fit ends four weeks before the validation
  weeks. Without that, the labels would contain information from the period being evaluated.
- **Test set used once.** Tree count (early stopping) and decision threshold come from the
  validation weeks. The test set only produces the reported numbers.
- **Metrics.** Outbreaks are 5.8% of test rows, so accuracy is meaningless (always "no" gives 94%).
  ROC-AUC measures ranking; average precision (PR-AUC) measures how clean the top of the ranking is
  and is compared against the base rate. Undefined values (e.g. precision with nothing flagged) are
  reported as undefined, not zero.
- **Rolling origin.** Re-training before each year from 2021 to 2025 shows the result is not one
  lucky split (ROC-AUC 0.82 to 0.92).

## Differential privacy

- **Unit and adjacency.** Neighbouring tables differ by one reported case. That case adds 1 to
  `new_cases` and at most 1 to `new_deaths` in one cell, so the L1 sensitivity is 2 (L2 is √2).
- **Laplace.** Noise Lap(2/ε) on each count gives ε-DP for the whole table. Each case sits in one
  cell, so the cells compose in parallel: the table costs ε, not ε × cells.
- **Post-processing is free.** Rounding and clipping at zero use only the noisy output, so they
  cost no privacy. Clipping does bias small counts upwards.
- **Repeated releases add up.** Two releases of the same counts cost ε₁ + ε₂ (sequential
  composition). `dp_release_runs` is a ledger that refuses a release beyond the total budget,
  because otherwise averaging many releases would remove the noise.
- **Randomness.** Real releases use `secrets.SystemRandom` (the OS cryptographic generator), drawing
  Laplace noise as the difference of two Exp(1) draws. Experiments use seeded NumPy so results can be
  reproduced. Floating-point noise still has known weaknesses (Mironov 2012); a production system
  should use OpenDP or another vetted library.
- **Gaussian.** σ = √(2 ln(1.25/δ)) · Δ₂ / ε, the classic bound, valid only for ε < 1; the code refuses
  other values.
- **What it does and does not mean.** The counts are already public, so this is a study of the cost
  of a release, not protection of these data. It protects case reports, not people reported twice
  (reinfections cost k·ε), and treats the shape of the table as public.
- **Result.** Overall accuracy barely moves (ROC-AUC 0.82 → 0.80 at ε = 1) because COVID-19 and dengue
  counts are large. Mpox, with a median of 5 cases in a non-zero week, falls from 0.82 to 0.67 and is
  worse than random at ε ≤ 0.25.

## API security

- **API keys, not JWT.** Callers are services and the dashboard proxy, not logged-in users. A key
  gives identity, revocation and per-client limits with nothing to sign or expire.
- **Constant-time comparison** (`secrets.compare_digest`) so the response time does not reveal how
  many characters of a guess were right. **Fail closed**: with no keys configured, every data route
  returns 401.
- **Probes open.** Kubernetes calls `/health` and `/ready` without credentials.
- **Rate limit.** A fixed 60-second window per key. Counters live in each process, so N pods allow N
  times the limit; a shared store (Redis) would fix that. nginx limits browsers per IP because they
  all share the dashboard's key, which nginx adds server-side so it never reaches the browser.

## Supply chain and deployment

- **pip-audit** checks `requirements.txt` against known vulnerabilities; **Trivy** scans the built
  images. The Trivy action is pinned to a commit, because its version tags were force-pushed to
  malware in March 2026 (CVE-2026-33634). A tag can be moved; a commit hash cannot.
- **Kubernetes.** The API and dashboard run as non-root with privilege escalation disabled; a NetworkPolicy lets
  only labelled clients reach PostgreSQL. Applying the YAML proves nothing unless the CNI enforces it.
- **AKS.** `deploy.sh` defaults to `plan`, which needs no login and creates nothing; `apply` creates
  billable resources after a prompt. It has never been applied to a subscription.

## Reproduce

```bash
cd backend
python -m pipeline etl          # download (with checksums) and load
python -m pipeline report       # model metrics and coverage -> docs/model/
python -m pipeline manifest     # source catalogue -> docs/data/
python -m pipeline dp-eval      # accuracy at each epsilon -> docs/dp/
pytest                          # needs PostgreSQL for the API and ledger tests
```
