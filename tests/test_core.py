from datetime import date

from shapely.geometry import shape

from kappka import analysis, evalscripts, pipeline
from kappka.waterbodies import parse_elements, to_utm

BBOX = (14.55, 48.82, 15.02, 49.25)


def _square(lon, lat, d):
    return [{"lon": lon, "lat": lat}, {"lon": lon + d, "lat": lat}, {"lon": lon + d, "lat": lat + d},
            {"lon": lon, "lat": lat + d}, {"lon": lon, "lat": lat}]


def test_parse_way_and_relation():
    elements = [
        {"type": "way", "id": 1, "tags": {"natural": "water", "name": "Velký"}, "geometry": _square(14.7, 49.0, 0.01)},
        {"type": "way", "id": 2, "tags": {"natural": "water", "name": "Malý"}, "geometry": _square(14.8, 49.0, 0.001)},
        {"type": "way", "id": 3, "tags": {"natural": "water", "water": "river"}, "geometry": _square(14.9, 49.0, 0.01)},
        {
            "type": "relation", "id": 4, "tags": {"natural": "water", "name": "Rozdělený"},
            "members": [
                {"type": "way", "role": "outer", "geometry": _square(14.6, 49.1, 0.01)[:3]},
                {"type": "way", "role": "outer", "geometry": _square(14.6, 49.1, 0.01)[2:]},
                {"type": "way", "role": "inner", "geometry": _square(14.603, 49.103, 0.002)},
            ],
        },
    ]
    items = {it["name"]: it for it in parse_elements(elements, BBOX, 10)}
    assert set(items) == {"Velký", "Rozdělený"}
    assert 70 < items["Velký"]["area_ha"] < 90
    assert items["Rozdělený"]["area_ha"] < items["Velký"]["area_ha"]


def test_score_monotonic_and_bounded():
    assert analysis.pollution_score(0, 0, 0) == 0
    assert analysis.pollution_score(500, 500, 1) == 100
    assert analysis.pollution_score(60, 10, 0) > analysis.pollution_score(20, 10, 0)
    assert analysis.rating(10).label == "Výborná"
    assert analysis.rating(None).label == "Bez dat"


def test_score_from_stats():
    def st(v, n=100, nd=10):
        return {"bands": {"B0": {"stats": {"mean": v, "sampleCount": n, "noDataCount": nd,
                                            "percentiles": {"10.0": v, "50.0": v, "90.0": v}}}}}
    res = analysis.score_from_stats({"chl": st(30), "turb": st(10), "scum": st(0.0)})
    assert res["clear_fraction"] == 0.9 and res["chl"] == 30 and 0 < res["score"] < 60
    cloudy = analysis.score_from_stats({"chl": st("NaN", 100, 100), "turb": st("NaN", 100, 100), "scum": st(0, 100, 100)})
    assert cloudy == {"clear_fraction": 0.0, "n_pixels": 0}


def test_missing_segments():
    s, e = date(2026, 5, 1), date(2026, 9, 1)
    assert pipeline._missing_segments(None, s, e) == [(s, e)]
    segs = pipeline._missing_segments(("2026-06-01", "2026-08-20"), s, e)
    assert segs[0] == (s, date(2026, 6, 1))
    assert segs[1] == (date(2026, 8, 15), e)


def test_evalscripts_render():
    for script in (evalscripts.s2_statistics(), evalscripts.s2_pollution_map(), evalscripts.landsat_temperature()):
        assert script.startswith("//VERSION=3")
        assert "%(" not in script
    assert "CHL_PTS = [[0, 0], [10, 15]" in evalscripts.s2_statistics()


def test_render_box():
    g = to_utm(shape({"type": "Polygon", "coordinates": [[(14.7, 49.0), (14.75, 49.0), (14.75, 49.02), (14.7, 49.0)]]}))
    bbox, w, h = pipeline._render_box(g)
    assert w <= 1200 and h <= 1200 and bbox[2] > bbox[0]
