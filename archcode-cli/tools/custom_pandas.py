"""
Custom Pandas Tools for Data Analysis Agent.

All tools are @tool-decorated module-level functions using langchain_core.tools.
DataFrames are stored in a module-level dict so they persist across tool calls.

Usage:
    from tools.custom_pandas import pandas_read_csv, pandas_head, ...
"""

import io
import os
import textwrap
from typing import Any, Dict, List, Optional, Union

import pandas as pd
from langchain_core.tools import tool


# Module-level DataFrame store — persists across tool calls within a session
_dataframes: Dict[str, pd.DataFrame] = {}


# =========================================================================
# COMPACT TABLE FORMATTING
# =========================================================================

def _get_terminal_width() -> int:
    """Get terminal width, default to 100 if unavailable."""
    try:
        return os.get_terminal_size().columns
    except (OSError, ValueError):
        return 100


def _short_col(name: str, max_len: int = 20) -> str:
    """Shorten a column name to fit in a compact table."""
    if len(name) <= max_len:
        return name
    return name[:max_len - 2] + ".."


def _compact_table(df: pd.DataFrame, max_rows: int = 10, max_col_width: int = 25) -> str:
    """Format a DataFrame as a compact, terminal-friendly table.

    - Truncates long column names
    - Limits column value widths
    - Fits within terminal width by selecting visible columns
    """
    if df.empty:
        return "(empty DataFrame)"

    term_w = _get_terminal_width() - 4  # leave margin
    show_df = df.head(max_rows).copy()

    # Shorten column names
    col_map = {c: _short_col(c, max_col_width) for c in show_df.columns}
    show_df = show_df.rename(columns=col_map)

    # Truncate cell values (convert to str first to handle NaN/floats safely)
    for col in show_df.columns:
        show_df[col] = show_df[col].fillna("").astype(str).apply(
            lambda v: (v[:max_col_width - 2] + "..") if len(str(v)) > max_col_width else v
        )

    # Convert to string with tabulate-style formatting
    try:
        table_str = show_df.to_string(index=False, max_colwidth=max_col_width)
    except TypeError:
        # Older pandas doesn't have max_colwidth in to_string
        table_str = show_df.to_string(index=False)

    # If still too wide, limit columns
    if table_str and len(table_str.split("\n")[0]) > term_w:
        # Try with fewer columns
        n_cols = max(3, int(len(show_df.columns) * term_w / len(table_str.split("\n")[0])))
        show_df = show_df.iloc[:, :n_cols]
        extra = len(df.columns) - n_cols
        try:
            table_str = show_df.to_string(index=False, max_colwidth=max_col_width)
        except TypeError:
            table_str = show_df.to_string(index=False)
        if extra > 0:
            table_str += f"\n  ... +{extra} more columns"

    if len(df) > max_rows:
        table_str += f"\n  ... ({len(df)} total rows, showing first {max_rows})"

    return table_str


# =========================================================================
# DATA LOADING TOOLS
# =========================================================================

@tool
def pandas_read_csv(
    dataframe_name: str,
    filepath_or_buffer: str,
    sep: str = ",",
    encoding: str = "utf-8",
    nrows: Optional[int] = None,
) -> str:
    """
    Load data from a CSV file into a pandas DataFrame.

    Args:
        dataframe_name: Name to assign to the DataFrame in memory (required)
        filepath_or_buffer: Path to the CSV file (required)
        sep: Column delimiter (default: ',')
        encoding: File encoding (default: 'utf-8')
        nrows: Number of rows to read

    Returns:
        Success message with DataFrame name and shape, or error message
    """
    try:
        if dataframe_name in _dataframes:
            return f"DataFrame '{dataframe_name}' already exists. Use a different name or delete it first."

        df = pd.read_csv(
            filepath_or_buffer=filepath_or_buffer,
            sep=sep,
            encoding=encoding,
            nrows=nrows,
        )

        _dataframes[dataframe_name] = df
        return f"Loaded '{dataframe_name}': {df.shape[0]} rows x {df.shape[1]} cols\n\n{_compact_table(df, max_rows=5)}"

    except FileNotFoundError:
        return f"Error: File not found at path: {filepath_or_buffer}"
    except Exception as e:
        return f"Error loading CSV: {str(e)}"


