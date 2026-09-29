"""CLI: mostra i lanci SpaceX di un giorno usando rich-ui per la visualizzazione.

Flusso: fetch/cache di Launch Library 2 → adapter verso i payload DSL → render
della spec ``specs/spacex.json`` → ascolto dei tasti delle action (T = viewer
nativo della timeline, Q = esci).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from rich.console import Console

try:
    from rich_ui import Theme, ViewMode, find_data_issues, parse_spec, render
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "rich_ui not found. Run .\\setup.ps1 or pip install -r requirements.txt.\n"
    )
    raise

from spacex_launches.adapter import build_payload, first_launch_phases, frame_title
from spacex_launches.fetcher import DEFAULT_CACHE_DIR, FetchError, fetch_launches

SPECS_DIR = Path(__file__).resolve().parent / "specs"
SPEC_FILE = SPECS_DIR / "spacex.json"
DATA_FILE = SPECS_DIR / "spacex.data.json"
SYNC_FILE = SPECS_DIR / "spacex.sync.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SpaceX launches of the day, rendered with rich-ui.")
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(timezone.utc).date(),
                        help="UTC day in YYYY-MM-DD format (default: today).")
    parser.add_argument("--view", choices=[mode.value for mode in ViewMode], default=ViewMode.DASHBOARD.value,
                        help="Rendering mode (default: dashboard).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Use the cache only, no network.")
    mode.add_argument("--refresh", action="store_true", help="Ignore the cache and download again.")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--dump-mocks", type=Path, metavar="DIR",
                        help="Write spec/data/sync into DIR as spacex.json, spacex.data.json, spacex.sync.json.")
    parser.add_argument("--open-timeline", action="store_true",
                        help="Open the native mission timeline viewer immediately and exit, without "
                             "waiting for the T key (useful for scripts/pipes).")
    return parser.parse_args(argv)


def _force_utf8_output() -> None:
    """Su Windows la console usa spesso cp1252 e non gestisce i caratteri
    Unicode dei bordi e dei separatori (─ │ ┌). Forziamo UTF-8 dove possibile."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def _load_spec(day: date) -> dict:
    spec = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    spec["title"] = frame_title(day)
    return spec


def _read_action_key() -> str:
    """Legge un singolo tasto (framework keyboard-action della libreria).

    Su Windows usa msvcrt.getwch (nessun invio richiesto); altrove ripiega su
    input(). Invio/newline valgono come "nessun tasto" → uscita dal loop.
    """
    if os.name == "nt":
        import msvcrt

        key = msvcrt.getwch()
        if key in {"\r", "\n"}:
            return ""
        # Tasti speciali (frecce, F1-F12, PagGiù): prefisso seguito dallo scan
        # code, che altrimenti verrebbe letto come lettera (PagGiù → "Q").
        if key in {"\x00", "\xe0"}:
            msvcrt.getwch()
            return "\x00"
        return key.upper()
    return input().strip().upper()[:1]


def _iter_block_actions(block) -> list:
    actions = list(getattr(block, "actions", ()) or ())
    for child in getattr(block, "children", ()) or ():
        actions.extend(_iter_block_actions(child))
    return actions


def _collect_key_actions(frame) -> dict:
    """Mappa {tasto maiuscolo: Action} per tutte le action con `key` nel frame."""
    actions = list(getattr(frame, "actions", ()) or ())
    for slot in frame.slots:
        for block in slot.blocks:
            actions.extend(_iter_block_actions(block))
    bindings = {}
    for action in actions:
        if not action.key:
            continue
        key = action.key.upper()
        existing = bindings.get(key)
        if existing is not None and existing.id != action.id:
            raise SystemExit(
                f"Key '{key}' is assigned to multiple actions "
                f"('{existing.id}' and '{action.id}')."
            )
        bindings[key] = action
    return bindings


