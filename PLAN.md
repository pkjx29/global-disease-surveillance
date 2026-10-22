# Plan and status

What exists, what was checked, and what is still open. "Checked" means a command was run and its
output inspected; anything else is marked as not run. Updated 22 October 2026.

## Done

| Area | What | How it was checked |
|---|---|---|
| Data | ETL for WHO COVID-19, OWID mpox, OpenDengue, WHO GHO, Natural Earth into PostgreSQL | 119,423 rows in `case_reports` (90,492 reported weeks); `docs/model/model_report.md` |
| Provenance | Sidecar per download (URL, bytes, SHA-256, retrieval time); `python -m pipeline manifest` | Unit test; `docs/data/sources.md` generated |
| Model | XGBoost vs logistic regression vs growth rule; out-of-time split with a 4-week purge before validation and test; threshold chosen on validation | `python -m pipeline report`: ROC-AUC 0.823 vs 0.745, test anchors 2023-01-02 to 2026-08-03 |
| Leakage | Look-ahead test on features; purge test on the fit/validation split | `pytest` |
| DP | Laplace and Gaussian release, sensitivity 2 per case, secure randomness for real releases, budget ledger (`dp_release_runs`) | `pytest` (empirical ε check, ledger refusal); `python -m pipeline dp-eval` |
| API | API keys (probes open), per-key rate limit, key added by nginx server-side | `pytest` (401/429/Retry-After) |
| CI | pip-audit on `requirements.txt`; Trivy on both images, pinned to a commit | Run on PR #1: tests, pip-audit and the backend scan passed; the dashboard scan failed on an old base image, now bumped |
| AKS | `deploy.sh` defaults to `plan` (no login, nothing created); `apply` needed to create resources | `plan` run locally; `apply` never run |

## Open, in priority order

1. **Keep CI green.** The first Trivy run flagged 57 fixable HIGH/CRITICAL issues in the dashboard's
   old base image (`nginx-unprivileged:1.27-alpine`, Alpine 3.21.3); it now uses `1.30-alpine`.
2. **Dengue deaths are stored as 0.** The OpenDengue extract has no deaths; `new_deaths` should be
   NULL ("not available") rather than a reported zero. Needs a nullable column and a `cfr_8w` that skips it.
3. **Re-run the ETL on fresh files.** The WHO file has 702 more country-weeks and 250 revised counts
   than the copy loaded locally; results must then be regenerated (`report`, `dp-eval`).
4. **Flink → Kafka anomaly topic → consumer.** The job writes alerts to PostgreSQL with a JDBC
   upsert sink. The brief asks for an anomaly topic plus an idempotent consumer, and an end-to-end
   test with synthetic events. Needs Docker (not available on this machine: Docker was off and the disk full).
5. **Dashboard page for the DP results and model report.** Needs `npm install` (not possible with
   under 0.5 GB of free disk).
6. **NetworkPolicy enforcement test.** Requires a cluster with an enforcing CNI (e.g. kind with
   Calico); apply the policy, then check an allowed and a denied connection.
7. **Database migrations.** Schema changes are applied by the idempotent `schema.sql`. Alembic would
   be needed once a column changes type (item 2).

## Deliberate differences from the project brief

- **Endpoint paths.** The API keeps its existing 16 endpoints (`/health`, `/cases/...`, `/risk/...`)
  rather than the brief's suggested paths, because the dashboard depends on them and the count matches.
- **Label.** An outbreak means the next four weeks' total is at least double the last four weeks'
  total and above a per-disease minimum. The brief's example ("any one of the next four weeks
  reaches twice the anchor week") is noisier on weekly data; the chosen definition is in
  `backend/pipeline/features.py` and `docs/model/model_report.md`.
- **Brief document.** The attached brief ends inside section 10 (differential privacy); there were no
  later sections to follow.
