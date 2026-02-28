# backend/archcode-terminal/archcode-cli/RAG/parser.py
import ast
import os
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json

# Try to import universal tree-sitter parser
try:
    from tree_sitter_languages import get_parser
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False


def _line_windows(lines, file_path, chunk_type, window=160, overlap=40):
    chunks =[]
    step = max(1, window - overlap)
    for i in range(0, len(lines), step):
        start = i + 1
        end = min(len(lines), i + window)
        text = "\n".join(lines[i:end])
        if text.strip():
            chunks.append(CodeChunk(
                content=text,
                file_path=file_path,
                start_line=start,
                end_line=end,
                chunk_type=chunk_type,
                name=None,
                scope=[]
            ))
        if end >= len(lines):
            break
    return chunks


def _parse_markdown(lines, file_path):
    chunks = []
    heading_idxs =[]
    for i, line in enumerate(lines):
        if re.match(r"^\s{0,3}#{1,6}\s+\S", line):
            heading_idxs.append(i)

    if not heading_idxs:
        return _line_windows(lines, file_path, chunk_type="md_block")

    heading_idxs.append(len(lines))  
    for j in range(len(heading_idxs) - 1):
        start_i = heading_idxs[j]
        end_i = heading_idxs[j + 1]
        section_lines = lines[start_i:end_i]
        if len(section_lines) > 400:
            chunks.extend(_line_windows(section_lines, file_path, chunk_type="md_block", window=200, overlap=50))
        else:
            start = start_i + 1
            end = start_i + len(section_lines)
            chunks.append(CodeChunk(
                content="\n".join(section_lines),
                file_path=file_path,
                start_line=start,
                end_line=end,
                chunk_type="md_block",
                name=section_lines[0].strip(),
                scope=[]
            ))
    return chunks


