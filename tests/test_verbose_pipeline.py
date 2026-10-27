"""Verbosity tests: the pipeline must narrate what it is doing."""

import http.server
import threading

import pytest

from checkit.logging_util import Logger
from checkit.pipeline import run_pipeline

SITE = {
    "/": """
    <html><head><title>Home</title></head><body><main>
    <h1>Home</h1>
    <p>Acme was founded on 2001-06-15.</p>
    <a href="/about">About</a>
    <a href="/missing">Missing</a>
    <a href="https://external.example/x">External</a>
    <a href="/logo.png">Logo</a>
    </main></body></html>
    """,
    "/about": """
    <html><head><title>About</title></head><body><main>
    <h1>About us</h1>
    <p>Acme was founded on 15 June 2005.</p>
    </main></body></html>
    """,
    "/robots.txt": "User-agent: *\nDisallow: /blocked\nAllow: /\n",
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


def run_and_collect(server, tmp_path, verbose):
    events = []
    logger = Logger(sink=events.append, verbose=verbose)
    run_pipeline(
        f"{server}/",
        out_dir=tmp_path,
        max_pages=10,
        delay=0,
        fmt="markdown",
        use_llm=False,
        logger=logger,
    )
    return events


def messages(events):
    return [e.message for e in events]


def test_verbose_narrates_every_step(server, tmp_path):
    events = run_and_collect(server, tmp_path, verbose=True)
    msgs = messages(events)

    # Phases are announced
    assert any("PHASE 1/3: CRAWL" in m for m in msgs)
    assert any("PHASE 2/3: DISTILL" in m for m in msgs)
    assert any("PHASE 3/3: CONSISTENCY CHECK" in m for m in msgs)

    # Each fetch is logged
    assert any("Fetching" in m and "/about" in m for m in msgs)
    # Per-page byte/link stats
    assert any("HTTP 200" in m and "links found" in m for m in msgs)
    # robots.txt is mentioned
    assert any("robots.txt" in m for m in msgs)
    # External links are reported as skipped (debug)
    assert any("external domain" in m for m in msgs)
    # Distillation detail
    assert any("Distilled" in m and "bytes" in m for m in msgs)
    # Date extraction detail
    assert any("date mention" in m.lower() for m in msgs)
    # Summary at the end
    assert any(m.startswith("DONE.") for m in msgs)


def test_quiet_mode_hides_debug(server, tmp_path):
    events = run_and_collect(server, tmp_path, verbose=False)
    msgs = messages(events)
    # Info-level narration still present
    assert any("PHASE 1/3: CRAWL" in m for m in msgs)
    # But no debug-level chatter (per-URL distill stats, skip reasons)
    assert not any("external domain" in m for m in msgs)
    assert not any("bytes HTML ->" in m for m in msgs)
    # No debug events at all
    assert all(e.level != "debug" for e in events)


def test_crawl_summary_counts(server, tmp_path):
    events = run_and_collect(server, tmp_path, verbose=True)
    msgs = messages(events)
    assert any("Crawl finished:" in m and "pages fetched" in m for m in msgs)
