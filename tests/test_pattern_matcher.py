from nodes.pattern_matcher import match_patterns
from models.schemas import EnrichedFileChange, ASTNode


def make_enriched(filename, hunks, ast_nodes=None, line_to_nodes=None):
    """Helper to build test EnrichedFileChange objects."""
    return EnrichedFileChange(
        filename=filename,
        language="python",
        hunks=hunks,
        added_lines=[],
        ast_nodes=ast_nodes or [],
        line_to_nodes=line_to_nodes or {},
    )


def test_orm_in_loop():
    """ORM call inside a loop should be detected."""
    hunks = """@@ -1,5 +1,7 @@
+for user in users:
+    user.objects.filter(active=True)"""

    ef = make_enriched("app.py", hunks, line_to_nodes={2: ["loop", "function"]})
    results = match_patterns(ef)

    matched = [r for r in results if r.suspected_pattern == "ORM call inside loop"]
    assert len(matched) > 0, f"Expected ORM-in-loop match, got {[r.suspected_pattern for r in results]}"
    print("✅ ORM call inside loop detected!")


def test_orm_outside_loop_ignored():
    """ORM call NOT inside a loop should NOT be flagged as N+1."""
    hunks = """@@ -1,3 +1,3 @@
+users = User.objects.filter(active=True)"""

    ef = make_enriched("app.py", hunks, line_to_nodes={1: ["function"]})
    results = match_patterns(ef)

    matched = [r for r in results if r.suspected_pattern == "ORM call inside loop"]
    assert len(matched) == 0, f"Should not flag ORM outside loop, got {matched}"
    print("✅ ORM outside loop correctly ignored!")


def test_blocking_in_async():
    """Blocking call inside async function should be detected."""
    hunks = """@@ -1,3 +1,3 @@
+    time.sleep(5)"""

    ef = make_enriched("app.py", hunks, line_to_nodes={1: ["async"]})
    results = match_patterns(ef)

    matched = [r for r in results if r.suspected_pattern == "Blocking call in async"]
    assert len(matched) > 0, f"Expected blocking-in-async match, got {[r.suspected_pattern for r in results]}"
    print("✅ Blocking call in async detected!")


def test_blocking_outside_async_ignored():
    """Blocking call NOT inside async should NOT be flagged."""
    hunks = """@@ -1,3 +1,3 @@
+    time.sleep(5)"""

    ef = make_enriched("app.py", hunks, line_to_nodes={1: ["function"]})
    results = match_patterns(ef)

    matched = [r for r in results if r.suspected_pattern == "Blocking call in async"]
    assert len(matched) == 0, f"Should not flag blocking call outside async, got {matched}"
    print("✅ Blocking call outside async correctly ignored!")


def test_unbounded_query():
    """Unbounded .all() should be detected."""
    hunks = """@@ -1,3 +1,3 @@
+    results = collection.all()"""

    ef = make_enriched("app.py", hunks)
    results = match_patterns(ef)

    matched = [r for r in results if r.suspected_pattern == "Unbounded query"]
    assert len(matched) > 0, f"Expected unbounded query match, got {[r.suspected_pattern for r in results]}"
    print("✅ Unbounded query detected!")


def test_unbounded_with_limit_ignored():
    """Unbounded .all() followed by .limit() nearby should be ignored."""
    hunks = """@@ -1,3 +1,3 @@
+    results = db.all().limit(100)"""

    ef = make_enriched("app.py", hunks)
    results = match_patterns(ef)

    matched = [r for r in results if r.suspected_pattern == "Unbounded query"]
    assert len(matched) == 0, f"Should not flag .all() with .limit(), got {matched}"
    print("✅ Unbounded query with limit correctly ignored!")


def test_no_false_positives_on_normal_code():
    """Normal code should not trigger any patterns."""
    hunks = """@@ -1,3 +1,3 @@
+    x = 1 + 2
+    print("hello")
+    return result"""

    ef = make_enriched("app.py", hunks)
    results = match_patterns(ef)

    assert len(results) == 0, f"Normal code should have no matches, got {[r.suspected_pattern for r in results]}"
    print("✅ No false positives on normal code!")


if __name__ == "__main__":
    test_orm_in_loop()
    test_orm_outside_loop_ignored()
    test_blocking_in_async()
    test_blocking_outside_async_ignored()
    test_unbounded_query()
    test_unbounded_with_limit_ignored()
    test_no_false_positives_on_normal_code()
    print("\n🎉 All Node 3 tests passed!")
