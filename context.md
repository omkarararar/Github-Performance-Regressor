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
├── main.py                 # FastAPI entry point — wires all 6 nodes + webhook signature verification
├── requirements.txt        # Python dependencies
├── context.md              # This file
│
├── models/
│   ├── __init__.py
│   └── schemas.py          # Pydantic models: FileChange, SuspectedPattern, Finding, ASTNode, EnrichedFileChange
│
├── nodes/
│   ├── __init__.py
│   ├── diff_fetcher.py     # Node 1 — fetches PR diff, parses per-file, filters noise
│   ├── parser.py           # Node 2 — Tree-sitter AST extraction (functions, classes, loops, async)
│   ├── pattern_matcher.py  # Node 3 — rule-based detection of 6 anti-patterns
│   ├── llm_analyzer.py     # Node 4 — sends suspects to Claude for confirmation
│   ├── severity_scorer.py  # Node 5 — scores findings as High/Medium/Low
│   └── responder.py        # Node 6 — posts inline PR comments + summary + commit status
│
├── prompts/
│   └── analyzer_prompt.txt # Claude prompt template for performance analysis
│
└── tests/
    ├── __init__.py
    ├── test_diff_fetcher.py    # Node 1 tests ✅
    ├── test_parser.py          # Node 2 tests ✅
    ├── test_pattern_matcher.py # Node 3 tests ✅
    ├── test_llm_analyzer.py    # Node 4 tests ✅
    ├── test_severity_scorer.py # Node 5 tests ✅
    └── test_responder.py       # Node 6 tests ✅
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
- [x] `models/schemas.py` — Pydantic data models (FileChange, SuspectedPattern, Finding, ASTNode, EnrichedFileChange)
- [x] `main.py` — Full pipeline wiring with webhook signature verification
- [x] `requirements.txt` — all deps installed (tree-sitter 0.25.0)
- [x] `nodes/diff_fetcher.py` — Node 1 (tested ✅)
- [x] `nodes/parser.py` — Node 2 Tree-sitter AST extraction (tested ✅)
- [x] `nodes/pattern_matcher.py` — Node 3 rule-based detection of 6 anti-patterns (tested ✅)
- [x] `nodes/llm_analyzer.py` — Node 4 Claude integration with response parsing (tested ✅)
- [x] `nodes/severity_scorer.py` — Node 5 severity scoring (tested ✅)
- [x] `nodes/responder.py` — Node 6 PR comment posting + summary (tested ✅)
- [x] `prompts/analyzer_prompt.txt` — Claude prompt template
- [x] All 6 test suites passing (26 total tests)

## What's Next ⬜ (Phase 2 — Production Hardening)
- [ ] End-to-end test on a real PR
- [ ] Deploy webhook (ngrok/smee.io + GitHub App)
- [ ] Harden Node 1 (line numbers, pagination, retries, full file fetch)
- [ ] Harden all nodes (error handling, logging, rate limiting)
- [ ] CI/CD pipeline
- [ ] README with architecture diagram
