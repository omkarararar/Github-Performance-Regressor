from nodes.diff_fetcher import parse_diff, should_skip, get_language

# A fake unified diff (similar to what GitHub returns)
SAMPLE_DIFF = """diff --git a/app.py b/app.py
index abc123..def456 100644
--- a/app.py
+++ b/app.py
@@ -10,3 +10,5 @@
 existing_line = True
+new_line = "hello"
+another_new_line = 42
-removed_line = False
diff --git a/package-lock.json b/package-lock.json
index 111..222 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1,2 +1,3 @@
+should be skipped
diff --git a/utils/helpers.js b/utils/helpers.js
index 333..444 100644
--- a/utils/helpers.js
+++ b/utils/helpers.js
@@ -5,2 +5,3 @@
+function newHelper() { return true; }"""

def test_parse_diff():
    results = parse_diff(SAMPLE_DIFF)

    # Should have 2 files (package-lock.json should be skipped)
    assert len(results) == 2, f"Expected 2 files, got {len(results)}"

    # First file: app.py
    assert results[0].filename == "app.py"
    assert results[0].language == "python"
    assert len(results[0].added_lines) == 2
    assert results[0].added_lines[0] == 'new_line = "hello"'

    # Second file: helpers.js
    assert results[1].filename == "utils/helpers.js"
    assert results[1].language == "javascript"
    assert len(results[1].added_lines) == 1

    print("✅ parse_diff works correctly!")

def test_should_skip():
    assert should_skip("package-lock.json") == True
    assert should_skip("styles.min.css") == True
    assert should_skip("app.py") == False
    assert should_skip("logo.png") == True
    print("✅ should_skip works correctly!")

def test_get_language():
    assert get_language("app.py") == "python"
    assert get_language("index.js") == "javascript"
    assert get_language("main.go") == "go"
    assert get_language("readme.md") == "unknown"
    print("✅ get_language works correctly!")

if __name__ == "__main__":
    test_should_skip()
    test_get_language()
    test_parse_diff()
    print("\n🎉 All Node 1 tests passed!")
