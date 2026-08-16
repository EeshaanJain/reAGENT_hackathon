"""
Serena Repository Understanding Harness

Reusable, repo-agnostic semantic code analysis using Serena MCP.
"""

from .harness import (
    Finding,
    RepositoryFindings,
    SerenaRepositoryAnalyzer,
)

__version__ = "0.1.0"
__all__ = [
    "Finding",
    "RepositoryFindings",
    "SerenaRepositoryAnalyzer",
]
