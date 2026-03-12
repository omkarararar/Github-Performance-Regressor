"""
End-to-end pipeline test — runs Nodes 1→2→3→5 locally with mock data.
Skips Node 4 (LLM) and Node 6 (GitHub posting) since they need API keys.
"""
from nodes.diff_fetcher import parse_diff
from nodes.parser import enrich_file
from nodes.pattern_matcher import scan_all_files
from nodes.severity_scorer import score_all
from nodes.responder import format_comment, build_summary
from models.schemas import Finding


# Simulate a PR diff with intentional performance anti-patterns
MOCK_DIFF = """diff --git a/views.py b/views.py
index abc..def 100644
--- a/views.py
+++ b/views.py
@@ -1,20 +1,35 @@
+import time
+from models import User, Order
+
+class UserAPI:
+    def get_users_handler(self):
+        users = User.objects.all()
+        for user in users:
+            orders = Order.objects.filter(user_id=user.id)
+            user.order_count = len(orders)
+        return users
+
+    async def fetch_report(self):
+        time.sleep(10)
+        data = generate_report()
+        return data
+
+def process_all():
+    results = db.find()
+    return results
diff --git a/package-lock.json b/package-lock.json
index 111..222 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1,2 +1,3 @@
+should be skipped entirely
diff --git a/utils.js b/utils.js
index 333..444 100644
--- a/utils.js
+++ b/utils.js
@@ -1,5 +1,10 @@
+function fetchAllRecords() {
+    const records = db.find();
+    for (let i = 0; i < records.length; i++) {
+        api.query(records[i].id);
+    }
+    return records;
+}"""

# Mock source code for the files (in production, Node 1 would fetch these)
MOCK_SOURCES = {
    "views.py": """import time
from models import User, Order

class UserAPI:
    def get_users_handler(self):
        users = User.objects.all()
        for user in users:
            orders = Order.objects.filter(user_id=user.id)
            user.order_count = len(orders)
        return users

    async def fetch_report(self):
        time.sleep(10)
        data = generate_report()
        return data

def process_all():
    results = db.find()
    return results""",

    "utils.js": """function fetchAllRecords() {
    const records = db.find();
    for (let i = 0; i < records.length; i++) {
        api.query(records[i].id);
    }
    return records;
}""",
}


def run_e2e():
    print("=" * 60)
    print("🔍 END-TO-END PIPELINE TEST")
    print("=" * 60)

    # --- Node 1: Diff Fetcher ---
    print("\n📥 Node 1: Parsing diff...")
    file_changes = parse_diff(MOCK_DIFF)
    print(f"   Found {len(file_changes)} files (filtered out lockfiles)")
    for fc in file_changes:
        print(f"   • {fc.filename} ({fc.language}) — {len(fc.added_lines)} added lines")

    # --- Node 2: Parser ---
    print("\n🌳 Node 2: Running Tree-sitter AST extraction...")
    enriched_files = []
    for fc in file_changes:
        source = MOCK_SOURCES.get(fc.filename, "\n".join(fc.added_lines))
        enriched = enrich_file(fc, source)
        enriched_files.append(enriched)
        print(f"   • {fc.filename}: {len(enriched.ast_nodes)} AST nodes found")
        for node in enriched.ast_nodes:
            print(f"     - {node.type}: {node.name} (lines {node.start_line}-{node.end_line})")

    # --- Node 3: Pattern Matcher ---
    print("\n🔎 Node 3: Scanning for anti-patterns...")
    suspects = scan_all_files(enriched_files)
    print(f"   Found {len(suspects)} suspected patterns:")
    for s in suspects:
        print(f"   ⚠️  {s.suspected_pattern} in {s.file}:{s.line}")
        print(f"      Code: {s.snippet}")

    # --- Node 4: LLM Analyzer (SKIPPED) ---
    print("\n🤖 Node 4: LLM Analysis — SKIPPED (no API key)")
    print("   Simulating: all suspects confirmed as real findings...")

    # Convert suspects to findings (simulating LLM confirmation)
    mock_findings = []
    for s in suspects:
        mock_findings.append(Finding(
            file=s.file,
            line=s.line,
            snippet=s.snippet,
            pattern=s.suspected_pattern,
            explanation=f"[Mock LLM] This is a {s.suspected_pattern} — will cause performance issues",
            suggested_fix=f"[Mock LLM] Refactor to avoid {s.suspected_pattern.lower()}",
        ))

    # --- Node 5: Severity Scorer ---
    print("\n📊 Node 5: Scoring severity...")
    scored = score_all(mock_findings, enriched_files)
    for f in scored:
        icon = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(f.severity, "⚪")
        print(f"   {icon} {f.severity}: {f.pattern} in {f.file}:{f.line}")

    # --- Node 6: Responder (dry run) ---
    print("\n💬 Node 6: Generating PR comments (dry run)...")
    print("-" * 50)
    for f in scored:
        comment = format_comment(f)
        print(f"\n📌 Comment on {f.file}:{f.line}:")
        print(comment)
    print("-" * 50)
    print("\n📋 Summary that would be posted on PR:")
    print("-" * 50)
    summary = build_summary(scored)
    print(summary)

    # --- Results ---
    print("\n" + "=" * 60)
    high = sum(1 for f in scored if f.severity == "High")
    med = sum(1 for f in scored if f.severity == "Medium")
    low = sum(1 for f in scored if f.severity == "Low")
    print(f"📊 Results: {high} High, {med} Medium, {low} Low")
    if high > 0:
        print("❌ PR would be BLOCKED from merging")
    else:
        print("✅ PR would be allowed to merge (with warnings)")
    print("=" * 60)


if __name__ == "__main__":
    run_e2e()
