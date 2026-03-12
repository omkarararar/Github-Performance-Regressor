from models.schemas import Finding, EnrichedFileChange


# Keywords that indicate a hot path (endpoint handler, API route, etc.)
HOT_PATH_INDICATORS = [
    "route", "endpoint", "handler", "view", "api",
    "get", "post", "put", "delete", "patch",
    "request", "response",
]

# Keywords that indicate pagination/limiting is present
PAGINATION_INDICATORS = [
    "paginate", "limit", "offset", "page",
    "slice", "[::", "[:",
]


def score_finding(finding: Finding, enriched_files: list[EnrichedFileChange]) -> Finding:
    """
    Score a single finding as High, Medium, or Low severity.

    - High: inside a hot path (endpoint handler, unbounded loop, called every request)
    - Medium: likely slow but depends on data size
    - Low: code smell, unlikely to regress in practice
    """
    score = _calculate_score(finding, enriched_files)

    if score >= 7:
        finding.severity = "High"
    elif score >= 4:
        finding.severity = "Medium"
    else:
        finding.severity = "Low"

    return finding


def _calculate_score(finding: Finding, enriched_files: list[EnrichedFileChange]) -> int:
    """Calculate a numeric severity score (1-10)."""
    score = 3  # base score

    # Check if inside a hot path
    if _is_hot_path(finding, enriched_files):
        score += 3

    # Check if inside a loop (from AST context)
    if _is_in_loop(finding, enriched_files):
        score += 2

    # Check if pagination exists nearby
    if _has_pagination(finding, enriched_files):
        score -= 2

    # Patterns that are inherently more severe
    high_severity_patterns = ["ORM call inside loop", "Blocking call in async"]
    if finding.pattern in high_severity_patterns:
        score += 1

    return max(1, min(10, score))


def _is_hot_path(finding: Finding, enriched_files: list[EnrichedFileChange]) -> bool:
    """Check if the finding is inside an API route handler or similar hot path."""
    for ef in enriched_files:
        if ef.filename != finding.file:
            continue
        for node in ef.ast_nodes:
            if node.start_line <= finding.line <= node.end_line:
                name_lower = node.name.lower()
                if any(indicator in name_lower for indicator in HOT_PATH_INDICATORS):
                    return True
    return False


def _is_in_loop(finding: Finding, enriched_files: list[EnrichedFileChange]) -> bool:
    """Check if the finding's line is inside a loop."""
    for ef in enriched_files:
        if ef.filename != finding.file:
            continue
        node_types = ef.line_to_nodes.get(finding.line, [])
        if "loop" in node_types:
            return True
    return False


def _has_pagination(finding: Finding, enriched_files: list[EnrichedFileChange]) -> bool:
    """Check if pagination/limiting exists in the same function."""
    for ef in enriched_files:
        if ef.filename != finding.file:
            continue
        for node in ef.ast_nodes:
            if node.start_line <= finding.line <= node.end_line:
                snippet_lower = node.snippet.lower()
                if any(indicator in snippet_lower for indicator in PAGINATION_INDICATORS):
                    return True
    return False


def score_all(findings: list[Finding], enriched_files: list[EnrichedFileChange]) -> list[Finding]:
    """
    Main entry point for Node 5.
    Score all findings and return them with severity attached.
    """
    return [score_finding(f, enriched_files) for f in findings]
