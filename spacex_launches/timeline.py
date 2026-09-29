"""Timeline della missione: dagli eventi ``timeline`` di Launch Library 2 ai dati
per lo ``scatter_2d`` e per il pannello ``Phases`` di rich-ui.

Nel terminale le fasi stanno su due corsie orizzontali: sopra countdown (a
sinistra di T-0) e ship (a destra), sotto il booster. La riga centrale resta
libera per il marker di T-0: un punto a pochi secondi da T-0 cadrebbe sotto la
soglia del renderer e collasserebbe sul centro. L'asse orizzontale è il tempo in scala logaritmica
simmetrica attorno a T-0, perché le fasi di ascesa (minuti) devono restare
leggibili accanto a rientro e atterraggio (ore).

Lo scatter di rich-ui è radiale: ogni punto viene portato a ``(d/L) ** 0.55``
lungo il suo angolo, con ``L`` pari a 1.15 volte la distanza massima. Le
coordinate vengono quindi pre-distorte con la trasformazione inversa, così le
corsie escono dritte sulla griglia. Il viewer nativo (``viewer.py``) usa invece
un asse del tempo lineare, con zoom.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# Secondi di riferimento della scala log: sotto questo valore la scala è quasi
# lineare, sopra si comprime con log1p.
LOG_SCALE_SECONDS = 10.0

# Posizioni normalizzate sulla griglia (1.0 = bordo). Il rettangolo deve stare
# nel cerchio di raggio GRID_MAX_RADIUS, oltre il quale il renderer satura.
GRID_HALF_WIDTH = 0.85
LANE_OFFSET = 0.35
# Esponente e margine del renderer scatter_2d di rich-ui (renderer.py).
_RENDERER_EXPONENT = 0.55
_RENDERER_MARGIN = 1.15
GRID_MAX_RADIUS = _RENDERER_MARGIN ** -_RENDERER_EXPONENT
# Distanza del punto più lontano, in unità display arbitrarie. Sotto 1 il
# renderer collassa il punto al centro: serve un valore grande.
DISPLAY_MAX_DISTANCE = 100.0

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


def _log_offset(seconds: float, span: float) -> float:
    """Tempo in scala log simmetrica, normalizzato in [-1, 1] su ``span`` secondi."""
    if not seconds or span <= 0:
        return 0.0
    return math.copysign(math.log1p(abs(seconds) / LOG_SCALE_SECONDS), seconds) / math.log1p(
        span / LOG_SCALE_SECONDS
    )


def _grid_point(gx: float, gy: float) -> dict[str, float]:
    """Posizione normalizzata sulla griglia → coordinate da passare al renderer.

    Inverte la compressione radiale di rich-ui: il renderer mette il punto a
    ``(d / L) ** 0.55`` del raggio, con ``L = 1.15 * d_max``. Chiedendo raggio
    ``r`` serve ``d = L * r ** (1 / 0.55)``; il punto più lontano ha
    ``r = GRID_MAX_RADIUS`` e quindi ``d_max = L / 1.15``.
    """
    radius = math.hypot(gx, gy)
    if radius == 0:
        return {"x": 0.0, "y": 0.0, "z": 0.0}
    scale = DISPLAY_MAX_DISTANCE * _RENDERER_MARGIN
    distance = scale * (min(radius, GRID_MAX_RADIUS) ** (1 / _RENDERER_EXPONENT))
    return {"x": distance * gx / radius, "y": distance * gy / radius, "z": 0.0}


_LANE_Y = {SHIP: LANE_OFFSET, COUNTDOWN: LANE_OFFSET, BOOSTER: -LANE_OFFSET}


def _lane_points(phases: list[Phase], span: float) -> list[dict[str, float]]:
    return [_grid_point(GRID_HALF_WIDTH * _log_offset(p.seconds, span), _LANE_Y[p.lane]) for p in phases]


def timeline_payload(launch_name: str, phases: list[Phase]) -> dict[str, Any]:
    """Dati per il bind ``timeline`` dello ``scatter_2d``."""
    span = max((abs(phase.seconds) for phase in phases), default=0.0)
    lanes = (
        (SHIP, "Ship", "◆", "bold cyan", "cyan"),
        (COUNTDOWN, "Countdown", "■", "bold white", "bright_black"),
        (BOOSTER, "Booster", "●", "bold magenta", "magenta"),
    )
    tracks: list[dict[str, Any]] = []
    points: list[dict[str, float]] = []
    for lane, label, marker, style, history_style in lanes:
        selected = [phase for phase in phases if phase.lane == lane]
        if not selected:
            continue
        lane_points = _lane_points(selected, span)
        points.extend(lane_points)
        tracks.append(_track(label, marker, style, history_style, selected, lane_points))
    if not tracks:
        tracks.append({"label": "No phases available", "marker": "?", "style": "dim",
                       "current": {"x": 0.0, "y": 0.0, "z": 0.0}})
    return {
        "center": {
            "label": "T-0",
            "caption": f"{launch_name} | log time scale",
            "marker": "▲",
            "style": "bold yellow",
        },
        "tracks": tracks,
    }


def _track(
    label: str,
    marker: str,
    style: str,
    history_style: str,
    phases: list[Phase],
    points: list[dict[str, float]],
) -> dict[str, Any]:
    return {
        "label": label,
        "caption": f"{len(phases)} phase{'' if len(phases) == 1 else 's'}, {phases[0].label} → {phases[-1].label}",
        "marker": marker,
        "style": style,
        "history_marker": marker,
        "history_style": history_style,
        "samples": points[:-1],
        "current": points[-1],
    }


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
