"""Backward-compatible parser utilities module.

This module preserves historical imports while delegating implementation
into the class-based core service layer.
"""

from core.search.parser_service import (
    CodeParser,
    TreeSitterCodeParserService,
    _build_parser,
    build_tree_sitter_parser,
)


__all__ = [
    "_build_parser",
    "build_tree_sitter_parser",
    "CodeParser",
    "TreeSitterCodeParserService",
]


if __name__ == "__main__":
    parser = CodeParser()
    test_code = """
class MyClass:
    def method_one(self):
        print("Hello")

def top_level_func():
    return 42
"""
    symbols = parser.chunk_file(test_code, "test.py")
    for s in symbols:
        print(f"Found {s['type']}: {s['name']} (Lines {s['start_line']}-{s['end_line']})")

    sigs = parser.get_signatures(test_code, "python")
    for s in sigs:
        print(f"Signature: {s}")
