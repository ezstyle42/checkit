"""GUI for checkit, built on pywebview.

`python -m checkit.gui` (or the `checkit-gui` entry point) opens a desktop
window with a form to configure and run the pipeline, a live verbose log, a
rendered report, and persistent settings (including API keys).

Works on Linux, Windows and macOS. Bundled into a single-file executable
with PyInstaller (see packaging/ and .github/workflows/release.yml).
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from . import __version__
from .llm import PROVIDERS
from .logging_util import Logger, LogEvent
from .settings import Settings, load_settings, save_settings

FRONTEND_DIR = Path(__file__).resolve().parent / "gui_frontend"


class CancelledError(RuntimeError):
    pass


class GuiBridge:
    """API exposed to the JavaScript frontend via pywebview."""

    def __init__(self):
        self._events: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_result: dict = {}
        self._logger = Logger(sink=self._on_log, verbose=True)

    # -- logging -----------------------------------------------------------
    def _on_log(self, event: LogEvent) -> None:
        self._events.put(event.to_dict())

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

    # -- settings ----------------------------------------------------------
    def load_settings(self) -> dict:
        s = load_settings()
        d = s.to_dict()
        # Never send keys to the frontend in bulk; the GUI shows masked status.
        d["api_keys"] = {k: ("••••" + v[-4:]) if v else ""
                         for k, v in s.api_keys.items()}
        d["settings_path"] = str(__import__("checkit.settings", fromlist=["settings_path"]).settings_path())
        return d

    def save_settings(self, data: dict) -> dict:
        s = load_settings()
        s.url = data.get("url", s.url)
        s.out_dir = data.get("out_dir", s.out_dir)
        s.max_pages = int(data.get("max_pages", s.max_pages))
        s.delay = float(data.get("delay", s.delay))
        s.fmt = data.get("fmt", s.fmt)
        s.use_llm = bool(data.get("use_llm", s.use_llm))
        s.provider = data.get("provider", s.provider)
        s.model = data.get("model", s.model)
        s.verbose = bool(data.get("verbose", s.verbose))
        # Only overwrite a key when a new one was actually entered (non-empty
        # and not the masked placeholder).
        for prov in PROVIDERS:
            key = (data.get("api_keys") or {}).get(prov)
            if key and not key.startswith("••••"):
                s.api_keys[prov] = key
        path = save_settings(s)
        return {"saved": True, "path": str(path)}

    # -- JS-callable API ---------------------------------------------------
    def run(self, config: dict) -> dict:
        if self._thread and self._thread.is_alive():
            return {"error": "A run is already in progress."}
        self._cancel.clear()
        self._last_result = {}
        self._logger.set_verbose(bool(config.get("verbose", True)))
        self._thread = threading.Thread(target=self._run_worker,
                                        args=(config,), daemon=True)
        self._thread.start()
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

    def _run_worker(self, config: dict) -> None:
        started = datetime.now().strftime("%H:%M:%S")
        self._logger.info(f"Run started at {started}.")
        try:
            result = run_pipeline_gui(config, self._logger, self._cancel)
            self._last_result = result
            self._emit({"type": "done"})
        except CancelledError:
            self._logger.warning("Run cancelled by user.")
            self._last_result = {"error": "Cancelled."}
        except Exception as exc:  # surfaced to the UI
            self._logger.error(f"{type(exc).__name__}: {exc}")
            self._last_result = {"error": f"{type(exc).__name__}: {exc}"}
        finally:
            elapsed = datetime.now().strftime("%H:%M:%S")
            self._logger.info(f"Run finished at {elapsed}.")


def run_pipeline_gui(config: dict, logger: Logger, cancel: threading.Event) -> dict:
    """GUI-friendly pipeline runner with verbose logging + cancellation."""
    from .checker import check_pages
    from .crawler import crawl
    from .distiller import distill_page, write_pages
    from .llm import LLMClient
    from .settings import load_settings

    url = config["url"]
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL {url!r}: must start with http:// or https://")
    out_dir = config.get("out") or "checkit-out"
    max_pages = int(config.get("max_pages") or 100)
    delay = float(config.get("delay") or 0)
    fmt = config.get("fmt") or "markdown"
    use_llm = bool(config.get("use_llm"))

    saved = load_settings()

    logger.info(f"Target: {url}")
    logger.info(f"Output directory: {Path(out_dir).resolve()}")
    logger.info(f"Config: max_pages={max_pages}, delay={delay}s, format={fmt}, "
                f"LLM={'on' if use_llm else 'off'}"
                f"{', verbose' if config.get('verbose') else ''}")

    logger.info("PHASE 1/3: CRAWL")
    crawled = crawl(url, max_pages=max_pages, delay=delay,
                    cancel_event=cancel, logger=logger)
    if cancel.is_set():
        raise CancelledError("cancelled by user")
    logger.info(f"Crawled {len(crawled)} pages.")

    logger.info("PHASE 2/3: DISTILL")
    pages = []
    for i, cp in enumerate(crawled):
        if cancel.is_set():
            raise CancelledError("cancelled by user")
        pages.append(distill_page(cp.html, cp.final_url or cp.url, logger))
        if (i + 1) % 10 == 0 or i + 1 == len(crawled):
            logger.info(f"Distilled {i + 1}/{len(crawled)} pages.")
    logger.info(f"Distilled {len(pages)} pages to {fmt}.")

    out = Path(out_dir)
    written = write_pages(pages, out / "pages", fmt=fmt, logger=logger)

    logger.info("PHASE 3/3: CONSISTENCY CHECK")
    client = None
    if use_llm:
        provider = config.get("provider") or "mistral"
        api_key = config.get("api_key") or saved.api_key_for(provider)
        if api_key:
            logger.info(f"Using saved/entered API key for {provider} "
                        f"(…{api_key[-4:]})")
        else:
            logger.warning(f"No API key found for {provider}; will try env vars "
                           "and checkit.env.")
        logger.info(f"Initializing LLM client: {provider} "
                    f"(model={config.get('model') or 'default'})")
        client = LLMClient(provider, api_key=api_key or None,
                           model=config.get("model") or None,
                           settings=saved)
        logger.info(f"LLM client ready: {client.provider} / {client.model}")
    else:
        logger.info("LLM checks disabled; running deterministic checks only.")

    report = check_pages(pages, client=client,
                         use_llm=use_llm and client is not None,
                         logger=logger, cancel_event=cancel)
    report_path = out / "report.md"
    report_path.write_text(report.to_markdown(), encoding="utf-8")
    logger.info(f"Report written to {report_path.resolve()}.")
    logger.info(f"DONE. Pages: {len(pages)}, findings: {len(report.findings)}, "
                f"overall: {'PASS' if report.ok else 'ISSUES FOUND'}.")

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
        width=1150,
        height=760,
        min_size=(900, 600),
        text_select=True,
    )
    webview.start(debug=debug)


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
