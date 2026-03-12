from nodes.responder import format_comment, build_summary
from models.schemas import Finding


def make_finding(severity="High", pattern="ORM call inside loop"):
    return Finding(
        file="app.py", line=42, snippet="db.query()",
        pattern=pattern, explanation="N+1 query detected",
        suggested_fix="Use bulk query", severity=severity,
    )


def test_format_comment_high():
    """High severity comment should have red badge."""
    finding = make_finding(severity="High")
    comment = format_comment(finding)
    assert "🔴" in comment
    assert "HIGH" in comment
    assert "N+1 query detected" in comment
    assert "Use bulk query" in comment
    print("✅ High severity comment formatted correctly!")


def test_format_comment_low():
    """Low severity comment should have green badge."""
    finding = make_finding(severity="Low")
    comment = format_comment(finding)
    assert "🟢" in comment
    assert "LOW" in comment
    print("✅ Low severity comment formatted correctly!")


def test_summary_with_high():
    """Summary with High findings should say merge blocked."""
    findings = [make_finding("High"), make_finding("Medium"), make_finding("Low")]
    summary = build_summary(findings)
    assert "blocked" in summary.lower()
    assert "1 High" in summary
    assert "1 Medium" in summary
    assert "1 Low" in summary
    print("✅ Summary with High findings works!")


def test_summary_no_high():
    """Summary without High findings should say no blocking issues."""
    findings = [make_finding("Medium"), make_finding("Low")]
    summary = build_summary(findings)
    assert "No blocking issues" in summary
    print("✅ Summary without High findings works!")


def test_summary_table():
    """Summary should include a markdown table."""
    findings = [make_finding("High")]
    summary = build_summary(findings)
    assert "| #" in summary
    assert "app.py" in summary
    print("✅ Summary table generated correctly!")


if __name__ == "__main__":
    test_format_comment_high()
    test_format_comment_low()
    test_summary_with_high()
    test_summary_no_high()
    test_summary_table()
    print("\n🎉 All Node 6 tests passed!")
