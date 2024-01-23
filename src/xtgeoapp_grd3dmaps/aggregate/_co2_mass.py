import os
from dataclasses import dataclass, fields
from typing import Dict, List, Literal, Optional, Tuple

import numpy as np
import xtgeo
from ecl.eclfile import EclFile
from ecl.grid import EclGrid
from ccs_scripts.co2_containment.co2_calculation import (_fetch_properties, _identify_gas_less_cells, _is_subset, Co2Data, Co2DataAtTimeStep)
from xtgeoapp_grd3dmaps.aggregate._config import CO2MassSettings

CO2_MASS_PNAME = "CO2Mass"


# pylint: disable=invalid-name,too-many-instance-attributes

def _get_gasless(properties: Dict[str, Dict[str, List[np.ndarray]]]) -> np.ndarray:
    if _is_subset(["SGAS", "AMFG"], list(properties.keys())):
        gasless = _identify_gas_less_cells(properties["SGAS"], properties["AMFG"])
    elif _is_subset(["SGAS", "XMF2"], list(properties.keys())):
        gasless = _identify_gas_less_cells(properties["SGAS"], properties["XMF2"])
    else:
        error_text = (
            "CO2 containment calculation failed. "
            "Cannot find required properties SGAS+AMFG or SGAS+XMF2."
        )
        raise RuntimeError(error_text)
    return gasless

def translate_co2data_to_property(
    co2_data: Co2Data,
    grid_file: str,
    co2_mass_settings: CO2MassSettings,
    properties_to_extract: List[str],
    grid_out_dir: str,
) -> List[List[xtgeo.GridProperty]]:
    """
    Convert CO2 mass arrays and save calculated CO2 mass as grid files
    """
    dimensions, triplets = _get_dimensions_and_triplets(
        grid_file, co2_mass_settings.unrst_source, properties_to_extract
    )

    # Setting up the grid folder to store the gridproperties
    if not os.path.exists(grid_out_dir):
        os.makedirs(grid_out_dir)

    maps = co2_mass_settings.maps
    if maps is None:
        maps = []
    elif isinstance(maps, str):
        maps = [maps]
    maps = [map_name.lower() for map_name in maps]

    total_mass_list = []
    dissolved_mass_list = []
    free_mass_list = []

    store_all = "all" in maps or len(maps) == 0
    for co2_at_date in co2_data.data_list:
        date = str(co2_at_date.date)
        mass_as_grids = _convert_to_grid(co2_at_date, dimensions, triplets)
        if store_all or "total_co2" in maps:
            mass_as_grids["mass-total"].to_file(
                grid_out_dir + "/MASS_TOTAL_" + date + ".roff", fformat="roff"
            )
            total_mass_list.append(mass_as_grids["mass-total"])
        if store_all or "dissolved_co2" in maps:
            mass_as_grids["mass-aqu-phase"].to_file(
                grid_out_dir + "/MASS_AQU_PHASE_" + date + ".roff",
                fformat="roff",
            )
            dissolved_mass_list.append(mass_as_grids["mass-aqu-phase"])
        if store_all or "free_co2" in maps:
            mass_as_grids["mass-gas-phase"].to_file(
                grid_out_dir + "/MASS_GAS_PHASE_" + date + ".roff",
                fformat="roff",
            )
            free_mass_list.append(mass_as_grids["mass-gas-phase"])

    return [
        free_mass_list,
        dissolved_mass_list,
        total_mass_list,
    ]


def _get_dimensions_and_triplets(
    grid_file: str,
    unrst_file: str,
    properties_to_extract: List[str],
) -> Tuple[Tuple[int, int, int], List[Tuple[int, int, int]]]:
    grid_pf = xtgeo.grid_from_file(grid_file)
    dimensions = (grid_pf.ncol, grid_pf.nrow, grid_pf.nlay)
    unrst = EclFile(unrst_file)
    properties, _ = _fetch_properties(unrst, properties_to_extract)
    gdf = grid_pf.get_dataframe()
    gdf = gdf.sort_values(by=["KZ", "JY", "IX"])

    gasless = _get_gasless(properties)
    gdf = gdf.loc[~gasless]
    triplets = [
        (int(row["IX"] - 1), int(row["JY"] - 1), int(row["KZ"] - 1))
        for _, row in gdf.iterrows()
    ]
    return dimensions, triplets


def _convert_to_grid(
    co2_at_date: Co2DataAtTimeStep,
    dimensions: Tuple[int, int, int],
    triplets: List[Tuple[int, int, int]],
) -> Dict[str, xtgeo.GridProperty]:
    """
    Store the CO2 mass arrays in grid objects
    """
    grids = {}
    date = str(co2_at_date.date)
    for mass, name in zip(
        [co2_at_date.total_mass(), co2_at_date.aqu_phase, co2_at_date.gas_phase],
        ["mass-total", "mass-aqu-phase", "mass-gas-phase"],
    ):
        mass_array = np.zeros(dimensions)
        for i, triplet in enumerate(triplets):
            mass_array[triplet] = mass[i]
        mass_name = "co2-" + name + "--" + date
        grids[name] = xtgeo.grid3d.GridProperty(
            ncol=dimensions[0],
            nrow=dimensions[1],
            nlay=dimensions[2],
            values=mass_array,
            name=mass_name,
            date=date,
        )
    return grids
