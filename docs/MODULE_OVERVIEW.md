# D-Health-Microbial Module Overview

## What is D-Health-Microbial?

**D-Health-Microbial** (Floods and Health Tool) is a scientific modeling framework that estimates microbial infection risk for humans that are exposed to floodwater. The current default implementation uses *E. coli* as the reference organism.

### Core Purpose

Given a flood event and a region's population distribution, D-Health computes:
- **Pathogen concentration** in floodwater (based on emissions from sanitation infrastructure)
- **Population exposure** (who is flooded at what depth)
- **Dose ingested** by individuals (water intake varies by age and water depth)
- **Infection risk** per individual (using dose-response models)
- **Expected infected population** and spatial distribution

### Why It Matters

Flood-related diseases are a major public health concern, especially in countries with limited sanitation coverage. D-Health-Microbial bridges flooding simulation and epidemiology by translating flood depth maps into quantified health risks.

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
├── Emissions: Compute E. coli load in floodwater
├── Concentration: Calculate pathogen concentration per cell
├── Exposure: Assign water depth to population groups
├── Dose: Estimate ingested water volume per individual
├── Risk: Apply dose-response model (Beta-Poisson)
└── Expected infections: Calculate infection probability × exposed population per group
        ↓
Output Layer
├── NetCDF files: emissions, concentration, dose, risk, infected
├── Geotiff: flood_classes, classified risk
├── Plots: per-group statistics, risk histograms, spatial maps
└── Summaries: total expected infected population by group
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
   - **Risk**: Probability of infection per individual from Beta-Poisson dose-response model (from WHO/QMRA literature)
   - **Infected**: Number of expected infected individuals

#### 4. **Postprocessing (`d_health.postprocessing`)**
   - Aggregate results by age group, and over polygons (`zonal_sums`)
   - Classify flood depth into risk bands
   - Generate plots and summary statistics
   - Compute expected infected population coverage within flood extent

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
   - Pathogen concentration in floodwater
   - Dose per population group
   - Infection probability and expected infections
3. Output: NetCDF files, classified maps, plots, summary statistics

### Stage 3: Analyze
1. Load model outputs from NetCDF
2. Aggregate by admin region (optional)
3. Visualize and compare across scenarios

---

## Key Data Inputs

### Required Files

| Input | Format | Description | Downloaded as part of module? |
|-------|--------|-------------|-------------------------------|
| `population` | NetCDF or GeoTIFF | Population per cell, labeled with age groups (e.g., `children`, `adults`) | Yes |
| `urban_rural` | NetCDF or GeoTIFF | GHS-SMOD classification: `1`=urban, `2`=rural, `0`=nodata | Yes |
| `country_indicators` | TOML | Per-tier sanitation coverage (%) and GDP per capita | Yes |
| `flood_depth_map` | GeoTIFF or NetCDF | Flood depth in metres; values > 0 are flooded, 0/negative/NaN are dry; any CRS (auto-aligned) | No |

### Configuration (TOML)

