# checkit

Crossplatform (Linux / Windows / macOS) application — **GUI desktop app and CLI** — that:

1. **Crawls** a website (same-domain, robots.txt-aware, polite rate limiting).
2. **Distills** every page into a compact, LLM-optimized **markdown** or **XML** file (one file per page).
3. **Checks** the site's content against itself: statements on different pages are compared for contradictions, dates mentioned across the site are extracted and cross-checked, and duplicates are flagged. A detailed report is produced.

LLM-powered claim extraction and contradiction detection supports **Mistral**, **OpenAI** and **Claude (Anthropic)**. Deterministic checks (dates, duplicates) run without any API key.

## Download the app (no Python needed)

Grab a **self-contained executable** for your OS from the
[Releases page](https://github.com/ezstyle42/checkit/releases):

| OS | File | How to run |
| --- | --- | --- |
| Linux | `checkit-linux-x64.tar.gz` | extract, then `./checkit` |
| Windows | `checkit-windows-x64.zip` | extract, double-click `checkit.exe` |
| macOS | `checkit-macos.zip` | extract, double-click `checkit.app` |

The app bundles Python and all dependencies — nothing to install. The GUI
lets you enter a URL, configure the crawl and LLM provider, watch live
progress, cancel, and read the rendered report.

## Install from source / PyPI

```bash
pip install .            # CLI + GUI (pywebview)
checkit-gui              # launch the desktop app
# or without installing:
python -m checkit.gui    # GUI
python -m checkit --help # CLI
```

Requires Python 3.9+. Runtime dependencies: `requests`, `beautifulsoup4`, `pywebview`.

## API keys

Provide keys in any of these ways (checked in this order):

1. The **API key field** in the GUI (or `--api-key` CLI flag)
2. Environment variables: `MISTRAL_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
3. A `checkit.env` file in the working directory:

```
MISTRAL_API_KEY=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
```

## CLI usage

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

### CLI options

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
- **LLM layer** (with a provider): extracts checkable factual claims per page (dates, numbers, names, facts), then cross-references all claims across pages to find contradictions, date mismatches, number mismatches and factual errors. Findings are reported with severity, kind, involved pages and evidence quotes.

## Building the app yourself

The self-contained executables are built with PyInstaller:

```bash
pip install -e ".[build]"   # installs pyinstaller
pyinstaller packaging/checkit.spec --distpath dist-app --workpath build-app --noconfirm
# -> dist-app/checkit (Linux/Windows) or dist-app/checkit.app (macOS)
```

## Releases

Releases are automated via GitHub Actions:

- Pushing to `main` or a `v*` tag triggers the **release build** workflow:
  runs tests, builds the Python sdist/wheel, and builds the **GUI executables
  for Linux, Windows and macOS** with PyInstaller.
- On tag pushes, a GitHub release is created with the wheel/sdist **and** the
  three GUI artifacts attached.
- Publishing that release triggers the **PyPI publish** workflow (trusted
  publishing, no token).

See `.github/workflows/README.md` for the one-time PyPI trusted-publisher
setup. After that, `pip install checkit` works for every release.

## Development

```bash
pip install -e ".[test]"
pytest
```

## License

MIT
