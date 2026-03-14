from pydantic import BaseModel, Field
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
    call_chain: Optional[list[str]] = None
    cross_file: bool = False

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
    called_from_loop: set[int] = Field(default_factory=set)
    called_from_async: set[int] = Field(default_factory=set)


class FunctionDefinition(BaseModel):
    """A function/method found in the codebase, used for call graph analysis."""
    name: str
    file_path: str
    start_line: int
    end_line: int
    containing_contexts: list[str] = []


class CallSite(BaseModel):
    """A call expression found in source code."""
    callee_name: str
    caller_file: str
    call_line: int
    call_context: list[str] = []