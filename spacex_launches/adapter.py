"""Trasforma la risposta grezza di Launch Library 2 nei payload di rich-ui.

Restituisce ``(data, sync)``: i dati sono legati ai ``bind`` della spec
(``specs/spacex.json``, che non contiene valori), il sync porta solo la
freschezza per ogni ``bind``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from spacex_launches.fetcher import REFRESH_INTERVAL_SECONDS, SOURCE_NAME
from spacex_launches.timeline import Phase, extract_phases, phase_items

DESCRIPTION_MAX_CHARS = 280
NO_TIME = "--:--:--"

_STATUS_STYLES = {
    "Go": "bold green",
    "Success": "bold green",
    "TBC": "yellow",
    "TBD": "yellow",
    "In Flight": "bold cyan",
    "Hold": "yellow",
    "Failure": "bold red",
    "Partial Failure": "red",
}


def build_payload(
    raw: dict[str, Any],
    day: date,
    fetched_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    launches = _launches(raw)

    data: dict[str, Any] = {
        "mission": _mission_items(launches, day),
        "launches": _launch_records(launches, day),
        "details": _detail_items(launches, day),
        "phases": _phase_items(launches),
        "links": _link_items(launches),
        "update": _update_items(fetched_at, raw, launches),
    }

    freshness = {
        "source": SOURCE_NAME,
        "updated_at": fetched_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "interval_seconds": REFRESH_INTERVAL_SECONDS,
    }
    sync = {bind: dict(freshness) for bind in data}
    return data, sync


def frame_title(day: date) -> str:
    return f"SpaceX Launches - {day.isoformat()} (UTC)"


def first_launch_phases(raw: dict[str, Any]) -> tuple[str, list[Phase]] | None:
    """Nome e fasi del primo lancio del giorno, per il viewer nativo. ``None`` se non ci sono lanci."""
    launches = _launches(raw)
    if not launches:
        return None
    return _str(launches[0].get("name")), extract_phases(launches[0])


def _launches(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return [launch for launch in (raw.get("results") or []) if isinstance(launch, dict)]


def _mission_items(launches: list[dict[str, Any]], day: date) -> list[Any]:
    if not launches:
        return [{"text": f"No SpaceX launches on {day.isoformat()} (UTC)", "style": "yellow"}]
    items: list[Any] = [
        {"segments": [
            {"text": f"{len(launches)} SpaceX launch{'' if len(launches) == 1 else 'es'} on {day.isoformat()} (UTC)", "style": "bold"},
        ]}
    ]
    for launch in launches:
        items.append({"segments": [
            {"text": _fmt_time(launch.get("net"), day), "style": "cyan"},
            {"text": "  "},
            {"text": _str(launch.get("name")), "style": "bold white"},
            {"text": "  "},
            {"text": _status_name(launch), "style": _STATUS_STYLES.get(_status_abbrev(launch), "white")},
        ]})
    return items


def _launch_records(launches: list[dict[str, Any]], day: date) -> list[dict[str, str]]:
    if not launches:
        return [{"T-0 (UTC)": "--", "Name": "No launches", "Rocket": "--", "Pad": "--", "Status": "--"}]
    records = []
    for launch in launches:
        rocket = _dict(_dict(launch.get("rocket")).get("configuration"))
        pad = _dict(launch.get("pad"))
        location = _dict(pad.get("location"))
        records.append({
            "T-0 (UTC)": _fmt_time(launch.get("net"), day),
            "Name": _str(launch.get("name")),
            "Rocket": _str(rocket.get("full_name"), _str(rocket.get("name"))),
            "Pad": f"{_str(pad.get('name'))} - {_str(location.get('name'))}",
            "Status": _status_name(launch),
        })
    return records


def _detail_items(launches: list[dict[str, Any]], day: date) -> list[Any]:
    items: list[Any] = []
    for index, launch in enumerate(launches):
        if index:
            items.append("")
        mission = _dict(launch.get("mission"))
        orbit = _str(_dict(mission.get("orbit")).get("name"), "")
        window = f"{_fmt_time(launch.get('window_start'), day)} - {_fmt_time(launch.get('window_end'), day)}"
        items.append({"text": _str(launch.get("name")), "style": "bold"})
        items.append({"segments": [{"text": "Window: ", "style": "dim"}, {"text": window}]})
        if orbit:
            items.append({"segments": [{"text": "Orbit: ", "style": "dim"}, {"text": orbit}]})
        probability = launch.get("probability")
        if isinstance(probability, (int, float)) and not isinstance(probability, bool):
            items.append({"segments": [
                {"text": "Weather go: ", "style": "dim"},
                {"text": f"{probability}%"},
            ]})
        description = _str(mission.get("description"), "").strip()
        if description:
            items.append(_truncate(description, DESCRIPTION_MAX_CHARS))
    return items or [{"text": "No details available", "style": "dim"}]


def _phase_items(launches: list[dict[str, Any]]) -> list[Any]:
    """Fasi del primo lancio del giorno (una sola missione nel pannello)."""
    if not launches:
        return phase_items("No launches", [])
    launch = launches[0]
    return phase_items(_str(launch.get("name")), extract_phases(launch))


def _link_items(launches: list[dict[str, Any]]) -> list[Any]:
    items: list[Any] = []
    for launch in launches:
        videos = launch.get("vid_urls")
        for video in videos if isinstance(videos, list) else []:
            video = _dict(video)
            url = _str(video.get("url"), "")
            if not url:
                continue
            publisher = _str(video.get("publisher"), _str(video.get("source"), "webcast"))
            items.append({"segments": [
                {"text": f"{publisher}: ", "style": "dim"},
                {"text": url, "style": "underline blue"},
            ]})
        api_url = _str(launch.get("url"), "")
        if api_url:
            items.append({"segments": [
                {"text": "LL2 API: ", "style": "dim"},
                {"text": api_url, "style": "dim"},
            ]})
    return items or [{"text": "No links available", "style": "dim"}]


def _update_items(fetched_at: datetime, raw: dict[str, Any], launches: list[dict[str, Any]]) -> list[Any]:
    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    count = raw.get("count")
    results = str(len(launches)) if count is None else f"{len(launches)}/{count}"
    return [
        {"segments": [{"text": "Fetched: ", "style": "dim"}, {"text": stamp}]},
        {"segments": [{"text": "Source: ", "style": "dim"}, {"text": SOURCE_NAME}]},
        {"segments": [{"text": "Results: ", "style": "dim"}, {"text": results}]},
    ]


def _status_name(launch: dict[str, Any]) -> str:
    return _str(_dict(launch.get("status")).get("name"), "Unknown")


def _status_abbrev(launch: dict[str, Any]) -> str:
    return _str(_dict(launch.get("status")).get("abbrev"), "")


def _fmt_time(value: Any, day: date) -> str:
    """Ora UTC ``HH:MM:SS``; se cade in un giorno diverso da ``day`` aggiunge ``mm-gg``."""
    if not isinstance(value, str) or not value:
        return NO_TIME
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    if parsed.date() != day:
        return parsed.strftime("%m-%d %H:%M:%S")
    return parsed.strftime("%H:%M:%S")


def _str(value: Any, default: str = "?") -> str:
    """Restituisce ``value`` solo se è una stringa non vuota, altrimenti ``default``."""
    return value if isinstance(value, str) and value else default


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
