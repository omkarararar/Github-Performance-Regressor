from nodes.severity_scorer import score_finding, score_all
from models.schemas import Finding, EnrichedFileChange, ASTNode


def make_finding(file="app.py", line=10, pattern="ORM call inside loop"):
    return Finding(
        file=file, line=line, snippet="db.query()",
        pattern=pattern, explanation="test", suggested_fix="fix",
    )


def make_enriched(filename="app.py", ast_nodes=None, line_to_nodes=None):
    return EnrichedFileChange(
        filename=filename, language="python", hunks="", added_lines=[],
        ast_nodes=ast_nodes or [], line_to_nodes=line_to_nodes or {},
    )


def test_high_severity():
    """Finding in a hot path + loop should be High."""
    finding = make_finding(pattern="ORM call inside loop")
    ef = make_enriched(
        ast_nodes=[ASTNode(type="function", name="get_api_handler", start_line=1, end_line=20, snippet="...")],
        line_to_nodes={10: ["function", "loop"]},
    )
    result = score_finding(finding, [ef])
    assert result.severity == "High", f"Expected High, got {result.severity}"
    print("✅ High severity scored correctly!")


def test_medium_severity():
    """Finding in loop but not hot path should be Medium."""
    finding = make_finding(pattern="Unbounded query")
    ef = make_enriched(
        ast_nodes=[ASTNode(type="function", name="process_data", start_line=1, end_line=20, snippet="...")],
        line_to_nodes={10: ["function", "loop"]},
    )
    result = score_finding(finding, [ef])
    assert result.severity == "Medium", f"Expected Medium, got {result.severity}"
    print("✅ Medium severity scored correctly!")


def test_low_severity_with_pagination():
    """Finding with pagination nearby should be Low."""
    finding = make_finding(pattern="Unbounded query")
    ef = make_enriched(
        ast_nodes=[ASTNode(type="function", name="helper", start_line=1, end_line=20, snippet="results = db.all().paginate(page=1)")],
        line_to_nodes={10: ["function"]},
    )
    result = score_finding(finding, [ef])
    assert result.severity == "Low", f"Expected Low, got {result.severity}"
    print("✅ Low severity with pagination scored correctly!")


def test_score_all():
    """score_all should process multiple findings."""
    findings = [make_finding(), make_finding(line=20)]
    ef = make_enriched(line_to_nodes={10: ["function"], 20: ["function"]})
    results = score_all(findings, [ef])
    assert len(results) == 2
    assert all(r.severity is not None for r in results)
    print("✅ score_all works!")


if __name__ == "__main__":
    test_high_severity()
    test_medium_severity()
    test_low_severity_with_pagination()
    test_score_all()
    print("\n🎉 All Node 5 tests passed!")
