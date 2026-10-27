"""Polite same-domain website crawler."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from .logging_util import Logger

DEFAULT_USER_AGENT = "checkit-crawler/0.1 (+https://github.com/ezstyle42/checkit)"

SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".css", ".js",
    ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip", ".gz", ".mp3",
    ".mp4", ".webm", ".mov", ".csv", ".json", ".xml",
}


@dataclass
class CrawledPage:
    url: str
    final_url: str
    status_code: int
    content_type: str
    html: str
    fetched_at: float = field(default_factory=time.time)
    links: list = field(default_factory=list)


def normalize_url(url: str) -> str:
    """Strip fragment and trailing whitespace so URLs compare canonically."""
    url, _frag = urldefrag(url.strip())
    return url


def is_same_domain(url: str, base_netloc: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return netloc == base_netloc.lower()


def is_html_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return not any(path.endswith(ext) for ext in SKIP_EXTENSIONS)


def extract_links(html: str, base_url: str) -> list:
    """Return absolute, normalized, same-page-anchor-free http(s) links."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    links = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = normalize_url(urljoin(base_url, href))
        if urlparse(absolute).scheme in ("http", "https"):
            links.append(absolute)
    return links


class RobotsCache:
    """Fetches and caches robots.txt per netloc."""

    def __init__(self, session: requests.Session, user_agent: str,
                 logger: Logger | None = None):
        self._session = session
        self._user_agent = user_agent
        self._cache: dict = {}
        self._log = logger or Logger()

    def allows(self, url: str) -> bool:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc not in self._cache:
            rp = RobotFileParser()
            rp.set_url(f"{parsed.scheme}://{netloc}/robots.txt")
            self._log.debug(f"Fetching robots.txt: {rp.url}")
            try:
                resp = self._session.get(
                    rp.url, timeout=10, headers={"User-Agent": self._user_agent}
                )
                if resp.status_code in (401, 403):
                    rp.disallow_all = True
                    self._log.warning(
                        f"robots.txt returned {resp.status_code} for {netloc}; "
                        "treating all paths as disallowed.")
                elif resp.status_code >= 400:
                    rp.allow_all = True
                    self._log.debug(
                        f"No robots.txt for {netloc} (HTTP {resp.status_code}); "
                        "assuming allowed.")
                else:
                    rp.parse(resp.text.splitlines())
                    self._log.debug(
                        f"Parsed robots.txt for {netloc} "
                        f"({len(resp.text.splitlines())} lines).")
            except requests.RequestException as exc:
                rp.allow_all = True
                self._log.warning(
                    f"Could not fetch robots.txt for {netloc} ({exc}); "
                    "assuming allowed.")
            self._cache[netloc] = rp
        allowed = self._cache[netloc].can_fetch(self._user_agent, url)
        if not allowed:
            self._log.info(f"robots.txt disallows: {url} — skipping")
        return allowed


def crawl(
    start_url: str,
    max_pages: int = 100,
    delay: float = 1.0,
    timeout: float = 30.0,
    respect_robots: bool = True,
    user_agent: str = DEFAULT_USER_AGENT,
    extra_seed_urls: Iterable[str] = (),
    session: requests.Session | None = None,
    cancel_event: threading.Event | None = None,
    logger: Logger | None = None,
) -> list:
    """Breadth-first crawl of same-domain HTML pages.

    Returns a list of CrawledPage in visit order. If `cancel_event` is set,
    the crawl stops early and returns the pages gathered so far.
    """
    log = logger or Logger()
    start_url = normalize_url(start_url)
    base = urlparse(start_url)
    base_netloc = base.netloc

    own = session is None
    sess = session or requests.Session()
    sess.headers.update({"User-Agent": user_agent})
    robots = RobotsCache(sess, user_agent, log)

    seeds = [start_url] + [normalize_url(s) for s in extra_seed_urls]
    seen = {s for s in seeds if is_same_domain(s, base_netloc)}

    queue = deque(seeds)
    pages: list = []

    def cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    log.info(f"Crawl start: {start_url} (same-domain only, max {max_pages} pages, "
             f"delay {delay}s, robots.txt {'respected' if respect_robots else 'ignored'})")
    log.debug(f"User-Agent: {user_agent}")

    skipped_ext = 0
    skipped_domain = 0
    skipped_robots = 0
    errors = 0
    non_html = 0

    try:
        while queue and len(pages) < max_pages:
            if cancelled():
                log.warning("Crawl cancelled by user.")
                break
            url = queue.popleft()
            if not is_html_url(url):
                skipped_ext += 1
                log.debug(f"Skip (not HTML): {url}")
                continue
            if not is_same_domain(url, base_netloc):
                skipped_domain += 1
                log.debug(f"Skip (external domain): {url}")
                continue
            if respect_robots and not robots.allows(url):
                skipped_robots += 1
                continue
            log.info(f"Fetching [{len(pages) + 1}/{max_pages}]: {url}")
            try:
                resp = sess.get(url, timeout=timeout, allow_redirects=True)
            except requests.RequestException as exc:
                errors += 1
                log.warning(f"Fetch failed: {url} — {type(exc).__name__}: {exc}")
                continue
            final_url = normalize_url(resp.url)
            ctype = resp.headers.get("Content-Type", "")
            if final_url != url:
                log.debug(f"Redirected: {url} -> {final_url}")
            if "html" not in ctype.lower():
                non_html += 1
                log.debug(f"Skip (Content-Type {ctype!r}): {final_url}")
                continue
            if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            page = CrawledPage(
                url=url,
                final_url=final_url,
                status_code=resp.status_code,
                content_type=ctype,
                html=resp.text,
            )
            page.links = extract_links(page.html, final_url)
            pages.append(page)
            new_links = 0
            external = 0
            for link in page.links:
                if not is_same_domain(link, base_netloc):
                    external += 1
                    continue
                if link in seen:
                    continue
                seen.add(link)
                queue.append(link)
                new_links += 1
            for link in page.links:
                if not is_same_domain(link, base_netloc):
                    log.debug(f"Skip (external domain): {link}")
            log.info(f"  -> HTTP {resp.status_code}, {len(resp.text)} bytes, "
                     f"{len(page.links)} links found ({new_links} new, "
                     f"{external} external ignored, {len(queue)} queued)")
            if queue and delay > 0 and not cancelled():
                # Sleep in small slices so cancellation stays responsive.
                waited = 0.0
                while waited < delay and not cancelled():
                    time.sleep(min(0.1, delay - waited))
                    waited += 0.1
    finally:
        if own:
            sess.close()

    log.info(
        f"Crawl finished: {len(pages)} pages fetched, "
        f"{errors} fetch errors, {non_html} non-HTML skipped, "
        f"{skipped_robots} robots-disallowed, {skipped_ext} non-HTML files, "
        f"{skipped_domain} external links ignored."
    )
    return pages
