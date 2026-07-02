# d_health

Floods and Health Tool: E. coli emissions, exposure, and risk modelling.

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

This creates a `.pixi/` environment with Python 3.11–3.12, all dependencies (numpy, rasterio, GDAL, OpenTURNS, dask, matplotlib, SALib, …), and installs the `d_health` package itself in editable mode. Re-run `pixi install` after pulling changes to `pyproject.toml` or `pixi.lock`.

## Using the environment

Open a shell with the environment activated:

```bash
pixi shell
```

Or run a single command without activating:

```bash
pixi run python -c "import d_health; print(d_health.__version__)"
```

## Running notebooks

Launch Jupyter Lab from the project root:

```bash
pixi run jupyter lab
```

Or classic Notebook:

```bash
pixi run jupyter notebook
```

The environment includes `ipykernel`, so notebooks will pick up the project's Python automatically when launched this way. If you prefer to register the env as a named kernel for use from another Jupyter install:

```bash
pixi run python -m ipykernel install --user --name d_health --display-name "Python (d_health)"
```

## Project layout

```
.
├── d_health/            # Python package
│   ├── cli.py           # `d-health run -c config.toml` entry point
│   ├── config/          # pydantic run configuration (exposure/event/settings/output)
│   ├── preprocessing/   # build inputs (WorldPop population, GHS-SMOD, World Bank indicators)
│   ├── model/           # pipeline: emissions → concentration → dose → risk → infected
│   ├── postprocessing/  # flood classes, coverage, risk classes, plots
│   ├── io.py            # raster read/write helpers
│   └── geo.py           # reprojection / grid alignment
├── examples/
│   ├── detailed/        # full step-by-step notebooks (preprocessing + run)
│   └── quickbuild/      # fast AOI setup + multi-scenario run notebooks
├── tests/               # pytest suite
├── pyproject.toml       # project metadata + pixi config
├── pixi.lock            # locked dependency versions (commit this)
└── README.md
```

## AOI-first setup workflow

You can now generate exposure inputs from a single AOI and write a reusable
`settings.toml` (without flood map) using either Python or CLI.

### Python API

```python
from d_health import model_setup, write_run_config_from_setup, run_model_from_toml

# Paramaribo bbox: xmin, ymin, xmax, ymax (EPSG:4326)
aoi = (-55.27, 5.78, -55.10, 5.93)

setup = model_setup(aoi=aoi, root_dir="examples/quickbuild/data/setup_paramaribo")
print(setup.country_code, setup.settings_toml)

# Later, inject a flood map and run
run_toml = write_run_config_from_setup(
	settings_toml=setup.settings_toml,
	flood_depth_map="examples/quickbuild/data/flood_extremes/flood_wl3m_paramaribo.tif",
	run_config_path="examples/quickbuild/outputs/run/scenario_wl3m/config.toml",
	output_out_dir="examples/quickbuild/outputs/run/scenario_wl3m",
)
outputs = run_model_from_toml(run_toml)
print(outputs.totals)
```

### CLI

```bash
d-health setup --bbox -55.27 5.78 -55.10 5.93 --root examples/quickbuild/data/setup_paramaribo
```

The setup command writes:

- `data/*.nc` and `data/*_indicators.toml` exposure inputs
- `settings.toml` (exposure/settings/output/metadata; no event section)

## Examples tracks

- Detailed: `examples/detailed/README.md`
- Quickbuild: `examples/quickbuild/README.md`

## Adding dependencies

- **Conda package:** `pixi add <name>`
- **PyPI-only package:** `pixi add --pypi <name>`

Both update `pyproject.toml` and `pixi.lock`.

## Platforms

`pyproject.toml` currently declares `platforms = ["win-64"]`. To support other systems, add them under `[tool.pixi.workspace]`, e.g.:

```toml
platforms = ["win-64", "linux-64", "osx-arm64", "osx-64"]
```

Then re-run `pixi install` to extend the lockfile.
