# GitHub Performance Regressor — Project Context

## Project Goal

**Production-grade** automated GitHub PR performance analysis bot — targeting resume-quality for **FAANG / Stripe / Atlassian / Atlan** level roles. Every node must be robust, well-tested, and handle edge cases. Not an MVP — this is a polished, deployable system.

## What Is This?

An automated bot that reviews pull requests for performance regressions (N+1 queries, blocking calls, unbounded queries, etc.) and posts inline review comments on GitHub PRs.

---

## Architecture — 6-Node Pipeline

```
GitHub PR webhook → Node 1 → Node 2 → Node 3 → Node 4 → Node 5 → Node 6 → PR comments
```

| Node | Name | Purpose | Input → Output |
|------|------|---------|----------------|
| 1 | `diff_fetcher` | Fetch PR diff from GitHub API, parse per-file, filter noise | PR number + repo → `list[FileChange]` |
| 2 | `parser` | Run Tree-sitter AST on changed files, extract functions/classes/loops/DB calls | FileChanges → enriched FileChanges with AST context |
| 3 | `pattern_matcher` | Rule-based pre-filter for known bad patterns (saves LLM tokens) | enriched FileChanges → `list[SuspectedPattern]` |
| 4 | `llm_analyzer` | Send suspects + context to Claude for confirmation + fix suggestions | SuspectedPatterns → `list[Finding]` (severity=None) |
| 5 | `severity_scorer` | Score findings as High/Medium/Low based on call depth, hot paths, pagination | Findings → Findings with severity |
| 6 | `responder` | Post inline PR comments, fail check on High severity | Findings → GitHub PR review comments |

### Patterns Node 3 Detects
- ORM call inside `for`/`while` loop (N+1 query)
- Missing `.select_related()` / `.prefetch_related()` in Django
- Unbounded `.all()` with no `.limit()`
- `time.sleep()` or blocking call in async function
- Raw SQL `ORDER BY`/`WHERE` on unindexed column
- Repeated function call with same args inside loop

### Severity Rules (Node 5)
- **High** — inside hot path (endpoint handler, unbounded loop, called every request) → blocks merge
- **Medium** — likely slow but depends on data size → warning
- **Low** — code smell, unlikely to regress → warning

---

## Tech Stack
- **Language:** Python
- **Web framework:** FastAPI + Uvicorn
- **GitHub integration:** PyGithub + httpx
- **AST parsing:** Tree-sitter (Python + JavaScript)
- **LLM:** Anthropic Claude (via `anthropic` SDK)
- **Data validation:** Pydantic

---

## Project Structure

```
Github Performance Regressor/
├── .env                    # API keys (GITHUB_TOKEN, ANTHROPIC_API_KEY, GITHUB_WEBHOOK_SECRET)
├── .gitignore
├── aim.md                  # Original pipeline design doc
├── config.py               # Loads env vars via python-dotenv
├── main.py                 # FastAPI entry point with /webhook endpoint
├── requirements.txt        # Python dependencies
├── context.md              # This file
│
├── models/
│   ├── __init__.py
│   └── schemas.py          # Pydantic models: FileChange, SuspectedPattern, Finding
│
├── nodes/
│   ├── __init__.py
│   └── diff_fetcher.py     # Node 1 — fetches PR diff, parses per-file, filters noise
│
├── prompts/                # LLM prompt templates (to be built)
│
└── tests/
    ├── __init__.py
    └── test_diff_fetcher.py  # Node 1 tests (all passing ✅)
```

---

## Data Models (`models/schemas.py`)

- **`FileChange`** — Node 1 output: `filename`, `language`, `hunks`, `added_lines`
- **`SuspectedPattern`** — Node 3 output: `file`, `line`, `snippet`, `suspected_pattern`
- **`Finding`** — Final result: `file`, `line`, `snippet`, `pattern`, `explanation`, `suggested_fix`, `severity`

---

## Key Decisions
- **Pydantic** for data validation between nodes — enforces type safety at node boundaries
- **Rule-based pre-filter (Node 3) before LLM (Node 4)** — reduces token cost by only sending suspected lines
- **FastAPI** as webhook listener — async-native, auto-generates API docs at `/docs`
- **Tree-sitter** for AST parsing — fast, multi-language, works on full file content (not just diff)

---

## What's Built ✅
- [x] Project scaffolding (folders, __init__.py files)
- [x] `config.py` — env var loading
- [x] `models/schemas.py` — Pydantic data models
- [x] `main.py` — FastAPI server (tested, runs on port 8000)
- [x] `requirements.txt` — all deps installed
- [x] `nodes/diff_fetcher.py` — Node 1 basic implementation (tested ✅)
- [x] `tests/test_diff_fetcher.py` — Node 1 tests (parse_diff, should_skip, get_language)

## Node 1 Enhancements Needed (before production)
- [ ] **Line number tracking** — map each added line to its actual line number in the file (Node 6 needs this for inline PR comments)
- [ ] **Full file content fetching** — Node 2 (Tree-sitter) needs the entire file, not just the diff. Add a second API call to fetch file contents.
- [ ] **Pagination** — GitHub caps diffs at ~3000 lines / 300 files. Handle large PRs.
- [ ] **Renamed file detection** — handle `rename from/to` markers in diffs
- [ ] **Binary file handling** — skip `Binary files differ` entries gracefully
- [ ] **Rate limiting + retries** — GitHub API has rate limits (5000 req/hr). Add retry logic with exponential backoff.
- [ ] **Error handling** — graceful failures for 404 (bad PR), 403 (no access), network errors

## What's Next ⬜
- [ ] `nodes/parser.py` — Node 2 (Tree-sitter AST)
- [ ] `nodes/pattern_matcher.py` — Node 3 (rule-based detection)
- [ ] `nodes/llm_analyzer.py` — Node 4 (Claude integration)
- [ ] `nodes/severity_scorer.py` — Node 5 (scoring logic)
- [ ] `nodes/responder.py` — Node 6 (PR comment posting)
- [ ] Wire pipeline in `main.py`
- [ ] `prompts/analyzer_prompt.txt` — Claude prompt template
- [ ] Harden Node 1 (line numbers, pagination, retries, full file fetch)
- [ ] End-to-end testing on a real PR
- [ ] Deploy as GitHub App
