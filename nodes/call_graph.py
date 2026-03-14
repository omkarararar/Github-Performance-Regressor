"""
Node 2.5 — Cross-File Call Graph Analysis.

Inserted between parser.py (Node 2) and pattern_matcher.py (Node 3).
Detects performance bugs spanning file boundaries by propagating
loop/async context along call edges across all changed files in a PR.
"""
import asyncio
from tree_sitter import Parser, Language
import tree_sitter_python
import tree_sitter_javascript

from models.schemas import (
    EnrichedFileChange, FunctionDefinition, CallSite,
)
from config import CALL_GRAPH_MAX_DEPTH, CALL_GRAPH_TIMEOUT
from logger import get_logger

log = get_logger("call_graph")

LANGUAGE_MODULES = {
    "python": tree_sitter_python.language(),
    "javascript": tree_sitter_javascript.language(),
}


def _get_parser(language: str) -> Parser | None:
    """Get a Tree-sitter parser for the given language."""
    if language not in LANGUAGE_MODULES:
        return None
    parser = Parser()
    parser.language = Language(LANGUAGE_MODULES[language])
    return parser


# ---------------------------------------------------------------------------
# Step 1 — Build a cross-file function index
# ---------------------------------------------------------------------------

def build_function_index(
    enriched_files: list[EnrichedFileChange],
) -> dict[str, list[FunctionDefinition]]:
    """
    Scan all enriched files and build an index of function definitions.

    Returns a dict mapping function name → list of FunctionDefinition objects
    (list because the same name could exist in multiple files).
    """
    index: dict[str, list[FunctionDefinition]] = {}

    for ef in enriched_files:
        for node in ef.ast_nodes:
            if node.type not in ("function", "async"):
                continue

            # Determine the contexts wrapping this function
            containing = []
            for other_node in ef.ast_nodes:
                if other_node is node:
                    continue
                if (other_node.start_line <= node.start_line
                        and other_node.end_line >= node.end_line):
                    containing.append(other_node.type)

            func_def = FunctionDefinition(
                name=node.name,
                file_path=ef.filename,
                start_line=node.start_line,
                end_line=node.end_line,
                containing_contexts=containing,
            )

            if node.name not in index:
                index[node.name] = []
            index[node.name].append(func_def)

    log.info(f"Function index: {sum(len(v) for v in index.values())} functions across {len(index)} unique names")
    return index


# ---------------------------------------------------------------------------
# Step 2 — Build call site map
# ---------------------------------------------------------------------------

def _extract_call_nodes(tree_node, results: list):
    """Recursively extract all call_expression nodes from a tree-sitter tree."""
    if tree_node.type == "call":  # Python
        results.append(tree_node)
    elif tree_node.type == "call_expression":  # JavaScript
        results.append(tree_node)
    for child in tree_node.children:
        _extract_call_nodes(child, results)


def _get_callee_name(call_node, language: str) -> str | None:
    """Extract the function name from a call expression node."""
    if language == "python":
        # Python call: the first child is the function being called
        func_node = call_node.children[0] if call_node.children else None
        if not func_node:
            return None
        # Simple name: foo()
        if func_node.type == "identifier":
            return func_node.text.decode("utf8")
        # Attribute access: obj.method() — return just the method name
        if func_node.type == "attribute":
            for child in func_node.children:
                if child.type == "identifier":
                    last_id = child.text.decode("utf8")
            return last_id if 'last_id' in dir() else None
        return None

    elif language == "javascript":
        func_node = call_node.children[0] if call_node.children else None
        if not func_node:
            return None
        if func_node.type == "identifier":
            return func_node.text.decode("utf8")
        if func_node.type == "member_expression":
            # obj.method() — get the property name
            for child in func_node.children:
                if child.type == "property_identifier":
                    return child.text.decode("utf8")
        return None

    return None


