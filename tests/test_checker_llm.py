"""LLM-layer tests with a stubbed client (no network)."""

from checkit.checker import cross_check_claims, extract_claims
from checkit.distiller import DistilledPage


class StubClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))

        class R:
            text = self.responses.pop(0)
        return R()


def page(url, md):
    return DistilledPage(url=url, title=url, markdown=md, xml="")


def test_extract_claims_parses_json_and_tags_page():
    client = StubClient(['[{"claim": "Founded in 2001", "type": "date", "value": "2001"}]'])
    claims = extract_claims(client, page("https://x/a", "# A\nFounded in 2001."))
    assert claims == [{"claim": "Founded in 2001", "type": "date",
                       "value": "2001", "page": "https://x/a"}]


def test_extract_claims_handles_prose_wrapped_json():
    client = StubClient(['Here you go:\n[{"claim": "c", "type": "fact", "value": "v"}]\nDone.'])
    claims = extract_claims(client, page("https://x/a", "# A"))
    assert claims[0]["claim"] == "c"


def test_extract_claims_empty_when_no_claims():
    client = StubClient(['[]'])
    assert extract_claims(client, page("https://x/a", "# A")) == []


def test_cross_check_claims_builds_findings():
    client = StubClient([
        '[{"severity": "high", "kind": "contradiction",'
        ' "pages": ["https://x/a", "https://x/b"],'
        ' "description": "Page A says founded 2001, page B says 2005.",'
        ' "evidence": "founded in 2001 / founded in 2005"}]'
    ])
    claims = {
        "https://x/a": [{"claim": "Founded in 2001", "type": "date", "value": "2001"}],
        "https://x/b": [{"claim": "Founded in 2005", "type": "date", "value": "2005"}],
    }
    findings = cross_check_claims(client, claims)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "high"
    assert f.kind == "contradiction"
    assert f.pages == ["https://x/a", "https://x/b"]
    assert "2001" in f.description and "2005" in f.description


def test_cross_check_claims_skips_pages_without_claims():
    client = StubClient(['[]'])
    findings = cross_check_claims(client, {"https://x/a": []})
    assert findings == []
    assert client.calls == []  # no LLM call when there is nothing to check


def test_check_pages_with_llm_counts_claims(tmp_path):
    from checkit.checker import check_pages

    client = StubClient([
        '[{"claim": "c1", "type": "fact", "value": "v"}]',  # page a
        '[{"claim": "c2", "type": "fact", "value": "v"}]',  # page b
        '[{"severity": "medium", "kind": "number_mismatch",'
        ' "pages": ["https://x/a", "https://x/b"], "description": "d"}]',
    ])
    pages = [page("https://x/a", "# A"), page("https://x/b", "# B")]
    report = check_pages(pages, client=client, use_llm=True)
    assert report.claims_extracted == 2
    assert any(f.kind == "number_mismatch" for f in report.findings)
