"""Pipeline CLI: ``python -m pipeline etl | train | all | dp-eval | dp-release``."""

from __future__ import annotations

import argparse
import logging
import time

from .settings import setup_logging

log = logging.getLogger("pipeline")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pipeline", description="Disease surveillance data pipeline")
    parser.add_argument(
        "step",
        choices=["etl", "train", "all", "dp-eval", "dp-release"],
        help="etl = download + load, train = fit XGBoost + score, dp-eval = model accuracy at several epsilons, dp-release = write a DP copy of the counts",
    )
    parser.add_argument("--force", action="store_true", help="re-download sources even if cached")
    parser.add_argument("--epsilon", type=float, default=1.0, help="privacy budget for dp-release")
    parser.add_argument("--out", default="case_reports_dp.csv", help="output file for dp-release")
    args = parser.parse_args(argv)
    setup_logging()

    t0 = time.time()
    if args.step in ("etl", "all"):
        from . import etl

        etl.run(force=args.force)
    if args.step in ("train", "all"):
        from . import model

        model.run()
    if args.step == "dp-eval":
        from . import dp_eval

        dp_eval.run()
    if args.step == "dp-release":
        from . import load, model, privacy

        cases, _, _ = model.read_inputs(load.get_engine())
        # one release per epsilon: publishing fresh noise again would let readers average it away
        privacy.release_case_counts(cases, args.epsilon).to_csv(args.out, index=False)
        log.info("wrote %d country-weeks with epsilon = %g to %s", len(cases), args.epsilon, args.out)
    log.info("%s finished in %.0f s", args.step, time.time() - t0)


if __name__ == "__main__":
    main()
