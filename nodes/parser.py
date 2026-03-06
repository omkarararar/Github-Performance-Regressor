from tree_sitter import Parser, Language
import tree_sitter_python
import tree_sitter_javascript
from models.schemas import FileChange, EnrichedFileChange, ASTNode


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
        return None
    parser = Parser()
    parser.language = Language(LANGUAGE_MODULES[language])
    return parser


def extract_ast_nodes(source_code: str, language: str) -> list[ASTNode]:
    parser = get_parser(language)
    if not parser:
        return []

    tree = parser.parse(bytes(source_code, "utf8"))
    node_types = NODE_TYPES.get(language, {})

    type_lookup = {}
    for category, ts_types in node_types.items():
        for ts_type in ts_types:
            type_lookup[ts_type] = category

    results = []
    _walk_tree(tree.root_node, type_lookup, source_code, results)
    return results


def _is_async(node) -> bool:
    """Check if a function_definition node has an 'async' keyword."""
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

        # Detect async functions (tree-sitter-python uses function_definition + async keyword child)
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


def enrich_file(file_change: FileChange, source_code: str) -> EnrichedFileChange:
    ast_nodes = extract_ast_nodes(source_code, file_change.language)
    line_map = build_line_map(ast_nodes)

    return EnrichedFileChange(
        filename=file_change.filename,
        language=file_change.language,
        hunks=file_change.hunks,
        added_lines=file_change.added_lines,
        ast_nodes=ast_nodes,
        line_to_nodes=line_map,
    )
