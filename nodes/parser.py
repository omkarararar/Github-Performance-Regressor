from tree_sitter import Parser, Language
import tree_sitter_python
import tree_sitter_javascript
from models.schemas import FileChange, EnrichedFileChange, ASTNode
from logger import get_logger

log = get_logger("parser")

MAX_FILE_SIZE = 500_000  # 500KB

LANGUAGE_MODULES = {
    "python": tree_sitter_python.language(),
    "javascript": tree_sitter_javascript.language(),
}

NODE_TYPES = {
    "python": {
        "function": ["function_definition"],
        "class": ["class_definition"],
        "loop": ["for_statement", "while_statement"],
    },
    "javascript": {
        "function": ["function_declaration", "arrow_function"],
        "class": ["class_declaration"],
        "loop": ["for_statement", "while_statement", "for_in_statement"],
        "async": ["async_function"],
    },
}


def get_parser(language: str) -> Parser | None:
    if language not in LANGUAGE_MODULES:
        log.debug(f"No Tree-sitter grammar for language: {language}")
        return None
    parser = Parser()
    parser.language = Language(LANGUAGE_MODULES[language])
    return parser


def extract_ast_nodes(source_code: str, language: str) -> list[ASTNode]:
    if not source_code or not source_code.strip():
        return []

    if len(source_code) > MAX_FILE_SIZE:
        log.warning(f"Source code too large ({len(source_code)} bytes), skipping AST extraction")
        return []

    parser = get_parser(language)
    if not parser:
        return []

    try:
        tree = parser.parse(bytes(source_code, "utf8"))
    except Exception as e:
        log.error(f"Tree-sitter parse failed: {e}")
        return []

    node_types = NODE_TYPES.get(language, {})

    type_lookup = {}
    for category, ts_types in node_types.items():
        for ts_type in ts_types:
            type_lookup[ts_type] = category

    results = []
    _walk_tree(tree.root_node, type_lookup, source_code, results)
    log.info(f"Extracted {len(results)} AST nodes for {language} source")
    return results


def _is_async(node) -> bool:
    for child in node.children:
        if child.type == "async":
            return True
    return False


def _walk_tree(node, type_lookup: dict, source: str, results: list[ASTNode]):
    if node.type in type_lookup:
        lines = source.split("\n")
        start = node.start_point[0]
        end = node.end_point[0]

        name = _get_node_name(node) or node.type

        category = type_lookup[node.type]
        if node.type == "function_definition" and _is_async(node):
            category = "async"

        results.append(ASTNode(
            type=category,
            name=name,
            start_line=start + 1,
            end_line=end + 1,
            snippet="\n".join(lines[start:end + 1]),
        ))

    for child in node.children:
        _walk_tree(child, type_lookup, source, results)


def _get_node_name(node) -> str | None:
    for child in node.children:
        if child.type in ("identifier", "property_identifier"):
            return child.text.decode("utf8")
    return None


def build_line_map(ast_nodes: list[ASTNode]) -> dict[int, list[str]]:
    line_map = {}
    for node in ast_nodes:
        for line in range(node.start_line, node.end_line + 1):
            if line not in line_map:
                line_map[line] = []
            line_map[line].append(node.type)
    return line_map


def enrich_file(file_change: FileChange, source_code: str = "") -> EnrichedFileChange:
    """
    Main entry point for Node 2.
    Uses full_source from FileChange if available, falls back to provided source_code.
    """
    code = file_change.full_source or source_code
    if not code:
        log.warning(f"No source code for {file_change.filename}, using added_lines as fallback")
        code = "\n".join(file_change.added_lines)

    ast_nodes = extract_ast_nodes(code, file_change.language)
    line_map = build_line_map(ast_nodes)

    return EnrichedFileChange(
        filename=file_change.filename,
        language=file_change.language,
        hunks=file_change.hunks,
        added_lines=file_change.added_lines,
        line_numbers=file_change.line_numbers,
        ast_nodes=ast_nodes,
        line_to_nodes=line_map,
    )
