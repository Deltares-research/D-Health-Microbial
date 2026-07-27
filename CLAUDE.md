# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

Everything runs through [pixi](https://pixi.sh) — the native geospatial stack (GDAL,
rasterio) comes from conda-forge, so a bare `python` outside the pixi env crashes on
import. Always prefix commands with `pixi run`.

Three environments are defined in `pyproject.toml`: `default` (notebook + editable +
lint), `test`, `lint`. Tasks pick their own default environment.

```bash
pixi install                 # create/update .pixi/ from pixi.lock
pixi run tests               # pytest + coverage (fails under 65%)
pixi run ruff                # lint
pixi run black               # format check
pixi run mypy                # type check (advisory; known backlog)
pixi run typos
pixi run precommit           # every pre-commit hook, all files
pixi run jupyter lab         # notebooks (ipykernel is in the env)
```

Single test — pass `--no-cov`, otherwise the `fail_under = 65` floor in
`[tool.coverage.report]` fails the run on a one-test subset:

```bash
pixi run -e test pytest tests/test_emissions.py::test_name --no-cov -q
```

Dependencies: `pixi add <name>` (conda) or `pixi add --pypi <name>`. If the library
itself imports it, also add it to `[project.dependencies]` — **except** native
geospatial packages like `gdal`, which belong only in `[tool.pixi.dependencies]`
(listing them as PyPI deps breaks `pip install`).

CI is Windows-only (`platforms = ["win-64"]` in `[tool.pixi.workspace]`); a Linux
runner has no lockfile to install from. Two workflows: `tests.yml` (`pixi run tests`)
and `precommit.yml`.

## What the model computes

Flood map + AOI → expected infected people:

```
population × sanitation × GDP  →  emissions (CFU/cell)
                                     ↓  ÷ (cell area × flood depth × 10000)
                             pathogen concentration (CFU/100 mL)
                                     ↓  × depth-banded ingestion × event hours
                                   dose
                                     ↓  beta-Poisson (alpha, beta)
                                   risk  →  infected = risk × population
```

## Architecture

Two entry points, both in `d_health/model/`, both re-exported from `d_health/__init__.py`:

- **`model_setup(aoi, root_dir)`** (`model/setup.py`) — one-time per region. Reverse-geocodes
  the AOI centroid (Nominatim → World Bank ISO2→ISO3), downloads WorldPop population,
  GHS-SMOD urban/rural and World Bank WDI indicators via `d_health/preprocessing/`, and
  writes `data/*.nc` + `data/*_indicators.toml` + a `settings.toml` **with no `[event]`
  section**. One setup serves many flood scenarios. `ModelSetupOverrides.raster_format`
  switches those rasters to `.tif` and records the choice in `settings.toml` under
  `[output]`; `write_run_config_from_setup` already merges that table into the run config,
  so runs inherit the format their inputs were written in.
- **`run_model_from_toml(path)` → `run_model(config)`** (`model/pipeline.py`) — one per
  scenario. `write_run_config_from_setup()` bridges the two by injecting a flood map path
  into a `settings.toml` to produce a runnable `config.toml`.

`cli.py` (`d-health setup|run`) is a thin argparse wrapper over those same functions.

Layer responsibilities:

| Module | Role |
|---|---|
| `config/` | Frozen pydantic models (`FrozenModel` base). `run.py` holds `RunConfig` = exposure + event + settings + output. `loaders.py::load_run_config` parses the TOML and resolves relative paths **against the config.toml's directory**, then validates. |
| `model/inputs.py` | `load_inputs` — reads the three rasters and aligns them onto one grid; returns `ModelInputs`. |
| `model/` steps | `emissions` → `concentration` → `exposure` (dose) → `risk` → `impact` (infected). Each is a pure numpy function; `pipeline.py` sequences them. |
| `postprocessing/` | `flood_classes`, `coverage`, `risk_classes`, `aggregate`, `plot` — analytics always computed, plots gated on `output.plots`. |
| `io.py`, `geo.py` | Raster read/write (`load_raster`, `from_numpy`, `wrap_like`, `write_raster`/`write_netcdf`/`write_geotiff`) and reprojection/`align_rasters`/`get_cell_area` (via UTM zone of the raster centre). **`io.py` must not import from `d_health.config`** — `config/run.py` and `config/setup.py` import `RasterFormat` from it, so the dependency runs config → io and any reverse import is a cycle. Put shared types in `io.py` or `config/base.py`, not in a config module `io` would need. |

Data-shape convention: the numeric core is **numpy 2-D arrays**; `population` alone stays
an `xarray.DataArray` with a labelled `group` dim so layers are selected by name. Results
are re-wrapped with `io.wrap_like(arr, grid, ...)` using `inputs.population` as the grid
before writing.

## Load-bearing conventions

These are the invariants the model assumes everywhere; violating one produces plausible
wrong numbers rather than an error.

- **The population raster defines the analysis grid** — not the flood map. Flood and
  urban/rural are resampled *onto* population's CRS/resolution (`average` for flood,
  `nearest` for the categorical urban/rural), clipped to the intersection of all three
  footprints. A 10 m flood map on a 100 m population grid is area-averaged, which
  attenuates peaks below swimming thresholds. `_check_common_grid` fails loudly if the
  three arrays end up on different grids.
