"""LangChain tools for the data analysis agent.

All tools are plain @tool-decorated functions from langchain_core.tools,
compatible with LangGraph's ToolNode and model.bind_tools().

For custom_pandas (PandasDataTools) and visualization tools, which are still
Agno Toolkit subclasses, we convert them via _convert_agno_toolkit().
"""

import io
import os
import sys
import glob as _glob
import json
import shlex
import runpy
import subprocess
from pathlib import Path
from typing import Optional, List

from langchain_core.tools import tool

# Force non-interactive backend at import time — prevents threading errors
import matplotlib
matplotlib.use("Agg")



# ─────────────────────────────────────────────────────────────────────────────
# Shell Tools
# ─────────────────────────────────────────────────────────────────────────────

@tool
def run_shell_command(command: str) -> str:
    """Execute a shell command and return the combined stdout and stderr output.

    This tool runs shell commands directly on the system. Use it for file operations,
    running scripts, installing packages, or any system-level task.

    Args:
        command: The complete shell command as a single string (e.g., 'ls -la', 'cat file.txt',
                 'python3 script.py', 'pip install pandas').

    Returns:
        A string containing the command output (stdout + stderr), or an error message
        if the command fails or times out. Returns exit code information if non-zero.

    Examples:
        run_shell_command("ls -la /home/user")
        run_shell_command("python3 analyze_data.py")
        run_shell_command("grep 'error' log.txt")
    """
    try:
        result = subprocess.run(
            shlex.split(command),
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 120 seconds."
    except Exception as e:
        return f"Error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# File Tools
# ─────────────────────────────────────────────────────────────────────────────

@tool
def save_file(file_name: str, contents: str, overwrite: bool = True) -> str:
    """Save text content to a file on disk, creating parent directories if they don't exist.

    Use this tool to write data, code, reports, or any text content to files.
    Automatically creates the directory structure if needed.

    Args:
        file_name: Path to the file (relative or absolute). Examples: 'output.txt',
                   'reports/sales.csv', '/tmp/analysis.json'.
        contents: The text content to write to the file.
        overwrite: If True (default), overwrites existing files. If False, returns
                   an error if the file already exists.

    Returns:
        Success message with character count saved, or error message if the operation fails.

    Examples:
        save_file("results.txt", "Analysis complete: 100 rows processed")
        save_file("data/output.json", json_data, overwrite=True)
    """
    try:
        path = Path(file_name)
        if path.exists() and not overwrite:
            return f"File '{file_name}' already exists and overwrite=False."
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return f"Saved {len(contents)} chars to '{file_name}'."
    except Exception as e:
        return f"Error saving file: {e}"


@tool
def read_file(file_name: str) -> str:
    """Read and return the complete contents of a text file.

    Use this tool to load files for analysis, inspection, or processing.
    Large files (>100KB) are automatically truncated with a note.

    Args:
        file_name: Path to the file to read (relative or absolute).

    Returns:
        The file contents as a string. If the file doesn't exist, returns an error message.
        Files larger than 100KB are truncated with an indicator of total size.

    Examples:
        read_file("data.csv")
        read_file("/home/user/documents/report.txt")
    """
    try:
        path = Path(file_name)
        if not path.exists():
            return f"File '{file_name}' not found."
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > 100_000:
            return content[:100_000] + f"\n... [truncated, total {len(content)} chars]"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def list_files(directory: str = ".") -> str:
    """List all files and subdirectories in a specified directory.

    Displays entries with [DIR] prefix for directories. Useful for exploring
    the file system and finding data files.

    Args:
        directory: Path to the directory to list (default: current directory '.').

    Returns:
        A formatted list of files and directories, or an error message if the
        directory doesn't exist or can't be accessed.

    Examples:
        list_files(".")
        list_files("/home/user/data")
        list_files("outputs")
    """
    try:
        entries = sorted(Path(directory).iterdir())
        lines = []
        for entry in entries:
            prefix = "[DIR] " if entry.is_dir() else "      "
            lines.append(f"{prefix}{entry.name}")
        return "\n".join(lines) if lines else "(empty directory)"
    except Exception as e:
        return f"Error listing directory: {e}"


@tool
def search_files(pattern: str) -> str:
    """Search for files matching a glob pattern in the file system.

    Supports standard glob patterns including wildcards (*) and recursive (**).
    Useful for finding data files, scripts, or any file type.

    Args:
        pattern: Glob pattern to match files. Examples:
                 '*.csv' - all CSV files in current directory
                 '**/*.py' - all Python files recursively
                 'data/*.json' - all JSON files in the data folder

    Returns:
        A list of matching file paths (up to 200 results), or a message if no matches found.

    Examples:
        search_files("*.csv")
        search_files("data/**/*.xlsx")
        search_files("reports/*2024*.pdf")
    """
    try:
        matches = sorted(_glob.glob(pattern, recursive=True))
        if not matches:
            return f"No files matching '{pattern}'."
        return "\n".join(matches[:200])
    except Exception as e:
        return f"Error searching: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Python Tools (with stdout capturing)
# ─────────────────────────────────────────────────────────────────────────────


@tool
def run_python_code(code: str) -> str:
    """Execute arbitrary Python code in a persistent session and return the output.

    This tool runs Python code with full access to the environment. Variables and
    imports persist across multiple calls within the same session. Use print() to
    produce visible output. Matplotlib is configured to use non-interactive backend.

    Args:
        code: The Python code to execute as a string. Can include imports, function
              definitions, data processing, and print statements.

    Returns:
        The captured stdout output, or error message with exception details if code fails.
        Returns "(no output)" if nothing was printed.

    Examples:
        run_python_code("print('Hello World')")
        run_python_code("import pandas as pd; df = pd.DataFrame({'a': [1,2,3]}); print(df)")
        run_python_code("x = 100")  # Variable x persists for next call
    """
    # Force Agg backend so matplotlib doesn't try to open a GUI
    if "matplotlib" in code or "plt" in code:
        _ensure_agg_backend()

    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        # Use a persistent namespace so variables survive across calls
        if not hasattr(run_python_code, "_ns"):
            run_python_code._ns = {}
        exec(code, run_python_code._ns)
    except Exception as e:
        sys.stdout = old_stdout
        captured = buf.getvalue().rstrip()
        err = f"Error: {type(e).__name__}: {e}"
        return f"{captured}\n{err}".strip() if captured else err
    finally:
        sys.stdout = old_stdout
    captured = buf.getvalue().rstrip()

    return captured or "(no output)"


@tool
def save_and_run_python(file_name: str, code: str) -> str:
    """Save Python code to a file and then execute it, returning the output.

    Combines file saving and execution in one step. Useful for creating reusable
    scripts or saving analysis code for later reference.

    Args:
        file_name: Path where the Python file should be saved (e.g., 'script.py',
                   'analysis/process_data.py').
        code: The Python code to save and execute.

    Returns:
        Combined output showing the save confirmation and any stdout/stderr from
        execution, or error details if saving or execution fails.

    Examples:
        save_and_run_python("analyze.py", "import pandas as pd; print('Done')")
        save_and_run_python("charts/plot.py", matplotlib_code)
    """
    try:
        Path(file_name).parent.mkdir(parents=True, exist_ok=True)
        Path(file_name).write_text(code, encoding="utf-8")
    except Exception as e:
        return f"Error saving file: {e}"

    if "matplotlib" in code or "plt" in code:
        _ensure_agg_backend()

    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        runpy.run_path(file_name, run_name="__main__")
    except Exception as e:
        sys.stdout = old_stdout
        captured = buf.getvalue().rstrip()
        err = f"Error: {type(e).__name__}: {e}"
        return f"Saved to '{file_name}'.\n{captured}\n{err}".strip()
    finally:
        sys.stdout = old_stdout
    captured = buf.getvalue().rstrip()

    return f"Saved to '{file_name}'.\n{captured}".strip()


@tool
def pip_install_package(package_name: str) -> str:
    """Install a Python package from PyPI using pip.

    Use this to install libraries needed for data analysis (pandas, numpy, scipy,
    matplotlib, etc.). The installation runs with a 120-second timeout.

    Args:
        package_name: Name of the package to install. Can include version specifiers
                      like 'pandas==2.0.0' or 'numpy>=1.20'.

    Returns:
        Installation output from pip (stdout + stderr), or error message if installation fails.

    Examples:
        pip_install_package("pandas")
        pip_install_package("matplotlib==3.7.0")
        pip_install_package("scipy numpy seaborn")
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package_name],
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            output += f"\nSTDERR:\n{result.stderr.strip()}"
        return output or "(no output)"
    except Exception as e:
        return f"Error installing package: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# SQL Tools (SQLAlchemy-based)
# ─────────────────────────────────────────────────────────────────────────────

_sql_engines = {}


def _get_sql_engine(db_url: str = None):
    """Return (or create) a shared SQLAlchemy engine for the given db_url.

    Uses the database_url from config if no db_url is passed explicitly.
    Raises an error if no database is configured.
    """
    from sqlalchemy import create_engine
    from config import config as _cfg

    url = db_url or getattr(_cfg, "database_url", None)
    if not url:
        raise ValueError(
            "No database configured. Set database_url in your config "
            "or pass db_url directly to the tool."
        )

    if url not in _sql_engines:
        _sql_engines[url] = create_engine(url)
    return _sql_engines[url]


@tool
def sql_query(query: str, db_url: Optional[str] = None) -> str:
    """Execute a SQL query against a database and return results as a formatted table.

    Connects to the configured database (from config) or uses the provided db_url.
    Supports SELECT, INSERT, UPDATE, DELETE, and other SQL statements. Results are
    formatted as a readable table with column headers.

    Args:
        query: The SQL query to execute. Examples:
               "SELECT * FROM customers LIMIT 10"
               "SELECT COUNT(*) as total FROM orders WHERE status = 'shipped'"
        db_url: Optional database connection URL to override the default config.
                Format: "dialect+driver://user:password@host:port/database"

    Returns:
        For SELECT queries: Formatted table with columns and rows (up to 500 rows shown).
        For other queries: Success message with rows affected count.
        Error message if the query fails or database is not configured.

    Examples:
        sql_query("SELECT * FROM users WHERE age > 25")
        sql_query("INSERT INTO logs VALUES (1, 'test')", db_url="postgresql://...")
    """
    try:
        from sqlalchemy import text
        engine = _get_sql_engine(db_url)
        with engine.connect() as conn:
            result = conn.execute(text(query))
            if result.returns_rows:
                columns = list(result.keys())
                rows = result.fetchall()
                if not rows:
                    return "Query executed successfully. No rows returned."
                header = " | ".join(columns)
                sep = "-+-".join("-" * max(len(c), 5) for c in columns)
                lines = [header, sep]
                for row in rows[:500]:
                    lines.append(" | ".join(str(v) for v in row))
                output = "\n".join(lines)
                if len(rows) > 500:
                    output += f"\n... [{len(rows)} total rows, showing first 500]"
                return output
            else:
                conn.commit()
                return f"Query executed successfully. Rows affected: {result.rowcount}"
    except Exception as e:
        return f"SQL error: {e}"


@tool
def sql_list_tables(db_url: Optional[str] = None) -> str:
    """List all table names in the connected database.

    Retrieves the complete list of tables available in the database schema.
    Useful for discovering what data is available before writing queries.

    Args:
        db_url: Optional database connection URL to override the default config.

    Returns:
        A list of table names (one per line), or a message if no tables exist
        or if the database connection fails.

    Examples:
        sql_list_tables()
        sql_list_tables(db_url="postgresql://user:pass@localhost/mydb")
    """
    try:
        from sqlalchemy import inspect
        engine = _get_sql_engine(db_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        if not tables:
            return "No tables found in the database."
        return "\n".join(tables)
    except Exception as e:
        return f"Error: {e}"


@tool
def sql_describe_table(table_name: str, db_url: Optional[str] = None) -> str:
    """Display the schema details of a specific database table.

    Shows column names, data types, nullability constraints, and default values.
    Essential for understanding table structure before querying or loading data.

    Args:
        table_name: Name of the table to describe (case-sensitive depending on database).
        db_url: Optional database connection URL to override the default config.

    Returns:
        Formatted schema information showing columns, types, and constraints,
        or error message if the table doesn't exist.

    Examples:
        sql_describe_table("customers")
        sql_describe_table("orders", db_url="postgresql://...")
    """
    try:
        from sqlalchemy import inspect
        engine = _get_sql_engine(db_url)
        inspector = inspect(engine)
        columns = inspector.get_columns(table_name)
        if not columns:
            return f"Table '{table_name}' not found or has no columns."
        lines = []
        for col in columns:
            nullable = "NULL" if col.get("nullable", True) else "NOT NULL"
            default = f" DEFAULT {col['default']}" if col.get("default") else ""
            lines.append(f"{col['name']:30s} {str(col['type']):20s} {nullable}{default}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@tool
def sql_load_csv(file_path: str, table_name: Optional[str] = None, db_url: Optional[str] = None) -> str:
    """Load data from a CSV file into a database table.

    Uses pandas to read the CSV and SQLAlchemy to load it into the database.
    If the table already exists, it will be replaced (dropped and recreated).
    Table name is auto-derived from filename if not specified.

    Args:
        file_path: Path to the CSV file to load.
        table_name: Target table name (optional). If not provided, derived from filename
                    with special characters replaced by underscores.
        db_url: Optional database connection URL to override the default config.

    Returns:
        Success message with row and column counts, or error message if loading fails.

    Examples:
        sql_load_csv("data/customers.csv")
        sql_load_csv("sales_2024.csv", table_name="sales", db_url="postgresql://...")
    """
    try:
        import pandas as pd
        engine = _get_sql_engine(db_url)
        path = Path(file_path)
        if not path.exists():
            return f"File not found: {file_path}"
        tname = table_name or path.stem.replace("-", "_").replace(" ", "_").replace(".", "_")
        df = pd.read_csv(file_path)
        df.to_sql(tname, engine, if_exists="replace", index=False)
        return f"Loaded '{file_path}' into table '{tname}': {len(df)} rows, {len(df.columns)} columns ({', '.join(df.columns)})"
    except Exception as e:
        return f"Error loading CSV: {e}"


@tool
def sql_load_excel(file_path: str, table_name: Optional[str] = None, sheet_name: Optional[str] = None, db_url: Optional[str] = None) -> str:
    """Load data from an Excel file into a database table.

    Reads Excel files (.xlsx, .xls) using pandas and loads into SQL database.
    Supports specifying a particular sheet. Replaces table if it exists.

    Args:
        file_path: Path to the Excel file to load.
        table_name: Target table name (optional). Auto-derived from filename if not provided.
        sheet_name: Specific sheet to read (optional). Reads first sheet if not specified.
        db_url: Optional database connection URL to override the default config.

    Returns:
        Success message with row and column counts, or error message if loading fails.

    Examples:
        sql_load_excel("data/sales.xlsx")
        sql_load_excel("report.xlsx", sheet_name="Q1 Data", table_name="quarterly_sales")
    """
    try:
        import pandas as pd
        engine = _get_sql_engine(db_url)
        path = Path(file_path)
        if not path.exists():
            return f"File not found: {file_path}"
        tname = table_name or path.stem.replace("-", "_").replace(" ", "_").replace(".", "_")
        kwargs = {}
        if sheet_name:
            kwargs["sheet_name"] = sheet_name
        df = pd.read_excel(file_path, **kwargs)
        df.to_sql(tname, engine, if_exists="replace", index=False)
        return f"Loaded '{file_path}' into table '{tname}': {len(df)} rows, {len(df.columns)} columns ({', '.join(df.columns)})"
    except Exception as e:
        return f"Error loading Excel: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# CSV Tools
# ─────────────────────────────────────────────────────────────────────────────

@tool
def read_csv_file(file_path: str, row_limit: int = 100) -> str:
    """Preview the contents of a CSV file without loading it into a DataFrame.

    Reads and displays the first N rows in a compact, terminal-friendly format.
    Shows file shape (rows x columns) and truncates wide columns for readability.

    Args:
        file_path: Path to the CSV file to preview.
        row_limit: Maximum number of rows to read (default: 100, displays first 20).

    Returns:
        Formatted preview showing shape, column headers, and sample rows,
        or error message if the file cannot be read.

    Examples:
        read_csv_file("data.csv")
        read_csv_file("large_file.csv", row_limit=50)
    """
    try:
        import pandas as pd
        df = pd.read_csv(file_path, nrows=row_limit)
        # Compact output: truncate columns and values to fit terminal
        show = df.head(min(row_limit, 20))
        max_cw = 22
        for col in show.columns:
            show[col] = show[col].astype(str).apply(
                lambda v: (v[:max_cw - 2] + "..") if len(v) > max_cw else v
            )
        col_map = {c: (c[:max_cw - 2] + "..") if len(c) > max_cw else c for c in show.columns}
        show = show.rename(columns=col_map)
        table = show.to_string(index=False)
        extra = ""
        if len(df) > 20:
            extra = f"\n  ... ({df.shape[0]} total rows, showing first 20)"
        return f"Shape: {df.shape[0]} rows x {df.shape[1]} cols\n\n{table}{extra}"
    except Exception as e:
        return f"Error reading CSV: {e}"


@tool
def get_csv_columns(file_path: str) -> str:
    """Inspect the column names and data types of a CSV file.

    Reads just the header row to quickly understand the structure of a CSV
    without loading all data. Shows column names and inferred pandas dtypes.

    Args:
        file_path: Path to the CSV file to inspect.

    Returns:
        List of column names with their data types, or error message if file
        cannot be read.

    Examples:
        get_csv_columns("data.csv")
        get_csv_columns("/path/to/dataset.csv")
    """
    try:
        import pandas as pd
        df = pd.read_csv(file_path, nrows=5)
        lines = [f"{col:30s} {dtype}" for col, dtype in zip(df.columns, df.dtypes)]
        return f"Columns ({len(df.columns)}):\n" + "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# File Generation Tools
# ─────────────────────────────────────────────────────────────────────────────

_OUTPUT_DIR = "outputs"


@tool
def generate_json_file(data: str, filename: Optional[str] = None) -> str:
    """Create a JSON file from a JSON-formatted string.

    Parses the input string as JSON and saves it as a formatted .json file
    in the outputs/ directory. Validates that the input is valid JSON.

    Args:
        data: JSON string to save. Example: '[{"id": 1, "name": "Alice"}, ...]'
        filename: Output filename (default: 'output.json'). Saved to outputs/ directory.

    Returns:
        Success message with the saved file path, or error if JSON is invalid.

    Examples:
        generate_json_file('[{"x": 1, "y": 2}, {"x": 3, "y": 4}]', "points.json")
        generate_json_file(json_string)  # Saves to outputs/output.json
    """
    try:
        parsed = json.loads(data)
        os.makedirs(_OUTPUT_DIR, exist_ok=True)
        fname = filename or "output.json"
        path = os.path.join(_OUTPUT_DIR, fname)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(parsed, f, indent=2, ensure_ascii=False)
        return f"JSON file saved to '{path}'."
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool
def generate_csv_file(data: str, filename: Optional[str] = None) -> str:
    """Create a CSV file from CSV-formatted text content.

    Writes raw CSV text directly to a file in the outputs/ directory.
    Does not validate the CSV format - writes exactly what is provided.

    Args:
        data: CSV-formatted text content (header row + data rows).
        filename: Output filename (default: 'output.csv'). Saved to outputs/ directory.

    Returns:
        Success message with the saved file path, or error if writing fails.

    Examples:
        generate_csv_file("name,age\\nAlice,30\\nBob,25", "people.csv")
        generate_csv_file(csv_content)  # Saves to outputs/output.csv
    """
    try:
        os.makedirs(_OUTPUT_DIR, exist_ok=True)
        fname = filename or "output.csv"
        path = os.path.join(_OUTPUT_DIR, fname)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
        return f"CSV file saved to '{path}'."
    except Exception as e:
        return f"Error: {e}"


@tool
def generate_text_file(content: str, filename: Optional[str] = None) -> str:
    """Create a plain text file with the provided content.

    Saves arbitrary text content to a file in the outputs/ directory.
    Useful for reports, summaries, logs, or any text output.

    Args:
        content: The text content to write to the file.
        filename: Output filename (default: 'output.txt'). Saved to outputs/ directory.

    Returns:
        Success message with the saved file path, or error if writing fails.

    Examples:
        generate_text_file("Analysis Summary\\n==============\\nTotal: 100", "report.txt")
        generate_text_file(log_content)  # Saves to outputs/output.txt
    """
    try:
        os.makedirs(_OUTPUT_DIR, exist_ok=True)
        fname = filename or "output.txt"
        path = os.path.join(_OUTPUT_DIR, fname)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Text file saved to '{path}'."
    except Exception as e:
        return f"Error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Visualization Tools (pure matplotlib — save PNG to disk)
# ─────────────────────────────────────────────────────────────────────────────

_CHARTS_DIR = "charts"


def _ensure_agg_backend():
    """Force matplotlib to use the non-interactive Agg backend."""
    import matplotlib
    matplotlib.use("Agg")


def _parse_data(data) -> list:
    """Parse data arg — accepts JSON string or list. Always returns a list."""
    if isinstance(data, list):
        return data
    if isinstance(data, str):
        return json.loads(data)
    return list(data)


def _save_chart(fig, chart_name: str) -> str:
    """Save a matplotlib figure to charts/ and return the path."""
    _ensure_agg_backend()
    os.makedirs(_CHARTS_DIR, exist_ok=True)
    fpath = os.path.join(_CHARTS_DIR, f"{chart_name}.png")
    fig.savefig(fpath, dpi=150, bbox_inches="tight")
    import matplotlib.pyplot as _plt
    _plt.close(fig)
    return f"Chart saved: {fpath}"


@tool
def create_bar_chart(data: str, x: str, y: str, title: str = "Bar Chart") -> str:
    """Create a bar chart visualization and save as PNG file.

    Generates a bar chart using matplotlib from JSON data. The chart is saved
    to the charts/ directory as a PNG file. Categories are auto-rotated for readability.

    Args:
        data: JSON string — list of objects with x and y values.
              Example: '[{"category": "A", "value": 10}, {"category": "B", "value": 20}]'
        x: Key name in the JSON objects for x-axis categories (bar labels).
        y: Key name in the JSON objects for y-axis values (bar heights).
        title: Chart title (used for display and filename). Default: "Bar Chart".

    Returns:
        Success message with the path to the saved PNG file, or error message.
        The PNG is saved as 'charts/{title}.png'.

    Examples:
        create_bar_chart('[{"cat": "A", "val": 10}, {"cat": "B", "val": 20}]', "cat", "val", "Sales")
    """
    try:
        _ensure_agg_backend()
        import matplotlib.pyplot as plt
        rows = _parse_data(data)
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar([str(r[x]) for r in rows], [r[y] for r in rows])
        ax.set_title(title)
        ax.set_xlabel(x)
        ax.set_ylabel(y)
        plt.xticks(rotation=45, ha="right")
        return _save_chart(fig, title.replace(" ", "_").lower())
    except Exception as e:
        return f"Error creating bar chart: {e}"


@tool
def create_line_chart(data: str, x: str, y: str, title: str = "Line Chart") -> str:
    """Create a line chart visualization and save as PNG file.

    Generates a line chart using matplotlib from JSON data. Useful for showing
    trends over time or continuous data. Chart is saved to charts/ directory.

    Args:
        data: JSON string — list of objects with x and y values.
              Example: '[{"date": "2024-01", "value": 42}, {"date": "2024-02", "value": 50}]'
        x: Key name in the JSON objects for x-axis values (e.g., dates, categories).
        y: Key name in the JSON objects for y-axis values (e.g., measurements).
        title: Chart title (used for display and filename). Default: "Line Chart".

    Returns:
        Success message with the path to the saved PNG file, or error message.
        The PNG is saved as 'charts/{title}.png'.

    Examples:
        create_line_chart('[{"month": "Jan", "sales": 100}, {"month": "Feb", "sales": 150}]', "month", "sales", "Monthly Sales")
    """
    try:
        import matplotlib.pyplot as plt
        rows = _parse_data(data)
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot([str(r[x]) for r in rows], [r[y] for r in rows], marker="o")
        ax.set_title(title)
        ax.set_xlabel(x)
        ax.set_ylabel(y)
        plt.xticks(rotation=45, ha="right")
        return _save_chart(fig, title.replace(" ", "_").lower())
    except Exception as e:
        return f"Error creating line chart: {e}"


@tool
def create_pie_chart(data: str, labels: str, values: str, title: str = "Pie Chart") -> str:
    """Create a pie chart visualization and save as PNG file.

    Generates a pie chart using matplotlib from JSON data. Shows proportions
    with percentage labels. Chart is saved to charts/ directory.

    Args:
        data: JSON string — list of objects with label and value fields.
              Example: '[{"label": "A", "count": 30}, {"label": "B", "count": 70}]'
        labels: Key name in the JSON objects for slice labels (category names).
        values: Key name in the JSON objects for slice values (sizes).
        title: Chart title (used for display and filename). Default: "Pie Chart".

    Returns:
        Success message with the path to the saved PNG file, or error message.
        The PNG is saved as 'charts/{title}.png' with percentage labels on slices.

    Examples:
        create_pie_chart('[{"type": "A", "pct": 40}, {"type": "B", "pct": 60}]', "type", "pct", "Distribution")
    """
    try:
        import matplotlib.pyplot as plt
        rows = _parse_data(data)
        fig, ax = plt.subplots(figsize=(8, 8))
        ax.pie(
            [r[values] for r in rows],
            labels=[str(r[labels]) for r in rows],
            autopct="%1.1f%%",
        )
        ax.set_title(title)
        return _save_chart(fig, title.replace(" ", "_").lower())
    except Exception as e:
        return f"Error creating pie chart: {e}"


@tool
def create_scatter_plot(data: str, x: str, y: str, title: str = "Scatter Plot") -> str:
    """Create a scatter plot visualization and save as PNG file.

    Generates a scatter plot using matplotlib from JSON data. Useful for showing
    relationships between two numeric variables. Chart is saved to charts/ directory.

    Args:
        data: JSON string — list of objects with x and y coordinates.
              Example: '[{"age": 25, "salary": 50000}, {"age": 30, "salary": 60000}]'
        x: Key name in the JSON objects for x-axis values (independent variable).
        y: Key name in the JSON objects for y-axis values (dependent variable).
        title: Chart title (used for display and filename). Default: "Scatter Plot".

    Returns:
        Success message with the path to the saved PNG file, or error message.
        The PNG is saved as 'charts/{title}.png'.

    Examples:
        create_scatter_plot('[{"x": 1, "y": 2}, {"x": 2, "y": 4}]', "x", "y", "Correlation")
    """
    try:
        import matplotlib.pyplot as plt
        rows = _parse_data(data)
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.scatter([r[x] for r in rows], [r[y] for r in rows], alpha=0.7)
        ax.set_title(title)
        ax.set_xlabel(x)
        ax.set_ylabel(y)
        return _save_chart(fig, title.replace(" ", "_").lower())
    except Exception as e:
        return f"Error creating scatter plot: {e}"


@tool
def create_histogram(data: str, column: str, bins: int = 20, title: str = "Histogram") -> str:
    """Create a histogram visualization and save as PNG file.

    Generates a histogram using matplotlib from JSON data. Shows the distribution
    of a single numeric variable. Chart is saved to charts/ directory.

    Args:
        data: JSON string — list of objects containing the values to plot.
              Example: '[{"age": 25}, {"age": 30}, {"age": 35}, ...]'
        column: Key name in the JSON objects for the values to histogram.
        bins: Number of histogram bins (default: 20). More bins = finer granularity.
        title: Chart title (used for display and filename). Default: "Histogram".

    Returns:
        Success message with the path to the saved PNG file, or error message.
        The PNG is saved as 'charts/{title}.png'.

    Examples:
        create_histogram('[{"age": 25}, {"age": 30}, {"age": 35}]', "age", bins=10, "Age Distribution")
    """
    try:
        import matplotlib.pyplot as plt
        rows = _parse_data(data)
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.hist([r[column] for r in rows], bins=bins, edgecolor="black", alpha=0.7)
        ax.set_title(title)
        ax.set_xlabel(column)
        ax.set_ylabel("Frequency")
        return _save_chart(fig, title.replace(" ", "_").lower())
    except Exception as e:
        return f"Error creating histogram: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Main assembler
# ─────────────────────────────────────────────────────────────────────────────

def get_all_data_tools(config=None) -> List:
    """Get all data analysis tools as a flat list of LangChain-compatible tools."""
    tools: list = [
        # Shell
        run_shell_command,
        # File operations
        save_file,
        read_file,
        list_files,
        search_files,
        # Python execution
        run_python_code,
        save_and_run_python,
        pip_install_package,
        # SQL
        sql_query,
        sql_list_tables,
        sql_describe_table,
        sql_load_csv,
        sql_load_excel,
        # CSV
        read_csv_file,
        get_csv_columns,
        # File generation
        generate_json_file,
        generate_csv_file,
        generate_text_file,
        # Visualization (matplotlib — saves PNG to charts/)
        create_bar_chart,
        create_line_chart,
        create_pie_chart,
        create_scatter_plot,
        create_histogram,
    ]

    # Pandas tools — direct @tool imports
    try:
        from tools.custom_pandas import ALL_PANDAS_TOOLS
        tools.extend(ALL_PANDAS_TOOLS)
    except Exception:
        pass

    return tools


__all__ = [
    "run_shell_command",
    "save_file",
    "read_file",
    "list_files",
    "search_files",
    "run_python_code",
    "save_and_run_python",
    "pip_install_package",
    "sql_query",
    "sql_list_tables",
    "sql_describe_table",
    "sql_load_csv",
    "sql_load_excel",
    "read_csv_file",
    "get_csv_columns",
    "generate_json_file",
    "generate_csv_file",
    "generate_text_file",
    "create_bar_chart",
    "create_line_chart",
    "create_pie_chart",
    "create_scatter_plot",
    "create_histogram",
    "get_all_data_tools",
]
