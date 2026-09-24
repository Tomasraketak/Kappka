"""Stahování a analýza dat – používá GUI i příkazová řádka."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from shapely.geometry import mapping, shape

from . import analysis, evalscripts, storage
from .cdse import CDSEClient, CDSEError
from .config import Settings
from .waterbodies import fetch_waterbodies, to_utm

ProgressFn = Callable[[float, str], None]
StopFn = Callable[[], bool]

S2 = "sentinel-2-l2a"
LANDSAT = "landsat-ot-l1"
REFETCH_DAYS = 5  # poslední dny se stahují znovu (scény se zpracovávají se zpožděním)


def _noop(_p: float, _m: str) -> None:
    pass


def period_start(settings: Settings, today: date | None = None) -> date:
    today = today or date.today()
    return today - timedelta(days=round(settings.months_back * 30.44))


def update_waterbodies(settings: Settings, store: storage.Storage, progress: ProgressFn = _noop) -> int:
    items = fetch_waterbodies(settings.bbox, settings.min_area_ha, progress)
    if not items:
        raise RuntimeError("V zadané oblasti nebyla nalezena žádná vodní plocha.")
    store.replace_waterbodies(items)
    return len(items)


def _missing_segments(fetched: tuple[str, str] | None, start: date, end: date) -> list[tuple[date, date]]:
    if fetched is None:
        return [(start, end)]
    f_from, f_to = date.fromisoformat(fetched[0]), date.fromisoformat(fetched[1])
    segments = []
    if start < f_from:
        segments.append((start, f_from))
    resume = max(start, f_to - timedelta(days=REFETCH_DAYS))
    if resume <= end:
        segments.append((resume, end))
    return segments


def _inner(geom_utm, buffer_m: float, min_area_m2: float):
    """Zmenší polygon o pobřežní pás (smíšené pixely voda/rákosí/břeh)."""
    for b in (buffer_m, buffer_m / 2, 0):
        g = geom_utm.buffer(-b) if b else geom_utm
        if not g.is_empty and g.area >= min_area_m2:
            return g
    return None


def _fetch_stats(client, store, wb_id, source, geom, collection, script, resolution, dfilter, start, end, parse):
    rows_all = []
    for seg_from, seg_to in _missing_segments(store.fetched_range(wb_id, source), start, end):
        data = client.statistics(
            mapping(geom), collection, script,
            f"{seg_from.isoformat()}T00:00:00Z", f"{seg_to.isoformat()}T23:59:59Z",
            resolution, dfilter,
        )
        rows = []
        for item in data:
            if "error" in item or "outputs" not in item:
                continue
            parsed = parse(item["outputs"])
            if parsed is None:
                continue
            parsed["date"] = item["interval"]["from"][:10]
            rows.append(parsed)
        rows_all.extend(rows)
        if source == "s2":
            store.save_observations(wb_id, rows)
        else:
            store.save_temperatures(wb_id, rows)
        prev = store.fetched_range(wb_id, source)
        new_from = min(seg_from.isoformat(), prev[0]) if prev else seg_from.isoformat()
        new_to = max(seg_to.isoformat(), prev[1]) if prev else seg_to.isoformat()
        store.set_fetched_range(wb_id, source, new_from, new_to)
    return rows_all


def _render_box(geom_utm, px: float = 10.0, max_px: int = 1200):
    minx, miny, maxx, maxy = geom_utm.bounds
    w, h = maxx - minx, maxy - miny
    span = max(w, h, 300.0) * 1.15
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    # zachovat poměr stran, ale nechat okraj kolem plochy
    half_w = max(w * 1.15, span * 0.6) / 2
    half_h = max(h * 1.15, span * 0.6) / 2
    bbox = (cx - half_w, cy - half_h, cx + half_w, cy + half_h)
    width = int(round(2 * half_w / px))
    height = int(round(2 * half_h / px))
    scale = min(1.0, max_px / max(width, height))
    return bbox, max(32, int(width * scale)), max(32, int(height * scale))


def ensure_images(client: CDSEClient, wb: dict, day: str) -> tuple[str, str]:
    """Stáhne (pokud už nejsou v cache) RGB snímek a mapu znečištění pro daný den."""
    rgb_path = storage.image_path(wb["id"], day, "rgb")
    map_path = storage.image_path(wb["id"], day, "map")
    if rgb_path.exists() and map_path.exists():
        return str(rgb_path), str(map_path)
    rgb_path.parent.mkdir(parents=True, exist_ok=True)
    geom_utm = to_utm(shape(wb["geometry"]))
    bbox, width, height = _render_box(geom_utm)
    if not rgb_path.exists():
        rgb_path.write_bytes(client.process_png(bbox, S2, evalscripts.s2_true_color(), day, width, height))
    if not map_path.exists():
        map_path.write_bytes(
            client.process_png(
                bbox, S2, evalscripts.s2_pollution_map(), day, width, height, geometry_utm=mapping(geom_utm)
            )
        )
    return str(rgb_path), str(map_path)


def update_analysis(
    settings: Settings,
    store: storage.Storage,
    client: CDSEClient,
    wb_ids: list[str] | None = None,
    progress: ProgressFn = _noop,
    should_stop: StopFn = lambda: False,
) -> dict:
    """Stáhne statistiky Sentinel-2 (a Landsat teploty) pro všechny / vybrané vodní plochy."""
    client.test_connection()
    ids = wb_ids or store.waterbodies()["id"].tolist()
    end = date.today()
    start = period_start(settings, end)
    s2_script = evalscripts.s2_statistics()
    t_script = evalscripts.landsat_temperature()
    s2_filter = {"maxCloudCoverage": settings.max_scene_cloud, "mosaickingOrder": "leastCC"}
    l_filter = {"maxCloudCoverage": settings.max_scene_cloud}
    summary = {"processed": 0, "observations": 0, "images": 0, "errors": []}

    for i, wb_id in enumerate(ids):
        if should_stop():
            break
        wb = store.waterbody(wb_id)
        if wb is None:
            continue
        progress(i / max(len(ids), 1), f"{wb['name']} ({i + 1}/{len(ids)}) – analýza Sentinel-2…")
        try:
            geom_utm = to_utm(shape(wb["geometry"]))
            g_s2 = _inner(geom_utm, 20, 20 * 100)  # aspoň ~20 pixelů 10 m
            if g_s2 is not None:
                rows = _fetch_stats(
                    client, store, wb_id, "s2", g_s2, S2, s2_script, 10, s2_filter, start, end,
                    analysis.score_from_stats,
                )
                summary["observations"] += len(rows)

            if settings.fetch_temperature:
                g_t = _inner(geom_utm, 60, 6 * 900)  # aspoň ~6 pixelů 30 m, mimo pobřeží
                if g_t is not None:
                    progress(i / max(len(ids), 1), f"{wb['name']} ({i + 1}/{len(ids)}) – teplota Landsat…")
                    _fetch_stats(
                        client, store, wb_id, "landsat", g_t, LANDSAT, t_script, 30, l_filter, start, end,
                        analysis.temperature_from_stats,
                    )

            obs = store.observations(wb_id, since=start.isoformat())
            valid = obs[(obs["clear_fraction"] >= settings.min_clear_fraction) & obs["score"].notna()]
            days = sorted(valid["date"].tolist(), reverse=True)
            if not settings.download_all_images:
                days = days[:1]
            for day in days:
                if should_stop():
                    break
                if not storage.image_path(wb_id, day, "map").exists():
                    progress(i / max(len(ids), 1), f"{wb['name']} ({i + 1}/{len(ids)}) – snímek {day}…")
                    ensure_images(client, wb, day)
                    summary["images"] += 1
            summary["processed"] += 1
        except CDSEError as exc:
            summary["errors"].append(f"{wb['name']}: {exc}")
            if "Přihlášení" in str(exc):
                raise
    progress(1.0, "Hotovo")
    return summary
