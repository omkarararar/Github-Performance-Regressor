import re
from models.schemas import EnrichedFileChange, SuspectedPattern
from logger import get_logger

log = get_logger("pattern_matcher")

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
        "regex": r"(time\.sleep|requests\.(get|post|put|delete|patch)|subprocess\.(run|call|Popen)|os\.system|urllib\.request)\s*\(",
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
        "name": "SQLAlchemy query in loop",
        "regex": r"session\.(query|execute|scalar)\s*\(",
        "requires_context": ["loop"],
        "description": "SQLAlchemy query inside a loop — likely N+1 query",
    },
    {
        "name": "Repeated call in loop",
        "regex": r"(\w+)\s*\([^)]*\)",
        "requires_context": ["loop"],
        "description": "Function call inside loop — consider hoisting if args don't change",
        "min_confidence": "low",
    },
]


def _parse_hunk_line_numbers(hunks: str) -> dict[int, int]:
    """
    Parse hunk headers to build a mapping: hunk_line_index → actual file line number.
    Returns {index_in_hunks: real_line_number} for added lines.
    """
    line_map = {}
    current_new_line = 0

    for i, line in enumerate(hunks.split("\n")):
        hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if hunk_match:
            current_new_line = int(hunk_match.group(1))
            continue

        if line.startswith("+") and not line.startswith("+++"):
            line_map[i] = current_new_line
            current_new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            pass
        else:
            current_new_line += 1

    return line_map


def _get_nearby_lines(lines: list[str], index: int, window: int = 3) -> str:
    start = max(0, index - window)
    end = min(len(lines), index + window + 1)
    return " ".join(lines[start:end])


def _check_line_context(
    line_number: int,
    required_context: list[str],
    line_to_nodes: dict[int, list[str]],
    called_from_loop: set[int] | None = None,
    called_from_async: set[int] | None = None,
) -> bool:
    """Check if a line has the required AST context, including cross-file call graph data."""
    if not required_context:
        return True
    node_types = list(line_to_nodes.get(line_number, []))

    # Augment with cross-file context from call graph
    if called_from_loop and line_number in called_from_loop:
        if "loop" not in node_types:
            node_types.append("loop")
    if called_from_async and line_number in called_from_async:
        if "async" not in node_types:
            node_types.append("async")

    return all(ctx in node_types for ctx in required_context)


def match_patterns(enriched_file: EnrichedFileChange) -> list[SuspectedPattern]:
    """
    Main entry point for Node 3.
    Scan an enriched file for known bad performance patterns.
    """
    results = []
    lines = enriched_file.hunks.split("\n")
    hunk_line_map = _parse_hunk_line_numbers(enriched_file.hunks)

    for i, line in enumerate(lines):
        if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
            continue

        if not line.startswith("+"):
            continue

        clean_line = line[1:].strip()
        if not clean_line:
            continue

        # Use real line number from hunk header, fall back to index
        real_line = hunk_line_map.get(i, i + 1)

        for pattern in PATTERNS:
            if not re.search(pattern["regex"], clean_line):
                continue

            if not _check_line_context(
                real_line, pattern.get("requires_context", []),
                enriched_file.line_to_nodes,
                called_from_loop=enriched_file.called_from_loop,
                called_from_async=enriched_file.called_from_async,
            ):
                continue

            if "exclude_if_nearby" in pattern:
                nearby = _get_nearby_lines(lines, i)
                if any(term in nearby for term in pattern["exclude_if_nearby"]):
                    continue

            if "line_contains" in pattern:
                if not any(term in clean_line for term in pattern["line_contains"]):
                    continue

            log.info(f"Pattern match: {pattern['name']} in {enriched_file.filename}:{real_line}")
            results.append(SuspectedPattern(
                file=enriched_file.filename,
                line=real_line,
                snippet=clean_line,
                suspected_pattern=pattern["name"],
            ))

    log.info(f"Found {len(results)} suspected patterns in {enriched_file.filename}")
    return results


def scan_all_files(enriched_files: list[EnrichedFileChange]) -> list[SuspectedPattern]:
    all_suspects = []
    for ef in enriched_files:
        all_suspects.extend(match_patterns(ef))
    log.info(f"Total suspected patterns across all files: {len(all_suspects)}")
    return all_suspects
