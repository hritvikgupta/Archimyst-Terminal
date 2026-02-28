import os
from history import HistoryManager
from diff_manager import get_diff_manager
from task_context import get_current_task_id, get_current_diff_manager, get_current_history_manager
from file_lock_registry import get_file_lock_registry
from tools.edit_engine.editblock_engine import find_original_update_blocks, do_replace
from tools.edit_engine.wholefile_engine import apply_whole_file_edits

from tools.approval_gate import approval_gate
from tools.axon_tools import reindex_axon

# Global history manager initialized with current directory
_history_manager = None

def get_history_manager():
    global _history_manager
    if _history_manager is None:
        _history_manager = HistoryManager(os.getcwd())
    return _history_manager

def trigger_checkpoint(msg, files):
    try:
        get_current_history_manager().create_checkpoint(msg, files)
    except Exception as e:
        import sys
        print(f"Checkpoint error: {e}", file=sys.stderr)


def _acquire_lock_or_fail(file_path):
    """Acquire a file lock for the current task. Returns error string or None."""
    abs_path = os.path.abspath(os.path.normpath(file_path))
    task_id = get_current_task_id()
    acquired, holder = get_file_lock_registry().acquire(abs_path, task_id)
    if not acquired:
        return f"Error: File '{file_path}' is locked by task '{holder}'. Cannot write."
    return None


MAX_FILE_CHARS = 0  # 0 = no cap

def read_file(file_path: str, line_numbers: bool = False) -> str:
    """Read the content of a file. Use this for smaller files (< 500 lines).
    For larger files, use read_file_chunked instead.

    Args:
        file_path (str): The path to the file to read.
        line_numbers (bool): If True, prefixes each line with its 1-indexed line number.

    Returns:
        str: File content as a string, or an error message if the file is missing or unreadable.
    """
    try:
        if not os.path.exists(file_path):
            return f"Error: File {file_path} not found."

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        if line_numbers:
            lines = content.splitlines()
            numbered_lines = [f"{i+1:3}: {line}" for i, line in enumerate(lines)]
            content = "\n".join(numbered_lines)

        if MAX_FILE_CHARS > 0 and len(content) > MAX_FILE_CHARS:
            half = MAX_FILE_CHARS // 2
            omitted = len(content) - MAX_FILE_CHARS
            content = (
                content[:half]
                + f"\n\n... [{omitted} chars omitted — file too large. Showing first {half} and last {half} chars] ...\n\n"
                + content[-half:]
            )

        return content
    except Exception as e:
        return f"Error reading file {file_path}: {e}"

def list_dir(directory: str = ".", recursive: bool = False, limit: int = 1000) -> str:
    """List files and directories in a given path. Filters out internal/large folders like .git and node_modules.

    Args:
        directory (str): The directory path to list. Defaults to ".".
        recursive (bool): If True, lists all files in subdirectories as well.
        limit (int): Maximum number of files to return to prevent token overflow. Defaults to 1000.

    Returns:
        str: A newline-separated string of file/directory paths.
    """
    ignore_dirs = {'.git', 'node_modules', 'venv', '__pycache__', '.next', 'dist', 'build', '.archcode'}

    try:
        if not recursive:
            items = os.listdir(directory)
            return "\n".join(items)

        all_files = []
        for root, dirs, files in os.walk(directory):
            # Modify dirs in-place to skip ignored directories
            dirs[:] = [d for d in dirs if d not in ignore_dirs]

            for name in files:
                rel_path = os.path.relpath(os.path.join(root, name), directory)
                all_files.append(rel_path)

                if len(all_files) >= limit:
                    all_files.append(f"... (limit of {limit} files reached)")
                    return "\n".join(all_files)

        return "\n".join(all_files)
    except Exception as e:
        return f"Error listing directory {directory}: {e}"

def write_to_file_tool(file_path: str, content: str) -> str:
    """Create a new file or overwrite an existing file with the provided content.

    Args:
        file_path (str): The path where the file should be created/updated.
        content (str): The full content to write to the file.

    Returns:
        str: Success message or failure Reason if the file is locked or unavailable.
    """
    try:
        # File lock check
        lock_err = _acquire_lock_or_fail(file_path)
        if lock_err:
            return lock_err

        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)

        # Read old content for diff (empty string if new file)
        old_content = ""
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    old_content = f.read()
            except Exception:
                old_content = ""

        # Per-file approval gate
        if approval_gate.is_rejected():
            return f"EDIT_REJECTED: User rejected changes to {file_path}."
        approved = approval_gate.request_approval(file_path, old_content, content)
        if not approved:
            return f"EDIT_REJECTED: User rejected changes to {file_path}."

        # Snapshot baseline BEFORE writing (only saved once per file per prompt)
        get_current_diff_manager().snapshot_baseline(file_path)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        try:
            reindex_axon()
        except Exception:
            pass
        return f"Successfully wrote to {file_path}"
    except Exception as e:
        return f"Error writing file {file_path}: {e}"

