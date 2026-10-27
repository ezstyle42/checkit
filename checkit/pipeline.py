"""End-to-end pipeline: crawl -> distill -> check."""

from __future__ import annotations

from pathlib import Path

from .checker import CheckReport, check_pages
from .crawler import crawl
from .distiller import distill_page, write_pages
from .llm import LLMClient


def run_pipeline(
    start_url: str,
    out_dir,
    max_pages: int = 100,
    delay: float = 1.0,
    fmt: str = "markdown",
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    use_llm: bool = True,
    respect_robots: bool = True,
    env_file: str = "checkit.env",
    progress=None,
):
    """Crawl, distill to disk, and run the consistency check.

    Returns (distilled_pages, written_files, report).
    """
    def log(msg):
        if progress:
            progress(msg)

    log(f"Crawling {start_url} (max {max_pages} pages)...")
    crawled = crawl(start_url, max_pages=max_pages, delay=delay,
                    respect_robots=respect_robots)
    log(f"Crawled {len(crawled)} pages.")

    pages = []
    for cp in crawled:
        pages.append(distill_page(cp.html, cp.final_url or cp.url))
    log(f"Distilled {len(pages)} pages to {fmt}.")

    out = Path(out_dir)
    written = write_pages(pages, out / "pages", fmt=fmt)
    log(f"Wrote {len(written)} files under {out / 'pages'}.")

    client = None
    if use_llm:
        if not provider:
            raise ValueError("--provider is required when LLM checks are enabled")
        client = LLMClient(provider, api_key=api_key, model=model,
                           env_file=env_file)
        log(f"Checking consistency with {provider} ({client.model})...")
    else:
        log("Checking consistency (deterministic checks only)...")

    report = check_pages(pages, client=client, use_llm=use_llm and client is not None)
    report_path = out / "report.md"
    report_path.write_text(report.to_markdown(), encoding="utf-8")
    log(f"Report written to {report_path}.")
    return pages, written, report
