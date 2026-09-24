"""Lokální cache v SQLite – vodní plochy, výsledky analýz a stažené rozsahy dat."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pandas as pd

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS waterbodies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    area_ha REAL NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    geometry TEXT NOT NULL,          -- GeoJSON ve WGS84
    tags TEXT
);
CREATE TABLE IF NOT EXISTS observations (
    wb_id TEXT NOT NULL,
    date TEXT NOT NULL,
    clear_fraction REAL,
    n_pixels INTEGER,
    chl REAL,
    chl_p90 REAL,
    turb REAL,
    scum_frac REAL,
    score REAL,
    PRIMARY KEY (wb_id, date)
);
CREATE TABLE IF NOT EXISTS temperatures (
    wb_id TEXT NOT NULL,
    date TEXT NOT NULL,
    clear_fraction REAL,
    n_pixels INTEGER,
    temp_c REAL,
    PRIMARY KEY (wb_id, date)
);
CREATE TABLE IF NOT EXISTS fetch_ranges (
    wb_id TEXT NOT NULL,
    source TEXT NOT NULL,
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL,
    PRIMARY KEY (wb_id, source)
);
"""


class Storage:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or config.DB_FILE)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------ waterbodies
    def replace_waterbodies(self, items: list[dict]) -> None:
        """Uloží nový seznam vodních ploch (výsledky analýz zůstávají v cache)."""
        ids = [it["id"] for it in items]
        with self.connect() as con:
            con.executemany(
                "INSERT OR REPLACE INTO waterbodies (id, name, area_ha, lat, lon, geometry, tags)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        it["id"], it["name"], it["area_ha"], it["lat"], it["lon"],
                        json.dumps(it["geometry"]), json.dumps(it.get("tags", {}), ensure_ascii=False),
                    )
                    for it in items
                ],
            )
            placeholders = ",".join("?" * len(ids)) or "''"
            con.execute(f"DELETE FROM waterbodies WHERE id NOT IN ({placeholders})", ids)

    def waterbodies(self) -> pd.DataFrame:
        with self.connect() as con:
            return pd.read_sql_query(
                "SELECT id, name, area_ha, lat, lon FROM waterbodies ORDER BY name COLLATE NOCASE", con
            )

    def waterbody(self, wb_id: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM waterbodies WHERE id = ?", (wb_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["geometry"] = json.loads(d["geometry"])
        d["tags"] = json.loads(d["tags"] or "{}")
        return d

    def all_geometries(self) -> list[dict]:
        with self.connect() as con:
            rows = con.execute("SELECT id, name, area_ha, geometry FROM waterbodies").fetchall()
        return [{**dict(r), "geometry": json.loads(r["geometry"])} for r in rows]

    # ----------------------------------------------------------- observations
    def save_observations(self, wb_id: str, rows: list[dict]) -> None:
        with self.connect() as con:
            con.executemany(
                "INSERT OR REPLACE INTO observations"
                " (wb_id, date, clear_fraction, n_pixels, chl, chl_p90, turb, scum_frac, score)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        wb_id, r["date"], r.get("clear_fraction"), r.get("n_pixels"), r.get("chl"),
                        r.get("chl_p90"), r.get("turb"), r.get("scum_frac"), r.get("score"),
                    )
                    for r in rows
                ],
            )

    def save_temperatures(self, wb_id: str, rows: list[dict]) -> None:
        with self.connect() as con:
            con.executemany(
                "INSERT OR REPLACE INTO temperatures (wb_id, date, clear_fraction, n_pixels, temp_c)"
                " VALUES (?, ?, ?, ?, ?)",
                [(wb_id, r["date"], r.get("clear_fraction"), r.get("n_pixels"), r.get("temp_c")) for r in rows],
            )

    def observations(self, wb_id: str, since: str | None = None) -> pd.DataFrame:
        q = "SELECT * FROM observations WHERE wb_id = ?"
        args: list = [wb_id]
        if since:
            q += " AND date >= ?"
            args.append(since)
        with self.connect() as con:
            return pd.read_sql_query(q + " ORDER BY date", con, params=args)

    def temperatures(self, wb_id: str, since: str | None = None) -> pd.DataFrame:
        q = "SELECT * FROM temperatures WHERE wb_id = ?"
        args: list = [wb_id]
        if since:
            q += " AND date >= ?"
            args.append(since)
        with self.connect() as con:
            return pd.read_sql_query(q + " ORDER BY date", con, params=args)

    def latest_summary(self, min_clear: float, since: str | None = None) -> pd.DataFrame:
        """Pro každou vodní plochu poslední platné pozorování (+ poslední teplota)."""
        since = since or "0000-00-00"
        with self.connect() as con:
            return pd.read_sql_query(
                """
                SELECT w.id, w.name, w.area_ha, w.lat, w.lon,
                       o.date AS obs_date, o.score, o.chl, o.turb, o.scum_frac,
                       t.date AS temp_date, t.temp_c
                FROM waterbodies w
                LEFT JOIN observations o ON o.wb_id = w.id AND o.date = (
                    SELECT MAX(date) FROM observations
                    WHERE wb_id = w.id AND score IS NOT NULL AND clear_fraction >= ? AND date >= ?)
                LEFT JOIN temperatures t ON t.wb_id = w.id AND t.date = (
                    SELECT MAX(date) FROM temperatures
                    WHERE wb_id = w.id AND temp_c IS NOT NULL AND clear_fraction >= ? AND date >= ?)
                ORDER BY w.name COLLATE NOCASE
                """,
                con,
                params=[min_clear, since, min_clear, since],
            )

    # ------------------------------------------------------------ fetch ranges
    def fetched_range(self, wb_id: str, source: str) -> tuple[str, str] | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT date_from, date_to FROM fetch_ranges WHERE wb_id = ? AND source = ?", (wb_id, source)
            ).fetchone()
        return (row["date_from"], row["date_to"]) if row else None

    def set_fetched_range(self, wb_id: str, source: str, date_from: str, date_to: str) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO fetch_ranges (wb_id, source, date_from, date_to) VALUES (?, ?, ?, ?)",
                (wb_id, source, date_from, date_to),
            )


def image_path(wb_id: str, date: str, kind: str) -> Path:
    """kind: 'rgb' nebo 'map'"""
    safe = wb_id.replace("/", "_")
    return config.IMAGES_DIR / safe / f"{date}_{kind}.png"