def delete_file(file_path: str) -> str:
    """Delete a file."""
    try:
        # File lock check
        lock_err = _acquire_lock_or_fail(file_path)
        if lock_err:
            return lock_err

        # Per-file approval gate
        if approval_gate.is_rejected():
            return f"DELETE_REJECTED: User rejected deletion of {file_path}."
        approved = approval_gate.request_delete_approval(file_path)
        if not approved:
            return f"DELETE_REJECTED: User rejected deletion of {file_path}."

        if os.path.exists(file_path):
            os.remove(file_path)
            try:
                reindex_axon()
            except Exception:
                pass
            return f"Successfully deleted {file_path}"
        return f"Error: File {file_path} not found"
    except Exception as e:
        return f"Error deleting file {file_path}: {e}"

def edit_file(file_path: str, edits: str, message: str = "AI Edit") -> str:
    """Apply surgical SEARCH/REPLACE edits to an existing file. Use this for targeted modifications.
    
    Format for edits:
    <<<<<<< SEARCH
    old code
    =======
    new code
    >>>>>>> REPLACE

    Args:
        file_path (str): The path to the file to modify.
        edits (str): One or more SEARCH/REPLACE blocks.
        message (str): A brief description of the change for history tracking. Defaults to "AI Edit".

    Returns:
        str: A report on how many edits were successfully applied.
    """
    try:
        # File lock check
        lock_err = _acquire_lock_or_fail(file_path)
        if lock_err:
            return lock_err

        if not os.path.exists(file_path):
            return f"Error: File {file_path} does not exist."

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Replicate Aider's block processing
        blocks = list(find_original_update_blocks(edits))

        if not blocks:
            return "Error: No valid Search/Replace blocks found in the input. Ensure you use the correct format with <<<<<<< SEARCH, =======, and >>>>>>> REPLACE."

        new_content = content
        applied_count = 0
        failed_blocks = []

        for block_fname, search, replace in blocks:
            result = do_replace(file_path, new_content, search, replace)
            if result is not None:
                new_content = result
                applied_count += 1
            else:
                # Provide a snippet of what failed to match for debugging
                snippet = search.strip()[:80].replace('\n', '\\n')
                failed_blocks.append(snippet)

        if applied_count > 0:
            # Per-file approval gate (show diff of original vs new_content)
            if approval_gate.is_rejected():
                return f"EDIT_REJECTED: User rejected changes to {file_path}."
            approved = approval_gate.request_approval(file_path, content, new_content)
            if not approved:
                return f"EDIT_REJECTED: User rejected changes to {file_path}."

            # Trigger checkpoint BEFORE writing changes
            trigger_checkpoint(message, [file_path])

            # Snapshot baseline BEFORE writing (only saved once per file per prompt)
            get_current_diff_manager().snapshot_baseline(file_path)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            # Verify the write actually persisted
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    verify = f.read()
                if verify != new_content:
                    return f"Error: Write to {file_path} did not persist. The file may be read-only or another process reverted it."
            except Exception as ve:
                return f"Warning: Could not verify write to {file_path}: {ve}"

            try:
                reindex_axon()
            except Exception:
                pass
            status = f"Successfully applied {applied_count} edits to {file_path}."
            if failed_blocks:
                status += f"\nWarning: {len(failed_blocks)} block(s) failed to match:"
                for fb in failed_blocks:
                    status += f"\n  - \"{fb}...\""
            return status
        else:
            detail = ""
            if failed_blocks:
                detail = "\nFailed SEARCH snippets:"
                for fb in failed_blocks:
                    detail += f"\n  - \"{fb}...\""
            return f"Error: Failed to apply any edits to {file_path}. The SEARCH blocks did not match the file content.{detail}\nTip: Read the file first to see the exact current content, then retry with matching text."

    except Exception as e:
        return f"Error in Aider edit engine: {e}"

