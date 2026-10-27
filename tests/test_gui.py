"""Headless tests for the GUI bridge and pipeline plumbing.

pywebview itself is not imported here (it needs a display); we test the
bridge logic, settings persistence, and the GUI pipeline runner directly.
"""

import http.server
import threading

import pytest

from checkit.gui import CancelledError, GuiBridge, run_pipeline_gui
from checkit.logging_util import Logger
from checkit.settings import Settings, load_settings, save_settings

SITE = {
    "/": """
    <html><head><title>Home</title></head><body><main>
    <h1>Home</h1>
    <p>Acme was founded on 2001-06-15.</p>
    <a href="/about">About</a>
    </main></body></html>
    """,
    "/about": """
    <html><head><title>About</title></head><body><main>
    <h1>About us</h1>
    <p>Acme was founded on 15 June 2005.</p>
    </main></body></html>
    """,
    "/robots.txt": "User-agent: *\nAllow: /\n",
}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = SITE.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        data = body.encode("utf-8")
        ctype = "text/plain" if self.path == "/robots.txt" else "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKIT_SETTINGS", str(tmp_path / "settings.json"))
    return tmp_path / "settings.json"


def make_config(server, tmp_path, **overrides):
    cfg = {
        "url": f"{server}/",
        "out": str(tmp_path / "out"),
        "max_pages": 10,
        "delay": 0,
        "fmt": "markdown",
        "use_llm": False,
        "verbose": True,
        "provider": "mistral",
        "model": None,
        "api_key": None,
    }
    cfg.update(overrides)
    return cfg


class TestRunPipelineGui:
    def test_full_run_no_llm(self, server, tmp_path):
        events = []
        logger = Logger(sink=events.append, verbose=True)
        result = run_pipeline_gui(
            make_config(server, tmp_path),
            logger=logger,
            cancel=threading.Event(),
        )
        assert result["ok"] is True
        assert result["pages"] == 2
        assert result["overall_ok"] is True
        assert "report.md" in result["report_path"]
        assert "# CheckIt consistency report" in result["report_md"]
        msgs = [e.message for e in events]
        assert any("PHASE 1/3: CRAWL" in m for m in msgs)
        assert any("PHASE 3/3: CONSISTENCY CHECK" in m for m in msgs)
        assert any(m.startswith("DONE.") for m in msgs)

    def test_verbose_log_narrates_crawl(self, server, tmp_path):
        events = []
        logger = Logger(sink=events.append, verbose=True)
        run_pipeline_gui(make_config(server, tmp_path), logger,
                         threading.Event())
        msgs = [e.message for e in events]
        assert any("Fetching" in m for m in msgs)
        assert any("HTTP 200" in m for m in msgs)
        assert any("Crawl finished:" in m for m in msgs)

    def test_report_written_to_disk(self, server, tmp_path):
        result = run_pipeline_gui(
            make_config(server, tmp_path),
            logger=Logger(verbose=True),
            cancel=threading.Event(),
        )
        with open(result["report_path"], encoding="utf-8") as fh:
            assert "Pages checked: 2" in fh.read()
        pages_dir = tmp_path / "out" / "pages"
        assert len(list(pages_dir.glob("*.md"))) == 3  # 2 pages + index

    def test_cancellation(self, server, tmp_path):
        cancel = threading.Event()
        cancel.set()  # pre-cancelled
        with pytest.raises(CancelledError):
            run_pipeline_gui(
                make_config(server, tmp_path),
                logger=Logger(verbose=True),
                cancel=cancel,
            )

    def test_invalid_url_raises(self, tmp_path):
        with pytest.raises(ValueError):
            run_pipeline_gui(
                make_config("notaurl", tmp_path),
                logger=Logger(verbose=True),
                cancel=threading.Event(),
            )

    def test_saved_api_key_is_used(self, server, tmp_path):
        # Save a key for mistral, then verify resolution order finds it.
        save_settings(Settings(api_keys={"mistral": "sk-saved-key"}))
        loaded = load_settings()
        assert loaded.api_key_for("mistral") == "sk-saved-key"


class TestGuiBridge:
    def test_run_executes_worker_and_returns_result(self, server, tmp_path):
        bridge = GuiBridge()
        result = bridge.run(make_config(server, tmp_path))
        assert result["ok"] is True
        assert result["pages"] == 2
        events = bridge.poll_events()
        assert any(e["type"] == "done" for e in events)
        assert bridge.poll_events() == []  # queue drained

    def test_run_logs_are_queued(self, server, tmp_path):
        bridge = GuiBridge()
        bridge.run(make_config(server, tmp_path))
        events = bridge.poll_events()
        log_events = [e for e in events if e["type"] == "log"]
        assert log_events, "expected log events"
        assert any("PHASE 1/3" in e["message"] for e in log_events)

    def test_run_error_is_returned_not_raised(self, tmp_path):
        bridge = GuiBridge()
        result = bridge.run(make_config("notaurl", tmp_path))
        assert "error" in result
        assert "ValueError" in result["error"]

    def test_cancel_sets_event(self):
        bridge = GuiBridge()
        assert bridge.cancel() == {"cancelled": True}
        assert bridge.poll_events() == []

    def test_providers_and_version(self):
        bridge = GuiBridge()
        assert bridge.providers() == ["mistral", "openai", "claude"]
        from checkit import __version__
        assert bridge.version() == __version__

    def test_load_settings_masks_api_keys(self):
        save_settings(Settings(
            url="https://x.example", provider="openai",
            api_keys={"openai": "sk-abcdef123456"},
        ))
        bridge = GuiBridge()
        d = bridge.load_settings()
        assert d["url"] == "https://x.example"
        assert d["api_keys"]["openai"] == "••••3456"
        assert d["api_keys"].get("mistral") in (None, "")
        assert "settings_path" in d

    def test_save_settings_persists_and_merges_keys(self):
        save_settings(Settings(api_keys={"mistral": "sk-old-mistral-key"}))
        bridge = GuiBridge()
        res = bridge.save_settings({
            "url": "https://new.example",
            "out_dir": "out2",
            "max_pages": 25,
            "delay": 0.2,
            "fmt": "xml",
            "use_llm": True,
            "verbose": True,
            "provider": "claude",
            "model": "",
            "api_keys": {
                "mistral": "",           # blank -> keep saved key
                "openai": "sk-new-openai",  # new key -> overwrite
                "claude": "••••" + "abcd",  # masked placeholder -> keep old (none)
            },
        })
        assert res["saved"] is True
        s = load_settings()
        assert s.url == "https://new.example"
        assert s.max_pages == 25
        assert s.fmt == "xml"
        assert s.verbose is True
        assert s.api_key_for("mistral") == "sk-old-mistral-key"  # preserved
        assert s.api_key_for("openai") == "sk-new-openai"        # updated
        assert s.api_key_for("claude") is None                   # not saved from mask

    def test_double_run_rejected(self, server, tmp_path):
        bridge = GuiBridge()
        blocker = threading.Event()

        def slow_worker():
            blocker.wait(5)

        bridge._thread = threading.Thread(target=slow_worker, daemon=True)
        bridge._thread.start()
        try:
            result = bridge.run(make_config(server, tmp_path))
            assert result == {"error": "A run is already in progress."}
        finally:
            blocker.set()
            bridge._thread.join()
