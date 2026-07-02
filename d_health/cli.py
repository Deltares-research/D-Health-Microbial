"""Tiny stdlib-argparse CLI: ``d-health run --config <toml>``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from d_health.config.loaders import load_run_config
from d_health.model.pipeline import run_model
from d_health.model.setup import ModelSetupOverrides, model_setup

logger = logging.getLogger("d_health.cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="d-health",
        description="d_health: flood → E. coli health-impact model.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run the model from a TOML config.")
    run.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to a configuration file (default: config.toml).",
    )
    run.add_argument(
        "-o",
        "--out",
        type=Path,
        default=None,
        help="Override output.out_dir from the config.",
    )
    run.add_argument(
        "--no-plots",
        action="store_true",
        help="Skip writing PNG plots (overrides output.plots).",
    )
    run.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Raise the d_health logger to DEBUG.",
    )

    setup = subparsers.add_parser(
        "setup",
        help="Prepare exposure inputs and write settings.toml from an AOI bbox.",
    )
    setup.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
        required=True,
        help="AOI bounds in EPSG:4326.",
    )
    setup.add_argument(
        "--root",
        type=Path,
        default=Path("setup"),
        help="Output folder where data/ and settings.toml are written.",
    )
    setup.add_argument(
        "--country-iso",
        type=str,
        default=None,
        help="Optional manual ISO3 override (skip reverse geocoding).",
    )
    setup.add_argument(
        "--year",
        type=int,
        default=2020,
        help="Population year for WorldPop (default: 2020).",
    )
    return parser


def _apply_overrides(config, out_dir: Path | None, no_plots: bool):
    """Return a copy of ``config`` with CLI flag overrides applied."""
    updates: dict = {}
    if out_dir is not None or no_plots:
        output = config.output.model_copy(
            update={
                **({"out_dir": out_dir} if out_dir is not None else {}),
                **({"plots": False} if no_plots else {}),
            }
        )
        updates["output"] = output
    return config.model_copy(update=updates) if updates else config


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.verbose:
        logging.getLogger("d_health").setLevel(logging.DEBUG)

    if args.command == "run":
        config = load_run_config(args.config)
        config = _apply_overrides(config, args.out, args.no_plots)
        outputs = run_model(config)
        for k, v in outputs.totals.items():
            print(f"{k}: {int(round(v))}")
        return 0

    if args.command == "setup":
        bbox = tuple(args.bbox)
        country_code = args.country_iso.upper() if args.country_iso else None
        overrides = ModelSetupOverrides(
            country_code=country_code,
            population_year=args.year,
        )
        result = model_setup(bbox, args.root, overrides=overrides)
        print(f"country_code: {result.country_code}")
        if result.country_name:
            print(f"country_name: {result.country_name}")
        print(f"settings_toml: {result.settings_toml}")
        print(f"population: {result.population}")
        print(f"urban_rural: {result.urban_rural}")
        print(f"country_indicators: {result.country_indicators}")
        return 0

    return 2  # unreachable; argparse enforces required subcommand


if __name__ == "__main__":
    sys.exit(main())
