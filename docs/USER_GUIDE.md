# D-Health User Guide: Quick Start & Common Tasks

This guide covers practical setup and common workflows using the D-Health module.

---

## Installation & Setup

### 1. Install Pixi (Dependency Manager)

**Windows (PowerShell)**:
```powershell
iwr -useb https://pixi.sh/install.ps1 | iex
```

**macOS / Linux**:
```bash
curl -fsSL https://pixi.sh/install.sh | sh
```

Verify:
```bash
pixi --version
```

### 2. Install D-Health

Clone the repository and install dependencies:

```bash
git clone https://github.com/Deltares-research/D-Health-Microbial.git
cd D-Health-Microbial
pixi install
```

This creates a `.pixi/` environment with all dependencies locked and reproducible.

### 3. Activate the Environment

**Option A: Interactive Shell**
```bash
pixi shell
python -c "import d_health; print(d_health.__version__)"
```

**Option B: Run Commands Without Shell**
```bash
pixi run python -c "import d_health; print(d_health.__version__)"
```

**Option C: Jupyter Notebooks**
```bash
pixi run jupyter lab
# or
pixi run jupyter notebook
```

---

## Task 1: Set Up Exposure Data for a New Region

**Goal**: Prepare reusable input files for a geographic area.

### Step 1: Define Your Area of Interest (AOI)

Get a bounding box in latitude/longitude (EPSG:4326):

```python
# Paramaribo, Suriname example:
# xmin, ymin, xmax, ymax
aoi = (-55.27, 5.78, -55.10, 5.93)
```

**How to find AOI coordinates**:
- Use Google Maps, zoom to your region
- Click and note the latitude/longitude in the URL or address bar
- Create a box: (lon_min, lat_min, lon_max, lat_max)

### Step 2: Download & Prepare Data

```python
from d_health import model_setup

result = model_setup(
    aoi=aoi,
    root_dir="data/setup_paramaribo"
)

print(f"✓ Exposure data saved to: {result.root_dir}")
print(f"✓ Settings TOML: {result.settings_toml}")
print(f"✓ Country detected: {result.country_code}")
```

**What happens**:
- Downloads high-resolution population grid (WorldPop, ~100 m resolution)
- Downloads urban/rural classification (GHS-SMOD)
- Looks up country sanitation/economic indicators (World Bank)
- Clips all data to your AOI
- Validates and organizes files

**Outputs**:
```
data/setup_paramaribo/
├── settings.toml          ← Config file (reuse for all scenarios)
├── population.nc          ← Population grid
├── urban_rural.nc         ← Urban/rural layer
├── country_indicators.toml
└── .metadata/             ← Download info & timestamps
```

**Notes**:
- Requires internet connection (first-time downloads)
- Takes 5–10 minutes depending on AOI size and internet speed
- Safe to run multiple times (checks for existing files)

---

## Task 2: Run the Model for One Flood Scenario

**Goal**: Compute infection risk for a specific flood event.

### Step 1: Prepare Your Flood Map

You need a raster file (GeoTIFF or NetCDF) with:
- **Units**: Flood depth in meters
- **Value = 0 or negative**: Dry cells
- **Value > 0**: Flood depth in that cell
- **CRS**: Any (auto-reprojected)

Example: `flood_maps/wl3m_paramaribo.tif`

### Step 2: Generate Run Configuration

```python
from d_health import write_run_config_from_setup

config_path = write_run_config_from_setup(
    settings_toml="data/setup_paramaribo/settings.toml",
    flood_depth_map="flood_maps/wl3m_paramaribo.tif",
    run_config_path="data/runs/scenario_wl3m/config.toml",
    output_out_dir="outputs/run_wl3m",
)

print(f"✓ Config saved: {config_path}")
```

### Step 3: Execute the Model

```python
from d_health import run_model_from_toml

result = run_model_from_toml(config_path)

print("✓ Model completed successfully!")
print("\nResults:")
print(f"  Infected adults: {result.totals['infected_adults']:.0f}")
print(f"  Infected children: {result.totals['infected_children']:.0f}")
print(f"  Total infected: {sum(result.totals.values()):.0f}")

# Coverage comes back on the result object — the pipeline writes no JSON files.
print(f"\nFlooded population: {result.coverage.flooded['total']:.0f}")
print(f"Dry population:     {result.coverage.dry['total']:.0f}")
```

