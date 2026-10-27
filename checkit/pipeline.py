"""End-to-end pipeline: crawl -> distill -> check."""

from __future__ import annotations

from pathlib import Path

from .checker import CheckReport, check_pages
from .crawler import crawl
from .distiller import distill_page, write_pages
from .llm import LLMClient
from .logging_util import Logger


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
    verbose: bool = False,
    settings=None,
    logger: Logger | None = None,
    cancel_event=None,
):
    """Crawl, distill to disk, and run the consistency check.

    Returns (distilled_pages, written_files, report).
    """
    log = logger or Logger(verbose=verbose)

    log.info(f"checkit run: {start_url}")
    log.info(f"Output directory: {Path(out_dir).resolve()}")
    log.info(f"Config: max_pages={max_pages}, delay={delay}s, format={fmt}, "
             f"LLM={'on (' + provider + ')' if use_llm and provider else 'off'}"
             f"{', verbose' if verbose else ''}")

    log.info("=" * 60)
    log.info("PHASE 1/3: CRAWL")
    log.info("=" * 60)
    crawled = crawl(start_url, max_pages=max_pages, delay=delay,
                    respect_robots=respect_robots, logger=log,
                    cancel_event=cancel_event)
    if cancel_event is not None and cancel_event.is_set():
        log.warning("Cancelled during crawl.")
    log.info(f"Crawled {len(crawled)} pages.")

    log.info("=" * 60)
    log.info("PHASE 2/3: DISTILL")
    log.info("=" * 60)
    pages = []
    for i, cp in enumerate(crawled):
        pages.append(distill_page(cp.html, cp.final_url or cp.url, log))
        if (i + 1) % 10 == 0 or i + 1 == len(crawled):
            log.info(f"Distilled {i + 1}/{len(crawled)} pages.")
    log.info(f"Distilled {len(pages)} pages to {fmt}.")

    out = Path(out_dir)
    written = write_pages(pages, out / "pages", fmt=fmt, logger=log)
    log.info(f"Wrote {len(written)} files under {out / 'pages'}.")

    log.info("=" * 60)
    log.info("PHASE 3/3: CONSISTENCY CHECK")
    log.info("=" * 60)
    client = None
    if use_llm:
        if not provider:
            raise ValueError("provider is required when LLM checks are enabled")
        log.info(f"Initializing LLM client: {provider} "
                 f"(model={model or 'default'})")
        client = LLMClient(provider, api_key=api_key, model=model,
                           env_file=env_file, settings=settings)
        log.info(f"LLM client ready: {client.provider} / {client.model}")
    else:
        log.info("LLM checks disabled; running deterministic checks only.")

    report = check_pages(pages, client=client,
                         use_llm=use_llm and client is not None,
                         logger=log, cancel_event=cancel_event)
    report_path = out / "report.md"
    report_path.write_text(report.to_markdown(), encoding="utf-8")
    log.info(f"Report written to {report_path.resolve()}.")
    log.info(f"DONE. Pages: {len(pages)}, findings: {len(report.findings)}, "
             f"overall: {'PASS' if report.ok else 'ISSUES FOUND'}.")
    return pages, written, report
