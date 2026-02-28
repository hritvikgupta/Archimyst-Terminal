"""GitHub tool wrappers with LangChain @tool decorators."""

from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from tools.services import github_service as _impl
from tools.services.github_service import GithubToolService

_service = GithubToolService()


def _gh_command(args: List[str], timeout: int = 30) -> Dict[str, Any]:
    return _impl._gh_command(args, timeout)


def _get_repo_nwo() -> Optional[str]:
    return _impl._get_repo_nwo()


def _require_permission(
    action: str,
    details: str,
    params: Dict[str, Any],
    command: List[str],
    write: bool = False,
) -> str:
    return _impl._require_permission(action, details, params, command, write)


@tool
def github_repo_info() -> str:
    """Get metadata about the current GitHub repository including name, description, stars, forks, and open issues."""
    return _service.github_repo_info()


@tool
def github_list_issues(state: str = "open", limit: int = 20, labels: str = "") -> str:
    """List GitHub issues for the current repository filtered by state and optional labels."""
    return _service.github_list_issues(state, limit, labels)


@tool
def github_view_issue(issue_number: int) -> str:
    """View the full details, comments, and metadata of a specific GitHub issue by number."""
    return _service.github_view_issue(issue_number)


@tool
def github_list_prs(state: str = "open", limit: int = 20) -> str:
    """List pull requests for the current repository filtered by state (open, closed, merged)."""
    return _service.github_list_prs(state, limit)


@tool
def github_view_pr(pr_number: int) -> str:
    """View the full details, diff, and comments of a specific pull request by number."""
    return _service.github_view_pr(pr_number)


@tool
def github_list_branches(limit: int = 30) -> str:
    """List all branches in the current GitHub repository."""
    return _service.github_list_branches(limit)


@tool
def github_list_commits(branch: str = "", limit: int = 20) -> str:
    """List recent commits for a branch. Defaults to the current branch if branch is empty."""
    return _service.github_list_commits(branch, limit)


@tool
def github_list_tags(limit: int = 20) -> str:
    """List tags in the current GitHub repository."""
    return _service.github_list_tags(limit)


@tool
def github_create_issue(title: str, body: str = "", labels: str = "") -> str:
    """Create a new GitHub issue with a title, optional body, and optional comma-separated labels."""
    return _service.github_create_issue(title, body, labels)


@tool
def github_create_pr(
    title: str,
    body: str = "",
    base: str = "",
    head: str = "",
    draft: bool = False,
) -> str:
    """Create a new pull request. base is the target branch, head is the source branch."""
    return _service.github_create_pr(title, body, base, head, draft)


@tool
def github_merge_pr(pr_number: int, merge_method: str = "merge") -> str:
    """Merge a pull request by number. merge_method can be merge, squash, or rebase."""
    return _service.github_merge_pr(pr_number, merge_method)


@tool
def github_close_issue(issue_number: int, comment: str = "") -> str:
    """Close a GitHub issue by number with an optional closing comment."""
    return _service.github_close_issue(issue_number, comment)


@tool
def github_create_comment(item_type: str, item_number: int, body: str) -> str:
    """Add a comment to a GitHub issue or pull request. item_type is issue or pr."""
    return _service.github_create_comment(item_type, item_number, body)


@tool
def github_create_branch(branch_name: str, from_branch: str = "") -> str:
    """Create a new branch. Branches from from_branch if provided, otherwise from the default branch."""
    return _service.github_create_branch(branch_name, from_branch)


@tool
def github_push_commits(branch: str = "", force: bool = False) -> str:
    """Push local commits to a remote GitHub branch."""
    return _service.github_push_commits(branch, force)


@tool
def execute_github_command(pending_data: Dict[str, Any]) -> str:
    """Execute a raw pending GitHub command payload. Used for complex or multi-step GitHub operations."""
    return _service.execute_github_command(pending_data)


__all__ = [
    "_gh_command",
    "_get_repo_nwo",
    "_require_permission",
    "github_repo_info",
    "github_list_issues",
    "github_view_issue",
    "github_list_prs",
    "github_view_pr",
    "github_list_branches",
    "github_list_commits",
    "github_list_tags",
    "github_create_issue",
    "github_create_pr",
    "github_merge_pr",
    "github_close_issue",
    "github_create_comment",
    "github_create_branch",
    "github_push_commits",
    "execute_github_command",
    "GithubToolService",
]
