from checkit.checker import (
    Finding,
    _parse_json_array,
    check_date_consistency,
    check_pages,
    extract_dates,
    find_duplicate_content,
)
from checkit.distiller import DistilledPage


def page(url, md):
    return DistilledPage(url=url, title=url, markdown=md, xml="")


class TestExtractDates:
    def test_iso_dates(self):
        mentions = extract_dates("Released on 2024-03-15.", "https://x/")
        assert len(mentions) == 1
        assert mentions[0].iso == "2024-03-15"
        assert mentions[0].raw == "2024-03-15"

    def test_written_dates(self):
        mentions = extract_dates("Founded March 15, 1998 and 5 April 2001.", "https://x/")
        isos = sorted(m.iso for m in mentions)
        assert isos == ["1998-03-15", "2001-04-05"]

    def test_day_first_written_dates(self):
        mentions = extract_dates("On 15 March 1998 it started.", "https://x/")
        assert mentions[0].iso == "1998-03-15"

    def test_invalid_dates_ignored(self):
        assert extract_dates("On 2024-13-45 nothing.", "https://x/") == []
        assert extract_dates("No dates here.", "https://x/") == []

    def test_context_included(self):
        mentions = extract_dates(
            "The company was founded on 15 June 2001 in Berlin.", "https://x/")
        assert mentions[0].iso == "2001-06-15"
        assert "founded" in mentions[0].context


class TestDateConsistency:
    def test_ambiguous_same_raw_different_parse(self):
        mentions = extract_dates("a 03/04/2024", "https://x/") + \
            extract_dates("b 2024-04-03", "https://x/")
        # craft raw collision explicitly
        from checkit.checker import DateMention
        mentions = [
            DateMention(raw="03/04/2024", iso="2024-03-04", url="https://x/a",
                        context=""),
            DateMention(raw="03/04/2024", iso="2024-04-03", url="https://x/b",
                        context=""),
        ]
        findings = check_date_consistency(mentions)
        assert len(findings) == 1
        assert findings[0].kind == "date_mismatch"
        assert findings[0].severity == "medium"

    def test_consistent_dates_no_findings(self):
        mentions = extract_dates("2024-01-01 and 2024-01-01", "https://x/")
        assert check_date_consistency(mentions) == []


class TestDuplicateContent:
    def test_near_duplicates_flagged(self):
        md = "# Same\n" + ("lorem ipsum dolor sit amet " * 50)
        pages = [page("https://x/a", md), page("https://x/b", md)]
        findings = find_duplicate_content(pages, threshold=0.9)
        assert len(findings) == 1
        assert findings[0].severity == "low"

    def test_distinct_pages_not_flagged(self):
        pages = [page("https://x/a", "# A\nCompletely different text about cats."),
                 page("https://x/b", "# B\nA page all about quantum physics and dogs.")]
        assert find_duplicate_content(pages) == []


class TestParseJsonArray:
    def test_plain_array(self):
        assert _parse_json_array('[{"a": 1}]') == [{"a": 1}]

    def test_array_in_prose(self):
        text = 'Sure! Here are the findings:\n[{"x": 2}]\nHope that helps.'
        assert _parse_json_array(text) == [{"x": 2}]

    def test_empty_on_garbage(self):
        assert _parse_json_array("no json here") == []
        assert _parse_json_array("[]") == []


class TestCheckPagesDeterministic:
    def test_report_without_llm(self):
        pages = [
            page("https://x/a", "# A\nFounded on 2001-06-15."),
            page("https://x/b", "# B\nFounded on 2005-01-10. Same company."),
        ]
        report = check_pages(pages, client=None, use_llm=False)
        assert report.pages_checked == 2
        assert len(report.date_mentions) == 2
        assert isinstance(report.to_markdown(), str)
        assert "Dates mentioned" in report.to_markdown()

    def test_report_marksdown_sections(self):
        report = check_pages([page("https://x/a", "# A\nnothing")],
                             client=None, use_llm=False)
        md = report.to_markdown()
        assert md.startswith("# CheckIt consistency report")
        assert "No inconsistencies found." in md

    def test_high_severity_finding_fails_report(self):
        report = check_pages([], client=None, use_llm=False)
        report.findings.append(Finding("high", "contradiction", [], "boom"))
        assert not report.ok
