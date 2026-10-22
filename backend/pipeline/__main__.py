"""Pipeline CLI: ``python -m pipeline etl | train | all | report | manifest | dp-eval | dp-release``."""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from .settings import setup_logging

log = logging.getLogger("pipeline")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pipeline", description="Disease surveillance data pipeline")
    parser.add_argument(
        "step",
        choices=["etl", "train", "all", "report", "manifest", "dp-eval", "dp-release"],
        help=(
            "etl = download + load, train = fit XGBoost + score, report = evaluation report without database writes, "
            "manifest = source catalogue with file checksums, "
            "dp-eval = model accuracy at several epsilons, dp-release = write a DP copy of the counts"
        ),
    )
    parser.add_argument("--force", action="store_true", help="re-download sources even if cached")
    parser.add_argument("--epsilon", type=float, default=1.0, help="privacy budget for dp-release")
    parser.add_argument("--mechanism", choices=["laplace", "gaussian"], default="laplace", help="noise for dp-release")
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
    if args.step == "manifest":
        from . import manifest

        manifest.run()
    if args.step == "report":
        from . import report

        report.run()
    if args.step == "dp-eval":
        from . import dp_eval

        dp_eval.run()
    if args.step == "dp-release":
        from . import dp_release, load

        # every release is recorded and counted against the total budget: fresh noise on the
        # same counts would otherwise let readers average it away
        dp_release.release(load.get_engine(), args.epsilon, Path(args.out), mechanism=args.mechanism)
    log.info("%s finished in %.0f s", args.step, time.time() - t0)


if __name__ == "__main__":
    main()
