# D-Health Documentation

Complete documentation for the D-Health (Floods and Health Tool) module.

---

## Documentation Structure

This folder contains four main documentation guides:

### 1. **[MODULE_OVERVIEW.md](MODULE_OVERVIEW.md)** — Start Here
**For**: Understanding what D-Health does and how it works.

Covers:
- What is D-Health and why it matters?
- Overall module architecture and data flow
- Key components (preprocessing, model pipeline, postprocessing)
- Conceptual workflow (setup → configure → run → analyze)
- Key data inputs and outputs
- Population groups and behavioral thresholds
- Methodological details (emissions, dose-response)

**Read this first** if you're new to D-Health.

---

### 2. **[WORKFLOW.md](WORKFLOW.md)** — Detailed Process Flow
**For**: Understanding the complete input → output pipeline.

Covers:
- Setup phase (downloading & preparing exposure data)
- Configuration phase (defining a flood scenario)
- Modeling phase (full pipeline execution)
- Detailed output file specifications
- Input data specifications and formats
- Multi-scenario workflows
- Data quality & validation
- Complete end-to-end example

**Read this** to understand the data flow and file requirements.

---

### 3. **[USER_GUIDE.md](USER_GUIDE.md)** — Practical How-To
**For**: Learning how to use D-Health in practice.

Covers:
- Installation & setup (pixi, environment activation)
- Task 1: Set up exposure data for a new region
- Task 2: Run the model for one flood scenario
- Task 3: Compare multiple flood scenarios
- Task 4: Load and analyze results
- Task 5: Customize population groups & thresholds
- Task 6: Command-line usage
- Troubleshooting guide
- Performance tips

**Read this** for step-by-step examples and practical guidance.

---

### 4. **[API_REFERENCE.md](API_REFERENCE.md)** — Function Reference
**For**: Looking up specific functions and classes.

Covers:
- Top-level functions (recommended entry points)
  - `model_setup()`
  - `write_run_config_from_setup()`
  - `run_model_from_toml()`
  - `run_model()`
- Configuration classes
  - `RunConfig`, `ExposureConfig`, `EventConfig`, `Settings`
- Data classes
  - `ModelOutputs`, `ModelSetupResult`
- Preprocessing functions
  - Population, urban/rural, country indicators
- Model pipeline functions (internal)
- Postprocessing functions
- I/O functions
- Common usage patterns
- Error handling

**Read this** when you need details on a specific function or class.

---

## Quick Navigation

### I want to...

**...understand what D-Health does**
→ Start with [MODULE_OVERVIEW.md](MODULE_OVERVIEW.md)

**...learn how to use D-Health**
→ Read [USER_GUIDE.md](USER_GUIDE.md) (practical examples)

**...understand the data pipeline**
→ Read [WORKFLOW.md](WORKFLOW.md) (inputs, processing, outputs)

**...look up a specific function**
→ See [API_REFERENCE.md](API_REFERENCE.md)