@tool
def pandas_read_excel(
    dataframe_name: str,
    file_path: str,
    sheet_name: Optional[str] = None,
    nrows: Optional[int] = None,
) -> str:
    """
    Load data from an Excel file into a pandas DataFrame.

    Args:
        dataframe_name: Name to assign to the DataFrame in memory (required)
        file_path: Path to the Excel file (required)
        sheet_name: Sheet name or index (default: first sheet)
        nrows: Number of rows to read

    Returns:
        Success message with DataFrame name and shape, or error message
    """
    try:
        if dataframe_name in _dataframes:
            return f"DataFrame '{dataframe_name}' already exists. Use a different name or delete it first."

        kwargs = {}
        if sheet_name is not None:
            kwargs["sheet_name"] = sheet_name
        if nrows is not None:
            kwargs["nrows"] = nrows

        df = pd.read_excel(file_path, **kwargs)

        _dataframes[dataframe_name] = df
        return f"Loaded '{dataframe_name}': {df.shape[0]} rows x {df.shape[1]} cols\n\n{_compact_table(df, max_rows=5)}"

    except FileNotFoundError:
        return f"Error: File not found at path: {file_path}"
    except Exception as e:
        return f"Error loading Excel: {str(e)}"


@tool
def pandas_read_json(
    dataframe_name: str,
    path_or_buf: str,
    orient: str = "columns",
    lines: bool = False,
    nrows: Optional[int] = None,
) -> str:
    """
    Load data from a JSON file into a pandas DataFrame.

    Args:
        dataframe_name: Name to assign to the DataFrame in memory (required)
        path_or_buf: Path to the JSON file (required)
        orient: Expected JSON format ('columns', 'records', 'index', 'split', 'table')
        lines: If True, read file as JSON lines (one JSON object per line)
        nrows: Number of rows to read

    Returns:
        Success message with DataFrame name and shape, or error message
    """
    try:
        if dataframe_name in _dataframes:
            return f"DataFrame '{dataframe_name}' already exists. Use a different name or delete it first."

        df = pd.read_json(
            path_or_buf=path_or_buf,
            orient=orient,
            lines=lines,
            nrows=nrows,
        )

        _dataframes[dataframe_name] = df
        return f"Loaded '{dataframe_name}': {df.shape[0]} rows x {df.shape[1]} cols\n\n{_compact_table(df, max_rows=5)}"

    except FileNotFoundError:
        return f"Error: File not found at path: {path_or_buf}"
    except Exception as e:
        return f"Error loading JSON: {str(e)}"


@tool
def pandas_read_parquet(
    dataframe_name: str,
    path: str,
    columns: Optional[List[str]] = None,
) -> str:
    """
    Load data from a Parquet file into a pandas DataFrame.

    Args:
        dataframe_name: Name to assign to the DataFrame in memory (required)
        path: Path to the Parquet file (required)
        columns: Column names to read (optional)

    Returns:
        Success message with DataFrame name and shape, or error message
    """
    try:
        if dataframe_name in _dataframes:
            return f"DataFrame '{dataframe_name}' already exists. Use a different name or delete it first."

        df = pd.read_parquet(path=path, columns=columns)

        _dataframes[dataframe_name] = df
        return f"Loaded '{dataframe_name}': {df.shape[0]} rows x {df.shape[1]} cols\n\n{_compact_table(df, max_rows=5)}"

    except FileNotFoundError:
        return f"Error: File not found at path: {path}"
    except Exception as e:
        return f"Error loading Parquet: {str(e)}"


# =========================================================================
# DATA EXPLORATION TOOLS
# =========================================================================

