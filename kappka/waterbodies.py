"""Seznam vodních ploch s názvy a hranicemi.

Copernicus neposkytuje pojmenovaný inventář vodních ploch, proto se polygony a
názvy berou z OpenStreetMap (Overpass API). Veškeré snímky a analýzy pak jdou
z Copernicus Data Space.
"""
from __future__ import annotations

import math
from typing import Callable

import requests
from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Polygon, mapping, shape
from shapely.ops import linemerge, polygonize, transform, unary_union

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# Tekoucí a technické vody nás nezajímají
EXCLUDED_WATER = {"river", "canal", "stream", "ditch", "drain", "wastewater", "lock", "fish_pass", "moat"}

_to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32633", always_xy=True).transform
_to_wgs = Transformer.from_crs("EPSG:32633", "EPSG:4326", always_xy=True).transform

ProgressFn = Callable[[float, str], None]


def to_utm(geom):
    return transform(_to_utm, geom)


def to_wgs(geom):
    return transform(_to_wgs, geom)


def _query(bbox: tuple[float, float, float, float]) -> str:
    w, s, e, n = bbox
    b = f"({s},{w},{n},{e})"
    return f"""
[out:json][timeout:600];
(
  way["natural"="water"]{b};
  relation["natural"="water"]{b};
  way["landuse"="reservoir"]{b};
  relation["landuse"="reservoir"]{b};
);
out geom;
"""


def _tiles(bbox: tuple[float, float, float, float], step: float = 0.6) -> list[tuple[float, float, float, float]]:
    w, s, e, n = bbox
    nx = max(1, math.ceil((e - w) / step))
    ny = max(1, math.ceil((n - s) / step))
    dx, dy = (e - w) / nx, (n - s) / ny
    return [(w + i * dx, s + j * dy, w + (i + 1) * dx, s + (j + 1) * dy) for i in range(nx) for j in range(ny)]


def _fetch_overpass(query: str) -> dict:
    errors = []
    for url in OVERPASS_URLS:
        try:
            resp = requests.post(
                url, data={"data": query}, timeout=900, headers={"User-Agent": "Kappka/1.0 (water quality app)"}
            )
            if resp.status_code == 200:
                return resp.json()
            errors.append(f"{url}: HTTP {resp.status_code}")
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Nepodařilo se stáhnout data z OpenStreetMap (Overpass):\n" + "\n".join(errors))


def _ring(coords: list[tuple[float, float]]) -> Polygon | None:
    if len(coords) < 4 or coords[0] != coords[-1]:
        return None
    poly = Polygon(coords)
    return poly if poly.is_valid else poly.buffer(0)


def _polygons_from_lines(lines: list[list[tuple[float, float]]]):
    if not lines:
        return None
    merged = linemerge([LineString(c) for c in lines if len(c) >= 2])
    polys = list(polygonize(merged))
    return unary_union(polys) if polys else None


def element_geometry(el: dict):
    """Polygon (WGS84) z elementu Overpass s `out geom`."""
    if el["type"] == "way":
        coords = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
        return _ring(coords)
    if el["type"] == "relation":
        outers, inners = [], []
        for m in el.get("members", []):
            if m.get("type") != "way" or "geometry" not in m:
                continue
            coords = [(p["lon"], p["lat"]) for p in m["geometry"]]
            (inners if m.get("role") == "inner" else outers).append(coords)
        outer = _polygons_from_lines(outers)
        if outer is None or outer.is_empty:
            return None
        inner = _polygons_from_lines(inners)
        geom = outer.difference(inner) if inner is not None and not inner.is_empty else outer
        return geom if geom.is_valid else geom.buffer(0)
    return None


def parse_elements(
    elements: list[dict], bbox: tuple[float, float, float, float], min_area_ha: float
) -> list[dict]:
    w, s, e, n = bbox
    result: dict[str, dict] = {}
    for el in elements:
        tags = el.get("tags", {})
        if tags.get("water") in EXCLUDED_WATER or tags.get("waterway"):
            continue
        geom = element_geometry(el)
        if geom is None or geom.is_empty or not isinstance(geom, (Polygon, MultiPolygon)):
            continue
        area_ha = to_utm(geom).area / 10_000
        if area_ha < min_area_ha:
            continue
        pt = geom.representative_point()
        if not (w <= pt.x <= e and s <= pt.y <= n):
            continue
        name = tags.get("name:cs") or tags.get("name") or ""
        wb_id = f"osm-{el['type']}-{el['id']}"
        if not name:
            name = f"Bezejmenná vodní plocha ({area_ha:.0f} ha, {pt.y:.3f}N {pt.x:.3f}E)"
        result[wb_id] = {
            "id": wb_id,
            "name": name,
            "area_ha": round(area_ha, 1),
            "lat": pt.y,
            "lon": pt.x,
            "geometry": mapping(geom.simplify(0.00002, preserve_topology=True)),
            "tags": {k: v for k, v in tags.items() if k in ("name", "water", "natural", "landuse", "wikidata")},
        }
    # Vnořené duplicity (např. way uvnitř multipolygonu se stejným názvem) – necháme větší
    items = sorted(result.values(), key=lambda d: -d["area_ha"])
    kept: list[dict] = []
    by_name: dict[str, list] = {}
    for it in items:
        g = shape(it["geometry"])
        same_name = by_name.setdefault(it["name"], [])
        if any(k.contains(g.representative_point()) for k in same_name):
            continue
        kept.append(it)
        same_name.append(g)
    return kept


def fetch_waterbodies(
    bbox: tuple[float, float, float, float], min_area_ha: float, progress: ProgressFn | None = None
) -> list[dict]:
    tiles = _tiles(bbox)
    elements: dict[tuple[str, int], dict] = {}
    for i, tile in enumerate(tiles):
        if progress:
            progress(i / len(tiles), f"Stahuji vodní plochy z OpenStreetMap ({i + 1}/{len(tiles)})…")
        data = _fetch_overpass(_query(tile))
        for el in data.get("elements", []):
            elements[(el["type"], el["id"])] = el
    if progress:
        progress(1.0, "Zpracovávám polygony…")
    return parse_elements(list(elements.values()), bbox, min_area_ha)