def _open_timeline_viewer(raw: dict) -> None:
    """Apre il viewer nativo sul primo lancio del giorno. ``RuntimeError`` se non è possibile."""
    from spacex_launches import viewer

    first = first_launch_phases(raw)
    if first is None:
        raise RuntimeError("no launches on this day: nothing to plot.")
    name, phases = first
    viewer.open_timeline(name, phases)


def _is_console(stream) -> bool:
    """``True`` solo se lo stream è una console vera.

    Su Windows ``isatty()`` è vero anche per ``NUL`` (è un device a caratteri):
    ``GetConsoleMode`` riesce solo su un handle di console.
    """
    try:
        if not stream.isatty():
            return False
        if os.name != "nt":
            return True
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(stream.fileno())
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(ctypes.c_ulong())))
    except (AttributeError, OSError, ValueError):
        return False


def _run_action_loop(frame, raw: dict, console: Console) -> None:
    """Ascolta i tasti delle action dichiarate nel frame (T = viewer, Q = esci).

    Attivo solo su terminale interattivo: se stdin o stdout non sono una console
    (output reindirizzato/pipe) la funzione ritorna subito, così i run non
    interattivi stampano e terminano senza bloccarsi in attesa di un tasto.
    """
    if not (_is_console(sys.stdin) and _is_console(sys.stdout)):
        return
    bindings = _collect_key_actions(frame)
    if not bindings:
        return
    console.print("[dim]Press an action key (e.g. T) · Q to quit.[/dim]")
    while True:
        try:
            key = _read_action_key()
        except (EOFError, KeyboardInterrupt):
            break
        # Ctrl+C con getwch arriva come "\x03", non come KeyboardInterrupt.
        if not key or key in {"Q", "\x03", "\x1b"}:
            break
        action = bindings.get(key)
        if action is None:
            continue
        if action.id == "open_timeline":
            try:
                _open_timeline_viewer(raw)
            except RuntimeError as exc:
                console.print(f"[yellow]Viewer unavailable: {exc}[/yellow]")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    args = parse_args(argv)
    console = Console()
    errors = Console(stderr=True)

    try:
        result = fetch_launches(args.date, cache_dir=args.cache_dir, offline=args.offline, refresh=args.refresh)
    except FetchError as exc:
        errors.print(f"[red]error:[/red] {exc}")
        return 1

    if result.warning:
        errors.print(f"[yellow]warning:[/yellow] {result.warning}")
    if result.from_cache:
        errors.print(f"[dim]cache: {result.cache_path}[/dim]")

    # Attivazione non interattiva (script/pipe): apri il viewer e termina.
    if args.open_timeline:
        try:
            _open_timeline_viewer(result.raw)
        except RuntimeError as exc:
            errors.print(f"[red]error:[/red] {exc}")
            return 4
        return 0

    spec = _load_spec(args.date)
    data, sync = build_payload(result.raw, args.date, result.fetched_at)

    # Persiste i payload accanto alla spec (utili anche per la CLI di rich-ui).
    _write_json(DATA_FILE, data)
    _write_json(SYNC_FILE, sync)

    if args.dump_mocks:
        _dump_mocks(args.dump_mocks, spec, data, sync)
        errors.print(f"[dim]mocks written to {args.dump_mocks}[/dim]")

    frame = parse_spec(spec)
    for issue in find_data_issues(frame, data):
        errors.print(f"[yellow]warning:[/yellow] {issue.message}")

    console.print(render(frame, data=data, sync=sync, view=ViewMode(args.view), theme=Theme()))

    # Framework keyboard-action: la dashboard mostra "Press T to ..."; qui
    # ascoltiamo i tasti e apriamo il viewer nativo (T), Q per uscire.
    _run_action_loop(frame, result.raw, console)
    return 0


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _dump_mocks(directory: Path, spec: dict, data: dict, sync: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, payload in (("spacex.json", spec), ("spacex.data.json", data), ("spacex.sync.json", sync)):
        _write_json(directory / name, payload)


if __name__ == "__main__":
    raise SystemExit(main())
