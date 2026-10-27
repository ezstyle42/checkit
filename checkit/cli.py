"""Command line interface for checkit."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .crawler import crawl
from .distiller import distill_page
from .llm import PROVIDERS
from .logging_util import Logger, cli_sink
from .pipeline import run_pipeline
from .settings import Settings, load_settings, save_settings


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
    p_run.add_argument("--api-key", help="API key (or set the env var / checkit.env / saved settings).")
    p_run.add_argument("--model", help="Model name (defaults per provider).")
    p_run.add_argument("--no-llm", action="store_true",
                       help="Skip LLM checks; run deterministic checks only.")
    p_run.add_argument("--format", choices=("markdown", "xml"), default=None,
                       help="Output format for distilled pages.")
    p_run.add_argument("--verbose", "-v", action="store_true",
                       help="Verbose logging: every fetch, skip, LLM call and finding.")
    p_run.add_argument("--save-settings", action="store_true",
                       help="Save the given options (and --api-key) to the "
                            "user settings file for future runs / the GUI.")
    p_run.set_defaults(func=_cmd_run)

    p_crawl = sub.add_parser("crawl", help="Crawl only; print discovered URLs.")
    _add_common(p_crawl)
    p_crawl.add_argument("--verbose", "-v", action="store_true",
                         help="Verbose logging: every fetch, skip and robots decision.")
    p_crawl.set_defaults(func=_cmd_crawl)

    p_distill = sub.add_parser("distill", help="Distill an HTML file to markdown/XML.")
    p_distill.add_argument("html_file")
    p_distill.add_argument("--url", default="", help="Source URL recorded in output.")
    p_distill.add_argument("--format", choices=("markdown", "xml"), default="markdown")
    p_distill.add_argument("--verbose", "-v", action="store_true")
    p_distill.set_defaults(func=_cmd_distill)

    p_settings = sub.add_parser("settings", help="Show or edit saved settings.")
    p_settings.add_argument("--show", action="store_true",
                            help="Print saved settings (API keys masked).")
    p_settings.add_argument("--set", nargs="+", metavar="KEY=VALUE",
                            help="Set settings, e.g. --set provider=openai max_pages=50")
    p_settings.add_argument("--path", action="store_true",
                            help="Print the settings file path.")
    p_settings.set_defaults(func=_cmd_settings)

    return parser


def _add_common(p):
    p.add_argument("url", help="Start URL of the website to crawl.")
    p.add_argument("--out", default=None, help="Output directory.")
    p.add_argument("--max-pages", type=int, default=None)
    p.add_argument("--delay", type=float, default=None,
                   help="Politeness delay between requests (seconds).")
    p.add_argument("--allow-robots-disabled", action="store_true",
                   help="Crawl even if robots.txt disallows (use responsibly).")


def _merge_with_settings(args, saved: Settings) -> None:
    """Fill unset CLI options from saved settings."""
    if getattr(args, "out", None) is None:
        args.out = saved.out_dir
    if getattr(args, "max_pages", None) is None:
        args.max_pages = saved.max_pages
    if getattr(args, "delay", None) is None:
        args.delay = saved.delay
    if getattr(args, "format", None) is None:
        args.format = saved.fmt
    if getattr(args, "provider", None) is None:
        args.provider = saved.provider if saved.use_llm else None
    if getattr(args, "no_llm", False):
        args.provider = None
    args.verbose = bool(getattr(args, "verbose", False)) or saved.verbose


def _cmd_run(args):
    saved = load_settings()
    _merge_with_settings(args, saved)

    if args.save_settings:
        saved.url = args.url
        saved.out_dir = args.out
        saved.max_pages = args.max_pages
        saved.delay = args.delay
        saved.fmt = args.format
        saved.use_llm = not args.no_llm
        if args.provider:
            saved.provider = args.provider
        if args.model:
            saved.model = args.model
        saved.verbose = args.verbose
        if args.api_key and args.provider:
            saved.api_keys[args.provider] = args.api_key
        path = save_settings(saved)
        print(f"Settings saved to {path}", file=sys.stderr)

    logger = Logger(sink=cli_sink(), verbose=args.verbose)
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
        verbose=args.verbose,
        settings=saved,
        logger=logger,
    )
    print()
    print(report.to_markdown())
    return 0 if report.ok else 1


def _cmd_crawl(args):
    saved = load_settings()
    if args.max_pages is None:
        args.max_pages = saved.max_pages
    if args.delay is None:
        args.delay = saved.delay
    logger = Logger(sink=cli_sink(), verbose=args.verbose)
    pages = crawl(args.url, max_pages=args.max_pages, delay=args.delay,
                  respect_robots=not args.allow_robots_disabled,
                  logger=logger)
    print(file=sys.stderr)
    for page in pages:
        print(f"{page.status_code}\t{page.final_url}")
    print(f"\n{len(pages)} pages crawled.", file=sys.stderr)
    return 0


def _cmd_distill(args):
    logger = Logger(sink=cli_sink(), verbose=args.verbose)
    html = open(args.html_file, encoding="utf-8").read()
    page = distill_page(html, args.url, logger)
    if args.format == "xml":
        print(page.xml)
    else:
        print(page.markdown)
    return 0


def _cmd_settings(args):
    from .settings import settings_path

    if args.path:
        print(settings_path())
        return 0

    s = load_settings()

    if args.set:
        valid = {f for f in Settings.__dataclass_fields__}
        for item in args.set:
            if "=" not in item:
                print(f"Invalid setting {item!r}; use KEY=VALUE", file=sys.stderr)
                return 2
            key, _, value = item.partition("=")
            if key not in valid:
                print(f"Unknown setting {key!r}; choose from {sorted(valid)}",
                      file=sys.stderr)
                return 2
            field_type = Settings.__dataclass_fields__[key].type
            if key in ("max_pages",):
                value = int(value)
            elif key in ("delay",):
                value = float(value)
            elif key in ("use_llm", "verbose"):
                value = value.lower() in ("1", "true", "yes", "on")
            elif key == "api_keys":
                value = __import__("json").loads(value)
            setattr(s, key, value)
        path = save_settings(s)
        print(f"Settings saved to {path}", file=sys.stderr)

    if args.show or args.set:
        d = s.to_dict()
        d["api_keys"] = {k: ("••••" + v[-4:]) if v else "" for k, v in s.api_keys.items()}
        import json
        print(json.dumps(d, indent=2))
    else:
        print("Usage: checkit settings --show | --path | --set KEY=VALUE ...",
              file=sys.stderr)
        print(f"Settings file: {settings_path()}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