def whole_file_update(edits: str, message: str = "Whole file update") -> str:
    """
    Apply Aider-style whole file updates from a chat response.
    Expects format:
    filename.ext
    ```
    file content...
    ```
    """
    try:
        updates = apply_whole_file_edits(edits)
        if not updates:
            return "Error: No whole file updates found in the correct format."

        results = []
        affected_files = [path for path, _ in updates]

        if affected_files:
            # Trigger checkpoint BEFORE writing changes
            trigger_checkpoint(message, affected_files)

        for path, content in updates:
            # write_to_file_tool already calls snapshot_baseline and lock check
            res = write_to_file_tool(path, content)
            results.append(res)

        return "\n".join(results)
    except Exception as e:
        return f"Error applying whole file updates: {e}"


# --- Smart Symbol-Aware Tools ---




def view_context(file_path: str, line_number: int, radius: int = 10) -> str:
    """Read a small window of lines around a specific line number.
    Ideal for understanding the surroundings of a search result.

    Args:
        file_path (str): The path to the file.
        line_number (int): The target line number (1-indexed).
        radius (int): How many lines to show before and after. Defaults to 10.

    Returns:
        str: Numbered lines centered around the target line.
    """
    try:
        if not os.path.isfile(file_path):
            return f"Error: File '{file_path}' not found."

        with open(file_path, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()

        total = len(all_lines)
        start = max(0, line_number - radius - 1)   # 0-indexed
        end = min(total, line_number + radius)       # exclusive

        numbered = []
        for i in range(start, end):
            lineno = i + 1
            marker = ">>>" if lineno == line_number else "   "
            numbered.append(f"{marker} {lineno:4}: {all_lines[i].rstrip()}")

        return (
            f"# Context: {file_path} around line {line_number} "
            f"(showing {start+1}-{end} of {total})\n\n"
            + "\n".join(numbered)
        )

    except Exception as e:
        return f"Error in view_context: {e}"


def read_file_chunked(file_path: str, chunk_number: int = 0, chunk_size: int = 200) -> str:
    """Read a large file in paginated chunks to avoid token overflow.

    Args:
        file_path (str): The path to the file to read.
        chunk_number (int): The page number to read (0-indexed). Defaults to 0.
        chunk_size (int): Number of lines per page. Defaults to 200.

    Returns:
        str: A numbered chunk of the file with navigation tips for the next page.
    """
    try:
        if not os.path.isfile(file_path):
            return f"Error: File '{file_path}' not found."

        with open(file_path, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()

        total_lines = len(all_lines)
        total_chunks = max(1, (total_lines + chunk_size - 1) // chunk_size)

        if chunk_number < 0 or chunk_number >= total_chunks:
            return (
                f"Error: chunk_number {chunk_number} out of range. "
                f"File has {total_chunks} chunks (0 to {total_chunks - 1})."
            )

        start = chunk_number * chunk_size
        end = min(total_lines, start + chunk_size)

        numbered = [
            f"{start + i + 1:4}: {all_lines[start + i].rstrip()}"
            for i in range(end - start)
        ]

        has_more = chunk_number < total_chunks - 1
        nav = (
            f"Chunk {chunk_number + 1}/{total_chunks} "
            f"(lines {start + 1}-{end} of {total_lines})"
        )
        if has_more:
            nav += f" | Next: read_file_chunked('{file_path}', chunk_number={chunk_number + 1})"

        return f"# {file_path} — {nav}\n\n" + "\n".join(numbered)

    except Exception as e:
        return f"Error in read_file_chunked: {e}"


class FilesystemToolService:
    """Class-based facade around filesystem tool functions."""

    def get_history_manager(self):
        return get_history_manager()

    def trigger_checkpoint(self, msg, files):
        return trigger_checkpoint(msg, files)

    def read_file(self, file_path: str, line_numbers: bool = False) -> str:
        return read_file(file_path, line_numbers)

    def list_dir(self, directory: str = ".", recursive: bool = False, limit: int = 1000) -> str:
        return list_dir(directory, recursive, limit)

    def write_to_file_tool(self, file_path: str, content: str) -> str:
        return write_to_file_tool(file_path, content)

    def delete_file(self, file_path: str) -> str:
        return delete_file(file_path)

    def edit_file(self, file_path: str, edits: str, message: str = "AI Edit") -> str:
        return edit_file(file_path, edits, message)

    def whole_file_update(self, edits: str, message: str = "Whole file update") -> str:
        return whole_file_update(edits, message)



    def view_context(self, file_path: str, line_number: int, radius: int = 10) -> str:
        return view_context(file_path, line_number, radius)

    def read_file_chunked(self, file_path: str, chunk_number: int = 0, chunk_size: int = 200) -> str:
        return read_file_chunked(file_path, chunk_number, chunk_size)


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
