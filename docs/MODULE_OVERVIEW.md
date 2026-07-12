# D-Health Module Overview

## What is D-Health?

**D-Health** (Floods and Health Tool) is a scientific modeling framework that estimates the health impacts of flooding, specifically the risk of *E. coli* infection among populations exposed to flood water.

### Core Purpose

Given a flood event and a region's population distribution, D-Health computes:
- **Pathogen concentration** in flood waters (based on emissions from sanitation infrastructure)
- **Population exposure** (who is flooded at what depth)
- **Dose ingested** by individuals (water intake varies by age and water depth)
- **Infection risk** per individual (using dose-response models)
- **Infected population** counts and spatial distribution

### Why It Matters

Flood-related diseases are a major public health concern, especially in countries with limited sanitation coverage. D-Health bridges water simulation and epidemiology by translating flood depth maps into quantified health risks.

---

## Module Architecture

### Data Flow

```
Input Data Layer
├── Population distribution (age groups)
├── Urban/rural classification
├── Flood depth map
└── Country-level sanitation/economic indicators
        ↓
Preprocessing Layer
├── Align all rasters to a common grid
├── Classify population into behavioral groups
└── Load country indicators
        ↓
Model Pipeline
├── Emissions: Compute E. coli load in flood water
├── Concentration: Calculate pathogen concentration per cell
├── Exposure: Assign water depth to population groups
├── Dose: Estimate ingested water volume per individual
├── Risk: Apply dose-response model (beta-poisson)
└── Infected: Calculate fraction infected per group
        ↓
Output Layer
├── NetCDF files: emissions, concentration, doses, risks, infected
├── Geotiff: flood_classes, classified risk
├── Plots: per-group statistics, risk histograms, spatial maps
└── Summaries: total infected population by group
```

### Key Components

#### 1. **Configuration (`d_health.config`)**
   - Defines the full run specification (exposure data, flood event, output settings)
   - Validates inputs and paths at load time
   - Supports TOML-based configuration for reproducibility

#### 2. **Preprocessing (`d_health.preprocessing`)**
   - Downloads and prepares open-source global datasets:
     - **WorldPop**: High-resolution population grids (~100 m)
     - **GHS-SMOD**: Global human settlement layer (urban/rural classification)
     - **World Bank WDI**: Sanitation coverage, GDP per capita by country
   - Clips and resamples data to a user-defined area of interest (AOI)

#### 3. **Model Pipeline (`d_health.model`)**
   - **Emissions**: E. coli load in wastewater based on sanitation indicators
   - **Concentration**: Dilution of pathogen in floodwater
   - **Dose**: Ingestion rate varies by depth and age group
   - **Risk**: Beta-Poisson dose-response model (from WHO/QMRA literature)
   - **Infected**: Probability of infection per individual

#### 4. **Postprocessing (`d_health.postprocessing`)**
   - Aggregate results by population group
   - Classify flood depth into risk bands
   - Generate plots and summary statistics
   - Compute population coverage within flood extent

#### 5. **Geospatial Utilities (`d_health.geo`, `d_health.io`)**
   - Raster alignment and resampling
   - NetCDF and GeoTIFF I/O
   - Metadata preservation (CRS, geotransform)

---

## Conceptual Workflow

### Stage 1: Setup (One-time per region)
1. Define your **area of interest** (bounding box in lat/lon)
2. D-Health auto-downloads and clips:
   - Population data from WorldPop
   - Urban/rural classification from GHS-SMOD
   - Country indicators (sanitation, GDP) from World Bank
3. Output: `settings.toml` (reusable across all flood scenarios for this region)

### Stage 2: Run Model (Once per flood scenario)
1. Provide:
   - A **flood depth map** (raster, any CRS; auto-reprojected)
   - The **settings.toml** from Stage 1
2. Model computes:
   - Emissions from sanitation coverage
   - Pathogen concentration in flood water
   - Dose per population group
   - Infection risk and counts
3. Output: NetCDF files, classified maps, plots, summary statistics

### Stage 3: Analyze
1. Load model outputs from NetCDF
2. Aggregate by admin region (optional)
3. Visualize and compare across scenarios

---

## Key Data Inputs

### Required Files

| Input | Format | Description |
|-------|--------|-------------|
| `population` | NetCDF or GeoTIFF | Population per cell, labeled with age groups (e.g., `children`, `adults`) |
| `urban_rural` | NetCDF or GeoTIFF | GHS-SMOD classification: `1`=urban, `2`=rural, `0`=nodata |
| `country_indicators` | TOML | Per-tier sanitation coverage (%) and GDP per capita |
| `flood_depth_map` | GeoTIFF | Flood depth in meters, any CRS (auto-aligned) |

