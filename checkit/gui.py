"""Tkinter-free GUI for checkit, built on pywebview.

`python -m checkit.gui` (or the `checkit-gui` entry point) opens a desktop
window with a form to configure and run the pipeline, a live log, and a
rendered report. All heavy work runs in a background thread; pywebview
exposes a small JS-callable API.

Works on Linux, Windows and macOS. Bundled into a single-file executable
with PyInstaller (see packaging/ and .github/workflows/release.yml).
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

from . import __version__
from .llm import PROVIDERS

FRONTEND_DIR = Path(__file__).resolve().parent / "gui_frontend"


class CancelledError(RuntimeError):
    pass


class GuiBridge:
    """API exposed to the JavaScript frontend via pywebview."""

    def __init__(self):
        self._events: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_result: dict = {}

    # -- event plumbing ---------------------------------------------------
    def _emit(self, event: dict) -> None:
        self._events.put(event)

    def poll_events(self) -> list:
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events

    # -- JS-callable API ---------------------------------------------------
    def run(self, config: dict) -> dict:
        if self._thread and self._thread.is_alive():
            return {"error": "A run is already in progress."}
        self._cancel.clear()
        self._last_result = {}
        self._thread = threading.Thread(target=self._run_worker,
                                        args=(config,), daemon=True)
        self._thread.start()
        # Block the pywebview call until done; result delivered here.
        return self._wait_result()

    def cancel(self) -> dict:
        self._cancel.set()
        return {"cancelled": True}

    def open_folder(self, path: str) -> dict:
        return {"path": open_folder(path)}

    def providers(self) -> list:
        return list(PROVIDERS)

    def version(self) -> str:
        return __version__

    # -- worker ------------------------------------------------------------
    def _wait_result(self) -> dict:
        self._thread.join()
        return self._last_result

    def _progress(self, message: str, percent: int | None = None):
        if self._cancel.is_set():
            raise CancelledError("cancelled by user")
        event = {"type": "log", "message": message, "level": "info"}
        if percent is not None:
            event = {"type": "progress", "message": message, "percent": percent}
        self._emit(event)

    def _run_worker(self, config: dict) -> None:
        try:
            result = run_pipeline_gui(config, self._progress, self._cancel)
            self._last_result = result
            self._emit({"type": "done"})
        except CancelledError:
            self._last_result = {"error": "Cancelled."}
        except Exception as exc:  # surfaced to the UI
            self._last_result = {"error": f"{type(exc).__name__}: {exc}"}
            self._emit({"type": "log", "message": str(exc), "level": "error"})


def run_pipeline_gui(config: dict, progress, cancel: threading.Event) -> dict:
    """GUI-friendly pipeline runner with progress + cancellation."""
    from .checker import check_pages
    from .crawler import crawl
    from .distiller import distill_page, write_pages
    from .llm import LLMClient

    url = config["url"]
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL {url!r}: must start with http:// or https://")
    out_dir = config.get("out") or "checkit-out"
    max_pages = int(config.get("max_pages") or 100)
    delay = float(config.get("delay") or 0)
    fmt = config.get("fmt") or "markdown"
    use_llm = bool(config.get("use_llm"))

    progress(f"Crawling {url} (max {max_pages} pages)…", 5)
    crawled = crawl(url, max_pages=max_pages, delay=delay,
                    cancel_event=cancel)
    if cancel.is_set():
        raise CancelledError("cancelled by user")
    progress(f"Crawled {len(crawled)} pages.", 35)

    pages = []
    for i, cp in enumerate(crawled):
        if cancel.is_set():
            raise CancelledError("cancelled by user")
        pages.append(distill_page(cp.html, cp.final_url or cp.url))
        if i % 5 == 0:
            pct = 35 + int(20 * (i + 1) / max(1, len(crawled)))
            progress(f"Distilled {i + 1}/{len(crawled)} pages.", pct)
    progress(f"Distilled {len(pages)} pages to {fmt}.", 55)

    out = Path(out_dir)
    written = write_pages(pages, out / "pages", fmt=fmt)
    progress(f"Wrote {len(written)} files under {out / 'pages'}.", 60)

    client = None
    if use_llm:
        provider = config.get("provider") or "mistral"
        progress(f"Checking consistency with {provider}…", 65)
        client = LLMClient(provider,
                           api_key=config.get("api_key"),
                           model=config.get("model"))
    else:
        progress("Checking consistency (deterministic checks only)…", 65)

    report = check_pages(pages, client=client,
                         use_llm=use_llm and client is not None,
                         progress=progress)
    report_path = out / "report.md"
    report_path.write_text(report.to_markdown(), encoding="utf-8")
    progress(f"Report written to {report_path}.", 100)

    return {
        "ok": True,
        "pages": len(pages),
        "findings": len(report.findings),
        "report_path": str(report_path.resolve()),
        "report_md": report.to_markdown(),
        "overall_ok": report.ok,
    }


def open_folder(path: str) -> str:
    """Open a folder in the OS file manager. Returns the absolute path."""
    target = str(Path(path).resolve())
    if sys.platform.startswith("darwin"):
        subprocess.Popen(["open", target])
    elif os.name == "nt":
        subprocess.Popen(["explorer", target])
    else:
        subprocess.Popen(["xdg-open", target])
    return target


def launch(debug: bool = False) -> None:
    """Open the checkit GUI window."""
    import webview

    bridge = GuiBridge()
    index = FRONTEND_DIR / "index.html"
    window = webview.create_window(
        "checkit — website consistency checker",
        url=index.as_uri(),
        width=1100,
        height=720,
        min_size=(860, 560),
        text_select=True,
    )
    webview.start(func=lambda: None, args=(bridge, window), debug=debug,
                  gui=None,  # let pywebview pick the best native backend
                  )


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="checkit-gui",
                                     description="checkit desktop application")
    parser.add_argument("--debug", action="store_true",
                        help="Open developer tools on start.")
    args = parser.parse_args(argv)
    launch(debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
