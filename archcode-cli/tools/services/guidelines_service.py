"""Guidelines tool service implementation."""

from pathlib import Path


class GuidelinesService:
    """Service providing static and dynamic guideline references."""

    TERMINAL_COMMANDS = """
━━━ TERMINAL COMMAND REFERENCE (USE THESE — NEVER ASK THE USER) ━━━
You are an AUTONOMOUS agent with FULL terminal access via run_terminal_command. Use it for ANYTHING — searching, finding, installing, running, diagnosing, fixing. NEVER ask the user for something you can find or do with a command.

⚠️ CRITICAL: Each run_terminal_command runs in a NEW shell. Nothing persists between calls.
   Environment variables, cd, exports — ALL reset between commands.
   To use something from one step in another, you MUST CHAIN them in a SINGLE command with &&.
   Example: `export $(grep -v '^#' backend/.env | xargs) && python3 my_script.py`
   WRONG:  Command 1: `export FOO=bar`  →  Command 2: `echo $FOO`  (FOO is gone!)
   RIGHT:  Single command: `export FOO=bar && echo $FOO`

**SEARCH FOR ENV VARS:**
- Find all .env files:            `find . -maxdepth 4 -name ".env" -not -path "*/node_modules/*"`
- Search for a specific var:      `grep -rn "VAR_NAME" --include=".env" . 2>/dev/null`
- Search across all config files: `grep -rn "VAR_NAME" . --include="*.env" --include="*.yaml" --include="*.yml" --include="*.toml" --include="*.json" --include="*.cfg" --include="*.ini" 2>/dev/null`
- Read a .env file:               `cat <path>/.env`
- Load .env AND run a command:    `export $(grep -v '^#' <path>/.env | xargs) && <your_command>`
- Copy a var to another .env:     `grep "VAR_NAME" <source>/.env >> <dest>/.env`

**SEARCH FOR FILES & FOLDERS:**
- Find file by name:              `find . -name "filename.ext" -not -path "*/node_modules/*" -not -path "*/.git/*"`
- Find file by pattern:           `find . -name "*.py" -not -path "*/node_modules/*" -not -path "*/.git/*"`
- Find folder by name:            `find . -type d -name "foldername" -not -path "*/node_modules/*"`
- List directory contents:        `ls -la <path>`
- Check if file/dir exists:       `test -f <path> && echo "exists" || echo "not found"`
- Find files containing text:     `grep -rn "search_text" . --include="*.py" --include="*.js" --include="*.ts" 2>/dev/null`

**SEARCH FOR PACKAGES & DEPENDENCIES:**
- Python packages installed:      `pip list 2>/dev/null | grep -i "package_name"`
- Python package location:        `pip show package_name 2>/dev/null`
- Node packages installed:        `npm list 2>/dev/null | grep "package_name"`
- Check requirements.txt:         `cat requirements.txt 2>/dev/null | grep "package_name"`
- Install Python package:         `pip install --quiet package_name`
- Install Node package:           `npm install package_name`

**SYSTEM & PROCESS INFO:**
- Check running processes:        `ps aux | grep "process_name"`
- Check port in use:              `lsof -i :<port> 2>/dev/null`
- Check Python/Node version:      `python3 --version` / `node --version`
- Check current directory:        `pwd`

**GIT & VERSION CONTROL:**
- Current branch:                 `git branch --show-current`
- Recent commits:                 `git log --oneline -10`
- Changed files:                  `git status --short`
- Diff of changes:                `git diff`

**NETWORK & API:**
- Check URL reachable:            `curl -s -o /dev/null -w "%{http_code}" <url>`
- Fetch API response:             `curl -s <url> | head -c 2000`

**DATABASE:**
- Check PostgreSQL:               `psql -c "SELECT 1" 2>/dev/null && echo "connected" || echo "not connected"`
- Check SQLite file:              `sqlite3 <file.db> ".tables" 2>/dev/null`

GOLDEN RULE: If ANYTHING is missing or fails:
  1. SEARCH for what you need using the commands above.
  2. If found, CHAIN it with your original command in a SINGLE run_terminal_command using &&.
  3. RETRY. Only ask the user after exhausting your terminal capabilities.
  NEVER say "not configured" or "please provide" — FIND IT AND USE IT.
"""

    GITHUB_COMMANDS = """
━━━ GITHUB COMMAND REFERENCE ━━━
Use dedicated GitHub tools (not run_terminal_command) for ALL GitHub operations.

**READ OPERATIONS:**
- github_repo_info(): Get repository metadata
- github_list_issues(state="open", limit=20, labels=""): List issues
- github_view_issue(issue_number): View issue details and comments
- github_list_prs(state="open", limit=20): List pull requests
- github_view_pr(pr_number): View PR details with reviews and status
- github_list_branches(limit=30): List repository branches
- github_list_commits(branch="", limit=20): List recent commits
- github_list_tags(limit=20): List repository tags

**WRITE OPERATIONS (require clear user intent):**
- github_create_issue(title, body="", labels=""): Create new issue
- github_create_pr(title, body="", base="", head="", draft=False): Create new PR
- github_merge_pr(pr_number, merge_method="merge"): Merge PR
- github_close_issue(issue_number, comment=""): Close an issue
- github_create_comment(item_type, item_number, body): Comment on issue or PR
- github_create_branch(branch_name, from_branch=""): Create a new branch
- github_push_commits(branch="", force=False): Push local commits

**AUTHENTICATION:**
- Requires `gh` CLI installed and authenticated
- Token via GITHUB_TOKEN or GH_TOKEN env var, or `gh auth login`
"""

    SKILL_COMMANDS = """
━━━ SKILL EXECUTION ━━━
Skills are Python functions in `.archcode/skills/<name>/`. Execute via terminal:
```bash
cd .archcode/skills/<name> && python3 -c "from tools import <func>; import json; r = <func>(<args>); print(json.dumps(r, indent=2) if isinstance(r, (dict, list)) else r)"
```
- Check list_available_skills() first for any task that might use an integration.
- NEVER modify files inside `.archcode/skills/`.
- Skills auto-load their .env via config.py.
"""

    CODING_STANDARDS = """
━━━ CODING STANDARDS ━━━
When CREATING files:
  - Module-level docstring explaining purpose
  - Consistent naming: snake_case (Python), camelCase (JS/TS)
  - Type hints / JSDoc for public APIs
  - Explicit error handling (try/except or .catch())
  - `if __name__ == "__main__":` guard for runnable Python
  - Group imports: stdlib → third-party → local

When MODIFYING files:
  - MINIMUM changes to fulfill the instruction — do NOT rewrite working code
  - Do NOT change style, naming, or formatting unless instructed
  - Preserve existing comments and docstrings
  - Match the existing patterns in the file
"""

    EXECUTION_PRINCIPLES = """
━━━ AUTONOMOUS EXECUTION PRINCIPLES ━━━
Act autonomously — see output, act on it immediately:
- **See error → Fix it**: If a command fails, diagnose root cause and fix immediately. Check .env files, missing deps, wrong paths.
- **See test failure → Fix it**: If tests fail, read the test, understand expected behavior, fix the code.
- **Self-correct**: If your edit causes a syntax error, read the file and fix it in the same session.
- **ONE verification**: Run the test/compile command once. If it passes, you are done — do NOT "double check".
- **No re-reading**: If you already read a file or symbol in this session, do NOT read it again. Use what you have.
- **No duplicate tool calls**: NEVER issue the same tool call (same tool + same arguments) more than once in a turn — not in the same response AND not across multiple responses. The result will be byte-for-byte identical. Duplicates burn tokens and trigger the loop guard which terminates your session with no output. Track what you have already called.
- **Prefer symbol tools**: view_symbol and view_context are 10-50x cheaper than read_file_chunked. Default to them whenever you have a symbol name or line number.
- **Chain operations**: Install deps AND run tests in a single command with &&.
- **ENV awareness**: If you get auth errors, search for .env files and load them: `export $(grep -v '^#' .env | xargs) && <command>`
"""

    def _build_active_skills_section(self) -> str:
        try:
            from skill_manager import skill_manager

            skills = skill_manager.list_skills()
            if not skills:
                return "No skills currently connected."

            lines = ["━━━ CONNECTED SKILLS ━━━"]
            for s in skills:
                name = s.get("name", "unknown")
                desc = s.get("description", "No description")
                lines.append(f"  - **{name}**: {desc}")

                skill_path = Path(s.get("path", ""))
                available_files = []
                for f in ["SKILL.md", "tools.py", "config.py"]:
                    if (skill_path / f).exists():
                        available_files.append(f)
                if available_files:
                    lines.append(f"    Available: {', '.join(available_files)}")

            from mcp_manager import mcp_manager

            if mcp_manager.is_connected():
                lines.append("\n**CONNECTED MCP SERVERS — USE THESE FIRST:**")
                lines.append(
                    "⚠️  RULE: If an MCP tool can do the job, call it directly. "
                    "Do NOT use curl/wget/run_terminal_command as a substitute."
                )
                for server_name, tool_list in mcp_manager.server_tool_map.items():
                    for t in tool_list:
                        lines.append(
                            f"  - `mcp__{server_name}__{t['name']}` — "
                            f"{t.get('description', '')}"
                        )
                lines.append("\nMCP tool names are prefixed: `mcp__<server>__<tool>`")
                lines.append(
                    "Call them exactly like any other tool. "
                    "They are already available in your tool list."
                )

            return "\n".join(lines)
        except Exception:
            return "No skills currently connected."

    def _build_mcp_section(self) -> str:
        try:
            from mcp_manager import mcp_manager

            if not mcp_manager.is_connected():
                return ""
            lines = [
                "**MCP Tools (call these directly — PREFER over curl/wget/terminal for matching tasks):**"
            ]
            lines.append(
                "RULE: If an MCP tool covers the task (fetching URLs, querying DBs, GitHub ops), "
                "call `mcp__<server>__<tool>` directly."
            )
            for server_name, tool_list in mcp_manager.server_tool_map.items():
                for t in tool_list:
                    lines.append(
                        f"- mcp__{server_name}__{t['name']}: "
                        f"{t.get('description', '')}"
                    )
            return "\n".join(lines)
        except Exception:
            return ""

    def get_terminal_reference(self) -> str:
        return self.TERMINAL_COMMANDS

    def get_github_reference(self) -> str:
        return self.GITHUB_COMMANDS

    def get_skill_usage_guidelines(self) -> str:
        return self.SKILL_COMMANDS

    def get_coding_standards(self) -> str:
        return self.CODING_STANDARDS

    def get_execution_principles(self) -> str:
        return self.EXECUTION_PRINCIPLES

    def get_mcp_guidelines(self) -> str:
        return self._build_mcp_section()

    def get_active_skills_overview(self) -> str:
        return self._build_active_skills_section()


__all__ = ["GuidelinesService"]
