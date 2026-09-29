"""Scarica i lanci SpaceX di un giorno da Launch Library 2 e li mette in cache.

Launch Library 2 (The Space Devs) limita le chiamate anonime a poche decine
l'ora: la cache su disco evita di consumare il budget a ogni esecuzione.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

LL2_LAUNCHES_URL = "https://ll.thespacedevs.com/2.3.0/launches/"
SOURCE_NAME = "launch-library-2"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
REQUEST_TIMEOUT_SECONDS = 30
REFRESH_INTERVAL_SECONDS = 600
PAGE_SIZE = 20
MAX_PAGES = 10


class FetchError(RuntimeError):
    """Errore di rete o cache assente/corrotta in modalità offline."""


@dataclass(frozen=True)
class FetchResult:
    raw: dict[str, Any]
    fetched_at: datetime
    from_cache: bool
    cache_path: Path
    warning: str | None = None


@dataclass(frozen=True)
class _Envelope:
    raw: dict[str, Any]
    fetched_at: datetime


def cache_path_for(day: date, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    return cache_dir / f"{day.isoformat()}.json"


def fetch_launches(
    day: date,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    offline: bool = False,
    refresh: bool = False,
    now: datetime | None = None,
) -> FetchResult:
    """Restituisce la risposta grezza di LL2 per i lanci SpaceX del giorno.

    - ``offline``: usa solo la cache, senza rete.
    - ``refresh``: ignora la cache e scarica di nuovo.

    La cache dei giorni recenti scade dopo ``REFRESH_INTERVAL_SECONDS``; quella
    dei giorni passati resta valida per sempre. Se il download fallisce e una
    cache esiste, viene usata quella con un avviso.
    """
    current = now or datetime.now(timezone.utc)
    path = cache_path_for(day, cache_dir)
    cached, cache_error = _load_cache(path)

    if offline:
        if cached is None:
            reason = cache_error or f"no cache for {day.isoformat()}"
            raise FetchError(f"Offline mode: {reason} ({path})")
        return FetchResult(raw=cached.raw, fetched_at=cached.fetched_at, from_cache=True, cache_path=path)

    if cached is not None and not refresh and not _is_stale(cached, day, current):
        return FetchResult(raw=cached.raw, fetched_at=cached.fetched_at, from_cache=True, cache_path=path)

    try:
        raw = _download(day)
    except FetchError as exc:
        if cached is None:
            raise
        return FetchResult(
            raw=cached.raw,
            fetched_at=cached.fetched_at,
            from_cache=True,
            cache_path=path,
            warning=f"download failed, using the cache from {cached.fetched_at:%Y-%m-%d %H:%M:%S %Z}: {exc}",
        )

    _write_cache(path, raw, current)
    return FetchResult(raw=raw, fetched_at=current, from_cache=False, cache_path=path)


def _is_stale(cached: _Envelope, day: date, now: datetime) -> bool:
    """La cache scade solo per il giorno corrente, quello precedente e le date future."""
    if day < (now - timedelta(days=1)).date():
        return False
    return (now - cached.fetched_at).total_seconds() > REFRESH_INTERVAL_SECONDS


def _load_cache(path: Path) -> tuple[_Envelope | None, str | None]:
    """Legge la cache in modo difensivo: restituisce (envelope, errore)."""
    if not path.exists():
        return None, None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        raw = envelope["raw"]
        fetched_at = datetime.fromisoformat(envelope["fetched_at"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, f"corrupted cache: {exc}"
    if not isinstance(raw, dict) or not isinstance(raw.get("results"), list):
        return None, "corrupted cache: missing 'results' list"
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return _Envelope(raw=raw, fetched_at=fetched_at), None


def _write_cache(path: Path, raw: dict[str, Any], fetched_at: datetime) -> None:
    """Scrive su file temporaneo e poi rinomina, così un'interruzione non lascia file troncati."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"fetched_at": fetched_at.isoformat(), "raw": raw}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    tmp.replace(path)


def _download(day: date) -> dict[str, Any]:
    """Scarica tutte le pagine del giorno e le fonde in un'unica risposta."""
    params: dict[str, Any] = {
        "lsp__name": "SpaceX",
        "net__gte": f"{day.isoformat()}T00:00:00Z",
        "net__lte": f"{day.isoformat()}T23:59:59Z",
        "limit": PAGE_SIZE,
        "mode": "detailed",
        "ordering": "net",
    }
    merged: dict[str, Any] | None = None
    url: str | None = LL2_LAUNCHES_URL
    pages = 0
    while url and pages < MAX_PAGES:
        page = _get_json(url, params if pages == 0 else None)
        pages += 1
        if merged is None:
            merged = page
        else:
            merged["results"].extend(page["results"])
        url = page.get("next") if isinstance(page.get("next"), str) else None
    assert merged is not None
    merged["next"] = None
    merged["previous"] = None
    return merged


def _get_json(url: str, params: dict[str, Any] | None) -> dict[str, Any]:
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise FetchError(f"Launch Library 2 request failed: {exc}") from exc
    except ValueError as exc:
        raise FetchError(f"LL2 response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise FetchError("Unexpected LL2 response: missing 'results' list")
    return payload
