"""Kouřový test GUI s umělými daty (bez přístupu k API)."""
import importlib
import struct
import zlib
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _png(path: Path) -> None:
    raw = b"".join(b"\x00" + b"\x40\x80\xc0\xff" * 4 for _ in range(4))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("KAPPKA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CDSE_CLIENT_ID", "")
    from kappka import config, storage
    importlib.reload(config)
    importlib.reload(storage)
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    store = storage.Storage()
    store.replace_waterbodies([
        {"id": "osm-way-1", "name": "Rožmberk", "area_ha": 489.0, "lat": 49.05, "lon": 14.77,
         "geometry": {"type": "Polygon", "coordinates": [[[14.76, 49.04], [14.79, 49.04], [14.79, 49.07], [14.76, 49.04]]]}},
        {"id": "osm-way-2", "name": "Svět", "area_ha": 201.0, "lat": 48.99, "lon": 14.76,
         "geometry": {"type": "Polygon", "coordinates": [[[14.75, 48.98], [14.77, 48.98], [14.77, 49.0], [14.75, 48.98]]]}},
    ])
    today = date.today()
    rows = []
    for k in range(6):
        d = (today - timedelta(days=5 * k + 2)).isoformat()
        rows.append({"date": d, "clear_fraction": 0.95 if k != 2 else 0.2, "n_pixels": 500,
                     "chl": 30 + k, "chl_p90": 50, "turb": 12, "scum_frac": 0.01, "score": 40 + k})
        _png(storage.image_path("osm-way-1", d, "rgb"))
        _png(storage.image_path("osm-way-1", d, "map"))
    store.save_observations("osm-way-1", rows)
    store.save_temperatures("osm-way-1", [{"date": (today - timedelta(days=3)).isoformat(),
                                           "clear_fraction": 1.0, "n_pixels": 40, "temp_c": 19.4}])
    return tmp_path


def test_app_renders(seeded):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception, at.exception
    assert any("Rožmberk" in h.value for h in at.header)
    at.text_input(key="search").set_value("rozmb").run()   # hledání bez diakritiky
    assert not at.exception, at.exception
    assert any("Rožmberk" in h.value for h in at.header)
    at.text_input(key="search").set_value("svet").run()
    assert not at.exception, at.exception
    assert any("Svět" in h.value for h in at.header)
