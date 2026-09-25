import copy

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Polygon

from ntu_climate.analysis import percent_change, scenario_grid, scenario_table
from ntu_climate.spatial import METRIC_CRS, covered_class, make_grid, walkable
from ntu_climate.weather import parse_v1


def test_covered_unknown_never_assumed_no_and_private_excluded():
    assert covered_class({}) == "unknown"
    assert covered_class({"covered": "maybe"}) == "unknown"
    assert covered_class({"covered": "yes"}) == "yes"
    assert not walkable({"highway": "footway", "foot": "no"})
    assert not walkable({"highway": "service", "access": "private"})


def test_valid_projected_geometry_length_and_geojson_coordinate_order():
    campus = gpd.GeoDataFrame({"geometry": [Polygon([(103.680, 1.345), (103.682, 1.345), (103.682, 1.347), (103.680, 1.347)])]}, crs="EPSG:4326")
    walks = gpd.GeoDataFrame({"covered_class": ["unknown"], "geometry": [LineString([(103.6805, 1.346), (103.6815, 1.346)])]}, crs="EPSG:4326")
    grid = make_grid(campus, walks, 100)
    assert grid.crs.to_string() == METRIC_CRS
    assert grid.is_valid.all()
    assert 100 < grid["walk_m"].sum() < 120
    assert grid["covered_no_m"].sum() == 0
    assert grid["covered_unknown_m"].sum() == pytest.approx(grid["walk_m"].sum())
    lon, lat = grid.to_crs("EPSG:4326").geometry.iloc[0].centroid.coords[0]
    assert 103 < lon < 104 and 1 < lat < 2


def test_shelter_selected_only_and_raw_unchanged():
    grid = gpd.GeoDataFrame({"grid_id": ["a", "b"], "covered_no_m": [100., 20.],
                             "covered_unknown_m": [40., 0.], "geometry": [Polygon([(0,0),(1,0),(1,1),(0,1)]),
                                                                          Polygon([(1,0),(2,0),(2,1),(1,1)])]}, crs=METRIC_CRS)
    original = grid.copy(deep=True)
    baseline = scenario_grid(grid, 10., 0.5)
    shelter = scenario_grid(grid, 10., 0.5, {"a"}, 0.5)
    assert shelter.loc[0, "proxy_degC_h_m"] == baseline.loc[0, "proxy_degC_h_m"] * 0.5
    assert shelter.loc[1, "proxy_degC_h_m"] == baseline.loc[1, "proxy_degC_h_m"]
    assert grid.equals(original)
    assert percent_change(5., 0.) is None
    assert baseline.loc[0, "effective_uncovered_m"] == 120


def test_scenarios_share_valid_time_mask_and_color_scale():
    grid = gpd.GeoDataFrame({"grid_id": ["a", "b"], "covered_no_m": [10., 20.],
                             "covered_unknown_m": [10., 0.], "geometry": [Polygon([(0,0),(1,0),(1,1),(0,1)]),
                                                                          Polygon([(1,0),(2,0),(2,1),(1,1)])]}, crs=METRIC_CRS)
    body = {"metadata": {"stations": [{"id": "S44"}], "reading_unit": "deg C"},
            "items": [{"timestamp": "2026-09-24T12:00:00+08:00", "readings": [{"station_id": "S44", "value": 31}]},
                      {"timestamp": "2026-09-24T12:01:00+08:00", "readings": [{"station_id": "S44", "value": 29}]}]}
    obs, _ = parse_v1(body, "temperature")
    original = obs.copy(deep=True)
    cfg = {"temperature_threshold_c": 30., "q_unknown": 0.5, "shelter_grid_ids": ["a"],
           "warming_c": [0., 1., 2.], "minimum_coverage": 0., "station_id": "S44", "rainfall_multipliers": [1., 1.1]}
    table, summary, _ = scenario_table(grid, obs, cfg, ["2026-09-24"])
    assert len({v["valid_hours"] for v in summary["heat"].values()}) == 1
    assert summary["heat"]["2.0"]["heat_degree_hours"] >= summary["heat"]["1.0"]["heat_degree_hours"] >= summary["heat"]["0.0"]["heat_degree_hours"]
    assert summary["common_color_max"] == table["proxy_degC_h_m"].max()
    assert table[(table.scenario == "Shelter 50%") & (table.grid_id == "b")].iloc[0]["proxy_degC_h_m"] == table[(table.scenario == "Observed-sample baseline") & (table.grid_id == "b")].iloc[0]["proxy_degC_h_m"]
    assert obs.equals(original)
