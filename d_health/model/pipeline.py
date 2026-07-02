from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from d_health.config.loaders import load_run_config
from d_health.config.run import RunConfig
from d_health.io import wrap_like, write_netcdf
from d_health.model.concentration import calc_pathogen_conc
from d_health.model.emissions import compute_emissions
from d_health.model.exposure import calc_dose_for_groups
from d_health.model.impact import calc_infected_pop_per_group
from d_health.model.inputs import ModelInputs, load_inputs
from d_health.model.outputs import ModelOutputs
from d_health.model.risk import calc_infection_risk_beta_poisson
from d_health.postprocessing.aggregate import per_group_totals
from d_health.postprocessing.coverage import flooded_dry_stats, log_coverage
from d_health.postprocessing.flood_classes import compute_flood_classes, plot_flood_classes
from d_health.postprocessing.plot import plot_per_group, plot_raster
from d_health.postprocessing.risk_classes import (
    DEFAULT_RISK_EDGES,
    bin_population_by_risk,
    plot_risk_class_histogram,
)

logger = logging.getLogger(__name__)


def run_model(config: RunConfig, *, inputs: ModelInputs | None = None) -> ModelOutputs:
    """End-to-end flooding → health-impact run.

    Parameters
    ----------
    config
        Loaded run configuration.
    inputs
        Optional pre-loaded ``ModelInputs``. When omitted, rasters are loaded
        from ``config.exposure`` and ``config.event`` via :func:`load_inputs`.
        The override is meant for tests that build inputs in memory — callers
        normally pass only ``config``.
    """
    logger.info("Starting d_health pipeline")
    if inputs is None:
        inputs = load_inputs(config.exposure, config.event)

    mc = config.settings
    country = config.exposure.load_country_indicators()

    # ── emissions step (no flood term; gating happens in concentration)
    popdens_total = inputs.population.sel(
        group=mc.emissions.total_population_group
    ).values
    emissions = compute_emissions(
        popdens=popdens_total,
        urban_rural=inputs.urban_rural,
        country=country,
        cfg=mc.emissions,
    )

    # ── pathogen concentration (NaN where unflooded, due to /flood in denominator)
    conc = calc_pathogen_conc(inputs.flood_meta, inputs.flood, emissions)

    # ── per-group dose / risk / infected (flood depth is already positive)
    doses = calc_dose_for_groups(
        inputs.flood, conc, mc.population_groups, mc.event_in_hours
    )

    pp = mc.pathogen.active
    risks: dict[str, np.ndarray] = {
        name: calc_infection_risk_beta_poisson(dose, pp.alpha, pp.beta)
        for name, dose in doses.items()
    }
    infected = calc_infected_pop_per_group(risks, inputs.population, mc.population_groups)
    totals = per_group_totals(infected)
    for k, v in totals.items():
        logger.info("Total %s = %d", k, int(round(v)))

    # ── postprocessing analytics (always computed; plots gated on outputs.plots)
    flood_classes = compute_flood_classes(inputs.flood, mc.population_groups)
    coverage = flooded_dry_stats(
        inputs.flood, inputs.population, mc.population_groups, mc.emissions,
        flood_classes=flood_classes,
    )
    log_coverage(coverage)
    risk_class_counts = bin_population_by_risk(
        risks, inputs.population, mc.population_groups,
        edges=DEFAULT_RISK_EDGES,
    )

    # ── write outputs (netCDF; ``inputs.population`` supplies the output grid)
    out_dir = Path(config.output.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    grid = inputs.population          # x/y coords + CRS for wrap_like
    paths: dict[str, Path] = {}
    paths["emissions"] = write_netcdf(
        wrap_like(emissions, grid, name="emissions"),
        out_dir / "emissions.nc",
        descriptions=("ecoli_emissions_cfu",),
    )
    paths["pathogen_conc"] = write_netcdf(
        wrap_like(conc, grid, name="pathogen_conc"),
        out_dir / "pathogen_conc.nc",
        descriptions=("ecoli_per_100ml",),
    )
    paths["flood_classes"] = write_netcdf(
        wrap_like(flood_classes.astype(np.int16), grid, name="flood_classes"),
        out_dir / "flood_classes.nc",
        descriptions=("flood_depth_class",),
    )
    # Per-group quantities → one netCDF each, stacked along the ``group`` dim
    # (mirrors the population input layout).
    for label, data in (("dose", doses), ("risk", risks), ("infected", infected)):
        names = list(data.keys())
        stacked = np.stack([data[n] for n in names], axis=0)
        paths[label] = write_netcdf(
            wrap_like(stacked, grid, name=label, group=names),
            out_dir / f"{label}.nc",
        )

    if config.output.plots:
        plot_raster(
            emissions, cmap="viridis", title="E. coli emissions (CFU)",
            save_path=out_dir / "emissions.png",
        )
        paths.update(plot_per_group(doses, label="dose", out_dir=out_dir))
        paths.update(plot_per_group(risks, label="risk", out_dir=out_dir))
        paths.update(plot_per_group(infected, label="infected", out_dir=out_dir))

        fc_plot = plot_flood_classes(
            flood_classes, mc.population_groups,
            save_path=out_dir / "flood_classes.png",
        )
        if fc_plot is not None:
            paths["flood_classes_plot"] = fc_plot

        rh_plot = plot_risk_class_histogram(
            risk_class_counts, edges=DEFAULT_RISK_EDGES,
            save_path=out_dir / "risk_histogram.png",
        )
        if rh_plot is not None:
            paths["risk_histogram"] = rh_plot

    return ModelOutputs(
        emissions=emissions,
        pathogen_conc=conc,
        doses=doses,
        risks=risks,
        infected=infected,
        totals=totals,
        paths=paths,
        meta=inputs.flood_meta,
        flood_classes=flood_classes,
        coverage=coverage,
        risk_class_counts=risk_class_counts,
        risk_class_edges=DEFAULT_RISK_EDGES,
    )


def run_model_from_toml(path: str | Path) -> ModelOutputs:
    """Load a config.toml then call :func:`run_model`."""
    return run_model(load_run_config(path))
