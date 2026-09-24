"""Výpočet arbitrárního skóre znečištění 0–100 (0 = čistá voda, 100 = nevhodné ke koupání).

Skóre vychází ze tří složek odhadnutých ze Sentinel-2:
  * chlorofyl-a (µg/l) – řasy a sinice v celém vodním sloupci
    (orientačně podle WHO pro rekreační vody: <10 nízké, 10–50 střední, >50 vysoké riziko),
  * zákal (NTU) – kal, rozvířený sediment, snížená průhlednost,
  * podíl hladiny pokrytý plovoucím povlakem (vodní květ sinic).

Každá složka se převede na 0–100 po částech lineární funkcí a výsledek je
průměr z nejhorší složky a váženého průměru (jedna výrazně špatná veličina tak
nezanikne v průměru).
"""
from __future__ import annotations

from dataclasses import dataclass

# (hodnota, skóre) – body po částech lineární funkce
CHL_POINTS = [(0, 0), (10, 15), (25, 40), (50, 65), (100, 85), (200, 100)]
TURB_POINTS = [(0, 0), (5, 5), (15, 30), (35, 60), (70, 85), (120, 100)]
SCUM_POINTS = [(0, 0), (0.05, 40), (0.2, 80), (0.4, 100)]
WEIGHTS = (0.55, 0.3, 0.15)  # chlorofyl, zákal, povlak


def interp(x: float, pts: list[tuple[float, float]]) -> float:
    if x <= pts[0][0]:
        return float(pts[0][1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return float(pts[-1][1])


def pollution_score(chl: float, turb: float, scum_frac: float) -> float:
    c = interp(chl, CHL_POINTS)
    t = interp(turb, TURB_POINTS)
    k = interp(scum_frac, SCUM_POINTS)
    weighted = WEIGHTS[0] * c + WEIGHTS[1] * t + WEIGHTS[2] * k
    return round(0.5 * max(c, t, k) + 0.5 * weighted, 1)


@dataclass(frozen=True)
class Rating:
    label: str
    color: str
    description: str


def rating(score: float | None) -> Rating:
    if score is None:
        return Rating("Bez dat", "#9e9e9e", "Za zvolené období není k dispozici žádný bezoblačný snímek.")
    if score < 20:
        return Rating("Výborná", "#1a9850", "Čistá voda, vhodná ke koupání.")
    if score < 40:
        return Rating("Dobrá", "#91cf60", "Mírný rozvoj řas nebo zákal, koupání bez omezení.")
    if score < 60:
        return Rating("Zhoršená", "#f2b701", "Zvýšené množství řas/sinic nebo kalu – opatrnost, zejména pro děti.")
    if score < 80:
        return Rating("Špatná", "#fc8d59", "Silný rozvoj sinic nebo vysoký zákal – koupání se nedoporučuje.")
    return Rating("Nevhodná", "#d73027", "Vodní květ sinic / velmi kalná voda – nekoupat se.")


def score_from_stats(outputs: dict) -> dict | None:
    """Z odpovědi Statistical API (jeden den) spočte metriky. Vrací None, když chybí data."""
    try:
        chl_stats = outputs["chl"]["bands"]["B0"]["stats"]
        turb_stats = outputs["turb"]["bands"]["B0"]["stats"]
        scum_stats = outputs["scum"]["bands"]["B0"]["stats"]
    except KeyError:
        return None
    total = chl_stats.get("sampleCount") or 0
    nodata = chl_stats.get("noDataCount") or 0
    clear = total - nodata
    if total <= 0 or clear <= 0:
        return {"clear_fraction": 0.0, "n_pixels": 0}

    def p50(stats: dict) -> float | None:
        perc = stats.get("percentiles") or {}
        val = perc.get("50.0", stats.get("mean"))
        return None if val is None or val != val else float(val)  # NaN check

    chl = p50(chl_stats)
    turb = p50(turb_stats)
    scum = scum_stats.get("mean")
    if chl is None or turb is None or scum is None or scum != scum:
        return {"clear_fraction": clear / total, "n_pixels": clear}
    return {
        "clear_fraction": clear / total,
        "n_pixels": clear,
        "chl": round(chl, 1),
        "chl_p90": round(float(chl_stats.get("percentiles", {}).get("90.0", chl)), 1),
        "turb": round(turb, 1),
        "scum_frac": round(float(scum), 3),
        "score": pollution_score(chl, turb, float(scum)),
    }


def temperature_from_stats(outputs: dict) -> dict | None:
    try:
        st = outputs["temp"]["bands"]["B0"]["stats"]
    except KeyError:
        return None
    total = st.get("sampleCount") or 0
    clear = total - (st.get("noDataCount") or 0)
    val = (st.get("percentiles") or {}).get("50.0", st.get("mean"))
    if total <= 0 or clear <= 0 or val is None or val != val:
        return {"clear_fraction": 0.0 if total <= 0 else clear / total, "n_pixels": max(clear, 0)}
    return {"clear_fraction": clear / total, "n_pixels": clear, "temp_c": round(float(val), 1)}
