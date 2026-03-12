from nodes.diff_fetcher import parse_diff, should_skip, get_language, _is_binary_diff

# A fake unified diff with proper hunk headers for line number tracking
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
    assert len(results) == 2, f"Expected 2 files, got {len(results)}"

    assert results[0].filename == "app.py"
    assert results[0].language == "python"
    assert len(results[0].added_lines) == 2
    assert results[0].added_lines[0] == 'new_line = "hello"'

    assert results[1].filename == "utils/helpers.js"
    assert results[1].language == "javascript"
    assert len(results[1].added_lines) == 1
    print("✅ parse_diff works correctly!")

def test_line_numbers():
    """New: line numbers should be tracked from hunk headers."""
    results = parse_diff(SAMPLE_DIFF)
    # app.py: @@ -10,3 +10,5 @@ → first added line at line 11 (after context line at 10)
    assert results[0].line_numbers[0] == 11, f"Expected line 11, got {results[0].line_numbers[0]}"
    assert results[0].line_numbers[1] == 12, f"Expected line 12, got {results[0].line_numbers[1]}"
    # helpers.js: @@ -5,2 +5,3 @@ → added line at line 5
    assert results[1].line_numbers[0] == 5, f"Expected line 5, got {results[1].line_numbers[0]}"
    print("✅ Line number tracking works!")

def test_should_skip():
    assert should_skip("package-lock.json") == True
    assert should_skip("styles.min.css") == True
    assert should_skip("app.py") == False
    assert should_skip("logo.png") == True
    assert should_skip("node_modules/foo.js") == True
    assert should_skip("vendor/lib.py") == True
    print("✅ should_skip works correctly!")

def test_get_language():
    assert get_language("app.py") == "python"
    assert get_language("index.js") == "javascript"
    assert get_language("main.go") == "go"
    assert get_language("readme.md") == "unknown"
    assert get_language("app.tsx") == "typescript"
    print("✅ get_language works correctly!")

def test_binary_detection():
    assert _is_binary_diff(["Binary files a/img.png and b/img.png differ"]) == True
    assert _is_binary_diff(["GIT binary patch"]) == True
    assert _is_binary_diff(["+normal code line"]) == False
    print("✅ Binary detection works!")

if __name__ == "__main__":
    test_should_skip()
    test_get_language()
    test_parse_diff()
    test_line_numbers()
    test_binary_detection()
    print("\n🎉 All Node 1 tests passed!")
