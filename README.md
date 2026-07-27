# d_health

Floods and Health Tool: E. coli emissions, exposure, and risk modelling.

Given a flood map and an area of interest, `d_health` estimates how many people are
likely to be infected: population and sanitation data become an E. coli emission
field, the floodwater dilutes it into a concentration, each population group
ingests a depth-dependent dose, and a dose-response curve turns that into an
infection probability and an expected infected count.

```
population × sanitation × GDP  →  emissions
                                      ↓  ÷ (cell area × flood depth)
                              pathogen concentration
                                      ↓  × depth-banded ingestion
                                    dose
                                      ↓  beta-Poisson
                                    risk  →  infected = risk × population
```

## Prerequisites

This project uses [pixi](https://pixi.sh) to manage its environment (conda + PyPI dependencies, pinned via `pixi.lock`).

Install pixi if you don't already have it:

- **Windows (PowerShell):** `iwr -useb https://pixi.sh/install.ps1 | iex`
- **macOS / Linux:** `curl -fsSL https://pixi.sh/install.sh | sh`

Verify with `pixi --version`.

## Installation

From the project root (the directory containing `pyproject.toml`):

```bash
pixi install
```

This creates a `.pixi/` environment with Python 3.12, the geospatial stack
(numpy, rasterio, GDAL, xarray/rioxarray, netCDF4, pandas, matplotlib), and
installs `d_health` itself in editable mode. Re-run `pixi install` after pulling
changes to `pyproject.toml` or `pixi.lock`.

> `pip install d_health` is **not** the supported path: the package depends on
> GDAL, which is not reliably installable from PyPI. Use pixi (or bring your own
> conda environment with GDAL already present).

## Using the environment

Open a shell with the environment activated:

```bash
pixi shell
```

Or run a single command without activating:

```bash
pixi run python -c "import d_health; print(d_health.__version__)"
```

## Quick start

Generate exposure inputs from a single AOI, then run one or more flood scenarios
against them.

### Python API

```python
from d_health import model_setup, write_run_config_from_setup, run_model_from_toml

# Paramaribo bbox: xmin, ymin, xmax, ymax (EPSG:4326)
aoi = (-55.27, 5.78, -55.10, 5.93)

# Downloads WorldPop, GHS-SMOD and World Bank indicators; writes settings.toml.
setup = model_setup(aoi=aoi, root_dir="examples/quickbuild/data/setup_paramaribo")
print(setup.country_code, setup.settings_toml)

# Later, inject a flood map and run. Reuse one setup for many scenarios.
run_toml = write_run_config_from_setup(
    settings_toml=setup.settings_toml,
    flood_depth_map="examples/quickbuild/data/flood_extremes/flood_wl03m_paramaribo.tif",
    run_config_path="examples/quickbuild/outputs/run/scenario_wl03m/config.toml",
    output_out_dir="examples/quickbuild/outputs/run/scenario_wl03m",
)
outputs = run_model_from_toml(run_toml)
print(outputs.totals)   # {'infected_adults': ..., 'infected_children': ...}
```

### CLI

```bash
# Prepare exposure inputs for an AOI (--bbox takes four space-separated numbers)
d-health setup --bbox -55.27 5.78 -55.10 5.93 --root examples/quickbuild/data/setup_paramaribo

# Skip reverse geocoding by naming the country yourself
d-health setup --bbox -55.27 5.78 -55.10 5.93 --root data/setup --country-iso SUR --year 2020

# ...or write GeoTIFFs instead of netCDFs
d-health setup --bbox -55.27 5.78 -55.10 5.93 --root data/setup --format geotiff

# Run a scenario
d-health run --config config.toml
d-health run -c config.toml --out other/dir --no-plots
```

`setup` writes `data/*.nc` + `data/*_indicators.toml` (the exposure inputs) and a
`settings.toml` with no `[event]` section — the flood map is injected later, so one
setup serves many scenarios.

`--format geotiff` writes `data/*.tif` instead and records the choice in
`settings.toml`, so every run built from that setup writes GeoTIFF outputs too. See
[Raster format](#raster-format).

## Things worth knowing before you trust a number

These are the model's load-bearing conventions. Each has bitten someone.

- **The population raster defines the analysis grid** — not the flood map. The flood
  and urban/rural rasters are resampled *onto* population's CRS and resolution
  (clipped to the intersection of all three footprints). Supplying a 10 m flood map
  against a 100 m population grid does **not** give you a 10 m run: the depths are
  area-averaged, which attenuates peaks, so a deep narrow channel can average
  *below* a group's swimming threshold.

- **Flood depth is positive**: `> 0` flooded, `0`/NaN dry. Negative depths (common
  in maps built by differencing a water surface against a DEM) are clipped to 0
  with a warning.

- **Unexposed cells are `NaN`, not `0`**, in `pathogen_conc`, `dose`, `risk` and
  `infected`. Aggregate with `np.nansum` / `np.nanmean`, or dry land will poison
  the result.

- **`reduction_factor` is a *retained* fraction, not a removed one.** `1.0` = no
  sanitation (full baseline emissions retained); `0.10` = strong sanitation (only
  10% retained). Smaller means *more* sanitation.

- **Unclassified urban/rural cells default to "no sanitation"** (`nodata_sanitation
  = "none"`, factor `1.0`) — the maximum-emission assumption, applied to the cells
  you know least about. GHS-SMOD leaves both nodata *and water* unclassified. The
  unclassified share is logged, and warned about past 20%. Set
  `settings.emissions.nodata_sanitation` to `"urban"`, `"rural"` or `"nan"` to
  change it.

- **Per-group outputs are stacked along a `group` dimension**, not one variable per
  group: `ds["risk"].sel(group="adults")`, not `ds["risk_adults"]`. In GeoTIFF mode
  the same layers become one named band per group, and `load_population` reads
  either layout back to the same labelled `group` dim.

## Outputs

Written to `output.out_dir`. One raster format or the other, never both; no JSON.

| File | Content |
|---|---|
| `emissions.nc` | E. coli load per cell (CFU per flood event) |
| `pathogen_conc.nc` | Concentration (CFU per 100 mL; NaN where dry) |
| `flood_classes.nc` | `0` dry, `1` wet but below every threshold, `2..n` activity bands |
| `dose.nc`, `risk.nc`, `infected.nc` | Per group, stacked along `group` |
| `*.png` | Maps and the risk histogram (only when `output.plots = true`) |

Summary statistics (`totals`, `coverage`, `risk_class_counts`) are returned on the
`ModelOutputs` object — they are **not** written to disk.

### Raster format

Every raster the model writes — the setup inputs and all outputs — is
georeferenced and opens directly in QGIS. Pick the format once, at setup:

```bash
d-health setup --bbox ... --format geotiff     # .tif everywhere
```

The choice lands in `settings.toml` under `[output]`, and
`write_run_config_from_setup` carries it into each `config.toml`, so runs inherit
it. Override per run with `output.raster_format = "netcdf" | "geotiff"` in the
config, or `d-health run --format geotiff`.

Which to pick:

- **netCDF** (default) — CF-1.8 georeferenced, zlib-compressed, and keeps the
  labelled `group` dimension, so `ds["risk"].sel(group="adults")` works. GDAL reads
  a per-group file as N bands in group order. Note the band *names* are not shown:
  the group labels live in dataset metadata as
  `NETCDF_DIM_group_VALUES={adults,children,total}`, so QGIS lists plain
  "Band 1 / 2 / 3".
- **GeoTIFF** — deflate-compressed and tiled, with each band named after its group,
  so QGIS shows "adults", "children", "total" in the styling panel. Choose this if
  you spend more time in a GIS than in xarray.

## Project layout

```
.
├── d_health/            # Python package
│   ├── cli.py           # `d-health run|setup` entry point
│   ├── config/          # pydantic configuration (exposure/event/settings/output)
│   ├── preprocessing/   # build inputs (WorldPop population, GHS-SMOD, World Bank)
│   ├── model/           # pipeline: emissions → concentration → dose → risk → infected
│   ├── postprocessing/  # flood classes, coverage, risk classes, plots
│   ├── io.py            # raster read/write helpers
│   └── geo.py           # reprojection / grid alignment
├── docs/                # user guide, workflow, API reference, module overview
├── examples/
│   ├── detailed/        # full step-by-step notebooks (preprocessing + run)
│   └── quickbuild/      # fast AOI setup + multi-scenario run notebooks
├── tests/               # pytest suite
├── pyproject.toml       # project metadata + pixi config + tooling
├── pixi.lock            # locked dependency versions (commit this)
└── README.md
```

## Documentation

- [User guide](docs/USER_GUIDE.md) — installation and common tasks
- [Workflow](docs/WORKFLOW.md) — inputs → processing → outputs, end to end
- [API reference](docs/API_REFERENCE.md) — every public function and config model
- [Module overview](docs/MODULE_OVERVIEW.md) — how the package fits together

Example notebooks: [`examples/detailed/`](examples/detailed/README.md) (step by
step) and [`examples/quickbuild/`](examples/quickbuild/README.md) (AOI setup +
multi-scenario runs). Notebook outputs are stripped on commit, so run them to see
the maps.

## Development

```bash
pixi run tests       # pytest + coverage (fails below 65%)
pixi run ruff        # lint
pixi run black       # format check
pixi run mypy        # type check (advisory; has a known backlog)
pixi run precommit   # every hook, on every file
```

Install the git hooks once with `pixi run -e lint pre-commit install`. They strip
notebook outputs, block files over 1 MB, and run ruff/black/typos.

### Running notebooks

```bash
pixi run jupyter lab
```

The environment includes `ipykernel`, so notebooks pick up the project's Python
automatically. To register it as a named kernel for another Jupyter install:

```bash
pixi run python -m ipykernel install --user --name d_health --display-name "Python (d_health)"
```

### Adding dependencies

- **Conda package:** `pixi add <name>`
- **PyPI-only package:** `pixi add --pypi <name>`

Both update `pyproject.toml` and `pixi.lock`. If a package is imported by the
library itself, add it to `[project.dependencies]` too — except for native
geospatial packages like GDAL, which belong only in `[tool.pixi.dependencies]`
(they are not pip-installable, and listing them breaks `pip install`).

## Platforms

`pyproject.toml` currently declares `platforms = ["win-64"]`, and CI runs on
Windows only. To support other systems, add them under `[tool.pixi.workspace]`:

```toml
platforms = ["win-64", "linux-64", "osx-arm64", "osx-64"]
```

Then re-run `pixi install` to extend the lockfile. Note this re-solves every
environment, so expect churn in `pixi.lock`.
