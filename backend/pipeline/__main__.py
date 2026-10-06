"""Pipeline CLI: ``python -m pipeline etl | train | all``."""

from __future__ import annotations

import argparse
import logging
import time

from .settings import setup_logging

log = logging.getLogger("pipeline")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pipeline", description="Disease surveillance data pipeline")
    parser.add_argument("step", choices=["etl", "train", "all"], help="etl = download + load, train = fit XGBoost + score")
    parser.add_argument("--force", action="store_true", help="re-download sources even if cached")
    args = parser.parse_args(argv)
    setup_logging()

    t0 = time.time()
    if args.step in ("etl", "all"):
        from . import etl

        etl.run(force=args.force)
    if args.step in ("train", "all"):
        from . import model

        model.run()
    log.info("%s finished in %.0f s", args.step, time.time() - t0)


if __name__ == "__main__":
    main()
