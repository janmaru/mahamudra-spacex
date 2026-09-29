"""Lanci SpaceX del giorno, visualizzati in terminale tramite rich-ui."""

from spacex_launches.adapter import build_payload
from spacex_launches.fetcher import fetch_launches

__all__ = ["build_payload", "fetch_launches"]
