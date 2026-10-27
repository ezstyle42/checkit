# checkit

Crossplatform (Linux / Windows / macOS) command line tool that:

1. **Crawls** a website (same-domain, robots.txt-aware, polite rate limiting).
2. **Distills** every page into a compact, LLM-optimized **markdown** or **XML** file (one file per page).
3. **Checks** the site's content against itself: statements on different pages are compared for contradictions, dates mentioned across the site are extracted and cross-checked, and duplicates are flagged. A detailed markdown report is produced.

LLM-powered claim extraction and contradiction detection supports **Mistral**, **OpenAI** and **Claude (Anthropic)**. Deterministic checks (dates, duplicates) run without any API key.

## Install

```bash
pip install .
# or run without installing:
python -m checkit --help
```

Requires Python 3.9+. Only runtime dependencies: `requests` and `beautifulsoup4`.

## API keys

Provide keys in any of these ways (checked in this order):

1. `--api-key` CLI flag
2. Environment variables: `MISTRAL_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
3. A `checkit.env` file in the working directory:

```
MISTRAL_API_KEY=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
```

## Usage

Full pipeline (crawl + distill + check):

```bash
checkit run https://example.com --out checkit-out \
    --provider mistral --format markdown --max-pages 50 --delay 1
```

Deterministic checks only (no API key needed):

```bash
checkit run https://example.com --no-llm
```

Crawl only:

```bash
checkit crawl https://example.com --max-pages 200
```

Distill a single HTML file:

```bash
checkit distill page.html --url https://example.com/page --format xml
```

### Options

| Option | Description |
| --- | --- |
| `--provider {mistral,openai,claude}` | LLM provider for the consistency audit |
| `--api-key KEY` | API key (overrides env var / `checkit.env`) |
| `--model NAME` | Model override (sensible default per provider) |
| `--no-llm` | Skip LLM checks; deterministic checks only |
| `--format {markdown,xml}` | Distilled page format |
| `--max-pages N` | Crawl page limit (default 100) |
| `--delay SECONDS` | Politeness delay between requests (default 1.0) |
| `--allow-robots-disabled` | Crawl even when robots.txt disallows (use responsibly) |

## Output layout

```
checkit-out/
  pages/
    <host>__<path>__<hash>.md   # one distilled file per page
    index.md                    # index of all pages
  report.md                     # consistency report
```

Exit code is `0` when no high-severity findings exist, `1` otherwise.

## How the check works

- **Deterministic layer** (always on, no key needed): extracts every date mentioned on every page (ISO, day-first, and written-out formats), flags ambiguous date formats that parse differently, and detects near-duplicate pages.
- **LLM layer** (with `--provider`): extracts checkable factual claims per page (dates, numbers, names, facts), then cross-references all claims across pages to find contradictions, date mismatches, number mismatches and factual errors. Findings are reported with severity, kind, involved pages and evidence quotes.

## Releases

Releases are automated via GitHub Actions:

- Pushing to `main` or a `v*` tag triggers the **release build** workflow
  (tests, sdist/wheel artifacts, GitHub release on tag push).
- Publishing a GitHub release triggers the **PyPI publish** workflow
  (tests, build, upload to PyPI via trusted publishing).

See `.github/workflows/README.md` for the one-time PyPI trusted-publisher
setup. After that, `pip install checkit` works for every release.

## Development

```bash
pip install -e ".[test]"
pytest
```

## License

MIT
