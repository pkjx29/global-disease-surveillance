# Plan and status

What exists, what was checked, and what is still open. "Checked" means a command was run and its
output inspected; anything else is marked as not run. Updated 3 November 2026.

## Done

| Area | What | How it was checked |
|---|---|---|
| Data | ETL for WHO COVID-19, OWID mpox, OpenDengue, WHO GHO, Natural Earth into PostgreSQL; deaths a source does not report are NULL | Reloaded from files downloaded 22 Oct 2026: 120,125 rows in `case_reports` (90,704 reported weeks); `docs/model/model_report.md` |
| Provenance | Sidecar per download (URL, bytes, SHA-256, retrieval time); `python -m pipeline manifest` | Unit test; `docs/data/sources.md` generated |
| Model | XGBoost vs logistic regression vs growth rule; out-of-time split with a 4-week purge before validation and test; test anchors end at `TEST_END`; threshold chosen on validation | `python -m pipeline report`: ROC-AUC 0.837 vs 0.748, test anchors 2023-01-02 to 2026-08-24 |
| Leakage | Look-ahead test on features; purge test on the fit/validation split | `pytest` |
| DP | Laplace and Gaussian release, sensitivity 2 per case, secure randomness for real releases, budget ledger (`dp_release_runs`) | `pytest` (empirical ε check, ledger refusal); `python -m pipeline dp-eval` |
| API | API keys (probes open), per-key rate limit, key added by nginx server-side | `pytest` (401/429/Retry-After) |
| CI | pip-audit on `requirements.txt`; Trivy on both images, pinned to a commit | Passing on `main` since PR #1. The dashboard image runs `apk upgrade` at build time, because Alpine fixes (e.g. brotli, curl, libexpat in November 2026) arrive before the base image is rebuilt |
| AKS | `deploy.sh` defaults to `plan` (no login, nothing created); `apply` needed to create resources | `plan` run locally; `apply` never run |

## Open, in priority order

1. **Flink → Kafka anomaly topic → consumer.** The job writes alerts to PostgreSQL with a JDBC
   upsert sink. The brief asks for an anomaly topic plus an idempotent consumer, and an end-to-end
   test with synthetic events. Needs Docker. The stream producer sends 0 deaths for dengue because
   the Flink tables need a number; the job only uses cases.
2. **Dashboard page for the DP results and model report.** Needs `npm install`.
3. **NetworkPolicy enforcement test.** Requires a cluster with an enforcing CNI (e.g. kind with
   Calico); apply the policy, then check an allowed and a denied connection.
4. **Database migrations.** Schema changes are applied by the idempotent `schema.sql` (the
   `new_deaths` change uses `ALTER TABLE ... DROP NOT NULL`). Alembic would be the next step if the
   schema keeps changing.

## Deliberate differences from the project brief

- **Endpoint paths.** The API keeps its existing 16 endpoints (`/health`, `/cases/...`, `/risk/...`)
  rather than the brief's suggested paths, because the dashboard depends on them and the count matches.
- **Label.** An outbreak means the next four weeks' total is at least double the last four weeks'
  total and above a per-disease minimum. The brief's example ("any one of the next four weeks
  reaches twice the anchor week") is noisier on weekly data; the chosen definition is in
  `backend/pipeline/features.py` and `docs/model/model_report.md`.
- **Brief document.** The attached brief ends inside section 10 (differential privacy); there were no
  later sections to follow.