**...compare multiple flood scenarios**
→ [USER_GUIDE.md Task 3](USER_GUIDE.md#task-3-compare-multiple-flood-scenarios)

**...customize population groups**
→ [USER_GUIDE.md Task 5](USER_GUIDE.md#task-5-customize-population-groups--depth-thresholds)

**...troubleshoot an error**
→ [USER_GUIDE.md Troubleshooting](USER_GUIDE.md#troubleshooting)

---

## Reading Order

### Beginner

1. [MODULE_OVERVIEW.md](MODULE_OVERVIEW.md) — Understand the concept
2. [USER_GUIDE.md](USER_GUIDE.md) (Task 1–2) — Set up and run your first model
3. [USER_GUIDE.md](USER_GUIDE.md) (Task 4) — Load and visualize results

### Intermediate

1. [WORKFLOW.md](WORKFLOW.md) — Understand the full pipeline
2. [USER_GUIDE.md](USER_GUIDE.md) (Task 3) — Run multiple scenarios
3. [USER_GUIDE.md](USER_GUIDE.md) (Task 5) — Customize for your use case

### Advanced

1. [API_REFERENCE.md](API_REFERENCE.md) — Function-level details
2. Example Notebooks — In `examples/detailed/` and `examples/quickbuild/`
3. Source Code — In `d_health/` directory

---

## Key Concepts

### Area of Interest (AOI)
A geographic bounding box (latitude/longitude) that defines your study region. Specified as `(lon_min, lat_min, lon_max, lat_max)`.

### Setup Phase
One-time preparation of exposure data (population, urban/rural, country indicators) for a region. Output: `settings.toml` (reusable).

### Run Phase
Model execution for a specific flood scenario. Input: `settings.toml` + flood map. Output: Expected infected population; calculated as infection probability × population. Values may be fractional and are not observed cases.

### Population Groups
Categories of people with different exposure behaviors (e.g., adults vs. children; wading vs. swimming). Each group has depth-dependent water intake rates.

### Dose-Response Model
Mathematical relationship between ingested pathogen dose and infection probability. D-Health uses the Beta-Poisson model from WHO QMRA guidelines.

---

## Data Overview

### Input Files

| Name | Type | Source | Unit |
|------|------|--------|------|
| Population | NetCDF or GeoTIFF | WorldPop (auto-downloaded) | persons/cell |
| Urban/Rural | NetCDF or GeoTIFF | GHS-SMOD (auto-downloaded) | classification (1=urban, 2=rural) |
| Country Indicators | TOML | World Bank (auto-downloaded) | sanitation %, GDP |
| Flood Depth Map | GeoTIFF or NetCDF | User-provided | metres flood depth; >0 flooded, 0/negative/NaN dry |

### Output Files

Every raster is netCDF **or** GeoTIFF, per `output.raster_format` — one or the other,
never both. The suffix below is `.nc` by default and `.tif` when
`raster_format = "geotiff"`. The pipeline writes no JSON.

| Name | Type | Content |
|------|------|---------|
| `emissions.<nc\|tif>` | Raster | E. coli load per cell (CFU per flood event) |
| `pathogen_conc.<nc\|tif>` | Raster | Concentration (CFU per 100 mL; **NaN where dry**) |
| `dose.<nc\|tif>` | Raster | Ingested dose, per group (CFU/event) |
| `risk.<nc\|tif>` | Raster | Expected infected population, per group (0-1); calculated as risk × population |
| `infected.<nc\|tif>` | Raster | Expected Infected population, per group (persons) |
| `flood_classes.<nc\|tif>` | Raster | Depth classification (0=dry, 1=wet-but-unexposed, 2..n=bands) |
| `*.png` | PNG | Plots and maps (only when `output.plots = true`) |

Per-group quantities are one variable stacked along `group` in netCDF — select with
`ds["risk"].sel(group="adults")`, not `ds["risk_adults"]`. In GeoTIFF they become one
band per group, each band named after its group label; `load_population` reads either
layout back to the same labelled `group` dim.

Summary statistics (`totals`, `coverage`, `risk_class_counts`) are **returned on
the `ModelOutputs` object**, not written to disk.

---

## Common Workflows

### Workflow 1: One-Time Setup + Single Run

```python
from d_health import model_setup, write_run_config_from_setup, run_model_from_toml

# Setup (once per region)
setup = model_setup(aoi=(...), root_dir="setup")

# Configure (once per scenario)
config_path = write_run_config_from_setup(
    settings_toml=setup.settings_toml,
    flood_depth_map="flood.tif",
    run_config_path="config.toml",
    output_out_dir="outputs",
)

# Run (once per scenario)
result = run_model_from_toml(config_path)
print(f"Infected: {result.totals}")
```

### Workflow 2: Multi-Scenario Comparison

```python
# Setup once
setup = model_setup(aoi=(...), root_dir="setup")

# Run each scenario
for scenario_name, flood_map in scenarios.items():
    config = write_run_config_from_setup(
        settings_toml=setup.settings_toml,
        flood_depth_map=flood_map,
        run_config_path=f"{scenario_name}/config.toml",
        output_out_dir=f"outputs/{scenario_name}",
    )
    result = run_model_from_toml(config)
    print(f"{scenario_name}: {result.totals['infected_adults']:.0f}")
```

### Workflow 3: Custom Population Groups

```python
from d_health.config.groups import PopulationGroup, DepthThreshold

custom_groups = [
    PopulationGroup(
        name="infants",
        depth_thresholds=[DepthThreshold(...)]
    ),
]

config_path = write_run_config_from_setup(
    settings_toml=...,
    flood_depth_map=...,
    run_config_path=...,
    output_out_dir=...,
    population_groups=custom_groups,
)
```

---

## Troubleshooting

**Problem**: Model runs but results are all zero/NaN
- Check: Do population and flood maps overlap spatially?
- Check: Are population grid dimensions correct (has `group` dimension)?
- Check: Is country_indicators.toml valid?

**Problem**: Setup fails to download data
- Cause: Network issue or invalid AOI
- Solution: Check AOI coordinates are valid (lon_min < lon_max, lat_min < lat_max)
- Solution: Verify internet connection

**Problem**: Out of memory
- Cause: AOI too large for available RAM
- Solution: Reduce AOI or split into smaller regions

For more troubleshooting, see [USER_GUIDE.md Troubleshooting](USER_GUIDE.md#troubleshooting).

---

## External Resources

- **GitHub Repository**: [D-Health-Microbial](https://github.com/Deltares-research/D-Health-Microbial)
- **Pixi Documentation**: [pixi.sh](https://pixi.sh)
- **WorldPop Data**: [worldpop.org](https://www.worldpop.org)
- **GHS-SMOD Data**: [GHS Settlement Data](https://ghsl.jrc.ec.europa.eu)
- **WHO QMRA**: [Quantitative Microbial Risk Assessment](https://www.who.int/publications/i/item/quantitative-microbial-risk-assessment)

---

## Contributing & Support

- **Report a Bug**: [GitHub Issues](https://github.com/Deltares-research/D-Health-Microbial/issues)
- **Request a Feature**: [GitHub Discussions](https://github.com/Deltares-research/D-Health-Microbial/discussions)
- **Ask a Question**: Open a GitHub Discussion or Issue

---

## Document Versions

| Document | Version | Last Updated |
|----------|---------|--------------|
| MODULE_OVERVIEW.md | 1.0 | 2026-07-03 |
| WORKFLOW.md | 1.0 | 2026-07-03 |
| USER_GUIDE.md | 1.0 | 2026-07-03 |
| API_REFERENCE.md | 1.0 | 2026-07-03 |

---

## Quick Reference

### Key Functions

| Function | Purpose | Input | Output |
|----------|---------|-------|--------|
| `model_setup()` | Download & prepare exposure data | AOI, directory | `settings.toml`, data files |
| `write_run_config_from_setup()` | Generate run configuration | settings.toml, flood map | `config.toml` |
| `run_model_from_toml()` | Execute model pipeline | config.toml | `ModelOutputs` (results) |

### Key Classes

| Class | Purpose |
|-------|---------|
| `RunConfig` | Complete model run specification |
| `ModelOutputs` | Model results (emissions, doses, risks, infected) |
| `PopulationGroup` | Definition of a population group (age, behavior) |

### Key Input Data

| Input | Source | Auto-downloaded? |
|-------|--------|------------------|
| Population | WorldPop | ✓ Yes |
| Urban/Rural | GHS-SMOD | ✓ Yes |
| Country Indicators | World Bank | ✓ Yes |
| Flood Map | User-provided | ✗ No |

---

## License

This documentation is part of the D-Health project. See LICENSE file in the main repository.
