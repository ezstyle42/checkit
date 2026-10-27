import re

from checkit.distiller import (
    distill_page,
    html_to_markdown,
    markdown_to_xml,
    slugify_url,
)

HTML = """
<html><head><title>Acme Corp</title>
<style>body{color:red}</style>
<script>track()</script>
</head><body>
<nav><a href="/products">Products</a></nav>
<main>
<h1>Welcome to Acme</h1>
<p>Founded in <strong>1998</strong> by <em>Jane Doe</em>.</p>
<p>Read the <a href="/about">about page</a>.</p>
<ul><li>Widgets</li><li>Gadgets</li></ul>
<table>
<tr><th>Product</th><th>Price</th></tr>
<tr><td>Widget</td><td>10 EUR</td></tr>
</table>
</main>
<footer>Copyright 2024</footer>
</body></html>
"""


def test_html_to_markdown_extracts_structure():
    title, md = html_to_markdown(HTML, "https://acme.example/")
    assert title == "Acme Corp"
    assert "# Acme Corp" in md
    assert "# Welcome to Acme" in md
    assert "Founded in **1998** by *Jane Doe*." in md
    assert "[about page](/about)" in md
    assert "- Widgets" in md and "- Gadgets" in md
    assert "| Product | Price |" in md
    assert "| Widget | 10 EUR |" in md


def test_html_to_markdown_drops_noise():
    _title, md = html_to_markdown(HTML)
    assert "track()" not in md
    assert "color:red" not in md
    assert "Copyright 2024" not in md  # footer dropped
    assert "Products" not in md  # nav dropped


def test_html_to_markdown_records_source_url():
    _title, md = html_to_markdown(HTML, "https://acme.example/page")
    assert "Source: https://acme.example/page" in md


def test_slugify_url_is_stable_and_unique():
    a = slugify_url("https://acme.example/products/list?page=2")
    b = slugify_url("https://acme.example/products/list?page=2")
    c = slugify_url("https://acme.example/other")
    assert a == b
    assert a != c
    assert re.fullmatch(r"[a-z0-9._-]+", a)


def test_distill_page_produces_markdown_and_xml():
    page = distill_page(HTML, "https://acme.example/")
    assert page.title == "Acme Corp"
    assert page.markdown.startswith("# Acme Corp")
    assert page.xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<url>https://acme.example/</url>" in page.xml
    assert "<title>Acme Corp</title>" in page.xml


def test_markdown_to_xml_escapes_content():
    xml = markdown_to_xml("T <&>", "https://x.example/", "a & b < c")
    assert "T &lt;&amp;&gt;" in xml
    assert "a &amp; b &lt; c" in xml
