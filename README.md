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
│   ├── __init__.py
│   └── get_population_data.py
├── pyproject.toml       # project metadata + pixi config
├── pixi.lock            # locked dependency versions (commit this)
└── README.md
```

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