@tool
def pandas_head(dataframe_name: str, n: int = 5) -> str:
    """
    Display the first N rows of a DataFrame.

    Args:
        dataframe_name: Name of the DataFrame to inspect
        n: Number of rows to display (default: 5)

    Returns:
        First N rows as a string, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        return f"First {n} rows of '{dataframe_name}':\n{_compact_table(df.head(n), max_rows=n)}"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def pandas_tail(dataframe_name: str, n: int = 5) -> str:
    """
    Display the last N rows of a DataFrame.

    Args:
        dataframe_name: Name of the DataFrame to inspect
        n: Number of rows to display (default: 5)

    Returns:
        Last N rows as a string, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        return f"Last {n} rows of '{dataframe_name}':\n{_compact_table(df.tail(n), max_rows=n)}"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def pandas_describe(dataframe_name: str) -> str:
    """
    Get statistical summary of numeric columns.

    Args:
        dataframe_name: Name of the DataFrame to describe

    Returns:
        Statistical summary as a string, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        return f"Statistical summary of '{dataframe_name}':\n{_compact_table(df.describe().reset_index().rename(columns={'index': 'stat'}), max_rows=10, max_col_width=18)}"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def pandas_info(dataframe_name: str) -> str:
    """
    Get detailed information about a DataFrame's structure.

    Args:
        dataframe_name: Name of the DataFrame to inspect

    Returns:
        DataFrame info as a string, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        rows, cols = df.shape
        lines = [f"'{dataframe_name}': {rows} rows x {cols} cols"]
        lines.append(f"{'Column':<25s} {'Non-Null':>10s}  {'Dtype':<10s}")
        lines.append("-" * 50)
        for col in df.columns:
            non_null = df[col].notna().sum()
            short_name = _short_col(col, 24)
            lines.append(f"{short_name:<25s} {non_null:>7d}/{rows}  {str(df[col].dtype):<10s}")
        mem = df.memory_usage(deep=True).sum()
        if mem > 1_000_000:
            lines.append(f"Memory: {mem / 1_000_000:.1f} MB")
        else:
            lines.append(f"Memory: {mem / 1_000:.1f} KB")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def pandas_shape(dataframe_name: str) -> str:
    """
    Get the dimensions of a DataFrame.

    Args:
        dataframe_name: Name of the DataFrame

    Returns:
        Shape as a string, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        rows, cols = df.shape
        return f"DataFrame '{dataframe_name}' shape: {rows} rows x {cols} columns"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def pandas_columns(dataframe_name: str) -> str:
    """
    Get the column names of a DataFrame.

    Args:
        dataframe_name: Name of the DataFrame

    Returns:
        Column names as a string, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        cols = df.columns.tolist()
        return f"Columns in '{dataframe_name}' ({len(cols)} total):\n{cols}"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def pandas_dtypes(dataframe_name: str) -> str:
    """
    Get the data types of all columns.

    Args:
        dataframe_name: Name of the DataFrame

    Returns:
        Data types as a string, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        lines = [f"Data types in '{dataframe_name}':"]
        for col in df.columns:
            short = _short_col(col, 30)
            lines.append(f"  {short:<32s} {str(df[col].dtype)}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def pandas_null_counts(dataframe_name: str) -> str:
    """
    Count null values in each column.

    Args:
        dataframe_name: Name of the DataFrame

    Returns:
        Null counts as a string, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        nulls = df.isnull().sum()
        total = len(df)
        null_pct = (nulls / total * 100).round(1)

        lines = [f"Null analysis for '{dataframe_name}' ({total} rows):"]
        lines.append(f"{'Column':<25s} {'Nulls':>6s} {'%':>6s}")
        lines.append("-" * 40)
        for col in df.columns:
            short = _short_col(col, 24)
            n = nulls[col]
            pct = null_pct[col]
            lines.append(f"{short:<25s} {n:>6d} {pct:>5.1f}%")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {str(e)}"


# =========================================================================
# DATA MANIPULATION TOOLS
# =========================================================================

