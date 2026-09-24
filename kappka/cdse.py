"""Klient pro Copernicus Data Space Ecosystem (Sentinel Hub API)."""
from __future__ import annotations

import time
from typing import Any

import requests

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SH_BASE = "https://sh.dataspace.copernicus.eu"
PROCESS_URL = f"{SH_BASE}/api/v1/process"
STATISTICS_URL = f"{SH_BASE}/api/v1/statistics"

CRS_UTM33 = "http://www.opengis.net/def/crs/EPSG/0/32633"
CRS_WGS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"


class CDSEError(RuntimeError):
    pass


class CDSEClient:
    def __init__(self, client_id: str, client_secret: str, timeout: int = 120):
        if not client_id or not client_secret:
            raise CDSEError("Chybí přihlašovací údaje k Copernicus Data Space (OAuth client ID a secret).")
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self.session = requests.Session()
        self._token: str | None = None
        self._token_expires = 0.0

    # ------------------------------------------------------------------ auth
    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise CDSEError(f"Přihlášení ke Copernicus selhalo ({resp.status_code}): {resp.text[:300]}")
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires = time.time() + float(payload.get("expires_in", 600))
        return self._token

    def test_connection(self) -> None:
        self._get_token()

    # ------------------------------------------------------------- requests
    def _post(self, url: str, body: dict[str, Any], accept: str) -> requests.Response:
        """POST s obnovou tokenu a opakováním při rate-limitu / chybách serveru."""
        delay = 2.0
        last_error = ""
        for _attempt in range(6):
            headers = {"Authorization": f"Bearer {self._get_token()}", "Accept": accept}
            try:
                resp = self.session.post(url, json=body, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = str(exc)
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code == 200:
                return resp
            if resp.status_code == 401:
                self._token = None
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) / 1000 if retry_after and retry_after.isdigit() else delay
                time.sleep(min(max(wait, 1.0), 60.0))
                delay *= 2
                last_error = f"{resp.status_code}: {resp.text[:300]}"
                continue
            raise CDSEError(f"Chyba API ({resp.status_code}): {resp.text[:500]}")
        raise CDSEError(f"API opakovaně selhalo: {last_error}")

    def statistics(
        self,
        geometry_utm: dict,
        collection: str,
        evalscript: str,
        time_from: str,
        time_to: str,
        resolution: float,
        data_filter: dict | None = None,
        percentiles: list[int] | None = None,
    ) -> list[dict]:
        """Statistical API – denní statistiky pixelů uvnitř polygonu (EPSG:32633)."""
        body = {
            "input": {
                "bounds": {"geometry": geometry_utm, "properties": {"crs": CRS_UTM33}},
                "data": [{"type": collection, "dataFilter": data_filter or {}}],
            },
            "aggregation": {
                "timeRange": {"from": time_from, "to": time_to},
                "aggregationInterval": {"of": "P1D"},
                "evalscript": evalscript,
                "resx": resolution,
                "resy": resolution,
            },
            "calculations": {
                "default": {"statistics": {"default": {"percentiles": {"k": percentiles or [10, 50, 90]}}}}
            },
        }
        data = self._post(STATISTICS_URL, body, "application/json").json()
        return data.get("data", [])

    def process_png(
        self,
        bbox_utm: tuple[float, float, float, float],
        collection: str,
        evalscript: str,
        date: str,
        width: int,
        height: int,
        geometry_utm: dict | None = None,
    ) -> bytes:
        """Process API – vykreslí PNG pro daný den (YYYY-MM-DD)."""
        bounds: dict[str, Any] = {"bbox": list(bbox_utm), "properties": {"crs": CRS_UTM33}}
        if geometry_utm is not None:
            bounds["geometry"] = geometry_utm
        body = {
            "input": {
                "bounds": bounds,
                "data": [
                    {
                        "type": collection,
                        "dataFilter": {
                            "timeRange": {"from": f"{date}T00:00:00Z", "to": f"{date}T23:59:59Z"},
                            "mosaickingOrder": "leastCC",
                        },
                    }
                ],
            },
            "output": {
                "width": width,
                "height": height,
                "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
            },
            "evalscript": evalscript,
        }
        return self._post(PROCESS_URL, body, "image/png").content
