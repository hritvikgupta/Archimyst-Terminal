"""Filesystem tool wrappers with LangChain @tool decorators."""

from langchain_core.tools import tool

from tools.services.filesystem_service import (
    MAX_FILE_CHARS,
    FilesystemToolService,
)

_service = FilesystemToolService()


def get_history_manager():
    return _service.get_history_manager()


def trigger_checkpoint(msg, files):
    return _service.trigger_checkpoint(msg, files)


def read_file(file_path: str, line_numbers: bool = False) -> str:
    return _service.read_file(file_path, line_numbers)


def list_dir(directory: str = ".", recursive: bool = False, limit: int = 1000) -> str:
    return _service.list_dir(directory, recursive, limit)


@tool
def write_to_file_tool(file_path: str, content: str) -> str:
    """Create a new file or overwrite an existing file with the given content."""
    return _service.write_to_file_tool(file_path, content)


@tool
def delete_file(file_path: str) -> str:
    """Permanently delete a file from the filesystem."""
    return _service.delete_file(file_path)


@tool
def edit_file(file_path: str, edits: str, message: str = "AI Edit") -> str:
    """Apply surgical search-and-replace edits to an existing file. The edits parameter is a diff-style block specifying SEARCH and REPLACE sections."""
    return _service.edit_file(file_path, edits, message)


@tool
def whole_file_update(edits: str, message: str = "Whole file update") -> str:
    """Replace the entire content of a file. Use when more than 50% of the file changes or when creating a new file."""
    return _service.whole_file_update(edits, message)




def view_context(file_path: str, line_number: int, radius: int = 10) -> str:
    return _service.view_context(file_path, line_number, radius)


def read_file_chunked(file_path: str, chunk_number: int = 0, chunk_size: int = 200) -> str:
    return _service.read_file_chunked(file_path, chunk_number, chunk_size)


__all__ = [
    "MAX_FILE_CHARS",
    "get_history_manager",
    "trigger_checkpoint",
    "read_file",
    "list_dir",
    "write_to_file_tool",
    "delete_file",
    "edit_file",
    "whole_file_update",
    "view_context",
    "read_file_chunked",
    "FilesystemToolService",
]
