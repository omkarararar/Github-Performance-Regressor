from nodes.parser import extract_ast_nodes, build_line_map, enrich_file
from models.schemas import FileChange

SAMPLE_PYTHON = """
import os

class UserService:
    def get_users(self):
        users = []
        for user in db.query(User):
            users.append(user)
        return users

    async def fetch_data(self):
        return await api.get("/data")

def helper():
    while True:
        pass
""".strip()

SAMPLE_JS = """
class UserManager {
    constructor() {
        this.users = [];
    }
}

function fetchUsers() {
    for (let i = 0; i < 10; i++) {
        console.log(i);
    }
}

const getUser = (id) => {
    return db.find(id);
};
""".strip()


def test_python_ast():
    nodes = extract_ast_nodes(SAMPLE_PYTHON, "python")
    types = [n.type for n in nodes]

    assert "class" in types, f"Expected 'class' in {types}"
    assert "function" in types, f"Expected 'function' in {types}"
    assert "loop" in types, f"Expected 'loop' in {types}"
    assert "async" in types, f"Expected 'async' in {types}"

    class_node = [n for n in nodes if n.type == "class"][0]
    assert class_node.name == "UserService"

    func_node = [n for n in nodes if n.type == "function"][0]
    assert func_node.name == "get_users"

    print("✅ Python AST extraction works!")


def test_javascript_ast():
    nodes = extract_ast_nodes(SAMPLE_JS, "javascript")
    types = [n.type for n in nodes]

    assert "class" in types, f"Expected 'class' in {types}"
    assert "function" in types, f"Expected 'function' in {types}"
    assert "loop" in types, f"Expected 'loop' in {types}"

    print("✅ JavaScript AST extraction works!")


def test_line_map():
    nodes = extract_ast_nodes(SAMPLE_PYTHON, "python")
    line_map = build_line_map(nodes)

    # Line 6 (for loop) should be inside both "class" and "function" and "loop"
    # Find the for loop's line
    loop_node = [n for n in nodes if n.type == "loop"][0]
    loop_line = loop_node.start_line
    assert "loop" in line_map[loop_line], f"Expected 'loop' at line {loop_line}"

    print("✅ Line map works!")


def test_enrich_file():
    fc = FileChange(
        filename="app.py",
        language="python",
        hunks="fake hunk",
        added_lines=["users.append(user)"],
    )
    enriched = enrich_file(fc, SAMPLE_PYTHON)

    assert enriched.filename == "app.py"
    assert len(enriched.ast_nodes) > 0
    assert len(enriched.line_to_nodes) > 0

    print("✅ enrich_file works!")


def test_unsupported_language():
    nodes = extract_ast_nodes("some code", "rust")
    assert nodes == [], "Unsupported language should return empty list"
    print("✅ Unsupported language handled!")


if __name__ == "__main__":
    test_python_ast()
    test_javascript_ast()
    test_line_map()
    test_enrich_file()
    test_unsupported_language()
    print("\n🎉 All Node 2 tests passed!")
