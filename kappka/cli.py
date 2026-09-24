"""Příkazová řádka – vhodné např. pro pravidelnou aktualizaci přes cron.

    python -m kappka.cli waterbodies     # načte seznam vodních ploch
    python -m kappka.cli update          # stáhne/aktualizuje analýzy a snímky
"""
from __future__ import annotations

import argparse
import sys
import unicodedata

from . import config, pipeline, storage
from .cdse import CDSEClient


def _normalize(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _progress(p: float, msg: str) -> None:
    print(f"[{p * 100:5.1f} %] {msg}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kappka")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("waterbodies", help="Načte seznam vodních ploch v nastavené oblasti")
    up = sub.add_parser("update", help="Stáhne a analyzuje snímky")
    up.add_argument("--name", help="Jen vodní plochy, jejichž název obsahuje tento text")
    args = parser.parse_args(argv)

    config.ensure_dirs()
    settings = config.Settings.load()
    store = storage.Storage()

    if args.cmd == "waterbodies":
        n = pipeline.update_waterbodies(settings, store, _progress)
        print(f"Uloženo {n} vodních ploch.")
        return 0

    creds = config.Credentials.load()
    if not creds.ok:
        print("Chybí CDSE_CLIENT_ID / CDSE_CLIENT_SECRET v .env", file=sys.stderr)
        return 1
    ids = None
    if args.name:
        wbs = store.waterbodies()
        q = _normalize(args.name)
        ids = wbs[wbs["name"].map(lambda n: q in _normalize(n))]["id"].tolist()
        if not ids:
            print(f"Žádná vodní plocha neodpovídá „{args.name}“.", file=sys.stderr)
            return 1
    res = pipeline.update_analysis(settings, store, CDSEClient(creds.client_id, creds.client_secret), ids, _progress)
    print(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
