"""Command line interface for checkit."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .crawler import crawl
from .distiller import distill_page, write_pages
from .llm import PROVIDERS
from .pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="checkit",
        description="Crawl a website, distill pages to LLM-optimized files, "
                    "and audit the content for internal consistency.",
    )
    parser.add_argument("--version", action="version",
                        version=f"checkit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Crawl, distill and check in one go.")
    _add_common(p_run)
    p_run.add_argument("--provider", choices=PROVIDERS,
                       help="LLM provider for the consistency check.")
    p_run.add_argument("--api-key", help="API key (or set the env var / checkit.env).")
    p_run.add_argument("--model", help="Model name (defaults per provider).")
    p_run.add_argument("--no-llm", action="store_true",
                       help="Skip LLM checks; run deterministic checks only.")
    p_run.add_argument("--format", choices=("markdown", "xml"), default="markdown",
                       help="Output format for distilled pages.")
    p_run.set_defaults(func=_cmd_run)

    p_crawl = sub.add_parser("crawl", help="Crawl only; print discovered URLs.")
    _add_common(p_crawl)
    p_crawl.set_defaults(func=_cmd_crawl)

    p_distill = sub.add_parser("distill", help="Distill an HTML file to markdown/XML.")
    p_distill.add_argument("html_file")
    p_distill.add_argument("--url", default="", help="Source URL recorded in output.")
    p_distill.add_argument("--format", choices=("markdown", "xml"), default="markdown")
    p_distill.set_defaults(func=_cmd_distill)

    return parser


def _add_common(p):
    p.add_argument("url", help="Start URL of the website to crawl.")
    p.add_argument("--out", default="checkit-out", help="Output directory.")
    p.add_argument("--max-pages", type=int, default=100)
    p.add_argument("--delay", type=float, default=1.0,
                   help="Politeness delay between requests (seconds).")
    p.add_argument("--allow-robots-disabled", action="store_true",
                   help="Crawl even if robots.txt disallows (use responsibly).")


def _cmd_run(args):
    pages, written, report = run_pipeline(
        args.url,
        out_dir=args.out,
        max_pages=args.max_pages,
        delay=args.delay,
        fmt=args.format,
        provider=args.provider,
        api_key=args.api_key,
        model=args.model,
        use_llm=not args.no_llm,
        respect_robots=not args.allow_robots_disabled,
        progress=print,
    )
    print()
    print(report.to_markdown())
    return 0 if report.ok else 1


def _cmd_crawl(args):
    pages = crawl(args.url, max_pages=args.max_pages, delay=args.delay,
                  respect_robots=not args.allow_robots_disabled)
    for page in pages:
        print(f"{page.status_code}\t{page.final_url}")
    print(f"\n{len(pages)} pages crawled.", file=sys.stderr)
    return 0


def _cmd_distill(args):
    html = open(args.html_file, encoding="utf-8").read()
    page = distill_page(html, args.url)
    if args.format == "xml":
        print(page.xml)
    else:
        print(page.markdown)
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