def _get_call_context(
    call_line: int,
    ast_nodes: list,
    line_to_nodes: dict[int, list[str]],
) -> list[str]:
    """
    Determine what AST contexts wrap a call site (innermost first).

    Returns a list like ["loop", "function", "class"].
    """
    contexts = []
    # Sort by span size (smallest first = innermost first)
    wrapping = [
        n for n in ast_nodes
        if n.start_line <= call_line <= n.end_line
    ]
    wrapping.sort(key=lambda n: n.end_line - n.start_line)

    for node in wrapping:
        contexts.append(node.type)

    return contexts


def build_call_sites(
    enriched_files: list[EnrichedFileChange],
) -> list[CallSite]:
    """
    Use Tree-sitter to find all call expressions in each file's source.

    Returns a list of CallSite objects with callee name, caller file,
    call line, and wrapping AST context.
    """
    all_sites: list[CallSite] = []

    for ef in enriched_files:
        source = "\n".join(ef.added_lines)
        # Try to get full source from hunks for better parsing
        # But we really need the full content — use the AST nodes' snippets
        # to reconstruct or work with what we have

        parser = _get_parser(ef.language)
        if not parser:
            continue

        # Reconstruct source from the biggest AST node snippet, or added_lines
        # Best effort: use all added lines joined
        if not source.strip():
            continue

        try:
            tree = parser.parse(bytes(source, "utf8"))
        except Exception as e:
            log.warning(f"Failed to parse {ef.filename} for call sites: {e}")
            continue

        call_nodes: list = []
        _extract_call_nodes(tree.root_node, call_nodes)

        for call_node in call_nodes:
            callee = _get_callee_name(call_node, ef.language)
            if not callee:
                continue

            call_line = call_node.start_point[0] + 1  # 1-indexed
            context = _get_call_context(call_line, ef.ast_nodes, ef.line_to_nodes)

            all_sites.append(CallSite(
                callee_name=callee,
                caller_file=ef.filename,
                call_line=call_line,
                call_context=context,
            ))

    log.info(f"Found {len(all_sites)} call sites across all files")
    return all_sites


# ---------------------------------------------------------------------------
# Step 3 — Context propagation (DFS graph walk)
# ---------------------------------------------------------------------------

def propagate_context(
    function_index: dict[str, list[FunctionDefinition]],
    call_sites: list[CallSite],
    enriched_files: list[EnrichedFileChange],
    max_depth: int = CALL_GRAPH_MAX_DEPTH,
) -> dict[str, dict[str, set[int]]]:
    """
    For call sites inside loops/async, propagate that context to callee functions.

    Uses DFS with visited set. Returns a dict:
      { file_path: { "loop": set(line_numbers), "async": set(line_numbers) } }
    """
    # Build lookup: filename → EnrichedFileChange
    file_lookup = {ef.filename: ef for ef in enriched_files}

    # Result: file_path → { "loop": set[int], "async": set[int] }
    propagated: dict[str, dict[str, set[int]]] = {}

    # Build call graph: function_name → list of CallSite calling it
    callers_of: dict[str, list[CallSite]] = {}
    for site in call_sites:
        if site.callee_name not in callers_of:
            callers_of[site.callee_name] = []
        callers_of[site.callee_name].append(site)

    # Track call chains for findings
    call_chains: dict[str, list[list[str]]] = {}  # "file:line" → chain

    def _ensure_file(fp: str):
        if fp not in propagated:
            propagated[fp] = {"loop": set(), "async": set()}

    def _propagate_dfs(
        func_name: str,
        context_type: str,  # "loop" or "async"
        visited: set[str],
        depth: int,
        chain: list[str],
    ):
        """DFS to propagate context through call chains."""
        if depth > max_depth:
            return
        if func_name in visited:
            return

        visited.add(func_name)

        # Find all definitions of this function
        func_defs = function_index.get(func_name, [])
        for func_def in func_defs:
            _ensure_file(func_def.file_path)
            # Mark all lines in this function as having the propagated context
            for line in range(func_def.start_line, func_def.end_line + 1):
                propagated[func_def.file_path][context_type].add(line)

            # Build chain entry
            current_chain = chain + [f"{func_def.file_path}:{func_name}()"]
            chain_key = f"{func_def.file_path}:{func_def.start_line}"
            if chain_key not in call_chains:
                call_chains[chain_key] = []
            call_chains[chain_key].append(current_chain)

            # Find all call sites within this function and recurse
            ef = file_lookup.get(func_def.file_path)
            if not ef:
                continue

            for site in call_sites:
                if (site.caller_file == func_def.file_path
                        and func_def.start_line <= site.call_line <= func_def.end_line):
                    _propagate_dfs(
                        site.callee_name, context_type,
                        visited, depth + 1, current_chain,
                    )

        visited.discard(func_name)

    # Start propagation from call sites that are in loop or async context
    for site in call_sites:
        has_loop = "loop" in site.call_context
        has_async = "async" in site.call_context

        if has_loop:
            chain_start = f"{site.caller_file}:{site.call_line} [loop]"
            _propagate_dfs(
                site.callee_name, "loop",
                set(), 0, [chain_start],
            )

        if has_async:
            chain_start = f"{site.caller_file}:{site.call_line} [async]"
            _propagate_dfs(
                site.callee_name, "async",
                set(), 0, [chain_start],
            )

    log.info(f"Context propagation: {sum(len(v['loop']) for v in propagated.values())} loop-tagged lines, "
             f"{sum(len(v['async']) for v in propagated.values())} async-tagged lines")
    return propagated


