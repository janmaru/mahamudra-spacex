"""Viewer nativo (Tkinter) della timeline della missione.

Il viewer scatter di rich-ui (``show_scatter_window``) disegna una polilinea
attorno a un centro, senza asse del tempo né etichette per punto: per le fasi di
una missione non serve. Qui c'è un plot dedicato: asse X = tempo lineare da T-0,
asse Y = tre corsie (countdown, ship, booster), un marker con nome per ogni
evento. Rotella = zoom attorno al cursore, trascinamento = pan, R = vista
iniziale, ESC = chiudi. Stessa palette della finestra di rich-ui.
"""

from __future__ import annotations

from dataclasses import dataclass

from spacex_launches.timeline import BOOSTER, COUNTDOWN, SHIP, Phase, format_offset

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None  # type: ignore[assignment]

WINDOW_GEOMETRY = "1280x720"
BG = "#0f1117"
HEADER_BG = "#020617"
PLOT_BG = "#000000"
GRID = "#1a3a3a"
AXIS_TEXT = "#94a3b8"
TITLE_FG = "#7dd3fc"
T0_COLOR = "#facc15"

MARGIN_LEFT = 110
MARGIN_RIGHT = 30
MARGIN_TOP = 20
MARGIN_BOTTOM = 40
LABEL_FONT = ("Segoe UI", 9)
LABEL_LEVELS = 4
LABEL_GAP = 6
HOVER_RADIUS = 10
ZOOM_STEP = 1.25
MIN_SPAN_SECONDS = 10.0
# Passi candidati per le tacche dell'asse X, in secondi.
_TICK_STEPS = (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400)
TARGET_TICKS = 10
# Zoom-out massimo, in multipli della vista iniziale: oltre, le tacche (passo
# massimo un giorno) diventerebbero migliaia per ridisegno.
MAX_ZOOM_OUT = 4.0


@dataclass(frozen=True)
class _Lane:
    key: str
    label: str
    color: str
    shape: str


# Dall'alto in basso: il countdown sta sopra perché è la prima cosa che accade.
_LANES = (
    _Lane(COUNTDOWN, "Countdown", "#e2e8f0", "square"),
    _Lane(SHIP, "Ship", "#22d3ee", "diamond"),
    _Lane(BOOSTER, "Booster", "#e879f9", "circle"),
)


def open_timeline(launch_name: str, phases: list[Phase]) -> None:
    """Apre la finestra con la timeline e blocca fino alla chiusura."""
    if tk is None:
        raise RuntimeError("Tkinter is not available in this Python installation.")
    if not phases:
        raise RuntimeError("The launch has no phases to plot.")
    try:
        window = _TimelineWindow(launch_name, phases)
    except tk.TclError as exc:
        raise RuntimeError(f"cannot open the Tk window: {exc}") from exc
    window.run()


