"""Parser service layer for symbol extraction and file chunking."""

from typing import Any, Dict, List

import tree_sitter


def build_tree_sitter_parser(lang_name: str):
    """Build a tree-sitter parser, handling old and new API versions."""
    try:
        from tree_sitter_languages import get_parser

        return get_parser(lang_name)
    except (TypeError, Exception):
        pass

    import ctypes
    import pathlib

    import tree_sitter_languages as _tsl

    lang_lib = pathlib.Path(_tsl.__file__).parent / "languages.so"
    if not lang_lib.exists():
        lang_lib = pathlib.Path(_tsl.__file__).parent / "languages.dylib"

    lib = ctypes.cdll.LoadLibrary(str(lang_lib))
    func = getattr(lib, f"tree_sitter_{lang_name}")
    func.restype = ctypes.c_void_p
    lang_ptr = func()
    language = tree_sitter.Language(lang_ptr)
    parser = tree_sitter.Parser(language)
    return parser


class TreeSitterCodeParserService:
    """Uses Tree-sitter to parse source code and extract symbols."""

    LANG_NAMES = ["python", "javascript", "typescript", "tsx"]

    def __init__(self):
        self.parsers = {}
        self._init_errors = []

        for lang in self.LANG_NAMES:
            try:
                self.parsers[lang] = build_tree_sitter_parser(lang)
            except Exception as e:
                self._init_errors.append(f"{lang}: {e}")

    def get_symbols(self, code: str, language: str) -> List[Dict[str, Any]]:
        if language not in self.parsers:
            return []

        parser = self.parsers[language]
        code_bytes = bytes(code, "utf8")
        tree = parser.parse(code_bytes)

        symbols = []
        root_node = tree.root_node

        def walk(node):
            if node.type in [
                "function_definition",
                "class_definition",
                "method_definition",
                "arrow_function",
            ]:
                name_node = node.child_by_field_name("name")
                symbol_name = (
                    code_bytes[name_node.start_byte : name_node.end_byte].decode(
                        "utf8", errors="replace"
                    )
                    if name_node
                    else "anonymous"
                )

                symbols.append(
                    {
                        "name": symbol_name,
                        "type": node.type,
                        "start_line": node.start_point[0] + 1,
                        "end_line": node.end_point[0] + 1,
                        "content": code_bytes[node.start_byte : node.end_byte].decode(
                            "utf8", errors="replace"
                        ),
                    }
                )

            for child in node.children:
                walk(child)

        walk(root_node)
        return symbols

    def chunk_file(self, code: str, file_path: str) -> List[Dict[str, Any]]:
        ext = file_path.split(".")[-1].lower()
        lang_map = {
            "py": "python",
            "js": "javascript",
            "ts": "typescript",
            "tsx": "tsx",
        }
        lang = lang_map.get(ext)

        if not lang:
            lines = code.split("\n")
            return [
                {
                    "content": code,
                    "start_line": 1,
                    "end_line": len(lines),
                    "symbol_name": "file_content",
                    "language": "text",
                }
            ]

        symbols = self.get_symbols(code, lang)

        if not symbols:
            lines = code.split("\n")
            return [
                {
                    "content": code,
                    "start_line": 1,
                    "end_line": len(lines),
                    "symbol_name": "file_content",
                    "language": lang,
                }
            ]

        for s in symbols:
            s["language"] = lang

        return symbols

    def get_signatures(self, code: str, language: str) -> List[Dict[str, Any]]:
        if language not in self.parsers:
            return []

        parser = self.parsers[language]
        code_bytes = bytes(code, "utf8")
        tree = parser.parse(code_bytes)
        signatures = []

        def _slice(node) -> str:
            return code_bytes[node.start_byte : node.end_byte].decode(
                "utf8", errors="replace"
            )

        def extract_docstring_first_line(node, lang: str) -> str:
            body = node.child_by_field_name("body")
            if not body:
                return ""
            for child in body.children:
                if lang == "python" and child.type == "expression_statement":
                    for sc in child.children:
                        if sc.type == "string":
                            doc = _slice(sc).strip("\"' \n")
                            first_line = doc.split("\n")[0].strip()
                            return first_line
                break
            return ""

        def extract_params(node, lang: str) -> str:
            params = node.child_by_field_name("parameters")
            if params:
                return _slice(params)
            return "()"

        def extract_return_type(node, lang: str) -> str:
            ret = node.child_by_field_name("return_type")
            if ret:
                return _slice(ret)
            return ""

        def walk(node, parent_class=None):
            if node.type in ("function_definition", "method_definition"):
                name_node = node.child_by_field_name("name")
                name = _slice(name_node) if name_node else "anonymous"
                params = extract_params(node, language)
                ret = extract_return_type(node, language)
                doc = extract_docstring_first_line(node, language)

                sig = {
                    "type": "function",
                    "name": name,
                    "params": params,
                    "return_type": ret,
                    "docstring": doc,
                    "line": node.start_point[0] + 1,
                    "parent_class": parent_class,
                }
                signatures.append(sig)

            elif node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                class_name = _slice(name_node) if name_node else "anonymous"
                doc = extract_docstring_first_line(node, language)

                methods = []
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        if child.type in ("function_definition", "method_definition"):
                            m_name_node = child.child_by_field_name("name")
                            m_name = _slice(m_name_node) if m_name_node else "anonymous"
                            m_params = extract_params(child, language)
                            m_ret = extract_return_type(child, language)
                            m_doc = extract_docstring_first_line(child, language)
                            methods.append(
                                {
                                    "name": m_name,
                                    "params": m_params,
                                    "return_type": m_ret,
                                    "docstring": m_doc,
                                }
                            )

                signatures.append(
                    {
                        "type": "class",
                        "name": class_name,
                        "docstring": doc,
                        "methods": methods,
                        "line": node.start_point[0] + 1,
                    }
                )
                return

            elif node.type == "lexical_declaration" and language in (
                "javascript",
                "typescript",
                "tsx",
            ):
                for child in node.children:
                    if child.type == "variable_declarator":
                        name_node = child.child_by_field_name("name")
                        value_node = child.child_by_field_name("value")
                        if not name_node or not value_node:
                            continue
                        arrow = None
                        if value_node.type == "arrow_function":
                            arrow = value_node
                        elif value_node.type == "call_expression":
                            for arg in value_node.children:
                                if arg.type == "arguments":
                                    for a in arg.children:
                                        if a.type == "arrow_function":
                                            arrow = a
                                            break
                                    break
                        if arrow:
                            name = _slice(name_node)
                            params = extract_params(arrow, language)
                            ret = extract_return_type(arrow, language)
                            signatures.append(
                                {
                                    "type": "function",
                                    "name": name,
                                    "params": params,
                                    "return_type": ret,
                                    "docstring": "",
                                    "line": node.start_point[0] + 1,
                                    "parent_class": parent_class,
                                }
                            )

            for child in node.children:
                walk(child, parent_class)

        walk(tree.root_node)
        return signatures

    def get_imports(self, code: str, language: str) -> List[str]:
        if language not in self.parsers:
            return []

        parser = self.parsers[language]
        code_bytes = bytes(code, "utf8")
        tree = parser.parse(code_bytes)
        imports = []

        for child in tree.root_node.children:
            if language == "python":
                if child.type in ("import_statement", "import_from_statement"):
                    imports.append(
                        code_bytes[child.start_byte : child.end_byte]
                        .decode("utf8", errors="replace")
                        .strip()
                    )
            elif language in ("javascript", "typescript", "tsx"):
                if child.type == "import_statement":
                    imports.append(
                        code_bytes[child.start_byte : child.end_byte]
                        .decode("utf8", errors="replace")
                        .strip()
                    )

        return imports

    def get_exports(self, code: str, language: str) -> List[str]:
        if language not in ("javascript", "typescript", "tsx"):
            return []
        if language not in self.parsers:
            return []

        parser = self.parsers[language]
        code_bytes = bytes(code, "utf8")
        tree = parser.parse(code_bytes)
        exports = []

        for child in tree.root_node.children:
            if child.type in ("export_statement", "export_default_declaration"):
                text = (
                    code_bytes[child.start_byte : child.end_byte]
                    .decode("utf8", errors="replace")
                    .strip()
                )
                first_line = text.split("\n")[0]
                exports.append(first_line)

        return exports


# Backward-compatible aliases
CodeParser = TreeSitterCodeParserService
_build_parser = build_tree_sitter_parser


__all__ = [
    "build_tree_sitter_parser",
    "_build_parser",
    "TreeSitterCodeParserService",
    "CodeParser",
]
