from langchain_core.tools import tool
import subprocess
import shutil


def _axon_available() -> bool:
    """Check if the axon binary is on PATH."""
    return shutil.which("axon") is not None


_AXON_MISSING_MSG = (
    "Axon is not installed. Install it with:  pip install axoniq\n"
    "Then run 'axon analyze .' in your project root to build the code graph.\n"
    "Falling back to terminal tools (rg, grep, find) for this query."
)


def _run_axon(args: str, timeout: int = 120) -> str:
    if not _axon_available():
        return _AXON_MISSING_MSG
    result = subprocess.run(
        f"axon {args}", shell=True, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode == 0:
        return result.stdout.strip() or "Done."
    return f"Error: {result.stderr.strip()}"


def reindex_axon():
    """Trigger incremental reindex (called after file changes)."""
    if not _axon_available():
        return
    subprocess.Popen(
        "axon analyze .",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@tool
def search_codebase_graph(query: str, limit: int = 10) -> str:
    """Search the codebase knowledge graph using hybrid search (BM25 + vector + fuzzy).
    Returns functions, classes, and symbols matching the query, grouped by execution flow.
    Use this to find code by description or functionality."""
    return _run_axon(f'query "{query}" --limit {limit}')


@tool
def axon_context(symbol: str) -> str:
    """Get 360-degree view of a symbol: who calls it, what it calls, type references,
    which community/cluster it belongs to, and whether it's dead code.
    Use after search_codebase_graph to deep-dive a specific function or class.
    IMPORTANT: Pass the exact symbol name (e.g. 'get_agent_instructions', 'UserService'), NOT natural language."""
    return _run_axon(f'context {symbol}')


@tool
def axon_impact(symbol: str) -> str:
    """Analyze blast radius of changing a symbol. Shows what will break grouped by depth:
    Depth 1 = will break, Depth 2 = may break, Depth 3+ = review.
    Use before editing a function to understand downstream effects.
    IMPORTANT: Pass the exact symbol name (e.g. 'get_agent_instructions', 'UserService'), NOT natural language."""
    return _run_axon(f'impact {symbol}')
