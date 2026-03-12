from nodes.pattern_matcher import match_patterns, _parse_hunk_line_numbers
from models.schemas import EnrichedFileChange, ASTNode


def make_enriched(filename, hunks, ast_nodes=None, line_to_nodes=None):
    return EnrichedFileChange(
        filename=filename,
        language="python",
        hunks=hunks,
        added_lines=[],
        ast_nodes=ast_nodes or [],
        line_to_nodes=line_to_nodes or {},
    )


def test_hunk_line_parsing():
    """Hunk headers should produce correct line number mappings."""
    hunks = """@@ -1,5 +10,7 @@
 context line
+added at line 11
+added at line 12"""
    line_map = _parse_hunk_line_numbers(hunks)
    # index 1 = context (10), index 2 = +added (11), index 3 = +added (12)
    assert line_map.get(2) == 11, f"Expected 11, got {line_map.get(2)}"
    assert line_map.get(3) == 12, f"Expected 12, got {line_map.get(3)}"
    print("✅ Hunk line number parsing works!")


def test_orm_in_loop():
    hunks = """@@ -1,5 +10,7 @@
+for user in users:
+    user.objects.filter(active=True)"""
    # Line 11 is the +added ORM call (hunk starts at +10, context/added increments)
    ef = make_enriched("app.py", hunks, line_to_nodes={11: ["loop", "function"]})
    results = match_patterns(ef)
    matched = [r for r in results if r.suspected_pattern == "ORM call inside loop"]
    assert len(matched) > 0, f"Expected ORM-in-loop match, got {[r.suspected_pattern for r in results]}"
    print("✅ ORM call inside loop detected!")


def test_orm_outside_loop_ignored():
    hunks = """@@ -1,3 +1,3 @@
+users = User.objects.filter(active=True)"""
    ef = make_enriched("app.py", hunks, line_to_nodes={1: ["function"]})
    results = match_patterns(ef)
    matched = [r for r in results if r.suspected_pattern == "ORM call inside loop"]
    assert len(matched) == 0, f"Should not flag ORM outside loop, got {matched}"
    print("✅ ORM outside loop correctly ignored!")


def test_blocking_in_async():
    hunks = """@@ -1,3 +5,3 @@
+    time.sleep(5)"""
    ef = make_enriched("app.py", hunks, line_to_nodes={5: ["async"]})
    results = match_patterns(ef)
    matched = [r for r in results if r.suspected_pattern == "Blocking call in async"]
    assert len(matched) > 0, f"Expected blocking-in-async match, got {[r.suspected_pattern for r in results]}"
    print("✅ Blocking call in async detected!")


def test_blocking_outside_async_ignored():
    hunks = """@@ -1,3 +5,3 @@
+    time.sleep(5)"""
    ef = make_enriched("app.py", hunks, line_to_nodes={5: ["function"]})
    results = match_patterns(ef)
    matched = [r for r in results if r.suspected_pattern == "Blocking call in async"]
    assert len(matched) == 0, f"Should not flag blocking outside async, got {matched}"
    print("✅ Blocking call outside async correctly ignored!")


def test_unbounded_query():
    hunks = """@@ -1,3 +1,3 @@
+    results = collection.all()"""
    ef = make_enriched("app.py", hunks)
    results = match_patterns(ef)
    matched = [r for r in results if r.suspected_pattern == "Unbounded query"]
    assert len(matched) > 0, f"Expected unbounded query match, got {[r.suspected_pattern for r in results]}"
    print("✅ Unbounded query detected!")


def test_unbounded_with_limit_ignored():
    hunks = """@@ -1,3 +1,3 @@
+    results = collection.all().limit(100)"""
    ef = make_enriched("app.py", hunks)
    results = match_patterns(ef)
    matched = [r for r in results if r.suspected_pattern == "Unbounded query"]
    assert len(matched) == 0, f"Should not flag .all() with .limit(), got {matched}"
    print("✅ Unbounded query with limit correctly ignored!")


def test_no_false_positives():
    hunks = """@@ -1,3 +1,3 @@
+    x = 1 + 2
+    print("hello")
+    return result"""
    ef = make_enriched("app.py", hunks)
    results = match_patterns(ef)
    assert len(results) == 0, f"Normal code should have no matches, got {[r.suspected_pattern for r in results]}"
    print("✅ No false positives on normal code!")


if __name__ == "__main__":
    test_hunk_line_parsing()
    test_orm_in_loop()
    test_orm_outside_loop_ignored()
    test_blocking_in_async()
    test_blocking_outside_async_ignored()
    test_unbounded_query()
    test_unbounded_with_limit_ignored()
    test_no_false_positives()
    print("\n🎉 All Node 3 tests passed!")
