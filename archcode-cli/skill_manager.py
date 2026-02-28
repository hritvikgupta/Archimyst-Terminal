import os
import sys
import json
import re
import asyncio
import functools
import shutil
import importlib.util
from typing import Dict, List, Any, Optional
from pathlib import Path
from rich.console import Console

console = Console()
from langchain_core.tools import tool

GLOBAL_SKILLS_DIR = Path.home() / ".local" / "lib" / "archcode" / ".archcode" / "skills"


class SkillManager:
    def __init__(self, skills_dir: str = ".archcode/skills"):
        self.skills_dir = Path(skills_dir).absolute()
        self.global_skills_dir = GLOBAL_SKILLS_DIR

        self.registry_path = self.skills_dir / "registry.json"
        self.skills: Dict[str, Dict[str, Any]] = {}
        self.agno_skills = None
        self._load_registry()
        self._init_agno_skills()

    @staticmethod
    def _ensure_skill_frontmatter(skills_dir: Path) -> None:
        """Add minimal YAML frontmatter to any SKILL.md that is missing it."""
        if not skills_dir.exists():
            return
        for skill_md in skills_dir.glob("*/SKILL.md"):
            try:
                text = skill_md.read_text(encoding="utf-8", errors="ignore")
                if not text.lstrip().startswith("---"):
                    # name must be lowercase, letters/digits/hyphens only, matching dir name
                    dir_name = skill_md.parent.name
                    name = re.sub(r"[^a-z0-9-]", "-", dir_name.lower()).strip("-")
                    # Extract first heading as description
                    desc = name
                    for line in text.splitlines():
                        line = line.strip()
                        if line.startswith("#"):
                            desc = line.lstrip("#").strip()
                            break
                    # Only allowed fields: name, description (no version, etc.)
                    frontmatter = f"---\nname: {name}\ndescription: |\n  {desc}\n---\n"
                    skill_md.write_text(frontmatter + text, encoding="utf-8")
            except Exception:
                pass

    def _init_agno_skills(self):
        """Initialize Agno Skills object pointing at local + global skill directories."""
        try:
            from agno.skills import Skills, LocalSkills
            # Ensure all SKILL.md files have valid frontmatter before agno parses them
            self._ensure_skill_frontmatter(self.global_skills_dir)
            self._ensure_skill_frontmatter(self.skills_dir)
            loaders = []
            # Global skills first (lower priority — local overrides)
            if self.global_skills_dir.exists():
                loaders.append(LocalSkills(str(self.global_skills_dir)))
            loaders.append(LocalSkills(str(self.skills_dir)))
            self.agno_skills = Skills(loaders=loaders)
        except Exception as e:
            console.print(f"[dim yellow]Warning: Could not initialize Agno Skills: {e}[/dim yellow]")

    def _load_registry(self):
        """Scan skills directory on every startup to ensure registry is current."""
        self.refresh_registry()

    def _load_skill_md_metadata(self, skill_md_path: Path, default_name: str) -> Dict[str, Any]:
        """Parse basic metadata from Agno-style SKILL.md frontmatter."""
        metadata: Dict[str, Any] = {
            "name": default_name,
            "description": "",
            "version": "1.0.0",
        }
        try:
            text = skill_md_path.read_text()
        except Exception:
            return metadata

        fm_match = re.search(r"^---\s*\n(.*?)\n---\s*", text, re.DOTALL)
        if not fm_match:
            return metadata

        lines = fm_match.group(1).splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line.strip() or ":" not in line:
                i += 1
                continue

            key, raw_val = line.split(":", 1)
            key = key.strip()
            raw_val = raw_val.strip()

            if key == "description" and raw_val in {"|", ">", "|-", ">-"}:
                i += 1
                desc_lines: List[str] = []
                while i < len(lines):
                    next_line = lines[i]
                    if next_line.startswith("  ") or next_line.startswith("\t") or not next_line.strip():
                        desc_lines.append(next_line.lstrip())
                        i += 1
                    else:
                        break
                desc = "\n".join(desc_lines).strip()
                if desc:
                    metadata["description"] = desc
                continue

            value = raw_val.strip('"').strip("'")
            if key in {"name", "description", "version", "license"} and value:
                metadata[key] = value
            i += 1

        if not metadata.get("description"):
            metadata["description"] = "Agno-style skill"
        return metadata

    def _scan_skills_dir(self, directory: Path):
        """Scan one directory for skills and merge into self.skills (caller controls priority)."""
        if not directory.exists():
            return
        for item in directory.iterdir():
            if not item.is_dir():
                continue
            skill_json = item / "skill.json"
            skill_md = item / "SKILL.md"
            if skill_json.exists():
                try:
                    with open(skill_json, "r") as f:
                        metadata = json.load(f)
                        skill_name = metadata.get("name", item.name)
                        metadata["path"] = str(item)
                        self.skills[skill_name] = metadata
                except Exception as e:
                    console.print(f"[dim red]Error loading skill {item.name}: {e}[/dim red]")
            elif skill_md.exists():
                metadata = self._load_skill_md_metadata(skill_md, item.name)
                skill_name = metadata.get("name", item.name)
                metadata["path"] = str(item)
                self.skills[skill_name] = metadata

    def refresh_registry(self):
        """Scan global then local skill directories and merge. Local takes priority."""
        self.skills = {}
        if not self.skills_dir.exists():
            self.skills_dir.mkdir(parents=True, exist_ok=True)

        # Global skills first (lower priority)
        self._scan_skills_dir(self.global_skills_dir)
        # Local project skills second (override global if same name)
        self._scan_skills_dir(self.skills_dir)

        with open(self.registry_path, "w") as f:
            json.dump(self.skills, f, indent=2)

    def global_skill_count(self) -> int:
        """Number of skills available in the global install directory."""
        if not self.global_skills_dir.exists():
            return 0
        return sum(1 for p in self.global_skills_dir.iterdir() if p.is_dir() and not p.name.startswith("."))

    def get_skill(self, name: str) -> Optional[Dict[str, Any]]:
        return self.skills.get(name)

    def list_skills(self) -> List[Dict[str, Any]]:
        return list(self.skills.values())

    def search_skills(self, query: str) -> List[Dict[str, Any]]:
        """Search skills by name or description."""
        query = query.lower()
        results = []
        for name, metadata in self.skills.items():
            if query in name.lower() or query in metadata.get("description", "").lower():
                results.append(metadata)
        return results

    def get_skill_blueprint(self, name: str) -> str:
        """Fetch the full source code and docs of a skill."""
        skill = self.get_skill(name)
        if not skill:
            return f"Error: Skill '{name}' not found in registry."

        blueprint = f"=== BLUEPRINT: {name} ===\n"
        path = Path(skill["path"])
        
        files_to_read = [
            "SKILL.md",
            "scripts/helper.py",
            "references/guide.md",
            "skill.json",
            "schema.json",
            "skill.md",
            "handler.py",
            "tools.py",
            "config.py",
            "requirements.txt",
            "context.md"
        ]

        for filename in files_to_read:
            file_path = path / filename
            blueprint += f"\n--- FILE: {filename} ---\n"
            if file_path.exists():
                try:
                    blueprint += file_path.read_text()
                except Exception as e:
                    blueprint += f"[Error reading file: {e}]"
            else:
                blueprint += "[File not found]"
        
        return blueprint

    async def run_skill(self, skill_name: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Dynamically load and run a skill's handler."""
        skill = self.get_skill(skill_name)
        if not skill:
            raise ValueError(f"Skill '{skill_name}' not found.")

        handler_path = Path(skill["path"]) / "handler.py"
        if not handler_path.exists():
            raise FileNotFoundError(f"Handler not found for skill '{skill_name}' at {handler_path}")

        # Dynamic import
        spec = importlib.util.spec_from_file_location(f"skill.{skill_name}", str(handler_path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load spec for skill '{skill_name}'")
            
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "run"):
            raise AttributeError(f"Skill '{skill_name}' handler does not have a 'run' function.")

        # Run as a task for concurrency support
        return await module.run(inputs)

    def get_research_tools(self) -> List[Any]:
        """Get tools for skill discovery and blueprint reading.
        Returns plain callable functions that Agno can use directly."""

        def list_available_skills() -> str:
            """List all available skill blueprints in the registry."""
            skills = self.list_skills()
            if not skills: return "No skills found in registry."
            skill_names = [s['name'] for s in skills]
            skills_list = "\n".join([f"- {s['name']}: {s.get('description', '')}" for s in skills])
            return f"Found {len(skills)} skills: {', '.join(skill_names)}\n\n{skills_list}"

        def search_skills(query: str) -> str:
            """Search the skill registry for a specific blueprint or capability."""
            results = self.search_skills(query)
            if not results: return f"No skills found matching '{query}'."
            skill_names = [s['name'] for s in results]
            results_list = "\n".join([f"- {s['name']}: {s.get('description', '')}" for s in results])
            return f"Found {len(results)} skills matching '{query}': {', '.join(skill_names)}\n\n{results_list}"

        def read_skill_blueprint(skill_name: str) -> str:
            """Read the full source code and documentation of a skill to use as a blueprint or reference architecture."""
            blueprint = self.get_skill_blueprint(skill_name)
            return f"Loading skill blueprint: {skill_name}\n\n{blueprint}"

        return [list_available_skills, search_skills, read_skill_blueprint]

    def get_skill_tools(self) -> List[Any]:
        """
        Convert skills to LangChain-compatible tool definitions using @tool decorator.
        
        Each skill is converted to a tool that executes via terminal command,
        following the original Archimyst design of manual execution after research.
        
        The tool description is taken from SKILL.md metadata, and the tool
        executes the skill's handler.py or tools.py via python subprocess.
        """
        tools = []
        
        for skill_name, skill_metadata in self.skills.items():
            skill_path = Path(skill_metadata["path"])
            
            # Get skill description from metadata (from SKILL.md)
            skill_description = skill_metadata.get("description", f"Execute the {skill_name} skill")
            
            # Determine the main executable file (handler.py preferred, then tools.py)
            executable_file = None
            if (skill_path / "handler.py").exists():
                executable_file = "handler.py"
            elif (skill_path / "tools.py").exists():
                executable_file = "tools.py"
            else:
                # Skip skills without executable files
                continue
            
            # Create a tool that executes the skill via terminal command
            try:
                @tool
                def skill_tool(inputs: str = "") -> str:
                    """
                    Execute a skill by running its main Python file with provided inputs.
                    Inputs should be a JSON string or appropriate arguments for the skill.
                    """
                    import subprocess
                    import json
                    
                    # Prepare the command to execute the skill
                    cmd = f"cd {skill_path} && python3 {executable_file}"
                    
                    if inputs:
                        # Try to parse as JSON first, otherwise pass as string
                        try:
                            input_dict = json.loads(inputs)
                            # Convert dict to command line arguments if needed
                            cmd += f" '{inputs}'"
                        except json.JSONDecodeError:
                            cmd += f" '{inputs}'"
                    
                    try:
                        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                        if result.returncode == 0:
                            return result.stdout
                        else:
                            return f"Error executing skill: {result.stderr}"
                    except subprocess.TimeoutExpired:
                        return "Error: Skill execution timed out"
                    except Exception as e:
                        return f"Error executing skill: {str(e)}"
                
                # Set proper tool name and description
                skill_tool.name = f"execute_{skill_name}"
                skill_tool.description = f"Execute the {skill_name} skill. {skill_description}"
                
                tools.append(skill_tool)
                
            except Exception as e:
                console.print(f"[dim yellow]Warning: Could not create tool for skill '{skill_name}': {e}[/dim yellow]")
                continue
        
        return tools

    def check_skill_config(self, skill_name: str) -> Dict[str, Any]:
        """Import config.py for a skill, call validate_config(), return required vars and missing list."""
        skill = self.get_skill(skill_name)
        if not skill:
            return {"required": {}, "optional": {}, "missing": []}

        config_path = Path(skill["path"]) / "config.py"
        if not config_path.exists():
            return {"required": {}, "optional": {}, "missing": []}

        try:
            spec = importlib.util.spec_from_file_location(
                f"skill_config_check.{skill_name}", str(config_path)
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                required = getattr(module, "REQUIRED_ENV_VARS", {})
                optional = getattr(module, "OPTIONAL_ENV_VARS", {})
                missing = module.validate_config() if hasattr(module, "validate_config") else []
                return {"required": required, "optional": optional, "missing": missing}
        except Exception as e:
            console.print(f"[dim yellow]Warning: Failed to check config for '{skill_name}': {e}[/dim yellow]")

        return {"required": {}, "optional": {}, "missing": []}

    def save_skill_env(self, skill_name: str, env_vars: Dict[str, str]):
        """Write key=value pairs to .env inside the skill directory with restricted permissions."""
        skill = self.get_skill(skill_name)
        if not skill:
            return

        env_path = Path(skill["path"]) / ".env"
        lines = []

        # Preserve existing entries not being overwritten
        if env_path.exists():
            with open(env_path, "r") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and "=" in stripped:
                        key = stripped.partition("=")[0].strip()
                        if key not in env_vars:
                            lines.append(stripped)
                    elif stripped:
                        lines.append(stripped)

        for key, value in env_vars.items():
            lines.append(f"{key}={value}")

        with open(env_path, "w") as f:
            f.write("\n".join(lines) + "\n")

        # Restrict permissions to owner only
        os.chmod(env_path, 0o600)

    async def _connect_skills_sh(self, url: str) -> Dict[str, Any]:
        """
        Download a skill directly from skills.sh (backed by GitHub).
        URL format: https://skills.sh/<owner>/<repo>/<skill-name>
        """
        import httpx

        # Parse: https://skills.sh/vercel-labs/agent-skills/web-design-guidelines
        path = re.sub(r"https?://skills\.sh/", "", url).strip("/")
        parts = path.split("/")
        if len(parts) < 3:
            raise ValueError(
                "Invalid skills.sh URL. Expected: https://skills.sh/<owner>/<repo>/<skill-name>"
            )
        owner, repo, skill_name = parts[0], parts[1], parts[2]

        async with httpx.AsyncClient(timeout=60.0) as client:
            # Resolve the default branch (main or master)
            branch = "main"
            for candidate in ("main", "master"):
                check = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/git/trees/{candidate}",
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                if check.status_code == 200:
                    branch = candidate
                    break
            else:
                raise ValueError(f"Could not access GitHub repo {owner}/{repo}")

            # Fetch the full recursive tree
            tree_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            if tree_resp.status_code != 200:
                raise ValueError(f"Failed to fetch repo tree: {tree_resp.text}")

            # Find all blobs under skills/<skill-name>/
            skill_prefix = f"skills/{skill_name}/"
            skill_files = [
                item for item in tree_resp.json().get("tree", [])
                if item["path"].startswith(skill_prefix) and item["type"] == "blob"
            ]
            if not skill_files:
                raise ValueError(f"Skill '{skill_name}' not found in {owner}/{repo}. Check the URL.")

            # Download all files to a temp name first, then rename to match SKILL.md
            tmp_path = self.skills_dir / skill_name
            tmp_path.mkdir(parents=True, exist_ok=True)
            downloaded = []
            skill_md_content = None
            for item in skill_files:
                relative = item["path"][len(skill_prefix):]
                raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{item['path']}"
                file_resp = await client.get(raw_url)
                if file_resp.status_code != 200:
                    continue
                dest = tmp_path / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(file_resp.content)
                downloaded.append(relative)
                if relative == "SKILL.md":
                    skill_md_content = file_resp.text

        # Use skill name from SKILL.md so directory name matches (Agno requirement)
        actual_name = skill_name
        if skill_md_content:
            name_match = re.search(r"^name:\s*(.+)$", skill_md_content, re.MULTILINE)
            if name_match:
                actual_name = name_match.group(1).strip().strip('"').strip("'")

        skill_path = self.skills_dir / actual_name
        if tmp_path != skill_path:
            if skill_path.exists():
                shutil.rmtree(skill_path)
            tmp_path.rename(skill_path)

        self.refresh_registry()
        if self.agno_skills is not None:
            self.agno_skills.reload()

        return {"name": actual_name, "path": str(skill_path), "files": downloaded}

    async def connect_project(self, url_or_id: str) -> Dict[str, Any]:
        """
        Connect to an Archimyst project or a skills.sh skill URL.
        """
        import httpx
        from config import config

        # Route skills.sh URLs to the dedicated handler
        if "skills.sh/" in url_or_id:
            return await self._connect_skills_sh(url_or_id)

        # 1. ID Extraction (Archimyst project UUID)
        uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        match = re.search(uuid_pattern, url_or_id.lower())
        if not match:
            raise ValueError("Could not find a valid Project ID (UUID) in the provided URL.")
        
        project_id = match.group(0)
        backend_url = os.getenv("BACKEND_URL") or "https://archflow-backend.fly.dev"
        headers = {}
        if config.access_token:
            headers["Authorization"] = f"Bearer {config.access_token}"

        async with httpx.AsyncClient(timeout=300.0) as client:
            # 2. Fetch Project Metadata & Markdown Context
            ctx_resp = await client.get(f"{backend_url}/api/projects/{project_id}/markdown", headers=headers)
            if ctx_resp.status_code != 200:
                raise Exception(f"Failed to fetch project context: {ctx_resp.text}")
            
            # Use Content-Disposition filename to get project name if possible
            project_name = f"project_{project_id[:8]}"
            cd = ctx_resp.headers.get("Content-Disposition", "")
            if "filename=" in cd:
                project_name = cd.split("filename=")[1].replace("_design.md", "").replace('"', '').lower()

            context_md = ctx_resp.text

            # 3. Fetch Skill Package (Synthesized dynamically)
            skill_resp = await client.get(f"{backend_url}/api/projects/{project_id}/skill", headers=headers)
            if skill_resp.status_code != 200:
                raise Exception(f"Skill synthesis failed: {skill_resp.text}")
            
            skill_package = skill_resp.json()

        # 4. Unified Local Storage
        # Use skill name from SKILL.md so the directory name matches what
        # Agno's LocalSkills expects (directory name must equal skill name).
        skill_name = project_name
        if "SKILL.md" in skill_package:
            name_match = re.search(r"^name:\s*(.+)$", skill_package["SKILL.md"], re.MULTILINE)
            if name_match:
                skill_name = name_match.group(1).strip().strip('"').strip("'")

        skill_path = self.skills_dir / skill_name
        skill_path.mkdir(parents=True, exist_ok=True)

        # Save context.md
        (skill_path / "context.md").write_text(context_md)

        # Save skill files
        for filename, content in skill_package.items():
            file_path = skill_path / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if not isinstance(content, str):
                content = json.dumps(content, indent=2)
            file_path.write_text(content)
            if filename.startswith("scripts/") and file_path.suffix == ".py":
                try:
                    os.chmod(file_path, 0o755)
                except Exception:
                    pass
        
        # Refresh registry to make it active
        self.refresh_registry()

        # Reload Agno Skills so the agent sees the new skill immediately
        if self.agno_skills is not None:
            self.agno_skills.reload()

        return {
            "name": skill_name,
            "path": str(skill_path),
            "files": list(skill_package.keys()) + ["context.md"]
        }

# Singleton instance
skill_manager = SkillManager()
