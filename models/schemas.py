from pydantic import BaseModel
from typing import Optional

class FileChange(BaseModel):
    filename: str
    language: str
    hunks: str
    added_lines: list[str]

class SuspectedPattern(BaseModel):
    file: str
    line: int
    snippet: str
    suspected_pattern: str

class Finding(BaseModel):
    file: str
    line: int
    snippet: str
    pattern: str
    explanation: str
    suggested_fix: str
    severity: Optional[str] = None