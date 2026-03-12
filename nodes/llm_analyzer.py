import json
import anthropic
from config import ANTHROPIC_API_KEY
from models.schemas import SuspectedPattern, Finding


def load_prompt_template() -> str:
    with open("prompts/analyzer_prompt.txt", "r") as f:
        return f.read()


def format_suspects(suspects: list[SuspectedPattern]) -> str:
    """Format suspected patterns into a readable string for the LLM prompt."""
    lines = []
    for i, s in enumerate(suspects, 1):
        lines.append(f"### Issue {i}")
        lines.append(f"- **File:** {s.file}")
        lines.append(f"- **Line:** {s.line}")
        lines.append(f"- **Pattern:** {s.suspected_pattern}")
        lines.append(f"- **Code:** `{s.snippet}`")
        lines.append("")
    return "\n".join(lines)


async def analyze(suspects: list[SuspectedPattern]) -> list[Finding]:
    """
    Main entry point for Node 4.
    Sends suspected patterns to Claude for confirmation and returns confirmed findings.
    """
    if not suspects:
        return []

    template = load_prompt_template()
    formatted = format_suspects(suspects)
    prompt = template.replace("{suspected_patterns}", formatted)

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    message = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[
            {"role": "user", "content": prompt}
        ],
    )

    response_text = message.content[0].text
    findings = parse_response(response_text)
    return findings


def parse_response(response_text: str) -> list[Finding]:
    """Parse Claude's JSON response into Finding objects."""
    # Extract JSON from response (handle markdown code blocks)
    text = response_text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    findings = []
    for item in data:
        findings.append(Finding(
            file=item.get("file", ""),
            line=item.get("line", 0),
            snippet=item.get("snippet", ""),
            pattern=item.get("pattern", ""),
            explanation=item.get("explanation", ""),
            suggested_fix=item.get("suggested_fix", ""),
        ))

    return findings
