"""Nastavení aplikace – ukládá se do data/settings.json, přihlašovací údaje do .env."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import load_dotenv, set_key

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("KAPPKA_DATA_DIR", ROOT_DIR / "data"))
ENV_FILE = ROOT_DIR / ".env"
SETTINGS_FILE = DATA_DIR / "settings.json"
DB_FILE = DATA_DIR / "kappka.sqlite"
IMAGES_DIR = DATA_DIR / "images"

# Předdefinované oblasti: (min_lon, min_lat, max_lon, max_lat) ve WGS84
REGIONS: dict[str, tuple[float, float, float, float]] = {
    "Třeboňsko": (14.55, 48.82, 15.02, 49.25),
    "Celá ČR": (12.09, 48.55, 18.87, 51.06),
}


@dataclass
class Settings:
    region: str = "Třeboňsko"
    # Vlastní bbox, použije se když region == "Vlastní"
    custom_bbox: tuple[float, float, float, float] = (14.55, 48.82, 15.02, 49.25)
    min_area_ha: float = 10.0
    # Kolik měsíců zpět se stahují a analyzují snímky
    months_back: int = 4
    # Maximální oblačnost celé scény Sentinel-2 (filtr metadat), %
    max_scene_cloud: int = 80
    # Minimální podíl bezoblačných pixelů nad vodní plochou, aby se snímek počítal
    min_clear_fraction: float = 0.7
    # Stahovat náhledy (RGB + mapa znečištění) pro všechny bezoblačné snímky,
    # jinak jen pro nejnovější (ostatní se dotáhnou na vyžádání v GUI)
    download_all_images: bool = True
    # Zjišťovat teplotu hladiny z termálního pásma Landsat 8/9
    fetch_temperature: bool = True

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        if self.region in REGIONS:
            return REGIONS[self.region]
        return tuple(self.custom_bbox)  # type: ignore[return-value]

    @classmethod
    def load(cls) -> "Settings":
        if SETTINGS_FILE.exists():
            try:
                raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
                if "custom_bbox" in known:
                    known["custom_bbox"] = tuple(known["custom_bbox"])
                return cls(**known)
            except (ValueError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class Credentials:
    client_id: str = ""
    client_secret: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @classmethod
    def load(cls) -> "Credentials":
        load_dotenv(ENV_FILE, override=True)
        return cls(
            client_id=os.environ.get("CDSE_CLIENT_ID", "").strip(),
            client_secret=os.environ.get("CDSE_CLIENT_SECRET", "").strip(),
        )

    def save(self) -> None:
        ENV_FILE.touch(exist_ok=True)
        set_key(str(ENV_FILE), "CDSE_CLIENT_ID", self.client_id)
        set_key(str(ENV_FILE), "CDSE_CLIENT_SECRET", self.client_secret)
        os.environ["CDSE_CLIENT_ID"] = self.client_id
        os.environ["CDSE_CLIENT_SECRET"] = self.client_secret


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

