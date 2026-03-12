import re
from models.schemas import EnrichedFileChange, SuspectedPattern


# --- Pattern Definitions ---
# Each pattern: (name, regex, requires_context)
# requires_context = list of AST node types the line must be inside for the pattern to apply

PATTERNS = [
    {
        "name": "ORM call inside loop",
        "regex": r"\.(filter|find|query|objects\.|get_or_create|select|where|fetch|execute)\s*\(",
        "requires_context": ["loop"],
        "description": "Database/ORM call inside a loop — likely N+1 query",
    },
    {
        "name": "Missing select_related/prefetch_related",
        "regex": r"\.objects\.(all|filter|get|exclude)\s*\(",
        "requires_context": [],
        "exclude_if_nearby": ["select_related", "prefetch_related"],
        "description": "Django queryset without select_related/prefetch_related — may cause N+1",
    },
    {
        "name": "Unbounded query",
        "regex": r"\.(all|find|select)\s*\(\s*\)",
        "requires_context": [],
        "exclude_if_nearby": ["limit", "[:"],
        "description": "Unbounded .all()/.find() with no .limit() — may load entire table",
    },
    {
        "name": "Blocking call in async",
        "regex": r"(time\.sleep|requests\.(get|post|put|delete|patch)|subprocess\.run|os\.system)\s*\(",
        "requires_context": ["async"],
        "description": "Blocking call inside async function — blocks the event loop",
    },
    {
        "name": "Raw SQL without index hint",
        "regex": r"(ORDER BY|WHERE)\s+\w+",
        "requires_context": [],
        "line_contains": ["execute", "raw", "cursor", "sql", "SQL"],
        "description": "Raw SQL with ORDER BY/WHERE on column — verify index exists",
    },
    {
        "name": "Repeated call in loop",
        "regex": r"(\w+)\s*\([^)]*\)",
        "requires_context": ["loop"],
        "description": "Function call inside loop — consider hoisting if args don't change",
        "min_confidence": "low",
    },
]


def _get_nearby_lines(lines: list[str], index: int, window: int = 3) -> str:
    """Get surrounding lines as a single string for context checking."""
    start = max(0, index - window)
    end = min(len(lines), index + window + 1)
    return " ".join(lines[start:end])


def _check_line_context(line_number: int, required_context: list[str], line_to_nodes: dict[int, list[str]]) -> bool:
    """Check if the line is inside the required AST context (e.g., inside a loop)."""
    if not required_context:
        return True
    node_types = line_to_nodes.get(line_number, [])
    return all(ctx in node_types for ctx in required_context)


def match_patterns(enriched_file: EnrichedFileChange) -> list[SuspectedPattern]:
    """
    Main entry point for Node 3.
    Scan an enriched file for known bad performance patterns.
    Returns a list of SuspectedPattern objects for lines that match.
    """
    results = []
    lines = enriched_file.hunks.split("\n")

    for i, line in enumerate(lines):
        # Skip diff metadata lines
        if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
            continue

        # Only check added lines (start with +)
        if not line.startswith("+"):
            continue

        clean_line = line[1:].strip()  # remove the leading "+"
        if not clean_line:
            continue

        # Estimate line number (simplified — will be improved in production hardening)
        line_number = i + 1

        for pattern in PATTERNS:
            # Check regex match
            if not re.search(pattern["regex"], clean_line):
                continue

            # Check AST context requirement
            if not _check_line_context(line_number, pattern.get("requires_context", []), enriched_file.line_to_nodes):
                continue

            # Check exclude_if_nearby
            if "exclude_if_nearby" in pattern:
                nearby = _get_nearby_lines(lines, i)
                if any(term in nearby for term in pattern["exclude_if_nearby"]):
                    continue

            # Check line_contains requirement
            if "line_contains" in pattern:
                if not any(term in clean_line for term in pattern["line_contains"]):
                    continue

            results.append(SuspectedPattern(
                file=enriched_file.filename,
                line=line_number,
                snippet=clean_line,
                suspected_pattern=pattern["name"],
            ))

    return results


def scan_all_files(enriched_files: list[EnrichedFileChange]) -> list[SuspectedPattern]:
    """Scan multiple enriched files and return all suspected patterns."""
    all_suspects = []
    for ef in enriched_files:
        all_suspects.extend(match_patterns(ef))
    return all_suspects