def _parse_yaml(lines, file_path):
    chunks = []
    start = 1
    current =[]
    current_name = None

    def flush(end_line):
        nonlocal current, current_name, start
        if current and "\n".join(current).strip():
            chunks.append(CodeChunk(
                content="\n".join(current),
                file_path=file_path,
                start_line=start,
                end_line=end_line,
                chunk_type="yaml_block",
                name=current_name,
                scope=[]
            ))
        current =[]
        current_name = None

    for i, line in enumerate(lines):
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*:\s*(#.*)?$", line)
        if m and not line.startswith(" "):
            if current:
                flush(i)  
            start = i + 1
            current_name = m.group(1)
        current.append(line)

        if len(current) >= 450:
            flush(i + 1)
            start = i + 2

    flush(len(lines))
    return chunks


def _parse_json(content, lines, file_path):
    try:
        obj = json.loads(content)
    except Exception:
        return _line_windows(lines, file_path, chunk_type="json_block")

    if not isinstance(obj, dict):
        return _line_windows(lines, file_path, chunk_type="json_block")

    chunks =[]
    text = content

    for key in list(obj.keys())[:200]:  
        pat = f"\"{key}\""
        idx = text.find(pat)
        if idx == -1:
            continue
        start_char = max(0, idx - 200)
        end_char = min(len(text), idx + 3000)
        snippet = text[start_char:end_char]
        chunks.append(CodeChunk(
            content=snippet,
            file_path=file_path,
            start_line=1,
            end_line=min(len(lines), 200),  
            chunk_type="json_key_region",
            name=key,
            scope=[]
        ))

    if not chunks:
        chunks = _line_windows(lines, file_path, chunk_type="json_block")
    return chunks


def _parse_sql(lines, file_path):
    chunks = []
    start = 1
    buf =[]
    name = None
    stmt_re = re.compile(r"^\s*(CREATE|ALTER|DROP|SELECT|INSERT|UPDATE|DELETE|WITH)\b", re.IGNORECASE)

    def flush(end_line):
        nonlocal buf, name, start
        if buf and "\n".join(buf).strip():
            chunks.append(CodeChunk(
                content="\n".join(buf),
                file_path=file_path,
                start_line=start,
                end_line=end_line,
                chunk_type="sql_stmt",
                name=name,
                scope=[]
            ))
        buf =[]
        name = None

    for i, line in enumerate(lines):
        if stmt_re.match(line) and buf:
            flush(i)
            start = i + 1
        if name is None:
            m = stmt_re.match(line)
            if m:
                name = m.group(1).upper()
        buf.append(line)
        if line.strip().endswith(";") and len(buf) > 5:
            flush(i + 1)
            start = i + 2

        if len(buf) >= 500:
            flush(i + 1)
            start = i + 2

    flush(len(lines))
    return chunks


def detect_language(ext: str) -> str:
    ext = ext.lower()
    lang_map = {
        ".py": "python", ".ts": "typescript", ".tsx": "typescript", 
        ".js": "javascript", ".jsx": "javascript", ".java": "java", 
        ".go": "go", ".rs": "rust", ".c": "c", ".h": "c", 
        ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp", ".php": "php", 
        ".rb": "ruby", ".swift": "swift", ".kt": "kotlin", ".scala": "scala", 
        ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".ps1": "powershell", 
        ".css": "css", ".scss": "css", ".sass": "css", ".less": "css", 
        ".html": "html", ".json": "json", ".yaml": "yaml", ".yml": "yaml", 
        ".toml": "toml", ".ini": "config", ".cfg": "config", ".conf": "config", 
        ".env": "config", ".xml": "xml", ".md": "docs", ".mdx": "docs", 
        ".rst": "docs", ".txt": "docs", ".tf": "terraform", ".tfvars": "terraform", 
        ".sql": "sql", ".proto": "proto", ".dart": "dart", ".ex": "elixir", 
        ".exs": "elixir", ".lua": "lua", ".pl": "perl", ".m": "objective-c"
    }
    return lang_map.get(ext, "text")


@dataclass
class CodeChunk:
    content: str
    file_path: str
    start_line: int
    end_line: int
    chunk_type: str
    name: Optional[str] = None
    scope: List[str] = field(default_factory=list)
    language: Optional[str] = None
    ext: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        breadcrumb = " > ".join(self.scope + ([self.name] if self.name else []))
        meta: Dict[str, Any] = {
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "type": self.chunk_type,
            "name": self.name,
            "scope": breadcrumb,
            "ext": self.ext,
            "language": self.language,
        }

        tagged = (
            f"[FILE:{self.file_path}] "
            f"[LANG:{self.language}] "
            f"[EXT:{self.ext}]\n"
            f"{self.content}"
        )

        return {"content": tagged, "metadata": {k: v for k, v in meta.items() if v is not None}}


class ASTParser:
    """Universal parser utilizing Tree-sitter for all languages, falling back to AST/Regex."""

    # Universal heuristic symbol patterns for fallback if tree-sitter is missing
    _re_universal_func = re.compile(r'^\s*(?:export\s+|public\s+|private\s+|protected\s+|static\s+|async\s+|inline\s+)*(?:function|func|fn|def)\s+([A-Za-z0-9_$]+)\b')
    _re_universal_class = re.compile(r'^\s*(?:export\s+|public\s+|private\s+|protected\s+|abstract\s+)*(?:class|struct|interface|trait|impl)\s+([A-Za-z0-9_$]+)\b')
    _re_export_const_arrow = re.compile(r'^\s*export\s+const\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[A-Za-z0-9_$]+)\s*=>\s*[{(]')

    def parse_universal_tree_sitter(self, content: str, file_path: str, lang: str, ext: str) -> List[CodeChunk]:
        """Uses tree-sitter to parse any supported programming language universally."""
        lines = content.splitlines()
        
        ts_lang_map = {
            "python": "python", "javascript": "javascript", "typescript": "tsx" if ext == ".tsx" else "typescript",
            "java": "java", "go": "go", "rust": "rust", "c": "c", "cpp": "cpp", "csharp": "c_sharp",
            "php": "php", "ruby": "ruby", "swift": "swift", "kotlin": "kotlin", "scala": "scala",
            "shell": "bash", "html": "html", "css": "css", "elixir": "elixir", "dart": "dart"
        }
        
        ts_lang_str = ts_lang_map.get(lang)
        if not ts_lang_str:
            return self._fallback_parse(content, file_path, lang, ext, lines)

        try:
            parser = get_parser(ts_lang_str)
            tree = parser.parse(bytes(content, "utf8"))
        except Exception:
            return self._fallback_parse(content, file_path, lang, ext, lines)

        chunks: List[CodeChunk] =[]
        parsed_ranges: List[tuple[int, int]] =[]
        content_bytes = bytes(content, "utf8")

        def get_node_name(node) -> Optional[str]:
            for child in node.children:
                if any(k in child.type for k in["identifier", "name", "type_identifier", "property_identifier"]):
                    return content_bytes[child.start_byte:child.end_byte].decode("utf8")
            return None

        def traverse(node, scope):
            t = node.type
            
            # Universal categorization based on common tree-sitter node grammar naming conventions
            is_class = any(k in t for k in["class_definition", "class_declaration", "struct_specifier", "interface_declaration", "type_declaration", "trait_declaration", "impl_item"])
            is_func = any(k in t for k in["function_definition", "function_declaration", "method_definition", "method_declaration", "arrow_function", "function_item", "method_item", "func_literal"])

            if is_class or is_func:
                name = get_node_name(node)
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                
                chunk_type = "class" if is_class else "function"
                
                chunks.append(CodeChunk(
                    content="\n".join(lines[start_line - 1:end_line]),
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    chunk_type=chunk_type,
                    name=name,
                    scope=scope.copy(),
                    language=lang,
                    ext=ext,
                ))
                parsed_ranges.append((start_line, end_line))
                
                new_scope = scope + [name] if name else scope
                for child in node.children:
                    traverse(child, new_scope)
            else:
                for child in node.children:
                    traverse(child, scope)

        traverse(tree.root_node,[])

        return chunks + self._generic_windows(lines, file_path, lang, ext, parsed_ranges)

    def _fallback_parse(self, content: str, file_path: str, lang: str, ext: str, lines: List[str]) -> List[CodeChunk]:
        """Graceful degradation if Tree-sitter is missing or fails."""
        if lang == "python":
            return self.parse_python_ast(content, file_path, lang, ext, lines)
        elif lang in["javascript", "typescript", "java", "c", "cpp", "csharp", "go", "rust", "php", "swift", "kotlin", "scala"]:
            return self.parse_universal_regex(content, file_path, lang, ext, lines)
        else:
            return self._generic_windows(lines, file_path, lang, ext)

    def parse_python_ast(self, content: str, file_path: str, lang: str, ext: str, lines: List[str]) -> List[CodeChunk]:
        """Native Python AST Fallback"""
        chunks: List[CodeChunk] =[]
        try:
            tree = ast.parse(content)
            class Visitor(ast.NodeVisitor):
                def __init__(self):
                    self.stack: List[str] =[]

                def visit_ClassDef(self, node: ast.ClassDef):
                    start = node.lineno
                    end = getattr(node, "end_lineno", start)
                    chunks.append(CodeChunk("\n".join(lines[start - 1:end]), file_path, start, end, "class", node.name, self.stack.copy(), lang, ext))
                    self.stack.append(node.name)
                    self.generic_visit(node)
                    self.stack.pop()

                def visit_FunctionDef(self, node: ast.FunctionDef):
                    start = node.lineno
                    end = getattr(node, "end_lineno", start)
                    chunks.append(CodeChunk("\n".join(lines[start - 1:end]), file_path, start, end, "function", node.name, self.stack.copy(), lang, ext))
                    self.generic_visit(node)

                def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
                    self.visit_FunctionDef(node)

            Visitor().visit(tree)
            
            if not chunks and content.strip():
                chunks.append(CodeChunk(content, file_path, 1, len(lines), "module", None,[], lang, ext))
        except Exception:
            pass

        return chunks if chunks else self._generic_windows(lines, file_path, lang, ext)

    def _block_end_braces(self, lines: List[str], start_idx: int, max_lookahead: int = 800) -> int:
        brace = 0
        started = False
        end_idx = start_idx
        limit = min(len(lines), start_idx + max_lookahead)

        for j in range(start_idx, limit):
            line = lines[j]
            brace += line.count("{")
            brace -= line.count("}")
            if "{" in line:
                started = True
            if started:
                end_idx = j
                if brace <= 0:
                    break
        return end_idx

    def parse_universal_regex(self, content: str, file_path: str, lang: str, ext: str, lines: List[str]) -> List[CodeChunk]:
        """Regex heuristic fallback for C-family/Curly Brace languages."""
        chunks: List[CodeChunk] = []
        parsed_ranges: List[tuple[int, int]] =[]
        i = 0

        while i < len(lines):
            line = lines[i]
            name = None
            chunk_type = "symbol"

            for rx, ctype in[(self._re_universal_class, "class"), (self._re_universal_func, "function"), (self._re_export_const_arrow, "function")]:
                m = rx.search(line)
                if m:
                    name = m.group(1)
                    chunk_type = ctype
                    break

            if name:
                start = i + 1
                end = self._block_end_braces(lines, i) + 1
                if end <= start:
                    end = min(len(lines), start + 160)

                chunks.append(CodeChunk("\n".join(lines[start - 1:end]), file_path, start, end, chunk_type, name,[], lang, ext))
                parsed_ranges.append((start, end))
                i = end  
                continue

            i += 1

        return chunks + self._generic_windows(lines, file_path, lang, ext, parsed_ranges)

    def _generic_windows(
        self,
        lines: List[str],
        file_path: str,
        lang: str,
        ext: str,
        parsed_ranges: Optional[List[tuple[int, int]]] = None,
        window: int = 140,
        overlap: int = 30,
    ) -> List[CodeChunk]:
        parsed_ranges = parsed_ranges or[]
        chunks: List[CodeChunk] =[]

        def in_range(line_no: int) -> bool:
            return any(s <= line_no <= e for s, e in parsed_ranges)

        step = max(1, window - overlap)
        for i in range(0, len(lines), step):
            start_line = i + 1
            if in_range(start_line):
                continue
            end_line = min(len(lines), i + window)
            chunk_text = "\n".join(lines[i:end_line])
            if chunk_text.strip():
                chunks.append(CodeChunk(chunk_text, file_path, start_line, end_line, "generic", None,[], lang, ext))
            if end_line >= len(lines):
                break

        return chunks

    def parse_file(self, file_path: str) -> List[CodeChunk]:
        if not os.path.exists(file_path):
            return[]

        try:
            with open(file_path, "rb") as bf:
                head = bf.read(4096)
                if b"\x00" in head:
                    return []
        except Exception:
            return[]

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            return[]

        if not content.strip():
            return []

        ext = os.path.splitext(file_path)[1].lower()
        lang = detect_language(ext)
        lines = content.splitlines()

        # Domain-specific structural parsers (Data/Docs/Config)
        if ext in (".md", ".mdx", ".rst", ".txt"):
            return _parse_markdown(lines, file_path)
        if ext in (".yaml", ".yml"):
            return _parse_yaml(lines, file_path)
        if ext == ".json":
            return _parse_json(content, lines, file_path)
        if ext == ".sql":
            return _parse_sql(lines, file_path)
        if ext in (".toml", ".ini", ".cfg", ".conf", ".env"):
            blocks, buf, start = [],[], 1
            for i, line in enumerate(lines):
                if not line.strip() and buf:
                    blocks.append(CodeChunk("\n".join(buf), file_path, start, i, "config_block", None, []))
                    buf, start =[], i + 2
                else:
                    buf.append(line)
            buf.append(line)
            if buf:
                blocks.append(CodeChunk(
                    content="\n".join(buf), 
                    file_path=file_path, 
                    start_line=start, 
                    end_line=len(lines), 
                    chunk_type="config_block", 
                    name=None, 
                    scope=[],
                    language=lang,
                    ext=ext
                ))
            return blocks if blocks else self._generic_windows(lines, file_path, lang, ext)

        # ---------------------------------------------------------
        # UNIVERSAL CODE PARSING 
        # (Prioritizes Tree-Sitter -> falls back to Native AST / Regex)
        # ---------------------------------------------------------
        if HAS_TREE_SITTER:
            return self.parse_universal_tree_sitter(content, file_path, lang, ext)
        
        return self._fallback_parse(content, file_path, lang, ext, lines)