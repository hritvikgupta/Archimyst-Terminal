"""Agno tools for data analysis agent.

This module provides Agno-compatible tools for:
- File analytics (DuckDB)
- Database connectivity (SQL, PostgreSQL)
- File operations
- File generation/export
- Python code execution
- Shell commands

Installation:
    pip install duckdb pandas openpyxl
    pip install sqlalchemy psycopg-binary mysqlclient
    pip install reportlab httpx requests
"""

import io
import sys
import runpy
from typing import Optional, List, Dict, Any
from pathlib import Path


def get_duckdb_tools(db_path: str = None, read_only: bool = False) -> "DuckDbTools":
    """DuckDB tools for analyzing local files (CSV, Parquet, JSON, Excel).
    
    Requires: pip install duckdb pandas openpyxl
    """
    from agno.tools.duckdb import DuckDbTools
    return DuckDbTools(
        db_path=db_path,
        read_only=read_only,
    )


def get_sql_tools(
    db_url: str = None,
    dialect: str = "postgresql",
    user: str = None,
    password: str = None,
    host: str = None,
    port: int = 5432,
    schema: str = None,
    enable_list_tables: bool = True,
    enable_describe_table: bool = True,
    enable_run_sql_query: bool = True,
) -> "SQLTools":
    """SQL tools for any SQLAlchemy-compatible database.
    
    Requires: pip install sqlalchemy
    """
    from agno.tools.sql import SQLTools
    return SQLTools(
        db_url=db_url,
        dialect=dialect,
        user=user,
        password=password,
        host=host,
        port=port,
        schema=schema,
        enable_list_tables=enable_list_tables,
        enable_describe_table=enable_describe_table,
        enable_run_sql_query=enable_run_sql_query,
    )


def get_postgres_tools(
    host: str = None,
    port: int = 5432,
    db_name: str = "postgres",
    user: str = None,
    password: str = None,
) -> "PostgresTools":
    """PostgreSQL dedicated tools.
    
    Requires: pip install psycopg-binary
    """
    if not host:
        return None
    try:
        from agno.tools.postgres import PostgresTools
        return PostgresTools(
            host=host,
            port=port,
            db_name=db_name,
            user=user,
            password=password,
        )
    except ImportError:
        return None


def get_file_tools(
    base_dir = Path("."),
    enable_save_file: bool = True,
    enable_read_file: bool = True,
    enable_delete_file: bool = False,
    enable_list_files: bool = True,
    enable_search_files: bool = True,
) -> "FileTools":
    """File tools for local file operations."""
    from agno.tools.file import FileTools
    return FileTools(
        base_dir=base_dir,
        enable_save_file=enable_save_file,
        enable_read_file=enable_read_file,
        enable_delete_file=enable_delete_file,
        enable_list_files=enable_list_files,
        enable_search_files=enable_search_files,
    )


def get_file_generation_tools(output_directory: str = "outputs") -> "FileGenerationTools":
    """File generation tools for exporting JSON, CSV, PDF, TXT.
    
    Requires: pip install reportlab
    """
    from agno.tools.file_generation import FileGenerationTools
    return FileGenerationTools(
        output_directory=output_directory,
        enable_json_generation=True,
        enable_csv_generation=True,
        enable_pdf_generation=True,
        enable_txt_generation=True,
    )


class _CapturingPythonTools:
    """Subclass-like wrapper for Agno PythonTools that captures stdout.

    Agno's PythonTools.run_python_code uses exec() — any print() in the
    executed code writes directly to the terminal, producing unstructured
    output that bypasses the CLI renderer.  This wrapper redirects stdout
    so printed output is returned as part of the tool result string.
    """

    def __init__(self, base_dir=None, restrict_to_base_dir=True):
        from agno.tools.python import PythonTools
        self._inner = PythonTools(
            base_dir=base_dir,
            restrict_to_base_dir=restrict_to_base_dir,
        )
        # Patch the methods that call exec/runpy to capture stdout
        self._patch()

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @staticmethod
    def _capture(fn):
        """Wrap a function so its stdout is captured and appended to the return value."""
        def wrapper(*args, **kwargs):
            buf = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = buf
            try:
                result = fn(*args, **kwargs)
            finally:
                sys.stdout = old_stdout
            captured = buf.getvalue().rstrip()
            if captured and result:
                return f"{captured}\n{result}"
            return captured or result
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        wrapper.__module__ = getattr(fn, "__module__", None)
        return wrapper

    def _patch(self):
        """Replace entrypoints of code-executing functions with capturing versions."""
        targets = {"run_python_code", "save_to_file_and_run", "run_python_file_return_variable"}
        for name, func_obj in self._inner.functions.items():
            if name in targets and hasattr(func_obj, "entrypoint"):
                func_obj.entrypoint = self._capture(func_obj.entrypoint)


def get_python_tools(
    base_dir = Path("."),
    restrict_to_base_dir: bool = True,
):
    """Python tools for code execution with stdout capturing."""
    return _CapturingPythonTools(
        base_dir=base_dir,
        restrict_to_base_dir=restrict_to_base_dir,
    )


def get_shell_tools(
    base_dir = Path("."),
    enable_run_shell_command: bool = True,
) -> "ShellTools":
    """Shell tools for running shell commands."""
    from agno.tools.shell import ShellTools
    return ShellTools(
        base_dir=base_dir,
        enable_run_shell_command=enable_run_shell_command,
    )


def get_csv_tools() -> "CsvTools":
    """CSV tools for CSV file operations.
    
    Requires: pip install pandas
    """
    from agno.tools.csv_toolkit import CsvTools
    return CsvTools()


def get_all_data_tools(config=None) -> List:
    """Get all data analysis tools based on config.
    
    Args:
        config: Config object with optional database settings
            - config.database_url: SQLAlchemy connection string
            - config.db_host: PostgreSQL host
            - config.db_port: PostgreSQL port
            - config.db_name: Database name
            - config.db_user: Database user
            - config.db_password: Database password
    
    Returns:
        List of Agno tool instances
    
    Note:
        Some tools require additional dependencies:
        - PostgresTools: pip install psycopg-binary
        - FileGenerationTools: pip install reportlab
        - CsvTools: pip install pandas
    """
    tools = []

    # === Core Data Tools (always available) ===
    tools.append(get_duckdb_tools())
    tools.append(get_csv_tools())
    tools.append(get_file_tools())
    tools.append(get_python_tools())
    tools.append(get_shell_tools())
    tools.append(get_file_generation_tools())

    # === Database Tools (optional based on config) ===
    
    # SQL Tools - if database_url is provided
    db_url = getattr(config, 'database_url', None) if config else None
    if db_url:
        tools.append(get_sql_tools(
            db_url=db_url,
            dialect=getattr(config, 'db_dialect', 'postgresql') if config else "postgresql",
        ))
    
    # PostgreSQL Tools - if host is provided
    db_host = getattr(config, 'db_host', None) if config else None
    if db_host:
        pg_tool = get_postgres_tools(
            host=db_host,
            port=getattr(config, 'db_port', 5432) if config else 5432,
            db_name=getattr(config, 'db_name', 'postgres') if config else "postgres",
            user=getattr(config, 'db_user', None) if config else None,
            password=getattr(config, 'db_password', None) if config else None,
        )
        if pg_tool:
            tools.append(pg_tool)

    return tools


__all__ = [
    "get_duckdb_tools",
    "get_sql_tools",
    "get_postgres_tools",
    "get_file_tools",
    "get_file_generation_tools",
    "get_python_tools",
    "get_shell_tools",
    "get_csv_tools",
    "get_all_data_tools",
]
