import json

import pytest
import requests

import ntu_climate.io as io


def test_offline_missing_cache_raises_without_synthetic_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(io, "ROOT", tmp_path)
    with pytest.raises(FileNotFoundError, match="Missing cached observed data"):
        io.fetch_daily(["2026-09-24"], offline=True)


def test_download_failure_stays_failure(monkeypatch):
    class Session:
        def get(self, *args, **kwargs):
            raise requests.ConnectionError("network unavailable")
    downloader = io.Downloader(interval_s=0)
    downloader.session = Session()
    monkeypatch.setattr(io.time, "sleep", lambda _: None)
    with pytest.raises(requests.ConnectionError, match="network unavailable"):
        downloader.get("https://example.test/")
