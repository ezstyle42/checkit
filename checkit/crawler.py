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

    def __init__(self, session: requests.Session, user_agent: str):
        self._session = session
        self._user_agent = user_agent
        self._cache: dict = {}

    def allows(self, url: str) -> bool:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc not in self._cache:
            rp = RobotFileParser()
            rp.set_url(f"{parsed.scheme}://{netloc}/robots.txt")
            try:
                resp = self._session.get(
                    rp.url, timeout=10, headers={"User-Agent": self._user_agent}
                )
                if resp.status_code in (401, 403):
                    rp.disallow_all = True
                elif resp.status_code >= 400:
                    rp.allow_all = True
                else:
                    rp.parse(resp.text.splitlines())
            except requests.RequestException:
                rp.allow_all = True
            self._cache[netloc] = rp
        return self._cache[netloc].can_fetch(self._user_agent, url)


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
) -> list:
    """Breadth-first crawl of same-domain HTML pages.

    Returns a list of CrawledPage in visit order. If `cancel_event` is set,
    the crawl stops early and returns the pages gathered so far.
    """
    start_url = normalize_url(start_url)
    base = urlparse(start_url)
    base_netloc = base.netloc

    own = session is None
    sess = session or requests.Session()
    sess.headers.update({"User-Agent": user_agent})
    robots = RobotsCache(sess, user_agent)

    seeds = [start_url] + [normalize_url(s) for s in extra_seed_urls]
    seen = {s for s in seeds if is_same_domain(s, base_netloc)}

    queue = deque(seeds)
    pages: list = []

    def cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    try:
        while queue and len(pages) < max_pages:
            if cancelled():
                break
            url = queue.popleft()
            if respect_robots and not robots.allows(url):
                continue
            if not is_html_url(url):
                continue
            try:
                resp = sess.get(url, timeout=timeout, allow_redirects=True)
            except requests.RequestException:
                continue
            final_url = normalize_url(resp.url)
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype.lower():
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
            for link in page.links:
                if not is_same_domain(link, base_netloc):
                    continue
                if link in seen:
                    continue
                seen.add(link)
                queue.append(link)
            if queue and delay > 0 and not cancelled():
                # Sleep in small slices so cancellation stays responsive.
                waited = 0.0
                while waited < delay and not cancelled():
                    time.sleep(min(0.1, delay - waited))
                    waited += 0.1
    finally:
        if own:
            sess.close()

    return pages