# ---------------------------------------------------------------------------
# Step 4 — Enrich EnrichedFileChange objects with cross-file context
# ---------------------------------------------------------------------------

def apply_propagated_context(
    enriched_files: list[EnrichedFileChange],
    propagated: dict[str, dict[str, set[int]]],
) -> list[EnrichedFileChange]:
    """
    Write propagated loop/async context onto each EnrichedFileChange.

    Returns the updated list (mutations are in-place on the same objects).
    """
    for ef in enriched_files:
        file_ctx = propagated.get(ef.filename)
        if not file_ctx:
            continue

        ef.called_from_loop = file_ctx.get("loop", set())
        ef.called_from_async = file_ctx.get("async", set())

        if ef.called_from_loop:
            log.info(f"{ef.filename}: {len(ef.called_from_loop)} lines tagged as called-from-loop")
        if ef.called_from_async:
            log.info(f"{ef.filename}: {len(ef.called_from_async)} lines tagged as called-from-async")

    return enriched_files


# ---------------------------------------------------------------------------
# Public API — inserted into the pipeline
# ---------------------------------------------------------------------------

async def analyze(
    enriched_files: list[EnrichedFileChange],
) -> list[EnrichedFileChange]:
    """
    Main entry point for the call graph node (Node 2.5).

    Builds a cross-file function index, extracts call sites,
    propagates loop/async context through call chains, and enriches
    the file change objects with cross-file context.

    If analysis exceeds CALL_GRAPH_TIMEOUT seconds, returns files unchanged.
    """
    if not enriched_files:
        return enriched_files

    try:
        result = await asyncio.wait_for(
            _analyze_impl(enriched_files),
            timeout=CALL_GRAPH_TIMEOUT,
        )
        return result
    except asyncio.TimeoutError:
        log.warning(f"Call graph analysis timed out after {CALL_GRAPH_TIMEOUT}s — continuing without it")
        return enriched_files
    except Exception as e:
        log.error(f"Call graph analysis failed: {e}", exc_info=True)
        return enriched_files


async def _analyze_impl(
    enriched_files: list[EnrichedFileChange],
) -> list[EnrichedFileChange]:
    """Internal implementation of call graph analysis."""
    log.info(f"Starting call graph analysis for {len(enriched_files)} files")

    # Step 1: Build function index
    function_index = build_function_index(enriched_files)
    if not function_index:
        log.info("No functions found — skipping call graph")
        return enriched_files

    # Step 2: Build call site map
    call_sites = build_call_sites(enriched_files)
    if not call_sites:
        log.info("No call sites found — skipping context propagation")
        return enriched_files

    # Step 3: Propagate context
    propagated = propagate_context(function_index, call_sites, enriched_files)

    # Step 4: Apply to enriched files
    enriched_files = apply_propagated_context(enriched_files, propagated)

    log.info("Call graph analysis complete")
    return enriched_files
