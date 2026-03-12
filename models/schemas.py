from pydantic import BaseModel
from typing import Optional

class FileChange(BaseModel):
    filename: str
    language: str
    hunks: str
    added_lines: list[str]
    line_numbers: list[int] = []    # actual file line numbers for each added line
    full_source: str = ""           # complete file content (for AST parsing)

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

class ASTNode(BaseModel):
    type: str
    name: str
    start_line: int
    end_line: int
    snippet: str

class EnrichedFileChange(BaseModel):
    filename: str
    language: str
    hunks: str
    added_lines: list[str]
    line_numbers: list[int] = []
    ast_nodes: list[ASTNode]
    line_to_nodes: dict[int, list[str]]