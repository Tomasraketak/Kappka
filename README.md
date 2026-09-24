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

## Instalace (Windows, příkazový řádek `cmd`)

Potřebujete **Python 3.10 nebo novější** z <https://www.python.org/downloads/>. Při instalaci zaškrtněte
**„Add python.exe to PATH“**.

Otevřete `cmd` (Start → napište `cmd` → Enter), přejděte do složky s aplikací a nainstalujte ji:

```bat
cd C:\cesta\ke\Kappka
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Instalace se dělá jen jednou. `.venv` je izolované prostředí jen pro tuto aplikaci. Když se v řádku
objeví `(.venv)`, je aktivní.

<details>
<summary>Linux / macOS</summary>

```bash
cd ~/cesta/ke/Kappka
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
Další příkazy jsou stejné, jen místo `.venv\Scripts\activate` použijte `source .venv/bin/activate`.
</details>

## Přihlašovací údaje ke Copernicus (zdarma)

Aplikace stahuje snímky z **Copernicus Data Space Ecosystem** (CDSE). Potřebuje k tomu tzv. *OAuth
klienta*, což je dvojice **Client ID** + **Client secret**. Tady je, jak ji získat.

### 1. Registrace účtu

1. Otevřete <https://dataspace.copernicus.eu> a vpravo nahoře klikněte na **Login** → **Register**.
2. Vyplňte formulář a potvrďte registraci odkazem z e-mailu.

### 2. Vytvoření OAuth klienta

1. Otevřete Sentinel Hub dashboard: <https://shapps.dataspace.copernicus.eu/dashboard/>
   a přihlaste se stejným účtem.
2. Vlevo v menu klikněte na **User settings** (ikona uživatele).
3. V sekci **OAuth clients** klikněte na **+ Create**.
4. Zadejte libovolný název (např. `Kappka`). Platnost (*Expiry*) nastavte na **Never**, jinak klient po
   čase přestane fungovat. Pak klikněte na **Create**.
5. Zobrazí se **Client ID** a **Client secret**. **Secret si hned zkopírujte.** Znovu už ho neuvidíte;
   když ho ztratíte, vytvořte nového klienta.

### 3. Vložení údajů do aplikace

Máte dvě možnosti:

**a) V aplikaci (nejjednodušší):** spusťte aplikaci (viz níže). V levém panelu rozbalte
**🔑 Přístup ke Copernicus**, vložte Client ID a Client secret a klikněte na **Uložit a ověřit**.
Aplikace ověří přihlášení a uloží údaje do souboru `.env` ve složce aplikace.

**b) Ručně do souboru `.env`:**

```bat
copy .env.example .env
notepad .env
```

Do souboru doplňte údaje (bez uvozovek a mezer) a uložte ho:

```
CDSE_CLIENT_ID=sh-12345678-abcd-...
CDSE_CLIENT_SECRET=vas-tajny-klic
```

Soubor `.env` je v `.gitignore`, takže se do gitu nedostane. Nikomu ho neposílejte.

Bezplatná kvóta je 10 000 processing units a 50 000 požadavků měsíčně. Na Třeboňsko to bohatě stačí.
Spotřebu uvidíte v dashboardu v sekci **Usage**.

## Spuštění

V `cmd` ve složce aplikace:

```bat
cd C:\cesta\ke\Kappka
.venv\Scripts\activate
streamlit run app.py
```

Aplikace se sama otevře v prohlížeči na <http://localhost:8501>. Běží jen lokálně na vašem počítači.
Ukončíte ji v `cmd` klávesami **Ctrl+C**.

Při prvním spuštění postupujte v levém panelu takto:

1. **🔑 Přístup ke Copernicus**: vložte údaje (viz výše).
2. **1️⃣ Načíst seznam vodních ploch**: stáhne rybníky nad 10 ha v oblasti (asi minuta).
3. **2️⃣ Stáhnout / aktualizovat snímky**: stáhne a vyhodnotí snímky.
4. Hledejte rybník podle názvu na záložce **🔎 Vyhledat**.

První stažení Třeboňska trvá řádově desítky minut, protože stahuje i náhledy všech bezoblačných dnů.
To jde v **⚙️ Nastavení** vypnout; starší snímky se pak dotáhnou až při prohlížení. Stahování lze
přerušit, hotové plochy zůstanou uložené ve složce `data\`.

## Aktualizace dat

Nejjednodušší je kliknout v aplikaci na **2️⃣ Stáhnout / aktualizovat snímky**. Stahují se jen nové
snímky od poslední aktualizace, takže je to rychlé. Jde to i z `cmd` bez otevírání aplikace:

```bat
cd C:\cesta\ke\Kappka
.venv\Scripts\activate

:: znovu načíst seznam vodních ploch (stačí občas, nebo po změně oblasti)
python -m kappka.cli waterbodies

:: stáhnout nové snímky a přepočítat hodnocení všech ploch
python -m kappka.cli update

:: aktualizovat jen vybraný rybník (část názvu, diakritika není nutná)
python -m kappka.cli update --name Rozmberk
```

Automatickou denní aktualizaci nastavíte v **Plánovači úloh** Windows (Task Scheduler). Jako akci zadejte
program `C:\cesta\ke\Kappka\.venv\Scripts\python.exe`, argumenty `-m kappka.cli update` a jako
„Spustit v“ složku `C:\cesta\ke\Kappka`.

## Aktualizace samotné aplikace

Když stáhnete novou verzi kódu (např. `git pull`), aktualizujte i závislosti:

```bat
cd C:\cesta\ke\Kappka
.venv\Scripts\activate
git pull
pip install -r requirements.txt --upgrade
```

Stažená data ve složce `data\` i přihlašovací údaje v `.env` zůstanou zachované.

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
