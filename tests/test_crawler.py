from checkit.crawler import (
    extract_links,
    is_html_url,
    is_same_domain,
    normalize_url,
)


def test_normalize_url_strips_fragment_and_space():
    assert normalize_url(" https://x.example/a#section ") == "https://x.example/a"


def test_is_same_domain():
    assert is_same_domain("https://x.example/a", "x.example")
    assert is_same_domain("https://X.EXAMPLE/a", "x.example")
    assert not is_same_domain("https://other.example/a", "x.example")
    assert not is_same_domain("https://sub.x.example/a", "x.example")


def test_is_html_url_skips_binaries():
    assert is_html_url("https://x.example/page")
    assert is_html_url("https://x.example/")
    assert not is_html_url("https://x.example/logo.png")
    assert not is_html_url("https://x.example/data.pdf")
    assert not is_html_url("https://x.example/app.js")


def test_extract_links_absolute_and_filtered():
    html = """
    <a href="/a">A</a>
    <a href="https://other.example/b">B</a>
    <a href="#frag">C</a>
    <a href="mailto:x@y.z">D</a>
    <a href="javascript:void(0)">E</a>
    <a href="page2#frag">F</a>
    <a>No href</a>
    """
    links = extract_links(html, "https://x.example/dir/index.html")
    assert "https://x.example/a" in links
    assert "https://other.example/b" in links
    assert "https://x.example/dir/page2" in links
    assert not any("#" in link for link in links)
    assert not any(link.startswith(("mailto:", "javascript:")) for link in links)
    assert len(links) == 3
