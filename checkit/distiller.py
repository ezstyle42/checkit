"""Distill crawled HTML pages into LLM-optimized markdown or XML."""

from __future__ import annotations

import hashlib
import html as html_module
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from .logging_util import Logger

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}

DROP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe",
             "form", "button", "nav", "footer", "aside"}

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


@dataclass
class DistilledPage:
    url: str
    title: str
    markdown: str
    xml: str


def slugify_url(url: str) -> str:
    """Turn a URL into a filesystem-safe slug."""
    parsed = urlparse(url)
    path = parsed.path.strip("/") or "index"
    path = re.sub(r"[^A-Za-z0-9._-]+", "-", path).strip("-").lower()
    host = re.sub(r"[^a-z0-9.-]+", "-", parsed.netloc.lower()).strip("-")
    slug = f"{host}__{path}" if path != "index" else f"{host}__index"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:120]}__{digest}"


def html_to_markdown(html: str, url: str = "", logger: Logger | None = None) -> tuple:
    """Convert HTML to (title, markdown). Compact, LLM-friendly output."""
    log = logger or Logger()
    soup = BeautifulSoup(html, "html.parser")
    dropped = 0
    for tag in soup.find_all(list(DROP_TAGS)):
        dropped += 1
        tag.decompose()

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""

    main = soup.find("main") or soup.find("article") or soup.body or soup

    lines: list = []
    if title:
        lines.append(f"# {title}")
        lines.append("")
    if url:
        lines.append(f"Source: {url}")
        lines.append("")

    def inline_text(node: Tag) -> str:
        out = []
        for child in node.children:
            if isinstance(child, NavigableString):
                out.append(str(child))
            elif isinstance(child, Tag):
                if child.name in ("strong", "b"):
                    out.append(f"**{inline_text(child)}**")
                elif child.name in ("em", "i"):
                    out.append(f"*{inline_text(child)}*")
                elif child.name == "a" and child.get("href"):
                    text = inline_text(child).strip()
                    if text:
                        out.append(f"[{text}]({child['href']})")
                elif child.name == "code":
                    out.append(f"`{child.get_text()}`")
                elif child.name == "br":
                    out.append("\n")
                else:
                    out.append(inline_text(child))
        return re.sub(r"[ \t]+", " ", "".join(out))

    def emit_block(block: Tag) -> None:
        name = block.name
        text = re.sub(r"\s+", " ", inline_text(block)).strip()
        if not text:
            return
        if name in HEADING_TAGS:
            level = int(name[1])
            if level == 1 and title and text == title:
                return
            lines.append("")
            lines.append(f"{'#' * level} {text}")
            lines.append("")
        elif name in ("p", "div", "section", "article", "header", "main"):
            lines.append(text)
            lines.append("")
        elif name == "li":
            lines.append(f"- {text}")
        elif name in ("tr",):
            cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True))
                     for c in block.find_all(["td", "th"])]
            if cells:
                lines.append("| " + " | ".join(cells) + " |")
        elif name in ("ul", "ol"):
            for li in block.find_all("li", recursive=False):
                emit_block(li)
            lines.append("")
        elif name == "table":
            rows = block.find_all("tr")
            if rows:
                header_cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True))
                                for c in rows[0].find_all(["th", "td"])]
                if header_cells:
                    lines.append("| " + " | ".join(header_cells) + " |")
                    lines.append("|" + "|".join([" --- "] * len(header_cells)) + "|")
                    rows = rows[1:]
                for row in rows:
                    cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True))
                             for c in row.find_all(["td", "th"])]
                    if cells:
                        lines.append("| " + " | ".join(cells) + " |")
                lines.append("")
        elif name in ("blockquote", "pre"):
            lines.append("")
            lines.append("> " + text.replace("\n", "\n> "))
            lines.append("")

    for child in main.children:
        if isinstance(child, NavigableString):
            text = re.sub(r"\s+", " ", str(child)).strip()
            if text:
                lines.append(text)
                lines.append("")
        elif isinstance(child, Tag):
            if child.name in VOID_TAGS:
                continue
            emit_block(child)

    markdown = "\n".join(lines)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"
    words = len(markdown.split())
    log.debug(
        f"Distilled {url or '(no url)'}: title={title!r}, dropped {dropped} "
        f"boilerplate tags, {len(html)} bytes HTML -> {len(markdown)} bytes "
        f"markdown (~{words} words)"
    )
    return title, markdown


def markdown_to_xml(title: str, url: str, markdown: str) -> str:
    """Wrap page markdown in a small XML document for LLM consumption."""
    def esc(text: str) -> str:
        return html_module.escape(text, quote=False)

    body = esc(markdown)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<page>\n"
        f"  <url>{esc(url)}</url>\n"
        f"  <title>{esc(title)}</title>\n"
        f"  <content>{body}</content>\n"
        "</page>\n"
    )


def distill_page(html: str, url: str, logger: Logger | None = None) -> DistilledPage:
    title, markdown = html_to_markdown(html, url, logger)
    xml = markdown_to_xml(title, url, markdown)
    return DistilledPage(url=url, title=title, markdown=markdown, xml=xml)


def write_pages(pages, out_dir, fmt: str = "markdown",
                logger: Logger | None = None) -> list:
    """Write one file per page. Returns list of written file paths."""
    log = logger or Logger()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ext = ".md" if fmt == "markdown" else ".xml"
    written = []
    for page in pages:
        path = out / f"{slugify_url(page.url)}{ext}"
        path.write_text(page.markdown if fmt == "markdown" else page.xml,
                        encoding="utf-8")
        written.append(path)
        log.debug(f"Wrote {path.name} ({path.stat().st_size} bytes) for {page.url}")
    index = out / "index.md"
    lines = ["# Crawled pages", ""]
    for page in pages:
        lines.append(f"- [{page.title or page.url}]({slugify_url(page.url)}{ext}) — {page.url}")
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    written.append(index)
    log.info(f"Wrote {len(written)} files to {out} ({fmt} format).")
    return written
