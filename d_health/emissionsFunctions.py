import pandas as pd
import numpy as np
import dask.array as da
import rasterio

def getWBdata(worldBank_file, countryCode, varCode):
    df = pd.read_csv(worldBank_file, sep=';')
    result = df[
        (df["Country Code"] == countryCode) &
        (df["Indicator Code"] == varCode)
    ]
    
    if result.empty:
        print(f'Missing WorldBank data for {countryCode} for variable {varCode}')
        return None
    
    row = result.iloc[0]
    
    return {
        "country": row["Country Name"],
        "indicator": row["Indicator Name"],
        "latest_year": row["Latest Year"],
        "latest_value": row["Latest Value"]
    }

def calcWeightFactor(gdp):
    return max(0.5, (1 - (gdp / 80)))

def getSanitationFactors(worldBank_file, countryCode, sanitation_types):
    sani_safe_urban = getWBdata(worldBank_file, countryCode, 'SH.STA.SMSS.UR.ZS')['latest_value']
    sani_safe_rural = getWBdata(worldBank_file, countryCode, 'SH.STA.SMSS.RU.ZS')['latest_value']
    sani_adv_urban = getWBdata(worldBank_file, countryCode, 'SH.STA.BASS.UR.ZS')['latest_value']
    sani_adv_rural = getWBdata(worldBank_file, countryCode, 'SH.STA.BASS.RU.ZS')['latest_value']
    sani_none_urban = getWBdata(worldBank_file, countryCode, 'SH.STA.ODFC.UR.ZS')['latest_value']
    sani_none_rural = getWBdata(worldBank_file, countryCode, 'SH.STA.ODFC.RU.ZS')['latest_value']

    # compute missing values (should sum to 100) - missing is 'basic'
    # advanced includes safe - don't double count
    sani_bas_urban = 100 - sani_adv_urban - sani_none_urban
    sani_bas_rural = 100 - sani_adv_rural - sani_none_rural
    # Coverage arrays, converted from % to fractions
    urban_coverage = np.array([
        sani_safe_urban,
        sani_adv_urban - sani_safe_urban,#because advanced includes safe in the WorldBank data
        sani_bas_urban,
        sani_none_urban,
    ]) / 100

    rural_coverage = np.array([
        sani_safe_rural,
        sani_adv_rural - sani_safe_rural,#because advanced includes safe in the WorldBank data
        sani_bas_rural,
        sani_none_rural,
    ]) / 100

    sanitation_types_order = list(sanitation_types.keys())

    urban_reduction_factors = np.array([
        sanitation_types[st]["urban_reduction_factor"]
        for st in sanitation_types_order
    ])

    rural_reduction_factors = np.array([
        sanitation_types[st]["rural_reduction_factor"]
        for st in sanitation_types_order
    ])

    urban_sanitation_factor = np.dot(urban_reduction_factors, urban_coverage)
    rural_sanitation_factor = np.dot(rural_reduction_factors, rural_coverage)

    return urban_sanitation_factor, rural_sanitation_factor

def prepRastersForEmissions(urbRur, population_raster):
    with rasterio.open(urbRur[0]) as ur_src:
        urb_rur_data = ur_src.read(1).squeeze()
        # Convert Urban/Rural Classification into Boolean Masks
        urban_mask = da.from_array(urb_rur_data == 1, chunks=(250, 250))
        rural_mask = da.from_array(urb_rur_data == 2, chunks=(250, 250))

    # 📌 Load Population Raster (Ensure Single Band & Correct Shape)
    with rasterio.open(population_raster) as pop_src:
        population = da.from_array(pop_src.read(3).squeeze(), chunks=(250, 250)).astype(np.float64)  # Ensure (height, width)
        profile = pop_src.profile 

    # ✅ Ensure All Arrays Have the Same Shape & Chunking
    chunk_size = population.chunks  # Ensure chunking matches population raster
    urban_mask = urban_mask.rechunk(chunk_size)
    rural_mask = rural_mask.rechunk(chunk_size)

    return population, urban_mask, rural_mask, profile

def compute_emissions(pop_chunk, urban_chunk, rural_chunk, weight_factor, sanitationFactors, ECOLI_PER_PERSON):
    """Processes a chunk of the raster in parallel using Dask."""
    urban_sanitation_factor = sanitationFactors[0]
    rural_sanitation_factor = sanitationFactors[1]

    sanitation_factor = da.ones_like(pop_chunk, dtype=np.float64)  # Default = 1
    
    # Ensure urban and rural masks are boolean
    urban_chunk = urban_chunk.astype(bool)
    rural_chunk = rural_chunk.astype(bool)

    # Apply sanitation factors
    sanitation_factor = da.where(urban_chunk, urban_sanitation_factor, sanitation_factor)
    sanitation_factor = da.where(rural_chunk, rural_sanitation_factor, sanitation_factor)

    return pop_chunk * ECOLI_PER_PERSON * sanitation_factor * weight_factor

def saveMultibandRaster(profile, pop_chunk, urbRur, emissions, urban_chunk, rural_chunk, sanitationFactors, output_raster):
    profile.update(dtype=rasterio.float64, count=4)  # 4 Bands

    # 🚀 Create Multi-Band Raster Output
    with rasterio.open(output_raster, "w", **profile) as dst:
        dst.write(pop_chunk.compute(), 1)  # Band 1: Population Density
        with rasterio.open(urbRur) as ur_src:
            urb_rur_data = ur_src.read(1).astype(np.float64)
            dst.write(urb_rur_data, 2)  # Band 2: Urban/Rural Classification
        dst.write(emissions, 3)  # Band 3: E. coli Emissions
        dst.write((urban_chunk * sanitationFactors[0] + rural_chunk * sanitationFactors[1]).compute(), 4)  # Band 4: Reduction Factor

    print(f"✅ Multi-band E. coli Emission Map saved as {output_raster}")