### Configuration (TOML)

**settings.toml** (one per region, reusable):
```toml
[exposure]
population = "data/paramaribo_population.nc"
urban_rural = "data/paramaribo_urban_rural.nc"
country_indicators = "data/suriname_indicators.toml"
```

**config.toml** (one per run/scenario):
```toml
[exposure]
# ... same as settings.toml ...

[event]
flood_depth_map = "flood_maps/wl3m_scenario.tif"

[output]
out_dir = "outputs/run_wl3m"
plots = true
```

---

## Key Data Outputs

### Quantitative Results (NetCDF)

Everything is netCDF. Per-group quantities are **one variable stacked along a
`group` dimension**, not one file (or variable) per group.

| Output | Unit | Description |
|--------|------|-------------|
| `emissions.nc` | CFU per cell, per event | E. coli load per cell (population × sanitation × GDP weight) |
| `pathogen_conc.nc` | CFU per 100 mL | Concentration in floodwater. **NaN on dry cells** |
| `dose.nc` | CFU per event | Ingested dose, dims `(group, y, x)` |
| `risk.nc` | 0–1 | Infection probability, dims `(group, y, x)` |
| `infected.nc` | persons | Expected infected count, dims `(group, y, x)` |
| `flood_classes.nc` | int16 | `0`=dry, `1`=wet but below every threshold, `2..n`=activity bands |

Select a group with `ds["risk"].sel(group="adults")`.

### Summaries

Returned on the `ModelOutputs` object — **nothing is written to disk**. There are
no `totals.json` / `coverage.json` files.

| Attribute | Content |
|-----------|---------|
| `totals` | `{"infected_<group>": count}` |
| `coverage` | Flooded-vs-dry population breakdown, plus per flood class |
| `risk_class_counts` | Population histogram over risk bins, per group |

### Plots (only when `output.plots = true`)

| Output | Content |
|--------|---------|
| `emissions.png` | Emissions map |
| `flood_classes.png` | Map of flood depth classes |
| `risk_histogram.png` | One chart; each group is a bar series |
| `dose_<group>.png`, `risk_<group>.png`, `infected_<group>.png` | One map per group, per quantity |

---

## Population Groups & Behavioral Thresholds

The model divides population into **groups** (e.g., adults, children) with **depth-dependent behaviors**:

| Group | Activity | Min Depth | Water Intake |
|-------|----------|-----------|--------------|
| Adults (Wading) | Playing/working at water edge | 0.1 m | 10 ml/h |
| Adults (Swimming) | Swimming/diving | 1.5 m | 30 ml/h |
| Children (Wading) | Playing at water edge | 0.1 m | 30 ml/h |
| Children (Swimming) | Swimming/wading in deep water | 0.5 m | 50 ml/h |

These are defaults; they can be customized in configuration.

---

## Methodological Details

### Sanitation-Based Emissions

E. coli load in wastewater is estimated from:
$$\text{Emissions} = \text{Population} \times \text{E. coli per capita} \times f(\text{sanitation tier})$$

Where sanitation tiers are:
- **Urban improved** (sewered): Low E. coli (treatment)
- **Urban unimproved** (septic/pit): Moderate
- **Rural improved**: Moderate
- **Rural unimproved**: High (minimal treatment)

### Dose-Response Model (Beta-Poisson)

Infection probability given ingested dose ($d$):
$$P(\text{infection} | d) = 1 - \left(1 + \frac{d}{N50}\right)^{-\alpha}$$

Parameters ($N50$, $\alpha$) are from WHO QMRA guidelines for *E. coli* O157:H7.

### Spatial Grid Alignment

All rasters are resampled to match the **flood map resolution** using:
- Population, urban/rural: nearest-neighbor (preserve categories)
- Outputs: same grid as flood map

---

## Design Principles

1. **Reproducibility**: All inputs versioned; TOML-based config; locked dependencies
2. **Modularity**: Each stage (emissions → dose → risk) is independent and testable
3. **Transparency**: Intermediate outputs available; metadata preserved
4. **Scalability**: Dask support for large rasters; processed at native resolution
5. **Open Data**: Relies on freely available global datasets (WorldPop, GHS, World Bank)

---

## Further Reading

- **Examples**: See `examples/detailed/` and `examples/quickbuild/` for step-by-step notebooks
- **API Reference**: See [API_REFERENCE.md](API_REFERENCE.md)
- **User Guide**: See [USER_GUIDE.md](USER_GUIDE.md)
- **Workflow**: See [WORKFLOW.md](WORKFLOW.md)
