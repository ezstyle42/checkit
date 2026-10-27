"""Headless tests for the GUI bridge and pipeline plumbing.

pywebview itself is not imported here (it needs a display); we test the
bridge logic and the GUI pipeline runner directly.
"""

import http.server
import threading

import pytest

from checkit.gui import CancelledError, GuiBridge, run_pipeline_gui

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


def make_config(server, tmp_path, **overrides):
    cfg = {
        "url": f"{server}/",
        "out": str(tmp_path / "out"),
        "max_pages": 10,
        "delay": 0,
        "fmt": "markdown",
        "use_llm": False,
        "provider": "mistral",
        "model": None,
        "api_key": None,
    }
    cfg.update(overrides)
    return cfg


class TestRunPipelineGui:
    def test_full_run_no_llm(self, server, tmp_path):
        events = []
        result = run_pipeline_gui(
            make_config(server, tmp_path),
            progress=lambda msg, pct=None: events.append((msg, pct)),
            cancel=threading.Event(),
        )
        assert result["ok"] is True
        assert result["pages"] == 2
        assert result["overall_ok"] is True
        assert "report.md" in result["report_path"]
        assert "# CheckIt consistency report" in result["report_md"]
        # progress events were emitted with increasing percentages
        pcts = [p for _m, p in events if p is not None]
        assert pcts and pcts[-1] == 100
        assert pcts == sorted(pcts)

    def test_report_written_to_disk(self, server, tmp_path):
        result = run_pipeline_gui(
            make_config(server, tmp_path),
            progress=lambda *a: None,
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
                progress=lambda *a: None,
                cancel=cancel,
            )

    def test_invalid_url_raises(self, tmp_path):
        with pytest.raises(ValueError):
            run_pipeline_gui(
                make_config("notaurl", tmp_path),
                progress=lambda *a: None,
                cancel=threading.Event(),
            )


class TestGuiBridge:
    def test_run_executes_worker_and_returns_result(self, server, tmp_path):
        bridge = GuiBridge()
        result = bridge.run(make_config(server, tmp_path))
        assert result["ok"] is True
        assert result["pages"] == 2
        # events were queued for the frontend to poll
        events = bridge.poll_events()
        assert any(e["type"] == "done" for e in events)
        assert bridge.poll_events() == []  # queue drained

    def test_run_error_is_returned_not_raised(self, tmp_path):
        bridge = GuiBridge()
        result = bridge.run(make_config("notaurl", tmp_path))
        assert "error" in result
        assert "ValueError" in result["error"]

    def test_cancel_sets_event(self):
        bridge = GuiBridge()
        assert bridge.cancel() == {"cancelled": True}
        events = bridge.poll_events()
        assert events == []

    def test_providers_and_version(self):
        bridge = GuiBridge()
        assert bridge.providers() == ["mistral", "openai", "claude"]
        from checkit import __version__
        assert bridge.version() == __version__

    def test_double_run_rejected(self, server, tmp_path):
        bridge = GuiBridge()
        # Simulate an in-progress run by starting a slow worker
        started = threading.Event()

        def slow_progress(msg, pct=None):
            started.set()
            import time
            time.sleep(0.5)

        t = threading.Thread(
            target=lambda: bridge.run(make_config(server, tmp_path)),
            daemon=True,
        )
        # Force the "already running" path by marking the thread alive
        bridge._thread = threading.Thread(target=lambda: started.wait(2))
        bridge._thread.start()
        result = bridge.run(make_config(server, tmp_path))
        assert result == {"error": "A run is already in progress."}
        bridge._thread.join()