- **Flood depth is positive**: `> 0` flooded, `0`/NaN dry. Negative depths are clipped to 0
  with a warning (`model/inputs.py`).
- **Unexposed cells are `NaN`, not `0`** in `pathogen_conc`, `dose`, `risk`, `infected`.
  Aggregate with `np.nansum`/`np.nanmean`. The dry-cell gate is explicit in
  `calc_pathogen_conc` — without it, division by depth 0 gives `inf` → risk 1.0 on dry land.
- **`reduction_factor` is a *retained* fraction, not a removed one.** `1.0` = no sanitation
  (full baseline retained); `0.10` = strong sanitation. Smaller means *more* sanitation.
  Keep the `SanitationReduction` / `reduction_factor` naming — colleagues use this terminology.
- **Unclassified urban/rural cells default to "no sanitation"** (`nodata_sanitation = "none"`,
  factor `1.0`) — a maximum-emission assumption on the least-known cells. GHS-SMOD leaves
  both nodata and water unclassified. Warned past 20%. On disk that class is written as
  nodata (`0`), so `load_raster` returns it as `NaN` and `model/inputs.py` coerces it back
  to `0`. That coercion does *not* change the numbers — `compute_emissions` routes `NaN`
  and `0` into the same nodata branch either way — but it is what keeps
  `ModelInputs.urban_rural` matching its documented `1=urban, 2=rural, 0=nodata` integer
  contract, and keeps the code off an undefined `float→int8` cast of `NaN`.
- **The output format must never change the numbers.** `tests/test_format_equivalence.py`
  runs the whole pipeline from rasters on disk in both formats and compares totals,
  emissions and risk. It is the only test that exercises the read-back path — the other
  format tests assert on metadata or pass `inputs=` in memory — so it is what catches a
  regression in band↔group mapping, label ordering, grid alignment or CRS.
- **Per-group outputs stack along a `group` dimension**, not one variable per group:
  `ds["risk"].sel(group="adults")`, not `ds["risk_adults"]`. In GeoTIFF mode the same
  layers become one band per group, **named after the group label** — the labels are
  what `.sel(group=...)` and the config's group names select on, so they own the band
  description and any longer `descriptions` go to a per-band `long_name` tag instead.
  `load_population` reads either layout back to the same labelled `group` dim.
- **Cross-config invariant**: every `country_indicators` sanitation tier name must have a
  matching `settings.emissions.sanitation_reductions` entry. Enforced by a `RunConfig`
  validator at load time; the emissions function does not re-check.
- Summary statistics (`totals`, `coverage`, `risk_class_counts`) live on the returned
  `ModelOutputs` object only — **nothing is written to disk** as JSON. Every raster on
  disk is netCDF *or* GeoTIFF per `output.raster_format` — one or the other, never both
  (plus PNG plots when `output.plots`).
- **`write_raster` dispatches on the file suffix**, mirroring `load_raster`. `raster_path`
  is the only place a `RasterFormat` becomes a suffix. This is why `get_population_data` /
  `get_smod_data` need no format parameter — they already receive a full `output_path`.
- **`to_netcdf(encoding=...)` replaces a variable's `.encoding` wholesale**, it does not
  merge. `write_netcdf` therefore re-adds `grid_mapping` by hand; drop that and the CRS is
  written but never linked, and every `.nc` opens ungeoreferenced in QGIS while still
  round-tripping fine through `load_raster` (whose `spatial_ref` fallback hides it).

## Tests

`tests/conftest.py` builds synthetic 16×16 fixtures (`flood_16x16`, `population_16x16`,
`urban_rural_16x16`, `small_meta` with a real UTM CRS) — no test touches a real raster or
the network.

`tests/test_golden.py` freezes end-to-end numbers on those fixtures. A failure there means
**the physics changed** — if intentional, update the constants in the same commit that
changed the model and explain why in the message; otherwise you caught a regression.
`tests/test_grid_invariant.py` guards the alignment invariant above.

## Notebooks

Examples live in `examples/detailed/` (step-by-step) and `examples/quickbuild/` (AOI setup +
multi-scenario). `nbstripout` runs pre-commit, so committed notebooks have no outputs — run
them to see the maps. Ruff excludes `*.ipynb` in both the pre-commit hook and the
`pixi run ruff` task; keep those two in agreement.

Install the hooks once with `pixi run -e lint pre-commit install`. They also block files
over 1 MB — this repo is geospatial and a stray `.tif`/`.nc` is one `git add .` from being
permanent.

## Docs

`docs/USER_GUIDE.md`, `docs/WORKFLOW.md`, `docs/API_REFERENCE.md`, `docs/MODULE_OVERVIEW.md`.
Note `MODULE_OVERVIEW.md` predates some changes — where it disagrees with the README or the
code (e.g. it says outputs are on the flood map's grid, and mentions GeoTIFF outputs), the
code and README are correct.