**Outputs Generated**:
```
outputs/run_wl3m/
├── emissions.nc                 ← E. coli emissions (CFU per cell, per event)
├── pathogen_conc.nc             ← Pathogen concentration (CFU/100 mL; NaN where dry)
├── flood_classes.nc             ← Classified depth map
├── dose.nc                      ← Ingested dose, stacked along a `group` dim
├── risk.nc                      ← Infection probability, per group
├── infected.nc                  ← Expected infected persons, per group
│
├── emissions.png                ← (only when output.plots = true)
├── pathogen_conc.png            ← Pathogen concentration map
├── flood_classes.png
├── risk_histogram.png           ← One chart, all groups as bar series
├── dose_<group>.png             ← e.g. dose_adults.png, dose_children.png
├── risk_<group>.png
└── infected_<group>.png
```

The rasters are `.tif` instead when `output.raster_format = "geotiff"` — see
[Opening the results in QGIS](#opening-the-results-in-qgis).

Summary statistics are **not** written to disk — there are no `totals.json` or
`coverage.json` files. They live on the returned `ModelOutputs`
(`result.totals`, `result.coverage`, `result.risk_class_counts`). Serialise them
yourself if you want them on disk.

---

## Task 3: Compare Multiple Flood Scenarios

**Goal**: Run the model across different return periods or climate scenarios.

```python
from d_health import (
    write_run_config_from_setup,
    run_model_from_toml,
)
import json

settings_toml = "data/setup_paramaribo/settings.toml"

scenarios = {
    "wl1m": "flood_maps/wl1m_paramaribo.tif",
    "wl3m": "flood_maps/wl3m_paramaribo.tif",
    "rp100": "flood_maps/rp100_year_paramaribo.tif",
}

results_summary = {}

for scenario_name, flood_map in scenarios.items():
    print(f"\n--- Running scenario: {scenario_name} ---")

    # Generate config
    config_path = f"data/runs/{scenario_name}/config.toml"
    write_run_config_from_setup(
        settings_toml=settings_toml,
        flood_depth_map=flood_map,
        run_config_path=config_path,
        output_out_dir=f"outputs/run_{scenario_name}",
    )

    # Run model
    result = run_model_from_toml(config_path)

    # Store results
    results_summary[scenario_name] = {
        "infected_adults": result.totals['infected_adults'],
        "infected_children": result.totals['infected_children'],
        "output_dir": str(result.paths['emissions'].parent),
    }

    total = results_summary[scenario_name]['infected_adults'] + \
            results_summary[scenario_name]['infected_children']
    print(f"✓ Total infected: {total:.0f}")

# Save comparison
with open("outputs/scenario_comparison.json", "w") as f:
    json.dump(results_summary, f, indent=2)

print("\n--- Summary ---")
for scenario, data in results_summary.items():
    total = data['infected_adults'] + data['infected_children']
    print(f"{scenario:10s}: {total:10,.0f} infected")
```

---

## Task 4: Load and Analyze Results

**Goal**: Post-process model outputs for analysis and visualization.

### Load NetCDF Results

Per-group outputs are written as **one variable stacked along a `group`
dimension** — not one variable per group. So `risk.nc` holds a single `risk`
variable that you select from by group name; there is no `risk_adults` variable.

```python
import xarray as xr
import numpy as np

# Open model outputs
risk = xr.open_dataset("outputs/run_wl3m/risk.nc")
infected = xr.open_dataset("outputs/run_wl3m/infected.nc")

# View dimensions and variables
print(risk)   # Dimensions: (group: 2, y: ..., x: ...)

# Extract data for a group — select along `group`, don't index a variable name
risk_adults = risk["risk"].sel(group="adults").values
infected_children = infected["infected"].sel(group="children").values

# Compute statistics. Unexposed (dry) cells are NaN, not 0 — always use nan-safe
# reductions, or the dry cells will poison the result.
print(f"Mean infection risk (adults): {np.nanmean(risk_adults):.3f}")
print(f"Max infection risk (adults): {np.nanmax(risk_adults):.3f}")
print(f"Total infected children: {np.nansum(infected_children):.0f}")

# Spatial operations. NaN > 0.5 is False, so dry cells are excluded already.
high_risk = (risk_adults > 0.5).sum()
print(f"Cells with >50% infection risk: {high_risk}")
```

### Load the flood-class map

The pipeline writes netCDF by default, or GeoTIFF if you asked for it (see
[Opening the results in QGIS](#opening-the-results-in-qgis)). The package's own
loader handles both and attaches the CRS:

```python
import numpy as np
from d_health.io import load_raster

flood_classes = load_raster("outputs/run_wl3m/flood_classes.nc")

print(flood_classes.rio.crs)
print(flood_classes.rio.transform())

# Count cells in each class
classes, counts = np.unique(flood_classes.values, return_counts=True)
print("Flood class distribution:")
for cls, count in zip(classes, counts, strict=True):
    print(f"  Class {int(cls)}: {count} cells")
```

### Opening the results in QGIS

Every raster the model writes — the setup inputs and all outputs — is
georeferenced. Drag a file straight onto the QGIS canvas and it lands in the
right place; no "Georeferencer" step, no manual CRS assignment.

Pick the format once, at setup, and runs inherit it:

```bash
d-health setup --bbox -55.27 5.78 -55.10 5.93 --root data/setup --format geotiff
```

The choice is recorded in `settings.toml` under `[output]` and copied into each
`config.toml` by `write_run_config_from_setup`. Override it for a single run with
`d-health run --format netcdf`, or by setting `output.raster_format` in the
config.

**netCDF (default)** — CF-1.8, zlib-compressed, and keeps the labelled `group`
dimension so `.sel(group="adults")` works in xarray. One caveat when you open a
per-group file (`dose`, `risk`, `infected`, `population`) in QGIS: GDAL shows the
groups as bands in order, but *unnamed* — the layer list reads "Band 1", "Band 2",
"Band 3". The labels are there, in the layer metadata:

```
NETCDF_DIM_group_VALUES={adults,children,total}
```

Band order matches that list. Check it in *Layer Properties → Information* if you
are unsure which band is which.

**GeoTIFF** — deflate-compressed and tiled, with each band **named after its
group**, so the styling panel shows "adults", "children", "total" directly. If you
spend more time in QGIS than in xarray, this is the friendlier option. The model
reads either format back, so nothing else changes.

### Plot results

```python
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

# Spatial risk map, straight from the stacked netCDF.
risk = xr.open_dataset("outputs/run_wl3m/risk.nc")["risk"].sel(group="adults")

fig, ax = plt.subplots(figsize=(10, 8))
risk.plot(ax=ax, cmap="RdYlGn_r")   # xarray draws the axes in map coordinates
ax.set_title("Infection risk — adults")
plt.tight_layout()
plt.savefig("figures/risk_map_adults.png", dpi=150)

# Risk-class histogram. There is no risk_class_counts.json — the counts come back
# on the ModelOutputs object, so compute them in the same session as the run.
from d_health import run_model_from_toml
from d_health.postprocessing import DEFAULT_RISK_EDGES

result = run_model_from_toml("outputs/run_wl3m/config.toml")
edges = DEFAULT_RISK_EDGES
labels = [f"{edges[i]:.1f}-{edges[i + 1]:.1f}" for i in range(len(edges) - 1)]

fig, ax = plt.subplots(figsize=(8, 5))
index = np.arange(len(labels))
width = 0.8 / len(result.risk_class_counts)
for i, (group, counts) in enumerate(result.risk_class_counts.items()):
    ax.bar(index + i * width, counts, width, label=group, alpha=0.8)
ax.set_xticks(index + width * (len(result.risk_class_counts) - 1) / 2)
ax.set_xticklabels(labels)
ax.set_xlabel("Risk class")
ax.set_ylabel("Population count")
ax.legend()
plt.tight_layout()
plt.savefig("figures/risk_histogram.png", dpi=150)
```

(The pipeline already writes `risk_histogram.png` for you when
`output.plots = true` — this is only for customising it.)

---

## Task 5: Customize Population Groups & Depth Thresholds

**Goal**: Modify exposure behaviors (water intake, depth thresholds).

### Default Configuration

The default setup uses:
- **Adults**: wading (0.1–1.5 m, 10 ml/h) + swimming (1.5+ m, 30 ml/h)
- **Children**: wading (0.1–0.5 m, 30 ml/h) + swimming (0.5+ m, 50 ml/h)

### Customize Groups

```python
from d_health import RunConfig, load_run_config, run_model
from d_health.config.groups import PopulationGroup, DepthThreshold

# Load existing config
config = load_run_config("data/runs/wl3m/config.toml")

# Define custom groups
custom_groups = [
    PopulationGroup(
        name="infants",
        depth_thresholds=[
            DepthThreshold(
                name="wading",
                min_depth=0.05,  # Shallower threshold
                ing=20.0,  # Less water intake
                unit="ml/h",
            ),
        ],
    ),
    PopulationGroup(
        name="elderly",
        depth_thresholds=[
            DepthThreshold(
                name="wading",
                min_depth=0.2,  # Higher threshold (reduced mobility)
                ing=5.0,  # Minimal water intake
                unit="ml/h",
            ),
        ],
    ),
]

# Update config
config.settings.population_groups = custom_groups

# Run with custom groups
result = run_model(config)
print(f"Infected infants: {result.totals.get('infected_infants', 0):.0f}")
print(f"Infected elderly: {result.totals.get('infected_elderly', 0):.0f}")
```

**Note**: This requires custom population grids with matching group names (e.g., `infants`, `elderly` dimensions in NetCDF).

---

## Task 6: Run via Command Line

**Goal**: Execute the model without writing Python code.

### One-Time Setup

```bash
pixi shell
```

### Run Model

```bash
d-health run -c data/runs/wl3m/config.toml
```

### Setup New Region

```bash
d-health setup \
    --bbox -55.27 5.78 -55.10 5.93 \
    --root data/setup_paramaribo

# Skip reverse geocoding by naming the country yourself:
d-health setup --bbox -55.27 5.78 -55.10 5.93 --root data/setup_paramaribo \
    --country-iso SUR --year 2020

# Write GeoTIFFs instead of netCDFs (runs from this setup inherit the choice):
d-health setup --bbox -55.27 5.78 -55.10 5.93 --root data/setup_paramaribo \
    --format geotiff
```

`--bbox` takes four space-separated numbers (`XMIN YMIN XMAX YMAX`) in
EPSG:4326 — not a comma-separated string.

---

## Troubleshooting

### Problem: Raster Resolution Mismatch

**Error**: `ValueError: rasters have different spatial extents`

**Solution**: All rasters are automatically aligned to the flood depth map. Ensure the flood map covers the population grid extent.

### Problem: Pathogen Concentration is Zero

**Error**: Model runs but all pathogen_conc values are 0.

**Causes**:
- Sanitation coverage is 100% treated (no emissions)
- Check `country_indicators.toml` values
- Ensure urban/rural layer is correct (1=urban, 2=rural)

### Problem: Long Download Times

**Error**: `model_setup()` appears to hang on first run.

**Solution**: First download of global datasets is slow. Progress is logged; let it complete. Subsequent runs use cached data.

### Problem: Out of Memory

**Error**: `MemoryError` on large AOI

**Solution**: The model uses Dask lazy evaluation. For very large regions (>1000 km²):
1. Reduce AOI size
2. Increase available RAM
3. Process in tiles (not yet automated)

---

## Performance Tips

1. **Reuse settings.toml**: Set up exposure once, run many scenarios
2. **Batch multiple scenarios**: Run in a loop to avoid repeated data I/O
3. **Check outputs incrementally**: Don't wait for all plots; inspect after first run
4. **Monitor disk space**: NetCDF outputs for large grids can be 100s of MB

---

## Further Resources

- **Module Overview**: [MODULE_OVERVIEW.md](MODULE_OVERVIEW.md)
- **Workflow Details**: [WORKFLOW.md](WORKFLOW.md)
- **API Reference**: [API_REFERENCE.md](API_REFERENCE.md)
- **Example Notebooks**:
  - `examples/detailed/4_run_model.ipynb` — Step-by-step walkthrough
  - `examples/quickbuild/B_run_paramaribo_scenarios.ipynb` — Multi-scenario example
- **GitHub Issues**: [Report bugs or request features](https://github.com/Deltares-research/D-Health-Microbial/issues)
