"""Compatibility renderer for existing Python artifacts and imports."""
from dataclasses import dataclass
from .code import CodeRenderer


@dataclass(slots=True)
class PythonRenderer(CodeRenderer):
    kind: str = "python"
    default_language: str | None = "python"
