"""Structured logging for the checkit pipeline.

A small leveled logger so the CLI, GUI and tests all share one format.
`emit(level, message)` is the single entry point; a sink callback decides
where messages go (print, GUI event queue, test capture, ...).

Levels (increasing severity): debug < info < warning < error.
Verbose mode enables debug-level messages.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

LEVELS = ("debug", "info", "warning", "error")


@dataclass
class LogEvent:
    level: str
    message: str
    percent: Optional[int] = None

    def to_dict(self) -> dict:
        d = {"type": "log", "level": self.level, "message": self.message}
        if self.percent is not None:
            d["percent"] = self.percent
        return d


class Logger:
    """Fan-out logger: keeps a ring buffer and forwards to a sink."""

    def __init__(self, sink: Callable[[LogEvent], None] | None = None,
                 verbose: bool = False, history: int = 500):
        self.sink = sink
        self.verbose = verbose
        self._history: list = []
        self._history_size = history

    def set_sink(self, sink) -> None:
        self.sink = sink

    def set_verbose(self, verbose: bool) -> None:
        self.verbose = verbose

    def emit(self, level: str, message: str, percent: int | None = None) -> LogEvent:
        if level == "debug" and not self.verbose:
            return LogEvent(level, message, percent)
        event = LogEvent(level, message, percent)
        self._history.append(event)
        if len(self._history) > self._history_size:
            self._history = self._history[-self._history_size:]
        if self.sink is not None:
            self.sink(event)
        return event

    def debug(self, message: str, percent: int | None = None):
        return self.emit("debug", message, percent)

    def info(self, message: str, percent: int | None = None):
        return self.emit("info", message, percent)

    def warning(self, message: str, percent: int | None = None):
        return self.emit("warning", message, percent)

    def error(self, message: str, percent: int | None = None):
        return self.emit("error", message, percent)

    @property
    def history(self) -> list:
        return list(self._history)


def cli_sink(stream=None):
    """Return a sink that prints colored, leveled lines to a stream."""
    stream = stream or sys.stdout
    colors = {
        "debug": "\033[90m",     # gray
        "info": "\033[36m",      # cyan
        "warning": "\033[33m",   # yellow
        "error": "\033[31m",     # red
    }
    reset = "\033[0m"
    use_color = hasattr(stream, "isatty") and stream.isatty()

    def sink(event: LogEvent) -> None:
        prefix = ""
        if event.percent is not None:
            prefix = f"[{event.percent:3d}%] "
        if use_color:
            line = f"{colors.get(event.level, '')}{prefix}{event.message}{reset}"
        else:
            line = f"{prefix}{event.message}"
        print(line, file=stream, flush=True)

    return sink