@tool
def pandas_filter(dataframe_name: str, condition: str, result_name: Optional[str] = None) -> str:
    """
    Filter rows based on a condition.

    Args:
        dataframe_name: Name of the source DataFrame
        condition: Filter condition (e.g., "price > 100", "category == 'A'")
        result_name: Name for the filtered DataFrame (optional, overwrites original if not provided)

    Returns:
        Filtered DataFrame info, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        filtered_df = df.query(condition)

        target_name = result_name or dataframe_name
        _dataframes[target_name] = filtered_df

        return f"Filtered '{dataframe_name}' -> '{target_name}' ({condition}): {filtered_df.shape[0]} rows x {filtered_df.shape[1]} cols\n\n{_compact_table(filtered_df, max_rows=5)}"
    except Exception as e:
        return f"Error filtering: {str(e)}"


@tool
def pandas_select(dataframe_name: str, columns: List[str], result_name: Optional[str] = None) -> str:
    """
    Select specific columns from a DataFrame.

    Args:
        dataframe_name: Name of the source DataFrame
        columns: List of column names to keep
        result_name: Name for the new DataFrame (optional)

    Returns:
        Selected DataFrame info, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        missing = [c for c in columns if c not in df.columns]
        if missing:
            return f"Error: Columns not found: {missing}. Available: {df.columns.tolist()}"

        selected_df = df[columns]

        target_name = result_name or dataframe_name
        _dataframes[target_name] = selected_df

        return f"Selected {columns} from '{dataframe_name}' -> '{target_name}': {selected_df.shape[0]} rows x {selected_df.shape[1]} cols\n\n{_compact_table(selected_df, max_rows=5)}"
    except Exception as e:
        return f"Error selecting columns: {str(e)}"


@tool
def pandas_sort(dataframe_name: str, by: str, ascending: bool = True, result_name: Optional[str] = None) -> str:
    """
    Sort DataFrame by a column.

    Args:
        dataframe_name: Name of the source DataFrame
        by: Column name to sort by
        ascending: Sort order (default: True)
        result_name: Name for the sorted DataFrame (optional)

    Returns:
        Sorted DataFrame info, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        sorted_df = df.sort_values(by=by, ascending=ascending)

        target_name = result_name or dataframe_name
        _dataframes[target_name] = sorted_df

        order = "asc" if ascending else "desc"
        return f"Sorted '{dataframe_name}' by {by} ({order}) -> '{target_name}'\n\n{_compact_table(sorted_df, max_rows=5)}"
    except Exception as e:
        return f"Error sorting: {str(e)}"


@tool
def pandas_groupby(dataframe_name: str, by: str, agg: str, result_name: Optional[str] = None) -> str:
    """
    Group data and aggregate values.

    Args:
        dataframe_name: Name of the source DataFrame
        by: Column name to group by
        agg: Aggregation function ('sum', 'mean', 'count', 'min', 'max', 'std')
        result_name: Name for the grouped DataFrame (optional)

    Returns:
        Grouped DataFrame info, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        grouped_df = df.groupby(by).agg(agg).reset_index()

        target_name = result_name or f"{dataframe_name}_grouped"
        _dataframes[target_name] = grouped_df

        return f"Grouped '{dataframe_name}' by {by} ({agg}) -> '{target_name}': {grouped_df.shape[0]} groups\n\n{_compact_table(grouped_df, max_rows=10)}"
    except Exception as e:
        return f"Error in groupby: {str(e)}"


