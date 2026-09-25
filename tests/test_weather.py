import json

import numpy as np
import pandas as pd
import pytest

from ntu_climate.analysis import rainfall_events
from ntu_climate.io import fetch_v2_all_pages
from ntu_climate.weather import aggregate_quality, daily_quality, heat_degree_hours, load_weather, parse_v1, parse_v2_page


def body(variable, unit, items):
    return {"metadata": {"stations": [{"id": "S44", "name": "Nanyang Avenue", "location": {"latitude": 1.3458, "longitude": 103.6817}}],
                         "reading_unit": unit}, "items": items}


def item(ts, value):
    return {"timestamp": ts, "readings": [{"station_id": "S44", "value": value}]}


def test_v1_deduplicates_and_wind_knots_to_ms():
    data = body("wind_speed", "knots", [item("2026-09-24T12:00:00+08:00", 10), item("2026-09-24T12:00:00+08:00", 10)])
    frame, station = parse_v1(data, "wind_speed")
    assert len(frame) == 1
    assert frame.iloc[0]["raw_value"] == 10
    assert frame.iloc[0]["value"] == pytest.approx(5.14444)
    assert station["name"] == "Nanyang Avenue"


def test_v2_historical_and_latest_schema_and_pagination():
    class FakeDownloader:
        def __init__(self):
            self.params = []

        def get(self, url, params):
            self.params.append(params.copy())
            token = params.get("paginationToken")
            value = 30 if token is None else 31
            return json.dumps({"code": 0, "data": {"readingUnit": "deg C", "stations": [{"id": "S44"}],
                "readings": [{"timestamp": f"2026-09-24T00:0{len(self.params)}:00+08:00",
                              "data": [{"stationId": "S44", "value": value}]}],
                "paginationToken": "next" if token is None else None}}).encode()

    downloader = FakeDownloader()
    pages = fetch_v2_all_pages("temperature", "2026-09-24", downloader)
    assert len(pages) == 2
    assert downloader.params[1]["paginationToken"] == "next"
    assert len(pd.concat([parse_v2_page(p, "temperature") for p in pages])) == 2


def test_timezone_rainfall_boundary_aggregation_and_missing_not_zero():
    rain, _ = parse_v1(body("rainfall", "mm", [item("2026-09-25T00:00:00+08:00", 2),
                                                  item("2026-09-25T00:05:00+08:00", 3)]), "rainfall")
    temp, _ = parse_v1(body("temperature", "deg C", [item("2026-09-25T00:00:00+08:00", 31)]), "temperature")
    assert rain.iloc[0]["local_day"] == "2026-09-24"
    assert temp.iloc[0]["local_day"] == "2026-09-25"
    hourly = aggregate_quality(pd.concat([rain, temp], ignore_index=True))
    prior = hourly[(hourly.variable == "rainfall") & (hourly.local_day == "2026-09-24") & (hourly.hour == 23)].iloc[0]
    assert prior["value"] == 2
    missing = hourly[(hourly.variable == "rainfall") & (hourly.local_day == "2026-09-24") & (hourly.hour == 1)].iloc[0]
    assert np.isnan(missing["value"])
    assert missing["status"] == "missing"
    daily = daily_quality(hourly)
    assert daily[(daily.variable == "rainfall") & (daily.local_day == "2026-09-24")].iloc[0]["status"] == "partial"


def test_heat_integrates_only_observed_minutes_and_warming_order():
    frame, _ = parse_v1(body("temperature", "deg C", [item("2026-09-24T12:00:00+08:00", 31),
                                                         item("2026-09-24T12:59:00+08:00", 29)]), "temperature")
    values = [heat_degree_hours(frame, 30, delta) for delta in (0, 1, 2)]
    assert values[0]["heat_degree_hours"] == pytest.approx(1 / 60)
    assert values[0]["valid_hours"] == pytest.approx(2 / 60)
    assert values[0]["coverage"] < 0.8
    assert values[2]["heat_degree_hours"] >= values[1]["heat_degree_hours"] >= values[0]["heat_degree_hours"]


def test_missing_station_and_wrong_unit_are_explicit():
    with pytest.raises(ValueError, match="absent"):
        parse_v1(body("temperature", "deg C", []), "temperature", "S999")
    with pytest.raises(ValueError, match="Unexpected"):
        parse_v1(body("temperature", "Fahrenheit", []), "temperature")


def test_processes_only_selected_cached_days(tmp_path, monkeypatch):
    import ntu_climate.weather as weather
    monkeypatch.setattr(weather, "ROOT", tmp_path)
    folder = tmp_path / "data/raw/weather/temperature"
    folder.mkdir(parents=True)
    for day, value in [("2026-09-23", 29), ("2026-09-24", 31)]:
        (folder / f"{day}.json").write_text(json.dumps(body("temperature", "deg C", [item(f"{day}T12:00:00+08:00", value)])))
    obs, _, _ = load_weather(days=["2026-09-24"])
    assert len(obs) == 1
    assert obs.iloc[0]["raw_value"] == 31


def test_rain_threshold_sensitivity_uses_same_qualified_hours():
    items = [item(f"2026-09-24T00:{minute:02d}:00+08:00", 2) for minute in range(5, 60, 5)]
    items.append(item("2026-09-24T01:00:00+08:00", 2))
    rain, _ = parse_v1(body("rainfall", "mm", items), "rainfall")
    result = rainfall_events(rain, [1.0, 1.1], threshold_mm_h=25)
    assert result["qualified_hours"] == 1
    assert [x["qualified_sample_hours_at_or_above_threshold"] for x in result["scenarios"]] == [0, 1]
