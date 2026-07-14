# D-Health Workflow: Inputs → Processing → Outputs

This document describes the complete data flow from preparation through modeling to results.

---

## 1. Setup Phase: Preparing Exposure Data

### Purpose
Create reusable exposure configuration (`settings.toml`) for a region, independent of any specific flood scenario.

### Workflow

```
User Input (AOI bbox)
    ↓
Step 1: Call model_setup()
├─ Download WorldPop population grid
├─ Download GHS-SMOD urban/rural classification
├─ Download World Bank indicators (sanitation, GDP)
├─ Clip to AOI bounding box
├─ Reproject to common CRS
├─ Save to setup directory
    ↓
Step 2: Auto-generate settings.toml
├─ Reference downloaded exposure files
├─ Validate file paths and formats
└─ Output: Reusable settings file
    ↓
Result: ModelSetupResult
├─ root_dir: Path to setup directory
├─ settings_toml: Path to settings file
├─ population: Path to population netCDF
├─ urban_rural: Path to urban/rural netCDF
├─ country_indicators: Path to indicators TOML
├─ country_code: ISO3, derived from AOI
└─ country_name: From reverse geocoding (None if ISO3 was supplied)
```

### Python API Example

```python
from d_health import model_setup

# Define AOI (bounding box in EPSG:4326)
aoi = (-55.27, 5.78, -55.10, 5.93)  # Paramaribo, Suriname

result = model_setup(
    aoi=aoi,
    root_dir="data/setup_paramaribo",
    # Optional overrides:
    # country_code="SUR",  # Force specific country
    # population_url="...",  # Custom WorldPop source
)

print(f"Setup saved to: {result.root_dir}")
print(f"Settings TOML: {result.settings_toml}")
print(f"Country: {result.country_code}")
```

### Outputs

| File | Format | Description |
|------|--------|-------------|
| `settings.toml` | Text | Configuration referencing exposure files (portable, reusable) |
| `population.nc` | NetCDF | Population grid (units: persons/cell) with `group` dimension (e.g., `children`, `adults`, `total`) |
| `urban_rural.nc` | NetCDF | GHS-SMOD classification: `1`=urban, `2`=rural, `0`=nodata |
| `country_indicators.toml` | Text | Per-tier sanitation coverage (%) and GDP per capita |
| `.metadata/` | Directory | Provenance: download URLs, timestamps, versions |

---

## 2. Configuration Phase: Define a Run Scenario

### Purpose
Specify which flood event to model and where to save outputs.

### Workflow

```
Starting from: settings.toml (from Setup Phase)
    ↓
User provides:
├─ Flood depth map (GeoTIFF)
├─ Output directory
└─ Optional: Custom population groups, output settings
    ↓
Step 1: Call write_run_config_from_setup()
├─ Read settings.toml
├─ Inject flood_depth_map path
├─ Set output directory
├─ Auto-generate run-specific config.toml
    ↓
Result: config.toml
├─ References exposure data (from settings.toml)
├─ References flood map
├─ Specifies output locations
└─ Includes run metadata
```

### Python API Example

```python
from d_health import write_run_config_from_setup

result = write_run_config_from_setup(
    settings_toml="data/setup_paramaribo/settings.toml",
    flood_depth_map="data/flood_maps/wl3m_paramaribo.tif",
    run_config_path="data/runs/paramaribo_wl3m/config.toml",
    output_out_dir="outputs/run/scenario_wl3m",
)

print(f"Run config: {result}")
```

### CLI Alternative

```bash
d-health setup --bbox <xmin> <ymin> <xmax> <ymax> --root data/setup_paramaribo
```

(There is no `setup-aoi` command, and `--bbox` takes four space-separated
numbers, not a comma-separated string.)

---

## 3. Modeling Phase: Execute the Pipeline

### Purpose
Load inputs, compute emissions → concentration → dose → risk → infection counts.

### Workflow

