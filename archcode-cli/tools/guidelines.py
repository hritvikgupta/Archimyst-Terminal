"""Backward-compatible guidelines wrapper."""

from langchain_core.tools import tool

from tools.services.guidelines_service import GuidelinesService


_service = GuidelinesService()

TERMINAL_COMMANDS = _service.TERMINAL_COMMANDS
GITHUB_COMMANDS = _service.GITHUB_COMMANDS
SKILL_COMMANDS = _service.SKILL_COMMANDS
CODING_STANDARDS = _service.CODING_STANDARDS
EXECUTION_PRINCIPLES = _service.EXECUTION_PRINCIPLES


def _build_active_skills_section() -> str:
    return _service._build_active_skills_section()


def _build_mcp_section() -> str:
    return _service._build_mcp_section()


@tool
def get_terminal_reference() -> str:
    """Return the terminal command reference guide covering search, git, network, and environment-variable patterns."""
    return _service.get_terminal_reference()


@tool
def get_github_reference() -> str:
    """Return the GitHub CLI command reference guide for issues, pull requests, branches, and commits."""
    return _service.get_github_reference()


@tool
def get_skill_usage_guidelines() -> str:
    """Return usage guidelines for the available skills (slash commands) in this session."""
    return _service.get_skill_usage_guidelines()


@tool
def get_coding_standards() -> str:
    """Return the project coding standards including style, structure, and naming conventions."""
    return _service.get_coding_standards()


@tool
def get_execution_principles() -> str:
    """Return the execution principles that govern how the agent should plan and carry out tasks."""
    return _service.get_execution_principles()


@tool
def get_mcp_guidelines() -> str:
    """Return guidelines for working with MCP (Model Context Protocol) servers and tools."""
    return _service.get_mcp_guidelines()


@tool
def get_active_skills_overview() -> str:
    """Return an overview of all currently active skills and what each one does."""
    return _service.get_active_skills_overview()


__all__ = [
    "TERMINAL_COMMANDS",
    "GITHUB_COMMANDS",
    "SKILL_COMMANDS",
    "CODING_STANDARDS",
    "EXECUTION_PRINCIPLES",
    "_build_active_skills_section",
    "_build_mcp_section",
    "get_terminal_reference",
    "get_github_reference",
    "get_skill_usage_guidelines",
    "get_coding_standards",
    "get_execution_principles",
    "get_mcp_guidelines",
    "get_active_skills_overview",
    "GuidelinesService",
]
