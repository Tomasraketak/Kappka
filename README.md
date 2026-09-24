# 💧 Kappka – kvalita vody pro koupání ze satelitů Copernicus

Lokální aplikace (Python + Streamlit), která:

1. sestaví seznam vodních ploch nad 10 ha ve zvolené oblasti (zatím **Třeboňsko**),
2. pro každou plochu stáhne a vyhodnotí **všechny snímky Sentinel-2** za posledních *N* měsíců
   (výchozí 4, nastavitelné) a **odfiltruje oblačnost**,
3. spočítá orientační **index znečištění 0–100** (sinice/řasy, kal, povlak na hladině),
4. odhadne **teplotu hladiny** z termálního pásma Landsat 8/9 (u dost velkých ploch),
5. vše uloží lokálně (`data/`), takže se příště stahují jen nové snímky,
6. v GUI umožní vyhledat plochu podle názvu (i bez diakritiky) a ukáže hodnocení,
   nejčerstvější satelitní snímek, mapu znečištění a vývoj v čase. K tomu je tu mapa a žebříček všech ploch.

## Instalace

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Přístup ke Copernicus (zdarma)

1. Zaregistrujte se na <https://dataspace.copernicus.eu>.
2. Otevřete <https://shapps.dataspace.copernicus.eu/dashboard/> → **User settings** → **OAuth clients** → *Create*.
3. Client ID a secret vložte v aplikaci (levý panel → *Přístup ke Copernicus*), nebo zkopírujte
   `.env.example` do `.env` a vyplňte.

Bezplatná kvóta je 10 000 processing units a 50 000 požadavků měsíčně. Na Třeboňsko to bohatě stačí.

## Spuštění

```bash
streamlit run app.py
```

Aplikace se otevře v prohlížeči (běží jen lokálně na vašem počítači). Postup:
**1️⃣ Načíst seznam vodních ploch** → **2️⃣ Stáhnout / aktualizovat snímky** → vyhledávat.

První stažení Třeboňska trvá řádově desítky minut, protože stahuje i náhledy všech bezoblačných dnů.
To jde v nastavení vypnout; starší snímky se pak dotáhnou až při prohlížení. Stahování lze přerušit,
hotové plochy zůstanou uložené.

Pravidelná aktualizace z příkazové řádky (např. cron):

```bash
python -m kappka.cli waterbodies   # seznam ploch
python -m kappka.cli update        # analýzy + snímky (jen chybějící data)
python -m kappka.cli update --name Rožmberk
```

## Jak to funguje

| Krok | Zdroj | Poznámka |
|---|---|---|
| Seznam vodních ploch | OpenStreetMap (Overpass API) | Copernicus pojmenovaný inventář vodních ploch nemá. Filtr podle rozlohy, bez řek a kanálů. |
| Kvalita vody | Copernicus Data Space – Sentinel-2 L2A, **Statistical API** | Evalscript běží na serveru nad každým pixelem, z polygonu se odřízne 20m pobřežní pás. |
| Maska oblačnosti | SCL (Sen2Cor) + CLD + test na opar | Den se použije jen, když je bez mraků ≥ 70 % hladiny (nastavitelné). |
| Teplota | Copernicus Data Space – Landsat 8/9 L1, pásmo B10 | Korekce emisivity vody, bez atmosférické korekce, tedy odhad ±2 °C. |
| Náhledy | Process API | Přirozené barvy + barevná mapa znečištění po pixelech. |

**Index 0–100** (0 = čistá, 100 = nevhodná ke koupání) kombinuje:

* chlorofyl-a z NDCI (Mishra & Mishra 2012): řasy a sinice ve vodním sloupci,
* zákal v NTU (Dogliotti et al. 2015): kal a snížená průhlednost,
* podíl hladiny s plovoucím povlakem (NDVI > 0,2), tedy vodní květ.

Index = ½ · nejhorší složka + ½ · vážený průměr (0,55 / 0,30 / 0,15). Prahy jsou v `kappka/analysis.py`.
Hodnota je **orientační**: družice nevidí bakterie ani toxiny. Oficiální stav koupacích vod zveřejňují
krajské hygienické stanice.

## Struktura

```
app.py                  GUI (Streamlit)
kappka/config.py        nastavení, oblasti, přihlašovací údaje
kappka/waterbodies.py   seznam vodních ploch (OSM)
kappka/cdse.py          klient Copernicus Data Space (OAuth, Statistical + Process API)
kappka/evalscripts.py   evalscripty – maska mraků, chlorofyl, zákal, teplota, vizualizace
kappka/analysis.py      výpočet skóre
kappka/pipeline.py      stahování, inkrementální cache, náhledy
kappka/storage.py       SQLite cache
tests/                  testy (pytest)
```

Změna oblasti: v nastavení zvolte *Celá ČR* nebo *Vlastní* bbox a znovu načtěte seznam vodních ploch.
