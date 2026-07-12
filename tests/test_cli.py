"""The `d-health` CLI: argument parsing, flag overrides, both subcommands.

This is the documented entry point — the first thing a new user touches — and it
had no test coverage at all. The model itself is stubbed out here: what's under
test is the wiring (does `--out` actually reach the config? does `--no-plots`?),
not the physics, which the golden tests cover.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from d_health import cli
from d_health.model.outputs import ModelOutputs


@pytest.fixture
def stub_outputs():
    import numpy as np

    return ModelOutputs(
        emissions=np.zeros((2, 2)),
        pathogen_conc=np.zeros((2, 2)),
        doses={"adults": np.zeros((2, 2))},
        risks={"adults": np.zeros((2, 2))},
        infected={"adults": np.zeros((2, 2))},
        totals={"infected_adults": 12.7},
        paths={},
        meta={},
    )


@pytest.fixture
def captured_config(monkeypatch, stub_outputs):
    """Intercept the RunConfig that the CLI hands to run_model."""
    seen: dict = {}

    def fake_run_model(config, **kwargs):
        seen["config"] = config
        return stub_outputs

    monkeypatch.setattr(cli, "run_model", fake_run_model)
    return seen


def _write_config(tmp_path: Path) -> Path:
    ind = tmp_path / "ind.toml"
    ind.write_text(
        'country_code = "SUR"\n'
        "gdp_per_capita = 7000.0\n"
        "[[sanitation]]\n"
        'name = "None"\n'
        "urban = 100\n"
        "rural = 100\n",
        encoding="utf-8",
    )
    for name in ("pop.nc", "ur.nc", "flood.nc"):
        (tmp_path / name).write_bytes(b"")  # paths are not opened; load is stubbed

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[exposure]\n"
        'population = "pop.nc"\n'
        'urban_rural = "ur.nc"\n'
        'country_indicators = "ind.toml"\n'
        "[event]\n"
        'flood_depth_map = "flood.nc"\n'
        "[output]\n"
        'out_dir = "out"\n'
        "plots = true\n",
        encoding="utf-8",
    )
    return cfg


def test_run_prints_totals_and_exits_zero(tmp_path, captured_config, capsys):
    rc = cli.main(["run", "--config", str(_write_config(tmp_path))])

    assert rc == 0
    assert "infected_adults: 13" in capsys.readouterr().out  # 12.7 -> rounded


def test_run_out_flag_overrides_config_out_dir(tmp_path, captured_config):
    override = tmp_path / "elsewhere"
    cli.main(["run", "--config", str(_write_config(tmp_path)), "--out", str(override)])

    assert captured_config["config"].output.out_dir == override


def test_run_no_plots_flag_overrides_config(tmp_path, captured_config):
    cfg = _write_config(tmp_path)

    cli.main(["run", "--config", str(cfg)])
    assert captured_config["config"].output.plots is True, "config says plots = true"

    cli.main(["run", "--config", str(cfg), "--no-plots"])
    assert captured_config["config"].output.plots is False


def test_run_without_overrides_leaves_config_untouched(tmp_path, captured_config):
    cfg_path = _write_config(tmp_path)
    cli.main(["run", "--config", str(cfg_path)])

    config = captured_config["config"]
    assert config.output.plots is True
    assert config.output.out_dir == (tmp_path / "out")


def test_verbose_raises_log_level(tmp_path, captured_config):
    import logging

    logger = logging.getLogger("d_health")
    original = logger.level
    try:
        cli.main(["run", "--config", str(_write_config(tmp_path)), "--verbose"])
        assert logger.level == logging.DEBUG
    finally:
        logger.setLevel(original)


def test_setup_passes_bbox_and_uppercases_iso(tmp_path, monkeypatch, capsys):
    from d_health.model.setup import ModelSetupResult

    seen: dict = {}

    def fake_model_setup(aoi, root, *, overrides=None):
        seen["aoi"] = aoi
        seen["root"] = root
        seen["overrides"] = overrides
        return ModelSetupResult(
            root_dir=tmp_path,
            settings_toml=tmp_path / "settings.toml",
            population=tmp_path / "p.nc",
            urban_rural=tmp_path / "u.nc",
            country_indicators=tmp_path / "i.toml",
            country_code="SUR",
            country_name="Suriname",
        )

    monkeypatch.setattr(cli, "model_setup", fake_model_setup)

    rc = cli.main(
        [
            "setup",
            "--bbox",
            "-55.27",
            "5.78",
            "-55.10",
            "5.93",
            "--root",
            str(tmp_path),
            "--country-iso",
            "sur",  # lowercase on purpose
            "--year",
            "2019",
        ]
    )

    assert rc == 0
    assert seen["aoi"] == (-55.27, 5.78, -55.10, 5.93)
    assert seen["overrides"].country_code == "SUR", "ISO must be upper-cased"
    assert seen["overrides"].population_year == 2019
    assert "country_code: SUR" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv", [["run", "--config", "c.toml"], ["setup", "--bbox", "0", "0", "1", "1"]]
)
def test_verbose_is_accepted_by_every_subcommand(argv):
    """Regression: `main` reads args.verbose whatever the subcommand.

    `--verbose` used to be declared only on `run`, so `d-health setup` — the
    command the README documents — raised AttributeError on *every* invocation,
    before doing any work. Parsing must succeed with and without the flag, for
    every subcommand.
    """
    parser = cli._build_parser()

    assert parser.parse_args(argv).verbose is False
    assert parser.parse_args([*argv, "--verbose"]).verbose is True


def test_missing_subcommand_exits_nonzero():
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code != 0


def test_unknown_flag_exits_nonzero(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--nonsense"])
    assert exc.value.code != 0