@tool
def pandas_join(dataframe_name: str, other: str, on: str, how: str = "left", result_name: Optional[str] = None) -> str:
    """
    Join two DataFrames together.

    Args:
        dataframe_name: Name of the left DataFrame
        other: Name of the right DataFrame
        on: Column name to join on
        how: Join type ('inner', 'left', 'right', 'outer', 'cross')
        result_name: Name for the joined DataFrame (optional)

    Returns:
        Joined DataFrame info, or error message
    """
    try:
        df1 = _dataframes.get(dataframe_name)
        df2 = _dataframes.get(other)

        if df1 is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"
        if df2 is None:
            return f"Error: DataFrame '{other}' not found. Available: {list(_dataframes.keys())}"

        joined_df = df1.merge(df2, on=on, how=how)

        target_name = result_name or f"{dataframe_name}_joined"
        _dataframes[target_name] = joined_df

        return f"Joined '{dataframe_name}' + '{other}' ({how} on {on}) -> '{target_name}': {joined_df.shape[0]} rows x {joined_df.shape[1]} cols\n\n{_compact_table(joined_df, max_rows=5)}"
    except Exception as e:
        return f"Error joining: {str(e)}"


@tool
def pandas_add_column(dataframe_name: str, column: str, expression: str, result_name: Optional[str] = None) -> str:
    """
    Add a new calculated column to a DataFrame.

    Args:
        dataframe_name: Name of the source DataFrame
        column: Name for the new column
        expression: Python expression using column names (evaluated with df.eval)
        result_name: Name for the result DataFrame (optional)

    Returns:
        Updated DataFrame info, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        result_df = df.copy()
        result_df[column] = result_df.eval(expression)

        target_name = result_name or dataframe_name
        _dataframes[target_name] = result_df

        return f"Added '{column}' = {expression} -> '{target_name}': {result_df.shape[0]} rows x {result_df.shape[1]} cols\n\n{_compact_table(result_df, max_rows=5)}"
    except Exception as e:
        return f"Error adding column: {str(e)}"


@tool
def pandas_drop_columns(dataframe_name: str, columns: List[str], result_name: Optional[str] = None) -> str:
    """
    Drop columns from a DataFrame.

    Args:
        dataframe_name: Name of the source DataFrame
        columns: List of column names to drop
        result_name: Name for the result DataFrame (optional)

    Returns:
        Updated DataFrame info, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        missing = [c for c in columns if c not in df.columns]
        if missing:
            return f"Error: Columns not found: {missing}. Available: {df.columns.tolist()}"

        result_df = df.drop(columns=columns)

        target_name = result_name or dataframe_name
        _dataframes[target_name] = result_df

        return f"Dropped {columns} from '{dataframe_name}' -> '{target_name}': {result_df.shape[0]} rows x {result_df.shape[1]} cols\n\n{_compact_table(result_df, max_rows=5)}"
    except Exception as e:
        return f"Error dropping columns: {str(e)}"


@tool
def pandas_drop_na(dataframe_name: str, how: str = "any", result_name: Optional[str] = None) -> str:
    """
    Drop rows with null values.

    Args:
        dataframe_name: Name of the source DataFrame
        how: 'any' to drop if any null, 'all' to drop if all null
        result_name: Name for the result DataFrame (optional)

    Returns:
        Updated DataFrame info, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        original_rows = len(df)
        result_df = df.dropna(how=how)
        dropped = original_rows - len(result_df)

        target_name = result_name or dataframe_name
        _dataframes[target_name] = result_df

        return f"Dropped {dropped} null rows from '{dataframe_name}' -> '{target_name}': {result_df.shape[0]} rows remaining\n\n{_compact_table(result_df, max_rows=5)}"
    except Exception as e:
        return f"Error dropping NA: {str(e)}"


@tool
def pandas_fill_na(dataframe_name: str, value: str, result_name: Optional[str] = None) -> str:
    """
    Fill null values with a specified value.

    Args:
        dataframe_name: Name of the source DataFrame
        value: Value to fill with. Use 'mean', 'median', 'ffill', 'bfill', or a constant.
        result_name: Name for the result DataFrame (optional)

    Returns:
        Updated DataFrame info, or error message
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        result_df = df.copy()

        if value == 'mean':
            result_df = result_df.fillna(result_df.mean(numeric_only=True))
        elif value == 'median':
            result_df = result_df.fillna(result_df.median(numeric_only=True))
        elif value == 'ffill':
            result_df = result_df.ffill()
        elif value == 'bfill':
            result_df = result_df.bfill()
        else:
            result_df = result_df.fillna(value)

        target_name = result_name or dataframe_name
        _dataframes[target_name] = result_df

        return f"Filled nulls with '{value}' in '{dataframe_name}' -> '{target_name}': {result_df.shape[0]} rows x {result_df.shape[1]} cols\n\n{_compact_table(result_df, max_rows=5)}"
    except Exception as e:
        return f"Error filling NA: {str(e)}"


