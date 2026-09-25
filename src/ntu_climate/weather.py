"""NEA daily response parsing and coverage-aware aggregation."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .io import ROOT, SGT

EXPECTED = {"temperature": 60, "humidity": 60, "wind_speed": 60, "rainfall": 12}
UNITS = {"temperature": "deg C", "humidity": "percentage", "wind_speed": "knots", "rainfall": "mm"}
OUTPUT_UNITS = {"temperature": "deg C", "humidity": "%", "wind_speed": "m/s", "rainfall": "mm per 5-minute interval"}
PLAUSIBLE = {"temperature": (15, 45), "humidity": (0, 100), "wind_speed": (0, 100), "rainfall": (0, 500)}


def parse_v1(body: dict, variable: str, station_id: str = "S44", source: str = "NEA/data.gov.sg") -> tuple[pd.DataFrame, dict]:
    meta = body.get("metadata", {})
    stations = {s["id"]: s for s in meta.get("stations", [])}
    if station_id not in stations:
        raise ValueError(f"Station {station_id} absent from {variable} metadata")
    unit = meta.get("reading_unit")
    if unit != UNITS[variable]:
        raise ValueError(f"Unexpected {variable} unit {unit!r}; expected {UNITS[variable]!r}")
    rows = []
    for item in body.get("items", []):
        for reading in item.get("readings", []):
            if reading.get("station_id") == station_id:
                rows.append((source, station_id, variable, item["timestamp"], reading.get("value")))
    df = pd.DataFrame(rows, columns=["source", "station_id", "variable", "timestamp_raw", "raw_value"])
    if df.empty:
        return df, stations[station_id]
    df["timestamp"] = pd.to_datetime(df["timestamp_raw"], utc=True).dt.tz_convert(SGT)
    df["raw_value"] = pd.to_numeric(df["raw_value"], errors="coerce")
    df = df.drop_duplicates(["source", "station_id", "variable", "timestamp"], keep="first")
    lo, hi = PLAUSIBLE[variable]
    df["suspect"] = df["raw_value"].isna() | ~df["raw_value"].between(lo, hi)
    df["value"] = df["raw_value"] * (0.514444 if variable == "wind_speed" else 1.0)
    df["raw_unit"] = unit
    df["unit"] = OUTPUT_UNITS[variable]
    # Rainfall timestamps label the end of a 5-minute accumulation. Attribute 00:00 to prior day.
    df["interval_start"] = df["timestamp"] - pd.to_timedelta(5 if variable == "rainfall" else 1, unit="m")
    df["local_day"] = (df["timestamp"] - (pd.Timedelta(microseconds=1) if variable == "rainfall" else pd.Timedelta(0))).dt.date.astype(str)
    return df.sort_values("timestamp"), stations[station_id]


def parse_v2_page(body: dict, variable: str, station_id: str = "S44") -> pd.DataFrame:
    data = body.get("data", {})
    if body.get("code") != 0 or data.get("readingUnit") != UNITS[variable]:
        raise ValueError("Unexpected v2 response or unit")
    if station_id not in {s["id"] for s in data.get("stations", [])}:
        raise ValueError(f"Station {station_id} absent from v2 {variable} metadata")
    rows = []
    for item in data.get("readings", []):
        for reading in item.get("data", []):
            if reading.get("stationId") == station_id:
                rows.append((item["timestamp"], reading.get("value")))
    return pd.DataFrame(rows, columns=["timestamp_raw", "raw_value"]).drop_duplicates("timestamp_raw")


def load_weather(station_id: str = "S44", days: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    frames = []
    stations = {}
    for variable in EXPECTED:
        for path in sorted((ROOT / "data/raw/weather" / variable).glob("*.json")):
            if days is not None and path.stem not in days:
                continue
            frame, station = parse_v1(json.loads(path.read_text()), variable, station_id)
            frames.append(frame)
            stations[variable] = station
    if not frames:
        return pd.DataFrame(), pd.DataFrame(), stations
    observations = pd.concat(frames, ignore_index=True)
    observations = observations.drop_duplicates(["source", "station_id", "variable", "timestamp"])
    quality = aggregate_quality(observations)
    return observations, quality, stations


def aggregate_quality(observations: pd.DataFrame, minimum_coverage: float = 0.8,
                      expected_days: list[str] | None = None) -> pd.DataFrame:
    if observations.empty:
        return pd.DataFrame(columns=["station_id", "variable", "local_day", "hour", "valid_count", "expected_count", "coverage", "value", "unit", "status"])
    df = observations.copy()
    df["hour"] = np.where(df["variable"].eq("rainfall"), df["interval_start"].dt.hour, df["timestamp"].dt.hour)
    df["valid"] = (~df["suspect"]) & df["value"].notna()
    days = expected_days or sorted(df["local_day"].unique())
    combos = pd.MultiIndex.from_product([[df["station_id"].iloc[0]], EXPECTED.keys(), days, range(24)],
                                        names=["station_id", "variable", "local_day", "hour"])
    # Missing hours stay explicit; all-missing rainfall remains NaN, never zero.
    grouped = df[df["valid"]].groupby(["station_id", "variable", "local_day", "hour"])
    mean = grouped["value"].mean()
    total = grouped["value"].sum(min_count=1)
    count = grouped["value"].count()
    out = pd.DataFrame(index=combos).reset_index()
    idx = pd.MultiIndex.from_frame(out[["station_id", "variable", "local_day", "hour"]])
    out["valid_count"] = count.reindex(idx, fill_value=0).to_numpy()
    out["expected_count"] = out["variable"].map(EXPECTED)
    out["coverage"] = out["valid_count"] / out["expected_count"]
    out["value"] = [total.get(k, np.nan) if k[1] == "rainfall" else mean.get(k, np.nan) for k in idx]
    out["unit"] = out["variable"].map({"rainfall": "mm/hour", "temperature": "deg C", "humidity": "%", "wind_speed": "m/s"})
    out["status"] = np.where(out["valid_count"].eq(0), "missing", np.where(out["coverage"].ge(minimum_coverage), "qualified", "partial"))
    return out


def daily_quality(hourly: pd.DataFrame, minimum_coverage: float = 0.8) -> pd.DataFrame:
    if hourly.empty:
        return hourly.copy()
    grouped = hourly.groupby(["station_id", "variable", "local_day"], sort=True)
    rows = []
    for (station, variable, day), g in grouped:
        count = int(g["valid_count"].sum())
        expected = int(g["expected_count"].sum())
        coverage = count / expected
        valid = g[g["valid_count"] > 0]
        if variable == "rainfall":
            value = valid["value"].sum(min_count=1) if not valid.empty else np.nan
            unit = "mm/day"
        else:
            value = np.average(valid["value"], weights=valid["valid_count"]) if not valid.empty else np.nan
            unit = g["unit"].iloc[0]
        rows.append(dict(station_id=station, variable=variable, local_day=day, valid_count=count,
                         expected_count=expected, coverage=coverage, value=value, unit=unit,
                         status="missing" if count == 0 else "qualified" if coverage >= minimum_coverage else "partial"))
    return pd.DataFrame(rows)


def heat_degree_hours(observations: pd.DataFrame, threshold_c: float = 30.0, warming_c: float = 0.0,
                      expected_days: list[str] | None = None) -> dict:
    temp = observations[(observations["variable"] == "temperature") & (~observations["suspect"])].drop_duplicates("timestamp")
    if temp.empty:
        return {"heat_degree_hours": None, "valid_hours": 0.0, "coverage": 0.0, "per_valid_hour": None}
    days = len(expected_days) if expected_days else (pd.Timestamp(temp["local_day"].max()) - pd.Timestamp(temp["local_day"].min())).days + 1
    valid_hours = len(temp) / 60.0
    expected = days * 24.0
    h = float(np.maximum(temp["value"].to_numpy() + warming_c - threshold_c, 0).sum() / 60.0)
    return {"heat_degree_hours": h, "valid_hours": valid_hours, "coverage": valid_hours / expected,
            "per_valid_hour": h / valid_hours if valid_hours else None}
