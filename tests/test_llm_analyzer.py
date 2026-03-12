from nodes.llm_analyzer import parse_response, format_suspects
from models.schemas import SuspectedPattern


def test_parse_json_response():
    """Should parse a clean JSON response from Claude."""
    response = '''```json
[
  {
    "file": "app.py",
    "line": 42,
    "snippet": "db.query(User).all()",
    "pattern": "Unbounded query",
    "explanation": "This loads all users into memory",
    "suggested_fix": "db.query(User).limit(100)"
  }
]
```'''
    findings = parse_response(response)
    assert len(findings) == 1
    assert findings[0].file == "app.py"
    assert findings[0].line == 42
    assert findings[0].pattern == "Unbounded query"
    print("✅ JSON response parsing works!")


def test_parse_empty_response():
    """Should handle empty array response."""
    findings = parse_response("[]")
    assert len(findings) == 0
    print("✅ Empty response handled!")


def test_parse_invalid_json():
    """Should handle invalid JSON gracefully."""
    findings = parse_response("this is not json at all")
    assert len(findings) == 0
    print("✅ Invalid JSON handled gracefully!")


def test_format_suspects():
    """Should format suspects into readable text."""
    suspects = [
        SuspectedPattern(file="app.py", line=10, snippet="db.all()", suspected_pattern="Unbounded query"),
    ]
    formatted = format_suspects(suspects)
    assert "app.py" in formatted
    assert "Unbounded query" in formatted
    assert "db.all()" in formatted
    print("✅ Suspect formatting works!")


if __name__ == "__main__":
    test_parse_json_response()
    test_parse_empty_response()
    test_parse_invalid_json()
    test_format_suspects()
    print("\n🎉 All Node 4 tests passed!")