# =========================================================================
# DATA EXPORT TOOLS
# =========================================================================

@tool
def pandas_to_csv(dataframe_name: str, path: str, index: bool = False) -> str:
    """
    Export a DataFrame to a CSV file.

    Args:
        dataframe_name: Name of the DataFrame to export
        path: Output file path
        index: Whether to include row index (default: False)

    Returns:
        Success message or error
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        df.to_csv(path, index=index)
        return f"Exported '{dataframe_name}' to CSV: {path}\nRows: {df.shape[0]}, Columns: {df.shape[1]}"
    except Exception as e:
        return f"Error exporting to CSV: {str(e)}"


@tool
def pandas_to_excel(dataframe_name: str, path: str, sheet_name: str = "Sheet1", index: bool = False) -> str:
    """
    Export a DataFrame to an Excel file.

    Args:
        dataframe_name: Name of the DataFrame to export
        path: Output file path
        sheet_name: Sheet name (default: 'Sheet1')
        index: Whether to include row index (default: False)

    Returns:
        Success message or error
    """
    try:
        df = _dataframes.get(dataframe_name)
        if df is None:
            return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

        df.to_excel(path, sheet_name=sheet_name, index=index)
        return f"Exported '{dataframe_name}' to Excel: {path}\nSheet: {sheet_name}, Rows: {df.shape[0]}, Columns: {df.shape[1]}"
    except Exception as e:
        return f"Error exporting to Excel: {str(e)}"


# =========================================================================
# DATA MANAGEMENT TOOLS
# =========================================================================

@tool
def pandas_list_dataframes() -> str:
    """
    List all DataFrames currently in memory.

    Returns:
        List of DataFrames with their shapes
    """
    if not _dataframes:
        return "No DataFrames in memory. Load data using pandas_read_csv, pandas_read_excel, pandas_read_json, or pandas_read_parquet."

    result = "DataFrames in memory:\n"
    for name, df in _dataframes.items():
        result += f"  - {name}: {df.shape[0]} rows x {df.shape[1]} columns\n"
    return result


@tool
def pandas_delete_dataframe(dataframe_name: str) -> str:
    """
    Delete a DataFrame from memory.

    Args:
        dataframe_name: Name of the DataFrame to delete

    Returns:
        Success message or error
    """
    if dataframe_name not in _dataframes:
        return f"Error: DataFrame '{dataframe_name}' not found. Available: {list(_dataframes.keys())}"

    del _dataframes[dataframe_name]
    return f"Deleted DataFrame '{dataframe_name}' from memory."


# =========================================================================
# ALL TOOLS LIST
# =========================================================================

ALL_PANDAS_TOOLS = [
    pandas_read_csv,
    pandas_read_excel,
    pandas_read_json,
    pandas_read_parquet,
    pandas_head,
    pandas_tail,
    pandas_describe,
    pandas_info,
    pandas_shape,
    pandas_columns,
    pandas_dtypes,
    pandas_null_counts,
    pandas_filter,
    pandas_select,
    pandas_sort,
    pandas_groupby,
    pandas_join,
    pandas_add_column,
    pandas_drop_columns,
    pandas_drop_na,
    pandas_fill_na,
    pandas_to_csv,
    pandas_to_excel,
    pandas_list_dataframes,
    pandas_delete_dataframe,
]

__all__ = [t.name for t in ALL_PANDAS_TOOLS] + ["ALL_PANDAS_TOOLS"]