```
Inputs:
├─ config.toml (run configuration)
├─ population.nc (from setup)
├─ urban_rural.nc (from setup)
├─ country_indicators.toml (from setup)
└─ flood_depth_map.tif (provided by user)
    ↓
Pipeline Stage 1: Load & Align
├─ Read all rasters
├─ Align onto the POPULATION raster's grid (its CRS + resolution)
│  (the flood map is area-averaged onto it — it does NOT define the grid)
├─ Clip all three to the intersection of their footprints
└─ Validate: common grid asserted; negative depths clipped to 0 with a warning
    ↓
Pipeline Stage 2: Emissions
├─ Lookup sanitation coverage per country
├─ Compute E. coli load per cell
└─ Output: emissions.nc (CFU per cell, per flood event)
    ↓
Pipeline Stage 3: Concentration
├─ Simulate pathogen dilution in flood water
├─ Account for inundated area
└─ Output: pathogen_conc.nc (CFU per 100 mL; NaN on dry cells)
    ↓
Pipeline Stage 4: Exposure & Dose
├─ Match population groups to depth thresholds
├─ Compute water ingestion per group
│  (varies by depth: wading vs swimming)
├─ Calculate dose per individual
└─ Output: dose_<group>.nc (CFU/person)
    ↓
Pipeline Stage 5: Risk (Dose-Response)
├─ Apply Beta-Poisson model
├─ Convert dose → infection probability
└─ Output: risk_<group>.nc (0–1 per individual)
    ↓
Pipeline Stage 6: Infected Population
├─ Multiply risk × population per cell
├─ Aggregate by group
└─ Output: infected_<group>.nc (persons)
    ↓
Postprocessing:
├─ Compute flood classes (0=dry, 1..n=depth bands)
├─ Classify risk per group
├─ Generate plots (only when output.plots = true)
└─ Write NetCDF + PNG (no GeoTIFF, no JSON)
    ↓
Result: ModelOutputs  (in memory — summary stats are NOT written to disk)
├─ emissions, pathogen_conc (np.ndarray)
├─ doses, risks, infected (dict[group_name, np.ndarray])
├─ flood_classes (np.ndarray)
├─ totals (summary dict: {"infected_adults": N, ...})
├─ paths (file locations of the written rasters/plots)
└─ coverage, risk_class_counts, risk_class_edges (aggregated stats)
```

### Python API Example

```python
from d_health import run_model_from_toml

# The parameter is `path` — positional is simplest.
result = run_model_from_toml("data/runs/paramaribo_wl3m/config.toml")

print(f"Total infected adults: {result.totals['infected_adults']:.0f}")
print(f"Total infected children: {result.totals['infected_children']:.0f}")
print(f"Output directory: {result.paths['emissions'].parent}")
```

### CLI Alternative

```bash
d-health run -c data/runs/paramaribo_wl3m/config.toml
```

---

## 4. Output Files

### Quantitative Results (NetCDF)

Located in `output.out_dir` from the config. **Everything is netCDF — the
pipeline writes no GeoTIFFs.**

Per-group quantities are stacked along a `group` dimension, so `risk.nc` holds
one `risk` variable with `group = [adults, children]`, *not* separate
`risk_adults` / `risk_children` variables. Select with
`ds["risk"].sel(group="adults")`.

```
outputs/run/scenario_wl3m/
├── emissions.nc
│   ├── Variable: emissions        (dims: y, x)
│   └── Units: CFU per cell, per flood event
├── pathogen_conc.nc
│   ├── Variable: pathogen_conc    (dims: y, x)
│   └── Units: CFU per 100 mL. NaN on dry cells (no floodwater = no concentration)
├── flood_classes.nc
│   ├── Variable: flood_classes    (dims: y, x; int16)
│   ├── 0 = dry
│   ├── 1 = wet, but below every group's lowest threshold (nobody exposed)
│   └── 2..n = the activity bands, derived from the groups' depth thresholds
├── dose.nc
│   ├── Variable: dose             (dims: group, y, x)
│   └── Units: CFU ingested per event
├── risk.nc
│   ├── Variable: risk             (dims: group, y, x)
│   └── Units: infection probability (0–1)
└── infected.nc
    ├── Variable: infected         (dims: group, y, x)
    └── Units: persons (fractional)
```

Unexposed cells are **NaN**, not zero, in `pathogen_conc`, `dose`, `risk` and
`infected`. Aggregate with `np.nansum` / `np.nanmean`.

### Summary Statistics

**Not written to disk.** There are no `totals.json`, `coverage.json` or
`risk_class_counts.json` files. The statistics are returned on the
`ModelOutputs` object:

```python
result = run_model_from_toml("config.toml")

result.totals              # {"infected_adults": 1234.5, "infected_children": 789.3}
result.coverage.total      # {"total": ..., "adults": ..., "children": ...}
result.coverage.flooded    # population inside the flooded area
result.coverage.dry        # population outside it
result.coverage.per_class  # {flood_class: {group: count}}
result.risk_class_counts   # {group: ndarray over risk bins}
result.risk_class_edges    # (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
```

Serialise them yourself if you want them on disk.

### Visualizations (PNG)

Only when `output.plots = true`.

```
outputs/run/scenario_wl3m/
├── emissions.png            ← Emissions map
├── flood_classes.png        ← Depth-class map
├── risk_histogram.png       ← ONE chart; groups appear as bar series
├── dose_adults.png          ← One map per group, per quantity
├── dose_children.png
├── risk_adults.png
├── risk_children.png
├── infected_adults.png
└── infected_children.png
```

---

## 5. Input Data Specifications

### Population Grid (`population.nc` or `.tif`)

