### Node 1: `diff_fetcher`
- Receives PR number + repo name from webhook payload
- Calls GitHub API to fetch the raw unified diff
- Splits diff into per-file chunks
- Filters to only changed files (ignores deletions-only, lockfiles, generated files)
- Output: list of `{ filename, language, hunks, added_lines }` objects

### Node 2: `parser`
- Runs Tree-sitter on each changed file's full content (not just diff)
- Extracts: function definitions, class definitions, loop constructs, DB call sites, async/await usage
- Maps each AST node back to its line number in the diff
- Output: enriched file objects with AST context attached to each changed line

### Node 3: `pattern_matcher`
- Rule-based pre-filter BEFORE sending to LLM (reduces token cost)
- Flags lines matching known bad patterns:
  - ORM call (`.filter()`, `.find()`, `.query()`) inside a `for`/`while` loop
  - Missing `.select_related()` or `.prefetch_related()` in Django
  - Unbounded `.all()` with no `.limit()`
  - `time.sleep()` or blocking call on async function
  - Raw SQL with `ORDER BY` or `WHERE` on column with no index hint
  - Repeated function call with same args inside loop (should be hoisted)
- Output: list of `{ file, line, snippet, suspected_pattern }` — only suspected lines

### Node 4: `llm_analyzer`
- Receives suspected lines + their full function context from AST
- Sends to Claude with structured prompt (see Prompts section)
- Claude returns structured JSON: confirmed findings with explanation + suggested fix
- Output: list of confirmed `Finding` objects

### Node 5: `severity_scorer`
- Scores each confirmed finding:
  - **High** — inside a hot path (endpoint handler, loop with unbounded input, called on every request)
  - **Medium** — likely slow but not guaranteed (depends on data size)
  - **Low** — code smell, unlikely to regress in practice
- Scoring logic uses: AST call depth, presence of pagination, whether function is an API route handler
- Output: findings with severity attached

### Node 6: `responder`
- For each finding, posts an inline GitHub PR review comment on the exact line
- Comment format: severity badge + explanation + suggested fix code block
- After all comments posted:
  - If any **High** finding → fail the GitHub Check (blocks merge)
  - If only **Medium/Low** → pass with warnings
- Posts a summary review comment at the top of the PR listing all findings