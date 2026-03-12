import json
import asyncio
import anthropic
from config import ANTHROPIC_API_KEY
from models.schemas import SuspectedPattern, Finding
from logger import get_logger

log = get_logger("llm_analyzer")

MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]
MAX_SUSPECTS_PER_BATCH = 20  # avoid sending too many suspects in one prompt
API_TIMEOUT = 60.0


def load_prompt_template() -> str:
    with open("prompts/analyzer_prompt.txt", "r") as f:
        return f.read()


def format_suspects(suspects: list[SuspectedPattern]) -> str:
    lines = []
    for i, s in enumerate(suspects, 1):
        lines.append(f"### Issue {i}")
        lines.append(f"- **File:** {s.file}")
        lines.append(f"- **Line:** {s.line}")
        lines.append(f"- **Pattern:** {s.suspected_pattern}")
        lines.append(f"- **Code:** `{s.snippet}`")
        lines.append("")
    return "\n".join(lines)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token)."""
    return len(text) // 4


async def _call_claude(prompt: str) -> str:
    """Call Claude API with retry logic."""
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            message = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
                timeout=API_TIMEOUT,
            )
            log.info(f"Claude API call succeeded — {message.usage.input_tokens} input tokens, {message.usage.output_tokens} output tokens")
            return message.content[0].text

        except anthropic.RateLimitError as e:
            last_error = e
            delay = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else RETRY_DELAYS[-1]
            log.warning(f"Rate limited by Claude API. Retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})")
            await asyncio.sleep(delay)

        except anthropic.APIError as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                log.warning(f"Claude API error: {e}. Retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})")
                await asyncio.sleep(delay)
            else:
                log.error(f"Claude API failed after {MAX_RETRIES} attempts: {e}")
                raise

        except Exception as e:
            log.error(f"Unexpected error calling Claude: {e}")
            raise

    raise last_error


async def analyze(suspects: list[SuspectedPattern]) -> list[Finding]:
    """
    Main entry point for Node 4.
    Sends suspected patterns to Claude in batches for confirmation.
    """
    if not suspects:
        log.info("No suspects to analyze")
        return []

    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set — skipping LLM analysis")
        return []

    template = load_prompt_template()
    all_findings = []

    # Batch suspects to stay within token limits
    batches = [suspects[i:i + MAX_SUSPECTS_PER_BATCH] for i in range(0, len(suspects), MAX_SUSPECTS_PER_BATCH)]
    log.info(f"Analyzing {len(suspects)} suspects in {len(batches)} batch(es)")

    for batch_idx, batch in enumerate(batches):
        formatted = format_suspects(batch)
        prompt = template.replace("{suspected_patterns}", formatted)

        token_estimate = _estimate_tokens(prompt)
        log.info(f"Batch {batch_idx + 1}: {len(batch)} suspects, ~{token_estimate} tokens")

        try:
            response_text = await _call_claude(prompt)
            findings = parse_response(response_text)
            all_findings.extend(findings)
            log.info(f"Batch {batch_idx + 1}: {len(findings)} confirmed findings")
        except Exception as e:
            log.error(f"Batch {batch_idx + 1} failed: {e}")

    log.info(f"Node 4 complete: {len(all_findings)} confirmed findings from {len(suspects)} suspects")
    return all_findings


def parse_response(response_text: str) -> list[Finding]:
    """Parse Claude's JSON response into Finding objects with validation."""
    text = response_text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse Claude response as JSON: {e}")
        log.debug(f"Raw response: {text[:500]}")
        return []

    if not isinstance(data, list):
        log.error(f"Expected JSON array, got {type(data).__name__}")
        return []

    findings = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            log.warning(f"Skipping invalid finding at index {i}: not a dict")
            continue

        # Validate required fields
        required = ["file", "line", "pattern", "explanation", "suggested_fix"]
        missing = [f for f in required if not item.get(f)]
        if missing:
            log.warning(f"Finding {i} missing required fields: {missing}")

        try:
            findings.append(Finding(
                file=item.get("file", "unknown"),
                line=int(item.get("line", 0)),
                snippet=item.get("snippet", ""),
                pattern=item.get("pattern", "unknown"),
                explanation=item.get("explanation", "No explanation provided"),
                suggested_fix=item.get("suggested_fix", "No fix suggested"),
            ))
        except (ValueError, TypeError) as e:
            log.warning(f"Failed to create Finding from index {i}: {e}")

    return findings
