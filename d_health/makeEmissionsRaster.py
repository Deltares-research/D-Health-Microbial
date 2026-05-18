import emissionsFunctions as ef
import utils as utils
from pathlib import Path
import numpy as np
import dask.array as da

output_dir = Path('output')
output_dir.mkdirs(parents=True, exist_ok=True)

# Define Input File Paths
population_raster = r'inputs/clipped_population.tif'
urban_rural_raster = r'inputs/Urban_rural_classification.tif'
flood_raster = r'inputs/flooded_zoom_new.tif'
worldBank_file = r'wdi_data/wdi_2026-05-04.csv'
output_raster = f'{output_dir}/emissions.tif'

ECOLI_PER_PERSON = 1e9  
countryCode = 'SUR'
sanitation_types = {
    "Safe": {
        "rural_reduction_factor": 0.10,
        "urban_reduction_factor": 0.10,
    },
    "Advanced": {
        "rural_reduction_factor": 0.25,
        "urban_reduction_factor": 0.25,
    },
    "Basic": {
        "rural_reduction_factor": 0.30,
        "urban_reduction_factor": 0.70,
    },
    "None": {
        "rural_reduction_factor": 1.00,
        "urban_reduction_factor": 1.00,
    },
}

def main():
    # Get GDP data from WorldBank csv and calculate weight factor
    gdp = ef.getWBdata(worldBank_file, countryCode, 'NY.GDP.PCAP.CD')
    print(f'GDP = {int(gdp['latest_value'])}USD (from {gdp['latest_year']})')
    weight_factor = ef.calcWeightFactor(gdp['latest_value'])
    # calculate weighted sanitation factors
    sanitationFactors = ef.getSanitationFactors(worldBank_file, countryCode, sanitation_types)
    #clip urban-rural raster to population raster
    urbRur = utils.align_rasters(urban_rural_raster, population_raster, output_dir, resampling='nearest')
    #prepare urban/rural raster and population raster for emissions processing
    pop_chunk, urban_chunk, rural_chunk, profile = ef.prepRastersForEmissions(urbRur, population_raster)
    # Parallel Processing: Compute E. coli Emissions
    emissions = da.map_blocks(
        ef.compute_emissions, 
        pop_chunk, urban_chunk, rural_chunk, 
        weight_factor, sanitationFactors, ECOLI_PER_PERSON,
        dtype=np.float64
    )
    # Force Execution & Compute Results
    emissions = emissions.compute()
    # save output as multiband raster
    ef.saveMultibandRaster(profile, pop_chunk, urbRur[0], emissions, urban_chunk, rural_chunk, sanitationFactors, output_raster)

if __name__ == "__main__":
    main()