**settings.toml** (one per region, reusable):
```toml
[exposure]
population = "data/paramaribo_population.nc"
urban_rural = "data/paramaribo_urban_rural.nc"
country_indicators = "data/suriname_indicators.toml"

[settings]
event_in_hours = 1.0

[settings.pathogen]
selected = "E.coli"

[settings.pathogen.pathogens."E.coli"]
alpha = 0.373
beta = 39.71
source = "Teunis et al. (2008)"

[[settings.population_groups]]
name = "adults"
depth_thresholds = [
    { name = "wading", min_depth = 0.1, ing = 10.0, unit = "ml/h" },
    { name = "swimming", min_depth = 1.5, ing = 30.0, unit = "ml/h" },
]

[[settings.population_groups]]
name = "children"
depth_thresholds = [
    { name = "wading", min_depth = 0.1, ing = 30.0, unit = "ml/h" },
    { name = "swimming", min_depth = 0.5, ing = 50.0, unit = "ml/h" },
]

[settings.emissions]
per_capita_ecoli_rate = 1000000000.0
total_population_group = "total"
sanitation_reductions = [
    { name = "Safe", urban_reduction_factor = 0.1, rural_reduction_factor = 0.1 },
    { name = "Advanced", urban_reduction_factor = 0.25, rural_reduction_factor = 0.25 },
    { name = "Basic", urban_reduction_factor = 0.7, rural_reduction_factor = 0.3 },
    { name = "None", urban_reduction_factor = 1.0, rural_reduction_factor = 1.0 },
]
```
Key parameters are detailed below. Those marked (*editable*) may be varied as part of scenario analysis. We do not recommend editing of other parameters.
- [exposure]: locations of downloaded source files
- [settings]: "event_in_hours" is used if any of the depth_thresholds in [[settings.population_groups]] use the unit 'ml/event' (*editable*)
- [settings.pathogen]: "selected" is the pathogen of interest. Currently "E.coli" is the only option
- [settings.pathogen.pathogens."E.coli"]: alpha and beta values used for the Beta-Poisson dose-response model (*editable*)
- [[settings.population_groups]]: volume of water ingested by adults/children while wading/swimming (*editable*)
- [settings.emissions]:
   - "per_capita_ecoli_rate" is the amount of E.coli emitted by 1 person (CFU/person/day) (*editable*)
   - "sanitation_reductions" is the fraction of pathogen remaining after sanitation measures

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

### Quantitative Results (NetCDF or GeoTIFF)

Every raster is netCDF *or* GeoTIFF, per `output.raster_format` — one or the other,
never both. The `.nc` names below become `.tif` under `raster_format = "geotiff"`.

Per-group quantities are **one variable stacked along a `group` dimension**, not one
file (or variable) per group. In GeoTIFF they are one band per group, each named after
its group label.

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

### Pathogen representation and parameterisation

The model is structured to calculate infection risk for a selected microbial reference organism. In the current default configuration, the selected organism is `E.coli`.

The model distinguishes between:
- the microbial load emitted into floodwater;
- the resulting floodwater concentration;
- the ingested dose during one representative exposure interaction;
- the probability of infection based on a dose-response relation.

The default pathogen parameterisation is:
- selected organism: `E.coli`;
- dose-response model: Beta-Poisson;
- default parameters: alpha = 0.373, beta = 39.71;
- source: Teunis et al. (2008), for *E. coli* O157:H7.

If generic *E. coli* emissions are used as an indicator of faecal contamination rather than as a pathogen-specific input, risk results should be interpreted as relative or indicator-based microbial risk, not as observed clinical *E. coli* O157:H7 infections.

### Sanitation-Based Emissions

E. coli load is estimated from population density, country-level sanitation coverage, and sanitation-specific retained-emission factors:
$$\text{Emissions} = \text{Population} \times \text{E. coli per capita} \times f(\text{sanitation tier})$$

The model does not assign a sanitation type to each individual grid cell. Instead, it uses country-level sanitation coverage fractions and applies them separately to urban and rural cells. This results in one effective retained-emission factor for urban cells and one for rural cells.

The configured sanitation retained-emission factors are:

| Sanitation tier | Retained-emission factor |  | Interpretation |
|---|---:|---:|---|
| Safe | 0.10 | 10% of the baseline E. coli load remains |
| Advanced | 0.25 | 25% of the baseline E. coli load remains |
| Basic | 0.70 | 70% remains in urban cells |
| None | 1.00 | 100% of the baseline E. coli load remains |


The resulting emissions represent a screening-level estimate of local microbial load entering floodwater. The model does not explicitly simulate sewer-network routing, local sanitation infrastructure failure, wastewater transport, die-off, settling, resuspension, or hydrodynamic mixing between cells unless these processes are already represented in the input assumptions.

The model does not know the exact sanitation type of each grid cell. Instead, it applies country-level sanitation coverage fractions separately to urban and rural cells, resulting in one effective retained-emission factor for urban cells and one for rural cells.

Concentration is calculated as local cell dilution only. The model does not simulate hydrodynamic transport, mixing between cells, die-off, settling, resuspension, or sewer-network routing unless these are already represented in the input assumptions.

