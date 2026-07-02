# Quickbuild Examples (Paramaribo)

This track is the fastest way to go from AOI to multi-scenario model results.

## Notebook order

1. A_setup_paramaribo.ipynb
2. B_run_paramaribo_scenarios.ipynb

## What each notebook does

- A_setup_paramaribo.ipynb
  - Calls model_setup with the Paramaribo AOI.
  - Auto-derives country ISO from AOI.
  - Writes setup artifacts under examples/quickbuild/data/setup_paramaribo.
  - Creates example flood maps for several water levels in examples/quickbuild/data/flood_extremes.

- B_run_paramaribo_scenarios.ipynb
  - Converts settings.toml + each flood map into runnable config.toml files.
  - Runs the model for each flood scenario.
  - Stores outputs under examples/quickbuild/outputs/run/scenario_wl*m.
  - Exports a comparison table to examples/quickbuild/outputs/run/scenario_summary.csv.

## Scenarios

Default flood scenarios are:

- wl1m
- wl2m
- wl3m
- wl5m
- wl10m

## Notes

- Run notebook A once before notebook B.
- Flood scenarios are quick demonstration layers derived from the baseline Paramaribo flood map.