| Property | Value |
|----------|-------|
| **Spatial Dimensions** | (lat, lon) or (y, x) |
| **Group Dimension** | Named groups: `adults`, `children`, `total` (optional) |
| **Unit** | persons per cell |
| **Data Type** | float32 or float64 |
| **CRS** | Any (auto-reprojected) |
| **Resolution** | Typically 100 m or finer |

**Example (NetCDF structure)**:
```
Dimensions:
    lat: 1000
    lon: 1200
    group: 3

Variables:
    population[lat, lon, group]
        - attributes: units = "persons"
    group: ["children", "adults", "total"]
```

### Urban/Rural Grid (`urban_rural.nc` or `.tif`)

| Property | Value |
|----------|-------|
| **Encoding** | `1`=urban, `2`=rural, `0`=nodata |
| **Resolution** | Same as population grid (auto-resampled) |
| **CRS** | Any |

### Flood Depth Map (`flood_depth_map.tif`)

| Property | Value |
|----------|-------|
| **Units** | Meters (positive depth) |
| **Data Type** | float32 |
| **CRS** | Any (auto-reprojected to match population) |
| **No-data Value** | 0 or negative (treated as dry) |
| **Resolution** | Model output resolution will match this |

### Country Indicators (`country_indicators.toml`)

```toml
gdp_per_capita_usd = 8500

[sanitation_coverage]
urban_improved = 0.75
urban_unimproved = 0.25
rural_improved = 0.40
rural_unimproved = 0.60
```

---

## 6. Multi-Scenario Workflow

### Repeat for Multiple Flood Maps

```python
from d_health import write_run_config_from_setup, run_model_from_toml

settings_toml = "data/setup_paramaribo/settings.toml"
flood_scenarios = {
    "wl1m": "data/flood_maps/wl1m_paramaribo.tif",
    "wl3m": "data/flood_maps/wl3m_paramaribo.tif",
    "rp100": "data/flood_maps/rp100_paramaribo.tif",
}

for scenario_name, flood_map in flood_scenarios.items():
    # Generate config
    config_path = f"data/runs/{scenario_name}/config.toml"
    write_run_config_from_setup(
        settings_toml=settings_toml,
        flood_depth_map=flood_map,
        run_config_path=config_path,
        output_out_dir=f"outputs/run/scenario_{scenario_name}",
    )

    # Run model
    result = run_model_from_toml(config_path)
    print(f"Scenario {scenario_name}: {result.totals['infected_adults']:.0f} infected")
```

---

## 7. Data Quality & Validation

### Automatic Checks

1. **Path Resolution**: Relative paths in config resolved to absolute
2. **File Existence**: All input files verified at config load time
3. **CRS Handling**: All rasters reprojected to common CRS
4. **Grid Alignment**: All inputs resampled to match flood depth map
5. **Dimension Names**: Population groups validated against config
6. **Value Ranges**: Flood depth ≥ 0; risk ∈ [0, 1]

### Manual Verification (Recommended)

Before running, check:
- [ ] Population grid matches country/region
- [ ] Urban/rural layer has sensible spatial pattern
- [ ] Flood depth map covers expected area
- [ ] Country indicators match country in AOI
- [ ] Population and flood grids have overlapping extent

---

## 8. Example: Complete Setup & Run

```python
from d_health import (
    model_setup,
    write_run_config_from_setup,
    run_model_from_toml,
)

# ========== SETUP PHASE (Once per region) ==========
aoi = (-55.27, 5.78, -55.10, 5.93)  # Paramaribo, Suriname
setup = model_setup(
    aoi=aoi,
    root_dir="data/setup_paramaribo"
)
print(f"Setup complete: {setup.settings_toml}")

# ========== CONFIG PHASE (Once per scenario) ==========
config_path = write_run_config_from_setup(
    settings_toml=setup.settings_toml,
    flood_depth_map="data/floods/wl3m.tif",
    run_config_path="data/runs/wl3m/config.toml",
    output_out_dir="outputs/wl3m",
)
print(f"Config saved: {config_path}")

# ========== MODEL PHASE (Once per scenario) ==========
result = run_model_from_toml(config_path)
print(f"Adults infected: {result.totals['infected_adults']:.0f}")
print(f"Children infected: {result.totals['infected_children']:.0f}")
print(f"Total: {sum(result.totals.values()):.0f}")

# ========== ANALYSIS PHASE ==========
# Coverage is on the result object — the pipeline writes no JSON.
print(f"Flooded population: {result.coverage.flooded['total']:.0f}")
print(f"Dry population:     {result.coverage.dry['total']:.0f}")
```

---

## Additional Resources

- **Module Overview**: [MODULE_OVERVIEW.md](MODULE_OVERVIEW.md)
- **API Reference**: [API_REFERENCE.md](API_REFERENCE.md)
- **User Guide**: [USER_GUIDE.md](USER_GUIDE.md)
- **Example Notebooks**: `examples/detailed/` and `examples/quickbuild/`