### Exposure Behaviour and Ingested Dose

Exposure is estimated separately for each population group, for example adults and children. Each group has depth-dependent exposure behaviours that define when contact with floodwater is assumed to occur and how much floodwater is ingested during that contact.

The default population groups and exposure behaviours are:

| Group | Behaviour | Minimum flood depth | Ingestion rate |
|---|---:|---:|---:|
| Adults | Wading | 0.10 m | 10 mL/h |
| Adults | Swimming | 1.50 m | 30 mL/h |
| Children | Wading | 0.10 m | 30 mL/h |
| Children | Swimming | 0.50 m | 50 mL/h |

The model uses the flood depth in each grid cell to determine which exposure behaviour applies. If the flood depth is below the minimum threshold for a population group, no ingestion dose is calculated for that group in that cell. If the flood depth exceeds a threshold, the corresponding ingestion rate is used.

In the default configuration, one modelled flood event represents one day of flooding. During this event, exposed individuals are assumed to have one representative 1-hour contact interaction with floodwater. Therefore, ingestion rates given in `mL/h` are interpreted as the ingested volume during this representative exposure interaction.

For each population group \(g\) and grid cell \(i\), the ingested dose is calculated as:

$$
D_{g,i} = C_i \times \frac{I_{g,i}}{100}
$$

where:

- \(D_{g,i}\) = ingested dose for population group \(g\) in cell \(i\) [CFU/event interaction];
- \(C_i\) = pathogen concentration in floodwater in cell \(i\) [CFU/100 mL];
- \(I_{g,i}\) = ingested floodwater volume for population group \(g\) in cell \(i\) [mL/event interaction];
- \(100\) converts the ingested volume from mL to units of 100 mL.

The resulting dose is then used as input for the dose-response model.

### Dose-Response Model (Beta-Poisson)

In the default configuration, one modelled flood event represents one day of flooding. During that event, exposed individuals are assumed to have one representative 1-hour contact interaction with floodwater. Therefore, ingestion rates given in mL/h are interpreted as the ingested volume during this representative 1-hour interaction.

Infection probability given ingested dose ($d$):
$$P(\text{infection} | d) = 1 - \left(1 + \frac{d}{\beta}\right)^{-\alpha}$$

Default parameters ($\alpha$, $\beta$) are for *E. coli* O157:H7 and taken from Teunis PF, Ogden ID, Strachan NJ. Hierarchical dose response of E. coli O157:H7 from human outbreaks incorporating heterogeneity in exposure. Epidemiol Infect. 2008 Jun;136(6):761-70. doi: 10.1017/S095026880700877.

### Spatial Grid Alignment

All rasters are aligned to the population raster grid. Flood depths are area-averaged onto the population grid; urban/rural classes are nearest-neighbour resampled. Outputs are written on the population grid clipped to the common overlap.

### Model Units and Equations
For each cell i:

1. Emissions
E_i = P_total,i × r_Ecoli × S_i × W_GDP

where:
E_i = E. coli load in cell i [CFU/event]
P_total,i = total population in cell i [persons/cell]
r_Ecoli = baseline per-capita emitted load [CFU/person/event]
S_i = sanitation retained-emission factor [-]
W_GDP = GDP-based emission weight [-]

2. Floodwater concentration
C_i = E_i / (A_i × h_i × 10000), for h_i > 0
C_i = NaN, for h_i ≤ 0 or nodata

where:
C_i = concentration [CFU/100 mL]
A_i = cell area [m²]
h_i = flood depth [m]
10000 = number of 100 mL units per m³

3. Ingested dose for group g
I_g,i = depth-dependent ingested water volume [mL/event]
D_g,i = C_i × I_g,i / 100

where:
D_g,i = ingested dose [CFU/event]

4. Infection probability
R_g,i = 1 - (1 + D_g,i / beta)^(-alpha)

5. Expected infected population
N_g,i = R_g,i × P_g,i

where:
N_g,i = expected infections [persons]
P_g,i = population of group g in cell i [persons/cell]

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
