"""Country reference layer built with GeoPandas from Natural Earth."""

from __future__ import annotations

import json
import logging
import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pycountry
import shapely
from shapely.geometry import mapping

log = logging.getLogger(__name__)

# Natural Earth has no ISO code for a few territories; give them stable ones.
ISO3_OVERRIDES = {"KOS": "XKX", "SOL": "SOL", "CYN": "CYN"}
EXCLUDE_ADM0 = {"ATA", "KAS"}            # Antarctica, Siachen Glacier

SIMPLIFY_DEG = 0.05                      # ~5 km: plenty for a world map, keeps the payload small
NEIGHBOUR_BUFFER_DEG = 0.5               # also links countries separated by a narrow strait


def iso2_to_iso3(code: str) -> str | None:
    """ISO 3166-1 alpha-2 -> alpha-3 (Kosovo's user-assigned XK included)."""
    if code == "XK":
        return "XKX"
    country = pycountry.countries.get(alpha_2=code)
    return country.alpha_3 if country else None


def country_name(iso3: str) -> str:
    country = pycountry.countries.get(alpha_3=iso3)
    if country is None:
        return iso3
    return getattr(country, "common_name", country.name)


def load_countries(path: str | Path) -> gpd.GeoDataFrame:
    """One row per country: identifiers, region, population, label point and geometry."""
    ne = gpd.read_file(path)
    ne = ne[~ne["ADM0_A3"].isin(EXCLUDE_ADM0)].copy()
    ne["iso3"] = ne["ISO_A3_EH"].where(ne["ISO_A3_EH"] != "-99", ne["ADM0_A3"].replace(ISO3_OVERRIDES))
    ne["iso2"] = ne["ISO_A2_EH"].where(ne["ISO_A2_EH"] != "-99")

    # a few ISO codes span several Natural Earth features (e.g. overseas parts): merge them,
    # keeping the attributes of the most populous part
    ne = ne.sort_values("POP_EST", ascending=False)
    attrs = ne.drop_duplicates("iso3").set_index("iso3")
    geoms = ne.dissolve(by="iso3")["geometry"]
    out = gpd.GeoDataFrame(
        {
            "iso2": attrs["iso2"],
            "name": attrs["NAME_LONG"],
            "continent": attrs["CONTINENT"],
            "un_region": attrs["REGION_UN"],
            "subregion": attrs["SUBREGION"],
            "population": attrs["POP_EST"].round().astype("Int64"),
            "lat": attrs["LABEL_Y"],
            "lon": attrs["LABEL_X"],
        },
        geometry=geoms.reindex(attrs.index),
        crs=ne.crs,
    ).reset_index()
    out["geometry"] = out.geometry.make_valid()
    log.info("countries: %d with geometry", len(out))
    return out.sort_values("iso3").reset_index(drop=True)


def neighbours(countries: gpd.GeoDataFrame) -> pd.DataFrame:
    """Symmetric adjacency list: countries that share a border or lie within ~50 km."""
    with warnings.catch_warnings():
        # a buffer in degrees is not a true distance, but "roughly 50 km" is all adjacency needs
        warnings.simplefilter("ignore", UserWarning)
        buffered = countries[["iso3"]].set_geometry(countries.geometry.buffer(NEIGHBOUR_BUFFER_DEG))
    pairs = gpd.sjoin(buffered, countries[["iso3", "geometry"]], predicate="intersects", lsuffix="a", rsuffix="b")
    pairs = pairs[pairs["iso3_a"] != pairs["iso3_b"]]
    out = pd.DataFrame({"iso3": pairs["iso3_a"].to_numpy(), "neighbour_iso3": pairs["iso3_b"].to_numpy()})
    out = pd.concat([out, out.rename(columns={"iso3": "neighbour_iso3", "neighbour_iso3": "iso3"})]).drop_duplicates()
    log.info("neighbour pairs: %d", len(out))
    return out.sort_values(["iso3", "neighbour_iso3"]).reset_index(drop=True)


def web_geometry(geom) -> str | None:
    """Simplified GeoJSON geometry (as a JSON string) for the dashboard map."""
    if geom is None or geom.is_empty:
        return None
    simple = geom.simplify(SIMPLIFY_DEG, preserve_topology=True)
    simple = shapely.set_precision(simple, 0.01)
    if simple.is_empty:                 # tiny islands vanish at this tolerance: keep a coarse outline
        simple = shapely.set_precision(geom.envelope, 0.01) if not geom.envelope.is_empty else geom
    return json.dumps(mapping(simple), separators=(",", ":"))