class _TimelineWindow:
    def __init__(self, launch_name: str, phases: list[Phase]) -> None:
        self.phases = sorted(phases, key=lambda phase: phase.seconds)
        self.lanes = [lane for lane in _LANES if any(p.lane == lane.key for p in self.phases)]
        self.t_min, self.t_max = self._initial_range()
        self._max_span = (self.t_max - self.t_min) * MAX_ZOOM_OUT
        self._drag_x: int | None = None
        self._markers: list[tuple[float, float, Phase]] = []

        self.root = tk.Tk()
        self.root.title(f"{launch_name} - Mission Timeline")
        self.root.geometry(WINDOW_GEOMETRY)
        self.root.configure(bg=BG)

        header = tk.Frame(self.root, bg=HEADER_BG, height=44)
        header.pack(side=tk.TOP, fill=tk.X)
        tk.Label(header, text=f"{launch_name} — Mission Timeline", font=("Segoe UI", 14, "bold"),
                 bg=HEADER_BG, fg=TITLE_FG).pack(pady=10)

        self.canvas = tk.Canvas(self.root, bg=PLOT_BG, highlightthickness=1, highlightbackground="#1e3a4a")
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))

        footer = tk.Frame(self.root, bg=BG)
        footer.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=8)
        self.status = tk.Label(footer, text="", font=("Segoe UI", 10, "bold"), bg=BG, fg=TITLE_FG, anchor="w")
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(footer, text="wheel zoom · drag pan · R reset · ESC close", font=("Segoe UI", 9),
                 bg=BG, fg=AXIS_TEXT).pack(side=tk.RIGHT)

        self.canvas.bind("<Configure>", lambda _event: self.redraw())
        self.canvas.bind("<MouseWheel>", self._on_wheel)          # Windows / macOS
        self.canvas.bind("<Button-4>", lambda e: self._zoom(e.x, 1 / ZOOM_STEP))  # X11
        self.canvas.bind("<Button-5>", lambda e: self._zoom(e.x, ZOOM_STEP))
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", lambda _event: setattr(self, "_drag_x", None))
        self.canvas.bind("<Motion>", self._on_motion)
        self.root.bind("<Escape>", lambda _event: self.root.destroy())
        self.root.bind("<KeyPress-r>", self._reset)
        self.root.bind("<KeyPress-R>", self._reset)

    def run(self) -> None:
        self.root.mainloop()

    # --- geometria -------------------------------------------------------

    def _initial_range(self) -> tuple[float, float]:
        low = min(self.phases[0].seconds, 0.0)
        high = max(self.phases[-1].seconds, 0.0)
        pad = max((high - low) * 0.03, MIN_SPAN_SECONDS)
        return low - pad, high + pad

    def _plot_box(self) -> tuple[int, int, int, int]:
        width = max(self.canvas.winfo_width(), MARGIN_LEFT + MARGIN_RIGHT + 50)
        height = max(self.canvas.winfo_height(), MARGIN_TOP + MARGIN_BOTTOM + 50)
        return MARGIN_LEFT, MARGIN_TOP, width - MARGIN_RIGHT, height - MARGIN_BOTTOM

    def _to_px(self, seconds: float) -> float:
        left, _, right, _ = self._plot_box()
        return left + (seconds - self.t_min) / (self.t_max - self.t_min) * (right - left)

    def _to_seconds(self, px: float) -> float:
        left, _, right, _ = self._plot_box()
        return self.t_min + (px - left) / (right - left) * (self.t_max - self.t_min)

    # --- disegno ---------------------------------------------------------

    def redraw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        self._markers = []
        left, top, right, bottom = self._plot_box()
        lane_height = (bottom - top) / len(self.lanes)

        self._draw_time_axis(left, top, right, bottom)
        for index, lane in enumerate(self.lanes):
            lane_top = top + index * lane_height
            if index:
                canvas.create_line(left, lane_top, right, lane_top, fill="#1e293b")
            canvas.create_text(left - 12, lane_top + lane_height / 2, text=lane.label, anchor="e",
                               fill=lane.color, font=("Segoe UI", 10, "bold"))
            self._draw_lane(lane, lane_top, lane_height, left, right)

        if left <= self._to_px(0.0) <= right:
            x0 = self._to_px(0.0)
            canvas.create_line(x0, top, x0, bottom, fill=T0_COLOR, dash=(4, 3))
            canvas.create_text(x0, top - 2, text="T-0", anchor="s", fill=T0_COLOR, font=("Segoe UI", 9, "bold"))
        canvas.create_rectangle(left, top, right, bottom, outline="#334155")

    def _draw_time_axis(self, left: int, top: int, right: int, bottom: int) -> None:
        span = self.t_max - self.t_min
        step = next((s for s in _TICK_STEPS if span / s <= TARGET_TICKS), _TICK_STEPS[-1])
        tick = (self.t_min // step + 1) * step
        while tick < self.t_max:
            x = self._to_px(tick)
            self.canvas.create_line(x, top, x, bottom, fill=GRID)
            self.canvas.create_text(x, bottom + 6, text=_tick_label(tick, step), anchor="n",
                                    fill=AXIS_TEXT, font=LABEL_FONT)
            tick += step
        self.canvas.create_text((left + right) / 2, bottom + 24, text="time from T-0 (linear)",
                                anchor="n", fill=AXIS_TEXT, font=("Segoe UI", 8))

    def _draw_lane(self, lane: _Lane, lane_top: float, lane_height: float, left: int, right: int) -> None:
        """Marker sulla linea della corsia, etichette su livelli sfalsati sopra di essa.

        Assegnazione greedy: ogni etichetta va sul primo livello libero dove non
        si sovrappone a quelle già piazzate; se nessun livello è libero resta solo
        il marker (il nome compare al passaggio del mouse). Un'etichetta che
        sforerebbe il bordo destro viene ancorata a sinistra del marker.
        """
        baseline = lane_top + lane_height * 0.8
        level_step = max(0.0, (lane_height * 0.8 - 12) / LABEL_LEVELS)
        occupied: list[list[tuple[float, float]]] = [[] for _ in range(LABEL_LEVELS)]
        for phase in (p for p in self.phases if p.lane == lane.key):
            x = self._to_px(phase.seconds)
            if not left <= x <= right:
                continue
            _draw_marker(self.canvas, x, baseline, lane.shape, lane.color)
            self._markers.append((x, baseline, phase))
            text = f"{phase.name}  {format_offset(phase.seconds)}"
            item = self.canvas.create_text(x + 4, 0, text=text, anchor="sw", fill=lane.color, font=LABEL_FONT)
            x1, _, x2, _ = self.canvas.bbox(item)
            anchor, label_x = "sw", x + 4
            if x2 > right:
                anchor, label_x = "se", x - 4
                x1, x2 = x1 - (x2 - x1) - 8, x - 4
            level = next(
                (i for i in range(LABEL_LEVELS)
                 if all(x2 + LABEL_GAP < a or x1 > b + LABEL_GAP for a, b in occupied[i])),
                None,
            )
            if level is None or x1 < left or not level_step:
                self.canvas.delete(item)
                continue
            occupied[level].append((x1, x2))
            label_y = baseline - 10 - level * level_step
            self.canvas.itemconfigure(item, anchor=anchor)
            self.canvas.coords(item, label_x, label_y)
            self.canvas.create_line(x, baseline - 6, x, label_y, fill=GRID)

    # --- interazione -----------------------------------------------------

    def _on_wheel(self, event) -> None:
        self._zoom(event.x, 1 / ZOOM_STEP if event.delta > 0 else ZOOM_STEP)

    def _zoom(self, px: int, factor: float) -> None:
        anchor = self._to_seconds(px)
        span = min(max((self.t_max - self.t_min) * factor, MIN_SPAN_SECONDS), self._max_span)
        ratio = (anchor - self.t_min) / (self.t_max - self.t_min)
        self.t_min = anchor - ratio * span
        self.t_max = self.t_min + span
        self.redraw()

    def _on_press(self, event) -> None:
        self._drag_x = event.x

    def _on_drag(self, event) -> None:
        if self._drag_x is None:
            return
        shift = self._to_seconds(self._drag_x) - self._to_seconds(event.x)
        self.t_min += shift
        self.t_max += shift
        self._drag_x = event.x
        self.redraw()

    def _on_motion(self, event) -> None:
        near = [(abs(x - event.x) + abs(y - event.y), phase) for x, y, phase in self._markers]
        near = [item for item in near if item[0] <= HOVER_RADIUS]
        if near:
            phase = min(near, key=lambda item: item[0])[1]
            self.status.configure(text=f"{format_offset(phase.seconds)}  {phase.name}")
        else:
            self.status.configure(text="")

    def _reset(self, _event=None) -> None:
        self.t_min, self.t_max = self._initial_range()
        self.redraw()


def _draw_marker(canvas, x: float, y: float, shape: str, color: str, size: int = 5) -> None:
    if shape == "diamond":
        canvas.create_polygon(x, y - size, x + size, y, x, y + size, x - size, y, fill=color, outline=color)
    elif shape == "square":
        canvas.create_rectangle(x - size + 1, y - size + 1, x + size - 1, y + size - 1, fill=color, outline=color)
    else:
        canvas.create_oval(x - size, y - size, x + size, y + size, fill=color, outline=color)


def _tick_label(seconds: float, step: float) -> str:
    """``T+1:30`` per passi sotto l'ora, ``T+9h`` per passi orari, ``T+0:00:15`` sotto il minuto."""
    sign = "-" if seconds < 0 else "+"
    total = int(round(abs(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if step < 60:
        return f"T{sign}{hours}:{minutes:02d}:{secs:02d}"
    if step < 3600 or minutes:
        return f"T{sign}{hours}:{minutes:02d}"
    return f"T{sign}{hours}h"
