# API reference

Every signature on this page is generated from the code and checked against it.
If an example here does not run, that is a bug — please report it.

**Version:** 0.1.0 · **Last verified:** 2026-07-12

---

## Contents

- [The public API](#the-public-api)
- [Setup: AOI → exposure inputs](#setup-aoi--exposure-inputs)
- [Running the model](#running-the-model)
- [Preprocessing](#preprocessing)
- [Configuration models](#configuration-models)
- [Results](#results)
- [I/O and geospatial helpers](#io-and-geospatial-helpers)
- [Postprocessing](#postprocessing)

---

## The public API

Everything exported from the top-level package:

```python
from d_health import (
    # setup
    model_setup, write_run_config_from_setup, derive_country_from_aoi,
    ModelSetupOverrides, ModelSetupResult,
    # running
    run_model, run_model_from_toml, load_run_config, RunConfig, ModelOutputs,
    # preprocessing
    get_population_data, WorldPopConfig,
    get_smod_data, GHSSmodConfig,
    get_world_bank_data, WDIConfig,
    get_country_indicators, build_from_wdi,
    # geo
    align_rasters,
    __version__,
)
```

Anything not in that list is internal and may change without notice.

---

## Setup: AOI → exposure inputs

### `model_setup()`

Build the exposure inputs for an area of interest and write a reusable
`settings.toml`. This downloads data (WorldPop, GHS-SMOD, World Bank), so it
needs a network connection and takes a few minutes.

```python
model_setup(
    aoi: Any,
    root_dir: Path | str,
    *,
    overrides: ModelSetupOverrides | None = None,
) -> ModelSetupResult
```

`aoi` accepts a bounds tuple `(xmin, ymin, xmax, ymax)` in EPSG:4326, a shapely
geometry, a GeoJSON dict, or a GeoDataFrame/GeoSeries.

```python
from d_health import model_setup

# Paramaribo, Suriname
result = model_setup(
    aoi=(-55.27, 5.78, -55.10, 5.93),
    root_dir="data/setup_paramaribo",
)

print(result.country_code)        # 'SUR'
print(result.country_name)        # 'Suriname'  (None if --country-iso was given)
print(result.settings_toml)       # .../data/setup_paramaribo/settings.toml
print(result.population)          # .../data/sur_population_2020_combined.nc
print(result.urban_rural)         # .../data/sur_urban_rural.nc
print(result.country_indicators)  # .../data/sur_indicators.toml
print(result.root_dir)            # .../data/setup_paramaribo
```

**Returns** `ModelSetupResult`, with exactly these fields:

| Field | Type | |
|---|---|---|
| `root_dir` | `Path` | The directory that was written to |
| `settings_toml` | `Path` | Reusable settings (no flood map, no output dir) |
| `population` | `Path` | Population netCDF |
| `urban_rural` | `Path` | Urban/rural netCDF |
| `country_indicators` | `Path` | Country indicators TOML |
| `country_code` | `str` | ISO3, e.g. `"SUR"` |
| `country_name` | `str \| None` | From reverse geocoding; `None` if the ISO3 was supplied |

To skip reverse geocoding (and one of the two network round-trips), pass the
country explicitly:

```python
from d_health import model_setup, ModelSetupOverrides

result = model_setup(
    aoi=(-55.27, 5.78, -55.10, 5.93),
    root_dir="data/setup_paramaribo",
    overrides=ModelSetupOverrides(country_code="SUR", population_year=2020),
)
```

### `ModelSetupOverrides`

```python
ModelSetupOverrides(
    country_code: str | None = None,        # ISO3, uppercase; skips reverse geocoding
    population_year: int = 2020,            # 2000..2035
    worldpop: WorldPopConfig = WorldPopConfig(),
    smod: GHSSmodConfig = GHSSmodConfig(),
    wdi: WDIConfig = WDIConfig(),
    settings: SettingsConfig = SettingsConfig(),
    reverse_geocode_timeout_s: float = 30.0,
    reverse_geocode_user_agent: str = "d_health/0.1",
)
```

### `write_run_config_from_setup()`

Turn a `settings.toml` plus a flood map into a runnable `config.toml`. This is
how you run several flood scenarios against one setup.

```python
write_run_config_from_setup(
    settings_toml: Path | str,
    flood_depth_map: Path | str,
    run_config_path: Path | str,
    *,
    output_out_dir: Path | str | None = None,
) -> Path
```

Note the first three arguments are **positional-or-keyword and required**, in
that order.

```python
from d_health import write_run_config_from_setup, run_model_from_toml

for depth in ("01m", "03m", "10m"):
    config_path = write_run_config_from_setup(
        settings_toml="data/setup_paramaribo/settings.toml",
        flood_depth_map=f"data/flood_extremes/flood_wl{depth}.tif",
        run_config_path=f"outputs/run/scenario_wl{depth}/config.toml",
        output_out_dir=f"outputs/run/scenario_wl{depth}",
    )
    outputs = run_model_from_toml(config_path)
    print(depth, outputs.totals)
```

### `derive_country_from_aoi()`

```python
derive_country_from_aoi(
    aoi: Any,
    *,
    timeout_s: float = 30.0,
    user_agent: str = "d_health/0.1",
) -> tuple[str, str | None, tuple[float, float, float, float]]
```

Returns `(iso3, country_name, bounds)`. Makes two network calls (Nominatim
reverse geocode, then the World Bank API for ISO2 → ISO3). `model_setup` calls
this for you unless `overrides.country_code` is set.

---

## Running the model

### `run_model_from_toml()`

The usual entry point.

```python
run_model_from_toml(path: str | Path) -> ModelOutputs
```

```python
from d_health import run_model_from_toml

outputs = run_model_from_toml("outputs/run/scenario_wl03m/config.toml")
print(outputs.totals)   # {'infected_adults': 1234.5, 'infected_children': 678.9}
```

### `run_model()`

```python
run_model(config: RunConfig, *, inputs: ModelInputs | None = None) -> ModelOutputs
```

`inputs` is an escape hatch for tests that build arrays in memory; normally you
pass only `config` and the rasters are loaded from it.

```python
from d_health import load_run_config, run_model

config = load_run_config("config.toml")
outputs = run_model(config)
```

### `load_run_config()`

```python
load_run_config(path: str | Path) -> RunConfig
```

Loads and **validates** a `config.toml`. Relative paths inside it are resolved
against the config file's own directory, so a config is portable regardless of
the working directory you run from.

Validation is strict and happens here, not deep in the pipeline: unknown keys are
rejected (`extra="forbid"`), the country-indicators TOML is parsed, and every
sanitation tier in it must have a matching `sanitation_reductions` entry.

---

## Preprocessing

Each of these downloads a public dataset and writes one model input. They are
independent — call only the ones you need.

### `get_population_data()`

WorldPop age/sex rasters, summed into a netCDF with a labelled `group` dimension
(`children` 0–9, `adults` 10+, `total`).

```python
get_population_data(
    country: str,                    # ISO3, case-insensitive
    year: int,
    output_path: Path | str,         # .tif/.tiff is rewritten to .nc
    *,
    clip: Any = None,                # bounds tuple, shapely, GeoJSON, or GeoDataFrame
    cfg: WorldPopConfig = WorldPopConfig(),
    child_ages: Sequence[str] | None = None,
    adult_ages: Sequence[str] | None = None,
) -> Path
```

```python
from d_health import get_population_data

path = get_population_data(
    "SUR", 2020, "data/sur_population_2020.nc",
    clip=(-55.27, 5.78, -55.10, 5.93),
)
```

### `get_smod_data()`

GHS-SMOD, reclassified to `1` = urban, `2` = rural, `0` = nodata (which includes
water).

```python
get_smod_data(
    output_path: Path | str,
    *,
    clip: Any = None,
    cfg: GHSSmodConfig = GHSSmodConfig(),
) -> Path
```

Note there is **no country argument** — SMOD is a global product, so you clip it
by geometry.

```python
from d_health import get_smod_data

path = get_smod_data("data/sur_urban_rural.nc", clip=(-55.27, 5.78, -55.10, 5.93))
```

### `get_country_indicators()`

Fetch World Bank indicators for one country and write the `*_indicators.toml`
the model consumes. This is the one-call path; it needs no intermediate CSV.

```python
get_country_indicators(
    country_code: str,               # ISO3
    output_path: str | Path,
    *,
    cfg: WDIConfig = WDIConfig(),
) -> Path
```

```python
from d_health import get_country_indicators

path = get_country_indicators("SUR", "data/sur_indicators.toml")
```

### `get_world_bank_data()` and `build_from_wdi()`

The two-step path: pull a WDI table to CSV once, then derive per-country TOMLs
from it offline.

```python
get_world_bank_data(output_path: Path | str, *, cfg: WDIConfig = WDIConfig()) -> Path

build_from_wdi(
    wdi_csv: str | Path,
    country_code: str,
    out_path: str | Path,
    *,
    sep: str = ";",
) -> Path
```

```python
from d_health import get_world_bank_data, build_from_wdi

csv = get_world_bank_data("data/wdi.csv")
for iso3 in ("SUR", "MOZ"):
    build_from_wdi(csv, iso3, f"data/{iso3.lower()}_indicators.toml")
```

---

## Configuration models

All config classes are **frozen** pydantic models with `extra="forbid"`: they
cannot be mutated after construction, and an unknown key in a TOML is an error
rather than being silently ignored. Use `.model_copy(update={...})` to derive a
variant.

### `RunConfig`

```python
RunConfig(
    exposure: ExposureConfig,     # required
    event: EventConfig,           # required
    output: OutputConfig,         # required
    settings: SettingsConfig = SettingsConfig(),   # all defaults
)
```

The corresponding `config.toml`:

```toml
[exposure]
population         = "data/sur_population_2020_combined.nc"
urban_rural        = "data/sur_urban_rural.nc"
country_indicators = "data/sur_indicators.toml"

[event]
flood_depth_map = "data/flood_wl03m.tif"

[output]
out_dir = "outputs/scenario_wl03m"
plots   = true

# [settings] is entirely optional — every field has a default.
```

### `ExposureConfig`, `EventConfig`, `OutputConfig`

```python
ExposureConfig(population: Path, urban_rural: Path, country_indicators: Path)
EventConfig(flood_depth_map: Path)
OutputConfig(out_dir: Path, plots: bool = True)
```

> **Which raster defines the grid?**
> The **population** raster does. Its CRS and resolution are the analysis grid;
> the flood and urban/rural rasters are resampled *onto* it, clipped to the
> intersection of all three footprints. Supplying a flood map finer than the
> population raster does **not** make the run finer — it is area-averaged, which
> attenuates peak depths.

Flood depth uses the positive convention: `> 0` is flooded, `0`/NaN is dry.
Negative depths are clipped to 0 with a warning.

### `SettingsConfig`

```python
SettingsConfig(
    pathogen: PathogenConfig = PathogenConfig(),
    population_groups: list[PopulationGroup] = [adults, children],
    emissions: EmissionsConfig = EmissionsConfig(),
    event_in_hours: float = 1.0,
)
```

### `EmissionsConfig`

```python
EmissionsConfig(
    per_capita_ecoli_rate: float = 1.0e9,       # CFU per person per event
    total_population_group: str = "total",
    gdp_weight: GDPWeight = GDPWeight(),
    sanitation_reductions: list[SanitationReduction] = [Safe, Advanced, Basic, None],
    nodata_sanitation: Literal["none", "urban", "rural", "nan"] = "none",
)
```

`nodata_sanitation` decides what sanitation factor applies where the urban/rural
raster is unclassified (SMOD code 0 — nodata *and* water). The default `"none"`
means factor `1.0`, i.e. *no sanitation infrastructure* — the maximum-emission
assumption, applied to the cells you know least about. It is the historical
behaviour, and it is a conservative choice rather than a neutral one. The
unclassified share is logged, and warned about above 20%.

### `SanitationReduction` and `GDPWeight`

```python
SanitationReduction(name: str, urban_reduction_factor: float, rural_reduction_factor: float)
GDPWeight(floor: float = 0.5, intercept: float = 1.0, divisor: float = 80000.0)
```

> **`reduction_factor` is a *retained* fraction, not a removed one.**
> `1.0` = no sanitation = the full baseline emission is retained.
> `0.10` = strong sanitation = only 10% is retained.
> Smaller means *more* sanitation. This trips people up; the name is kept because
> it is the established term in this domain.

`weight_factor = max(floor, intercept - gdp_per_capita / divisor)`.

### `PopulationGroup` and `DepthThreshold`

```python
PopulationGroup(name: str, depth_thresholds: list[DepthThreshold])
DepthThreshold(name: str, min_depth: float, ing: float, unit: Literal["ml/h", "ml/event"])
```

A group's `name` does double duty: it labels the outputs *and* selects that
group's layer from the population raster's `group` dimension.

`depth_thresholds` must be sorted ascending by `min_depth`, names must be unique,
and **the lowest `min_depth` must be > 0** — a group cannot be exposed on dry
land, and allowing zero used to make dry cells report certain infection.

```toml
[[settings.population_groups]]
name = "adults"
  [[settings.population_groups.depth_thresholds]]
  name = "wading"
  min_depth = 0.1
  ing = 10.0
  unit = "ml/h"
  [[settings.population_groups.depth_thresholds]]
  name = "swimming"
  min_depth = 1.5
  ing = 30.0
  unit = "ml/h"
```

Declaring `[[settings.population_groups]]` **replaces the default list
wholesale** — the bundled adults/children groups are dropped unless you restate
them.

### `PathogenConfig`

```python
PathogenConfig(
    selected: str = "E.coli",
    pathogens: dict[str, PathogenParameters] = {"E.coli": PathogenParameters(...)},
)
PathogenParameters(alpha: float, beta: float, source: str = "")
```

`selected` must be a key of `pathogens`. Access the active one with
`config.settings.pathogen.active`. Defaults to E. coli with `alpha=0.373`,
`beta=39.71` (Teunis et al. 2008). As with population groups, declaring any
`pathogens` entry replaces the whole catalogue.

### `CountryIndicators`

Read from the standalone TOML that `exposure.country_indicators` points at, and
validated at config-load time.

```python
CountryIndicators(
    country_code: str,                    # ISO3, uppercase
    gdp_per_capita: float,                # current USD
    sanitation: list[SanitationLevel],
)
SanitationLevel(name: str, urban: float, rural: float)   # percent, 0-100
```

The urban and rural columns must each sum to 100% (±0.5 pp), tier names must be
unique, and every tier must have a matching `sanitation_reductions` entry in the
active `EmissionsConfig` — that cross-check runs at load time.

### Preprocessing configs

```python
WorldPopConfig(
    layout: Literal["global1_2000_2020", "global2_2015_2030"] = "global1_2000_2020",
    constrained: bool = True,
    release: str = "R2025A",
    version: str = "v1",
    resolution: Literal["100m", "1km"] = "100m",
)
GHSSmodConfig(epoch: int = 2025, release: str = "R2023A", version: str = "V2-0",
              crs_code: int = 4326, resolution: str = "30ss")
WDIConfig(indicator_codes: tuple[str, ...] = (...10 WDI codes...), csv_sep: str = ";")
```

`WDIConfig` has **no** `country_code` field — the country is an argument to
`get_country_indicators` / `build_from_wdi`, not part of the config.

---

## Results

### `ModelOutputs`

Returned by `run_model` and `run_model_from_toml`. All rasters are numpy arrays
on the common grid; dict keys are population-group names.

| Field | Type | |
|---|---|---|
| `emissions` | `np.ndarray` | CFU per cell, before flood gating |
| `pathogen_conc` | `np.ndarray` | CFU per 100 mL. **NaN on dry cells** |
| `doses` | `dict[str, np.ndarray]` | CFU ingested per event, per group |
| `risks` | `dict[str, np.ndarray]` | Infection probability, per group |
| `infected` | `dict[str, np.ndarray]` | `risk × population`, per group |
| `totals` | `dict[str, float]` | `infected_<group>` — the headline numbers |
| `paths` | `dict[str, Path]` | Written artifacts, by logical name |
| `meta` | `dict` | Common-grid georeferencing (transform/crs/bounds/…) |
| `flood_classes` | `np.ndarray \| None` | `0` dry, `1` wet-but-unexposed, `2..n` depth bands |
| `coverage` | `CoverageBreakdown \| None` | Population flooded vs dry |
| `risk_class_counts` | `dict[str, np.ndarray]` | Population histogram over risk bins |
| `risk_class_edges` | `tuple[float, ...]` | The bin edges used |

Unexposed cells are **NaN**, not zero, throughout `pathogen_conc`, `doses`,
`risks` and `infected`. Aggregate with `np.nansum`, not `sum`.

```python
outputs = run_model_from_toml("config.toml")

print(outputs.totals)                     # {'infected_adults': ..., 'infected_children': ...}
print(outputs.paths["emissions"])         # .../emissions.nc
print(float(np.nansum(outputs.infected["adults"])))
print(outputs.coverage.flooded["total"])  # people inside the flooded area
```

Written to `output.out_dir`: `emissions.nc`, `pathogen_conc.nc`,
`flood_classes.nc`, `dose.nc`, `risk.nc`, `infected.nc` (the last three stacked
along a `group` dimension), plus ONGs when `output.plots` is true.

### `ModelInputs`

A plain dataclass, produced by `load_inputs`. All three arrays share one grid —
that invariant is asserted at load time.

```python
ModelInputs(
    flood: np.ndarray,          # (rows, cols), depth in m, >0 flooded
    flood_meta: dict,           # transform / crs / bounds / width / height / count
    population: xr.DataArray,   # (group, rows, cols) — an xarray, with labelled groups
    urban_rural: np.ndarray,    # (rows, cols), 1=urban, 2=rural, 0=nodata
)
```

`population` is an `xarray.DataArray`, not a numpy array, so you select a layer
by name: `inputs.population.sel(group="adults").values`.

### `load_inputs()`

```python
load_inputs(exposure: ExposureConfig, event: EventConfig) -> ModelInputs
```

Loads the three rasters and aligns them onto the common grid (population's CRS
and resolution, clipped to the intersection of all three footprints).

---

## I/O and geospatial helpers

### `align_rasters()`

```python
align_rasters(
    input_da: xr.DataArray,
    target_da: xr.DataArray,
    *,
    resampling: str = "average",
) -> tuple[xr.DataArray, xr.DataArray]
```

Reprojects `input_da` onto `target_da`'s grid and clips **both** to the input's
footprint. It takes two DataArrays — not a list of paths — and returns both
arrays; it does not write files.

`resampling` is the name of a `rasterio.enums.Resampling` member: `"average"` for
fractional/mean quantities, `"nearest"` for categorical data (urban/rural),
`"bilinear"` for continuous fields, `"max"` for worst-case.

```python
from d_health import align_rasters
from d_health.io import load_raster, load_population

flood = load_raster("flood.tif")
population = load_population("pop.nc")

flood_on_grid, population_clipped = align_rasters(
    flood, population, resampling="average"
)
```

### Raster I/O

```python
from d_health.io import (
    load_raster, load_population, write_netcdf, from_numpy, wrap_like, da_to_meta,
)

load_raster(file_path, *, squeeze=True, masked=True) -> xr.DataArray
load_population(file_path, *, group_names=None) -> xr.DataArray
write_netcdf(obj, out_path, *, crs=None, descriptions=None, name=None) -> Path
from_numpy(values, transform, crs, *, name, group=None, nodata=None) -> xr.DataArray
wrap_like(values, ref_da, *, name, group=None) -> xr.DataArray
da_to_meta(da) -> dict
```

`load_raster` auto-detects `.tif`/`.tiff` (rioxarray) vs `.nc`/`.nc4`/`.cdf`
(xarray), converts source nodata to NaN, and reads fully into memory before
closing the file.

### Geo helpers

```python
from d_health.geo import get_cell_area, get_utm_zone

get_cell_area(meta: dict) -> float   # approximate cell area in m², via UTM
get_utm_zone(meta: dict) -> int      # EPSG code of the covering UTM zone
```

Both take the `meta` dict from `da_to_meta` / `ModelInputs.flood_meta`.

---

## Postprocessing

Computed automatically inside `run_model`; importable if you want them directly.

```python
from d_health.postprocessing import (
    compute_flood_classes, derive_flood_class_edges, flood_class_labels,
    flooded_dry_stats, log_coverage, CoverageBreakdown,
    bin_population_by_risk, DEFAULT_RISK_EDGES,
    per_group_totals,
    plot_raster, plot_per_group, plot_flood_classes, plot_risk_class_histogram,
)
```

| Function | |
|---|---|
| `compute_flood_classes(flood, groups)` | Integer raster: `0` dry, `1` wet-but-below-any-threshold, `2..n+1` activity bands |
| `flooded_dry_stats(flood, population, groups, emissions_cfg, *, flood_classes=None)` | → `CoverageBreakdown` (population flooded vs dry, and per class) |
| `bin_population_by_risk(risks, population, groups, *, edges=DEFAULT_RISK_EDGES)` | Population histogram over risk bins, per group |
| `per_group_totals(infected)` | `{"infected_<group>": float}`, NaN-safe |
| `plot_raster(data, *, cmap, title, save_path=None, ...)` | Single raster PNG |
| `plot_per_group(arrays, *, label, out_dir, ...)` | One PNG per group |

`DEFAULT_RISK_EDGES` is `(0.0, 0.2, 0.4, 0.6, 0.8, 1.0)`.

Note `bin_population_by_risk` skips NaN risks, so unexposed (dry-cell) population
does not appear in the histogram at all.

---

## The CLI

```bash
# Prepare exposure inputs for an AOI
d-health setup --bbox -55.27 5.78 -55.10 5.93 --root data/setup_paramaribo
d-health setup --bbox ... --country-iso SUR --year 2020   # skip reverse geocoding

# Run a config
d-health run --config config.toml
d-health run -c config.toml --out other/dir --no-plots
```

`-v` / `--verbose` raises the `d_health` logger to DEBUG and works with **both**
subcommands. `run` prints one `infected_<group>: <count>` line per group and
exits 0.
