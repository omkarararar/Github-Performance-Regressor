from models.schemas import Finding, EnrichedFileChange
from logger import get_logger

log = get_logger("severity_scorer")

# Configurable thresholds
HIGH_THRESHOLD = 7
MEDIUM_THRESHOLD = 4

HOT_PATH_INDICATORS = [
    "route", "endpoint", "handler", "view", "api",
    "get", "post", "put", "delete", "patch",
    "request", "response", "webhook", "callback",
    "middleware", "dispatch", "serve",
]

PAGINATION_INDICATORS = [
    "paginate", "limit", "offset", "page",
    "slice", "[::", "[:", "take", "skip",
    "per_page", "page_size",
]

DB_CALL_PATTERNS = [
    ".query(", ".filter(", ".find(", ".execute(",
    ".objects.", "session.", "cursor.",
    ".select(", ".where(", ".get_or_create(",
]


def score_finding(finding: Finding, enriched_files: list[EnrichedFileChange]) -> Finding:
    score, breakdown = _calculate_score(finding, enriched_files)

    if score >= HIGH_THRESHOLD:
        finding.severity = "High"
    elif score >= MEDIUM_THRESHOLD:
        finding.severity = "Medium"
    else:
        finding.severity = "Low"

    log.info(f"{finding.severity} ({score}/10) — {finding.pattern} in {finding.file}:{finding.line} | {breakdown}")
    return finding


def _calculate_score(finding: Finding, enriched_files: list[EnrichedFileChange]) -> tuple[int, str]:
    """Calculate severity score with breakdown for debugging."""
    score = 3
    reasons = ["base=3"]

    if _is_hot_path(finding, enriched_files):
        score += 3
        reasons.append("hot_path=+3")

    if _is_in_loop(finding, enriched_files):
        score += 2
        reasons.append("in_loop=+2")

    if _has_pagination(finding, enriched_files):
        score -= 2
        reasons.append("pagination=-2")

    if _is_db_call(finding):
        score += 1
        reasons.append("db_call=+1")

    high_severity_patterns = ["ORM call inside loop", "Blocking call in async", "SQLAlchemy query in loop"]
    if finding.pattern in high_severity_patterns:
        score += 1
        reasons.append("severe_pattern=+1")

    score = max(1, min(10, score))
    return score, " | ".join(reasons)


def _is_hot_path(finding: Finding, enriched_files: list[EnrichedFileChange]) -> bool:
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
    for ef in enriched_files:
        if ef.filename != finding.file:
            continue
        node_types = ef.line_to_nodes.get(finding.line, [])
        if "loop" in node_types:
            return True
    return False


def _has_pagination(finding: Finding, enriched_files: list[EnrichedFileChange]) -> bool:
    for ef in enriched_files:
        if ef.filename != finding.file:
            continue
        for node in ef.ast_nodes:
            if node.start_line <= finding.line <= node.end_line:
                snippet_lower = node.snippet.lower()
                if any(indicator in snippet_lower for indicator in PAGINATION_INDICATORS):
                    return True
    return False


def _is_db_call(finding: Finding) -> bool:
    """Check if the finding's snippet involves a known DB call."""
    snippet = finding.snippet.lower()
    return any(pattern in snippet for pattern in DB_CALL_PATTERNS)


def score_all(findings: list[Finding], enriched_files: list[EnrichedFileChange]) -> list[Finding]:
    """Main entry point for Node 5."""
    log.info(f"Scoring {len(findings)} findings")
    scored = [score_finding(f, enriched_files) for f in findings]
    high = sum(1 for f in scored if f.severity == "High")
    med = sum(1 for f in scored if f.severity == "Medium")
    low = sum(1 for f in scored if f.severity == "Low")
    log.info(f"Node 5 complete: {high} High, {med} Medium, {low} Low")
    return scored
