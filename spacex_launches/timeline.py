"""Timeline della missione: dagli eventi ``timeline`` di Launch Library 2 alle
fasi del pannello ``Phases`` di rich-ui e del viewer nativo (``viewer.py``).

Ogni fase appartiene a una corsia: countdown (prima di T-0), ship (dopo T-0) o
booster (eventi del primo stadio dopo T-0).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

COUNTDOWN, SHIP, BOOSTER = "countdown", "ship", "booster"

_BOOSTER_KEYWORDS = ("booster", "boostback", "stage 1", "meco")

# ISO 8601 duration così come la usa LL2: "-PT50M", "P0D", "PT1H4M50S".
# Il lookahead dopo ``P`` rifiuta le forme vuote ("P", "PT", "-P").
_DURATION_RE = re.compile(
    r"(?P<sign>-)?P(?=\d|T\d)(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?"
)


@dataclass(frozen=True)
class Phase:
    seconds: float  # relativi a T-0, negativi nel countdown
    name: str
    booster: bool

    @property
    def label(self) -> str:
        return format_offset(self.seconds)

    @property
    def lane(self) -> str:
        if self.booster:
            return BOOSTER
        return COUNTDOWN if self.seconds < 0 else SHIP


def parse_duration(value: Any) -> float | None:
    """Converte una durata ISO 8601 di LL2 in secondi con segno. ``None`` se malformata."""
    if not isinstance(value, str):
        return None
    match = _DURATION_RE.fullmatch(value.strip())
    if not match:
        return None
    parts = match.groupdict()
    total = (
        float(parts["days"] or 0) * 86400
        + float(parts["hours"] or 0) * 3600
        + float(parts["minutes"] or 0) * 60
        + float(parts["seconds"] or 0)
    )
    if not math.isfinite(total):
        return None
    return -total if parts["sign"] else total


def format_offset(seconds: float) -> str:
    """``T-00:50:00`` / ``T+09:50:30``."""
    sign = "-" if seconds < 0 else "+"
    total = int(round(abs(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"T{sign}{hours:02d}:{minutes:02d}:{secs:02d}"


def extract_phases(launch: dict[str, Any]) -> list[Phase]:
    """Le fasi dal campo ``timeline`` di LL2, ordinate nel tempo.

    Se LL2 non fornisce la timeline (succede per molti lanci futuri), ripiega su
    tre fasi minime ricavate da ``window_start``, ``net`` e ``window_end``.
    """
    phases: list[Phase] = []
    timeline = launch.get("timeline")
    for entry in timeline if isinstance(timeline, list) else []:
        if not isinstance(entry, dict):
            continue
        seconds = parse_duration(entry.get("relative_time"))
        kind = entry.get("type") if isinstance(entry.get("type"), dict) else {}
        abbrev = kind.get("abbrev")
        name = abbrev.strip() if isinstance(abbrev, str) else ""
        if seconds is None or not name:
            continue
        lowered = name.lower()
        booster = seconds >= 0 and any(word in lowered for word in _BOOSTER_KEYWORDS)
        phases.append(Phase(seconds, name, booster))
    if phases:
        return sorted(phases, key=lambda phase: phase.seconds)
    return _window_phases(launch)


def _window_phases(launch: dict[str, Any]) -> list[Phase]:
    net = _parse_instant(launch.get("net"))
    if net is None:
        return []
    phases = [Phase(0.0, "Liftoff (NET)", False)]
    for key, name in (("window_start", "Window open"), ("window_end", "Window close")):
        instant = _parse_instant(launch.get(key))
        if instant is not None and instant != net:
            phases.append(Phase((instant - net).total_seconds(), name, False))
    return sorted(phases, key=lambda phase: phase.seconds)


def _parse_instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def phase_items(launch_name: str, phases: list[Phase]) -> list[Any]:
    """Righe per il pannello ``Phases``: ``T±hh:mm:ss  evento``."""
    if not phases:
        return [{"text": "No phases available", "style": "dim"}]
    items: list[Any] = [{"text": launch_name, "style": "bold"}]
    for phase in phases:
        style = {BOOSTER: "magenta", COUNTDOWN: "dim"}.get(phase.lane, "cyan")
        items.append({"segments": [
            {"text": phase.label, "style": style},
            {"text": "  "},
            {"text": phase.name},
        ]})
    return items
