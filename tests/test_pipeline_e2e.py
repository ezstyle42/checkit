"""End-to-end test: crawl a local site, distill, run deterministic checks."""

import functools
import http.server
import threading

import pytest

from checkit.pipeline import run_pipeline

SITE = {
    "/": """
    <html><head><title>Home</title></head><body><main>
    <h1>Home</h1>
    <p>Acme was founded in 2001.</p>
    <a href="/about">About</a><a href="/product">Product</a>
    </main></body></html>
    """,
    "/about": """
    <html><head><title>About</title></head><body><main>
    <h1>About us</h1>
    <p>Acme was founded in 2005.</p>
    <p>We launched our first product on March 15, 2010.</p>
    </main></body></html>
    """,
    "/product": """
    <html><head><title>Product</title></head><body><main>
    <h1>Widget</h1>
    <p>The Widget costs 10 EUR and was released on 2010-03-15.</p>
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


def test_full_pipeline_local_site(server, tmp_path):
    pages, written, report = run_pipeline(
        f"{server}/",
        out_dir=tmp_path,
        max_pages=10,
        delay=0,
        fmt="markdown",
        use_llm=False,
    )
    assert len(pages) == 3
    urls = {p.url for p in pages}
    assert f"{server}/about" in urls

    pages_dir = tmp_path / "pages"
    md_files = list(pages_dir.glob("*.md"))
    assert len(md_files) == 4  # 3 pages + index.md
    assert (pages_dir / "index.md").exists()

    report_md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Pages checked: 3" in report_md
    isos = {d.iso for d in report.date_mentions}
    # "founded in 2001" / "founded in 2005" are bare years (no full date),
    # the two full dates for the product launch must both be extracted.
    assert "2010-03-15" in isos
    assert len(report.date_mentions) == 2


def test_pipeline_xml_format(server, tmp_path):
    pages, written, report = run_pipeline(
        f"{server}/",
        out_dir=tmp_path,
        max_pages=10,
        delay=0,
        fmt="xml",
        use_llm=False,
    )
    xml_files = list((tmp_path / "pages").glob("*.xml"))
    assert len(xml_files) == 3
    content = xml_files[0].read_text(encoding="utf-8")
    assert content.startswith("<?xml")
