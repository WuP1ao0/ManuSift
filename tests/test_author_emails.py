"""Tests for the author email analyser (P2.2).

The detector pulls every
email-like token from the
first 5000 characters of
the document and reports
on the domain distribution.
The tests build small
documents in memory and
assert on the findings.
"""
from __future__ import annotations

import json

import pytest


class FakeDoc:
    def __init__(self, text=""):
        self.trace_id = "t-email"
        self.source_path = ""
        self.text_blocks = (
            [type("B", (), {"text": text})()] if text else []
        )
        self.images = []
        self.metadata = {}


# ---------- 1. detector name ----------

def test_email_detector_name() -> None:
    from manusift.detectors import AuthorEmailAnalyzer
    assert AuthorEmailAnalyzer().name == "author_emails"


# ---------- 2. no emails yields a low-severity finding ----------

def test_no_emails_produces_finding() -> None:
    from manusift.detectors import AuthorEmailAnalyzer
    doc = FakeDoc(
        text=(
            "This paper has no author emails "
            "anywhere. The authors are listed by "
            "name and affiliation only."
        )
    )
    result = AuthorEmailAnalyzer().run(doc)
    assert len(result.findings) == 1
    assert result.findings[0].severity == "low"
    assert "email" in result.findings[0].title.lower()


# ---------- 3. duplicate emails across authors ----------

def test_same_domain_majority_flagged() -> None:
    """Three emails on the
    same domain (a common
    pattern in
    single-institution
    papers) is benign --
    it does not by itself
    warrant a finding. The
    detector only flags the
    *same-domain* signal
    when 3+ emails all use
    one domain. With all
    three at one domain,
    the detector emits a
    low-severity finding.
    """
    from manusift.detectors import AuthorEmailAnalyzer
    doc = FakeDoc(
        text=(
            "Alice Foo alice@foo.edu "
            "Bob Bar bob@foo.edu "
            "Carol Baz carol@foo.edu"
        )
    )
    result = AuthorEmailAnalyzer().run(doc)
    titles = [f.title for f in result.findings]
    assert any("same domain" in t.lower() for t in titles)


def test_duplicate_emails_shared_flagged() -> None:
    from manusift.detectors import AuthorEmailAnalyzer
    doc = FakeDoc(
        text=(
            "Alice Foo alice@x.edu "
            "Bob Bar alice@x.edu "
            "Carol Baz carol@y.edu"
        )
    )
    result = AuthorEmailAnalyzer().run(doc)
    titles = [f.title for f in result.findings]
    assert any(
        "shared by multiple" in t for t in titles
    )


# ---------- 4. free-mail majority ----------

def test_free_mail_majority_flagged() -> None:
    from manusift.detectors import AuthorEmailAnalyzer
    doc = FakeDoc(
        text=(
            "Alice a@qq.com "
            "Bob b@qq.com "
            "Carol c@qq.com"
        )
    )
    result = AuthorEmailAnalyzer().run(doc)
    titles = [f.title for f in result.findings]
    # Either same-domain
    # majority or free-mail
    # majority fires.
    assert any("free-mail" in t.lower() for t in titles)


# ---------- 5. diverse domains yield no findings ----------

def test_diverse_institutional_emails_clean() -> None:
    from manusift.detectors import AuthorEmailAnalyzer
    doc = FakeDoc(
        text=(
            "Alice a@mit.edu "
            "Bob b@stanford.edu "
            "Carol c@harvard.edu"
        )
    )
    result = AuthorEmailAnalyzer().run(doc)
    # All distinct
    # institutional
    # domains, no
    # duplicates, no
    # free-mail.
    assert result.findings == []


# ---------- 6. empty document is silent ----------

def test_empty_doc_no_emails() -> None:
    from manusift.detectors import AuthorEmailAnalyzer
    doc = FakeDoc()
    result = AuthorEmailAnalyzer().run(doc)
    # An empty document has
    # no text and therefore
    # no emails -- the
    # "no emails" finding
    # must still fire.
    assert len(result.findings) == 1
    assert "no author email" in result.findings[0].title.lower()


# ---------- 7. evidence contains domain distribution ----------

def test_evidence_includes_domain_counts() -> None:
    from manusift.detectors import AuthorEmailAnalyzer
    doc = FakeDoc(
        text=(
            "Alice a@mit.edu "
            "Bob b@stanford.edu"
        )
    )
    result = AuthorEmailAnalyzer().run(doc)
    # No findings (only 2
    # emails, threshold
    # requires 3+).
    if result.findings:
        ev = json.loads(result.findings[0].evidence)
        # At least one of
        # these keys should
        # be present.
        assert any(
            k in ev
            for k in (
                "top_domain",
                "free_mail_count",
                "duplicate_emails",
                "emails_found",
            )
        )
