"""Kappka – kvalita vody pro koupání ze satelitních dat Copernicus.

Spuštění:  streamlit run app.py
"""
from __future__ import annotations

import unicodedata
from datetime import date

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

from kappka import analysis, config, pipeline, storage
from kappka.cdse import CDSEClient, CDSEError

st.set_page_config(page_title="Kappka – kvalita vody", page_icon="💧", layout="wide")

st.markdown(
    """
    <style>
    .score-card {border-radius: 16px; padding: 18px 22px; color: white; box-shadow: 0 2px 8px rgba(0,0,0,.15);}
    .score-card .value {font-size: 3.2rem; font-weight: 800; line-height: 1;}
    .score-card .label {font-size: 1.3rem; font-weight: 600; margin-top: 4px;}
    .score-card .desc {font-size: .9rem; opacity: .95; margin-top: 6px;}
    .muted {color: #888; font-size: .85rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

config.ensure_dirs()


@st.cache_resource
def get_store() -> storage.Storage:
    return storage.Storage()


store = get_store()
settings = config.Settings.load()
creds = config.Credentials.load()


def get_client() -> CDSEClient | None:
    if not creds.ok:
        return None
    key = (creds.client_id, creds.client_secret)
    if st.session_state.get("_client_key") != key:
        st.session_state["_client"] = CDSEClient(*key)
        st.session_state["_client_key"] = key
    return st.session_state["_client"]


def normalize(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


# ============================================================== postranní panel
with st.sidebar:
    st.title("💧 Kappka")
    st.caption("Kvalita vody pro koupání ze satelitů Copernicus Sentinel-2 a Landsat")

    with st.expander("🔑 Přístup ke Copernicus", expanded=not creds.ok):
        st.markdown(
            "Zdarma na [dataspace.copernicus.eu](https://dataspace.copernicus.eu). Pak v "
            "[Sentinel Hub dashboardu](https://shapps.dataspace.copernicus.eu/dashboard/) → "
            "*User settings* → *OAuth clients* vytvořte klienta."
        )
        cid = st.text_input("Client ID", value=creds.client_id)
        csecret = st.text_input("Client secret", value=creds.client_secret, type="password")
        if st.button("Uložit a ověřit", width="stretch"):
            try:
                CDSEClient(cid.strip(), csecret.strip()).test_connection()
                config.Credentials(cid.strip(), csecret.strip()).save()
                st.success("Přihlášení funguje, údaje uloženy do .env")
                st.rerun()
            except CDSEError as exc:
                st.error(str(exc))

    with st.expander("⚙️ Nastavení", expanded=False):
        regions = list(config.REGIONS) + ["Vlastní"]
        settings.region = st.selectbox(
            "Oblast", regions, index=regions.index(settings.region) if settings.region in regions else 0
        )
        if settings.region == "Vlastní":
            c1, c2 = st.columns(2)
            b = list(settings.custom_bbox)
            b[0] = c1.number_input("Západ (lon)", value=float(b[0]), format="%.3f")
            b[2] = c2.number_input("Východ (lon)", value=float(b[2]), format="%.3f")
            b[1] = c1.number_input("Jih (lat)", value=float(b[1]), format="%.3f")
            b[3] = c2.number_input("Sever (lat)", value=float(b[3]), format="%.3f")
            settings.custom_bbox = tuple(b)
        settings.min_area_ha = st.number_input("Minimální plocha (ha)", 1.0, 5000.0, float(settings.min_area_ha), 1.0)
        settings.months_back = st.slider("Období analýzy (měsíce zpět)", 1, 24, int(settings.months_back))
        settings.min_clear_fraction = st.slider(
            "Min. podíl hladiny bez mraků", 0.3, 1.0, float(settings.min_clear_fraction), 0.05,
            help="Snímky, kde je větší část hladiny zakrytá mraky nebo jejich stíny, se ignorují.",
        )
        settings.max_scene_cloud = st.slider(
            "Max. oblačnost celé scény (%)", 10, 100, int(settings.max_scene_cloud), 5,
            help="Předfiltr podle metadat scény – zrychluje stahování.",
        )
        settings.download_all_images = st.toggle(
            "Stahovat snímky všech bezoblačných dnů", settings.download_all_images,
            help="Vypnuto: stáhne se jen nejnovější snímek, starší se dotáhnou při prohlížení.",
        )
        settings.fetch_temperature = st.toggle("Teplota hladiny (Landsat 8/9)", settings.fetch_temperature)
        settings.save()

    st.divider()
    n_wb = len(store.waterbodies())
    st.markdown(f"**Oblast:** {settings.region} · **Vodních ploch:** {n_wb}")

    if st.button("1️⃣ Načíst seznam vodních ploch", width="stretch"):
        bar = st.progress(0.0, "Začínám…")
        try:
            n = pipeline.update_waterbodies(settings, store, lambda p, m: bar.progress(min(p, 1.0), m))
            st.success(f"Nalezeno {n} vodních ploch nad {settings.min_area_ha:g} ha.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001 – chybu chceme ukázat v GUI
            st.error(str(exc))

    client = get_client()
    if st.button(
        "2️⃣ Stáhnout / aktualizovat snímky", width="stretch", type="primary",
        disabled=client is None or n_wb == 0,
        help=None if client else "Nejdřív vyplňte přístup ke Copernicus.",
    ):
        bar = st.progress(0.0, "Připojuji se ke Copernicus…")
        try:
            res = pipeline.update_analysis(
                settings, store, client, progress=lambda p, m: bar.progress(min(p, 1.0), m)
            )
            st.success(
                f"Zpracováno {res['processed']} ploch, {res['observations']} snímků analyzováno, "
                f"{res['images']} náhledů staženo."
            )
            for err in res["errors"][:10]:
                st.warning(err)
        except CDSEError as exc:
            st.error(str(exc))
    st.caption(
        "Stažená data se ukládají do složky `data/` – při dalším spuštění se stahují jen nové snímky. "
        "Stahování lze kdykoliv přerušit, hotové plochy zůstanou uložené."
    )


# ============================================================== hlavní část
since = pipeline.period_start(settings).isoformat()
summary = store.latest_summary(settings.min_clear_fraction, since)

if summary.empty:
    st.title("Kvalita vody pro koupání 🛰️")
    st.info(
        "Začněte v levém panelu:\n\n"
        "1. vyplňte přístup ke **Copernicus Data Space** (zdarma),\n"
        "2. klikněte na **Načíst seznam vodních ploch**,\n"
        "3. klikněte na **Stáhnout / aktualizovat snímky**."
    )
    st.stop()

tab_detail, tab_map, tab_table, tab_about = st.tabs(["🔎 Vyhledat", "🗺️ Mapa", "📋 Žebříček", "ℹ️ Jak to funguje"])


def score_card(score: float | None, subtitle: str) -> str:
    r = analysis.rating(score)
    value = "–" if score is None or pd.isna(score) else f"{score:.0f}"
    return (
        f'<div class="score-card" style="background:{r.color}">'
        f'<div class="muted" style="color:rgba(255,255,255,.85)">Index znečištění (0 = čistá, 100 = nevhodná)</div>'
        f'<div class="value">{value}</div><div class="label">{r.label}</div>'
        f'<div class="desc">{r.description}<br>{subtitle}</div></div>'
    )


def fmt_date(d: str | None) -> str:
    if not d or pd.isna(d):
        return "–"
    dd = date.fromisoformat(d)
    days = (date.today() - dd).days
    ago = "dnes" if days == 0 else "včera" if days == 1 else f"před {days} dny"
    return f"{dd.day}. {dd.month}. {dd.year} ({ago})"


# ------------------------------------------------------------------ detail
def render_detail() -> None:
    query = st.text_input("Hledat vodní plochu", key="search", placeholder="např. Rožmberk, Svět, Opatovický…")
    candidates = summary
    if query:
        q = normalize(query)
        candidates = summary[summary["name"].map(lambda n: q in normalize(n))]
    candidates = candidates.sort_values("area_ha", ascending=False)
    if candidates.empty:
        st.warning("Nic nenalezeno.")
        return

    options = candidates["id"].tolist()
    labels = dict(zip(candidates["id"], candidates["name"] + " · " + candidates["area_ha"].round(0).astype(int).astype(str) + " ha"))
    default = st.session_state.get("selected_wb")
    wb_id = st.selectbox(
        f"Výsledky ({len(options)})", options, format_func=labels.get,
        index=options.index(default) if default in options else 0,
    )
    st.session_state["selected_wb"] = wb_id
    row = summary[summary["id"] == wb_id].iloc[0]
    wb = store.waterbody(wb_id)

    st.header(row["name"])
    st.caption(f"Rozloha {row['area_ha']:.0f} ha · {row['lat']:.4f} N, {row['lon']:.4f} E · "
               f"[mapy.cz](https://mapy.cz/zakladni?x={row['lon']}&y={row['lat']}&z=14)")

    obs = store.observations(wb_id, since)
    valid = obs[(obs["clear_fraction"] >= settings.min_clear_fraction) & obs["score"].notna()]
    temps = store.temperatures(wb_id, since)
    temps_valid = temps[(temps["clear_fraction"] >= settings.min_clear_fraction) & temps["temp_c"].notna()]

    c_score, c_metrics = st.columns([1, 2])
    with c_score:
        st.markdown(score_card(row["score"], f"Snímek: {fmt_date(row['obs_date'])}"), unsafe_allow_html=True)
    with c_metrics:
        m1, m2, m3 = st.columns(3)
        prev = valid.iloc[-2] if len(valid) >= 2 else None
        m1.metric("Chlorofyl-a (odhad)", "–" if pd.isna(row["chl"]) else f"{row['chl']:.0f} µg/l",
                  None if prev is None or pd.isna(row["chl"]) else f"{row['chl'] - prev['chl']:+.0f}",
                  delta_color="inverse")
        m2.metric("Zákal (odhad)", "–" if pd.isna(row["turb"]) else f"{row['turb']:.0f} NTU",
                  None if prev is None or pd.isna(row["turb"]) else f"{row['turb'] - prev['turb']:+.0f}",
                  delta_color="inverse")
        m3.metric("Povlak sinic na hladině", "–" if pd.isna(row["scum_frac"]) else f"{row['scum_frac'] * 100:.0f} %")
        t1, t2, t3 = st.columns(3)
        if pd.notna(row["temp_c"]):
            t1.metric("🌡️ Teplota hladiny", f"{row['temp_c']:.1f} °C")
            t1.caption(f"Landsat, {fmt_date(row['temp_date'])} · odhad ±2 °C")
        else:
            t1.metric("🌡️ Teplota hladiny", "–")
            t1.caption("Plocha je pro termální pásmo (100 m) malá, nebo chybí jasný snímek.")
        t2.metric("Bezoblačných snímků", f"{len(valid)} / {len(obs)}")
        t3.metric("Období", f"{settings.months_back} měs.")
        client = get_client()
        if client and st.button("🔄 Aktualizovat tuto plochu"):
            bar = st.progress(0.0)
            try:
                pipeline.update_analysis(settings, store, client, [wb_id], lambda p, m: bar.progress(min(p, 1.0), m))
                st.rerun()
            except CDSEError as exc:
                st.error(str(exc))

    if valid.empty:
        st.info("Za zvolené období zatím nejsou žádné bezoblačné snímky – zkuste stáhnout data nebo prodloužit období.")
    else:
        st.subheader("🛰️ Satelitní snímek")
        days = valid["date"].tolist()
        day = st.select_slider("Datum snímku", options=days, value=days[-1], format_func=lambda d: fmt_date(d))
        day_row = valid[valid["date"] == day].iloc[0]
        rgb_p, map_p = storage.image_path(wb_id, day, "rgb"), storage.image_path(wb_id, day, "map")
        if not (rgb_p.exists() and map_p.exists()):
            client = get_client()
            if client:
                with st.spinner("Stahuji snímek z Copernicus…"):
                    try:
                        pipeline.ensure_images(client, wb, day)
                    except CDSEError as exc:
                        st.error(str(exc))
        i1, i2 = st.columns(2)
        if rgb_p.exists():
            i1.image(str(rgb_p), caption=f"Sentinel-2, přirozené barvy – {fmt_date(day)}", width="stretch")
        else:
            i1.info("Snímek není stažen.")
        if map_p.exists():
            i2.image(
                str(map_p), width="stretch",
                caption=f"Mapa znečištění: 🟩 čistá → 🟨 → 🟥 znečištěná, ⬜ mraky · skóre {day_row['score']:.0f}",
            )

        st.subheader("📈 Vývoj")
        hist = valid.assign(datum=pd.to_datetime(valid["date"]))
        bands = pd.DataFrame(
            {"od": [0, 20, 40, 60, 80], "do": [20, 40, 60, 80, 100],
             "barva": ["#1a9850", "#91cf60", "#f2b701", "#fc8d59", "#d73027"]}
        )
        bg = alt.Chart(bands).mark_rect(opacity=0.12).encode(
            y=alt.Y("od:Q", scale=alt.Scale(domain=[0, 100])), y2="do:Q", color=alt.Color("barva:N", scale=None)
        )
        line = alt.Chart(hist).mark_line(point=alt.OverlayMarkDef(color="#1f3b73"), color="#1f3b73").encode(
            x=alt.X("datum:T", title=None, axis=alt.Axis(format="%-d. %-m.")),
            y=alt.Y("score:Q", title="Index znečištění", scale=alt.Scale(domain=[0, 100])),
            tooltip=[alt.Tooltip("datum:T", title="Datum"), alt.Tooltip("score:Q", title="Skóre"),
                     alt.Tooltip("chl:Q", title="Chlorofyl µg/l"), alt.Tooltip("turb:Q", title="Zákal NTU"),
                     alt.Tooltip("clear_fraction:Q", title="Bez mraků", format=".0%")],
        )
        charts = [(bg + line).properties(height=260, width="container")]
        if not temps_valid.empty:
            th = temps_valid.assign(datum=pd.to_datetime(temps_valid["date"]))
            charts.append(
                alt.Chart(th).mark_line(point=alt.OverlayMarkDef(color="#e4572e"), color="#e4572e").encode(
                    x=alt.X("datum:T", title=None, axis=alt.Axis(format="%-d. %-m."),
                          scale=alt.Scale(domain=[hist["datum"].min(), hist["datum"].max()])),
                    y=alt.Y("temp_c:Q", title="Teplota °C"),
                    tooltip=[alt.Tooltip("datum:T", title="Datum"), alt.Tooltip("temp_c:Q", title="°C")],
                ).properties(height=160, width="container")
            )
        for ch in charts:
            st.altair_chart(ch, width="stretch", theme=None)

        with st.expander("Tabulka všech snímků (včetně zamítnutých kvůli oblačnosti)"):
            tbl = obs.merge(temps[["date", "temp_c"]], on="date", how="outer").sort_values("date", ascending=False)
            tbl["použito"] = (tbl["clear_fraction"] >= settings.min_clear_fraction) & tbl["score"].notna()
            st.dataframe(
                tbl[["date", "použito", "clear_fraction", "score", "chl", "turb", "scum_frac", "temp_c"]],
                hide_index=True, width="stretch",
                column_config={
                    "date": "Datum",
                    "clear_fraction": st.column_config.ProgressColumn("Bez mraků", min_value=0, max_value=1, format="percent"),
                    "score": st.column_config.NumberColumn("Skóre", format="%.0f"),
                    "chl": st.column_config.NumberColumn("Chlorofyl µg/l", format="%.0f"),
                    "turb": st.column_config.NumberColumn("Zákal NTU", format="%.0f"),
                    "scum_frac": st.column_config.NumberColumn("Povlak", format="%.2f"),
                    "temp_c": st.column_config.NumberColumn("Teplota °C", format="%.1f"),
                },
            )


with tab_detail:
    render_detail()


# ------------------------------------------------------------------ mapa
def _hex_to_rgb(h: str) -> list[int]:
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


with tab_map:
    by_id = summary.set_index("id")
    features = []
    for g in store.all_geometries():
        if g["id"] not in by_id.index:
            continue
        r = by_id.loc[g["id"]]
        score = None if pd.isna(r["score"]) else float(r["score"])
        features.append({
            "type": "Feature",
            "geometry": g["geometry"],
            "properties": {
                "name": g["name"],
                "score": "–" if score is None else f"{score:.0f}",
                "label": analysis.rating(score).label,
                "temp": "–" if pd.isna(r["temp_c"]) else f"{r['temp_c']:.1f} °C",
                "date": r["obs_date"] if isinstance(r["obs_date"], str) else "–",
                "color": _hex_to_rgb(analysis.rating(score).color) + [190],
            },
        })
    layer = pdk.Layer(
        "GeoJsonLayer", {"type": "FeatureCollection", "features": features},
        pickable=True, stroked=True, filled=True, get_fill_color="properties.color",
        get_line_color=[40, 40, 40, 200], line_width_min_pixels=1,
    )
    view = pdk.ViewState(latitude=float(summary["lat"].mean()), longitude=float(summary["lon"].mean()), zoom=10)
    st.pydeck_chart(
        pdk.Deck(
            layers=[layer], initial_view_state=view,
            tooltip={"html": "<b>{name}</b><br/>Skóre: {score} ({label})<br/>Teplota: {temp}<br/>Snímek: {date}"},
        ),
        height=620,
    )
    st.caption("Barva = poslední bezoblačné skóre. Najetím myši zobrazíte detail.")


# ------------------------------------------------------------------ tabulka
with tab_table:
    t = summary.copy()
    t["hodnocení"] = t["score"].map(lambda s: analysis.rating(None if pd.isna(s) else s).label)
    t = t.sort_values("score", na_position="last")
    st.dataframe(
        t[["name", "score", "hodnocení", "area_ha", "chl", "turb", "temp_c", "obs_date"]],
        hide_index=True, width="stretch", height=min(640, 40 + 35 * len(t)),
        column_config={
            "name": "Vodní plocha",
            "score": st.column_config.ProgressColumn("Index znečištění", min_value=0, max_value=100, format="%.0f"),
            "area_ha": st.column_config.NumberColumn("Rozloha ha", format="%.0f"),
            "chl": st.column_config.NumberColumn("Chlorofyl µg/l", format="%.0f"),
            "turb": st.column_config.NumberColumn("Zákal NTU", format="%.0f"),
            "temp_c": st.column_config.NumberColumn("Teplota °C", format="%.1f"),
            "obs_date": "Poslední snímek",
        },
    )


# ------------------------------------------------------------------ o aplikaci
with tab_about:
    st.markdown(
        """
### Odkud jsou data
* **Seznam vodních ploch** – polygony a názvy z OpenStreetMap (Copernicus pojmenovaný inventář nemá),
  filtrované podle rozlohy.
* **Kvalita vody** – Sentinel-2 L2A (Copernicus Data Space, Statistical API). Pro každou plochu
  a každý den se na serveru vyhodnotí všechny pixely uvnitř plochy (bez 20 m pobřežního pásu).
* **Teplota** – termální pásmo B10 družic Landsat 8/9 (Copernicus Data Space), korekce na emisivitu vody.
  Bez atmosférické korekce, takže je to odhad (typicky o 1–3 °C níž). Jen pro plochy, kam se vejde
  několik pixelů mimo pobřeží.

### Odstranění oblačnosti
Pixel se použije, jen když ho klasifikace Sen2Cor (SCL) neoznačí jako mrak, stín mraku, cirrus nebo sníh,
pravděpodobnost oblaku (CLD) je pod 20 % a modré pásmo nepřesahuje 0,12 (opar). Den se započítá,
jen když je bez mraků aspoň nastavený podíl hladiny. U Landsatu se používá QA pásmo.

### Jak se počítá index 0–100
| složka | z čeho | převod na body |
|---|---|---|
| Chlorofyl-a (řasy, sinice) | NDCI = (B05−B04)/(B05+B04), vzorec Mishra & Mishra 2012 | 10 µg/l → 15, 25 → 40, 50 → 65, 100 → 85, 200 → 100 |
| Zákal (kal) | odrazivost B04/B08, Dogliotti et al. 2015 | 5 NTU → 5, 15 → 30, 35 → 60, 70 → 85, 120 → 100 |
| Povlak sinic na hladině | podíl pixelů vody s NDVI > 0,2 | 5 % → 40, 20 % → 80, 40 % → 100 |

Index = ½ · nejhorší složka + ½ · (0,55 · chlorofyl + 0,30 · zákal + 0,15 · povlak).
Hodnota je **orientační** – družice nevidí bakterie ani toxiny. Oficiální stav koupacích vod
zveřejňují hygienické stanice (koupacivody.cz).
"""
    )
