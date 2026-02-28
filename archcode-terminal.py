import argparse
import sys
from typing import Optional

from engine import ArchCodeEngine


class ArchCodeTerminalCLI:
    """Class-based CLI runner for indexing and semantic code search."""

    def __init__(self):
        self.parser = self._build_parser()

    @staticmethod
    def _build_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="ArchCode Terminal - Professional Code Indexing"
        )
        parser.add_argument("--index", type=str, help="Directory to index")
        parser.add_argument("--search", type=str, help="Query to search")
        parser.add_argument("--limit", type=int, default=5, help="Number of results")
        parser.add_argument(
            "--key",
            type=str,
            help="Voyage AI API Key (optional if VOYAGE_API_KEY is in envy)",
        )
        return parser

    def _render_search_results(self, query: str, results: list[dict]) -> None:
        print(f"\n🔍 Searching for: [bold]{query}[/bold]")

        if not results:
            print("No results found.")
            return

        for i, res in enumerate(results):
            print(
                f"\n[{i+1}] {res['file_path']} "
                f"(Lines {res['start_line']}-{res['end_line']})"
            )
            print(f"Symbol: {res['symbol_name']} | Score: {res['score']:.4f}")
            print("-" * 40)
            content_lines = res["content"].split("\n")
            preview = "\n".join(content_lines[:5])
            print(preview)
            if len(content_lines) > 5:
                print("...")

    def run(self, argv: Optional[list[str]] = None) -> int:
        args = self.parser.parse_args(argv)

        try:
            engine = ArchCodeEngine(api_key=args.key)

            if args.index:
                engine.index_directory(args.index)

            if args.search:
                results = engine.search(args.search, limit=args.limit)
                self._render_search_results(args.search, results)

            if not args.index and not args.search:
                self.parser.print_help()

            return 0

        except ValueError as ve:
            print(f"❌ Configuration Error: {ve}")
            return 1
        except Exception as e:
            print(f"❌ An error occurred: {e}")
            return 1


def main() -> None:
    cli = ArchCodeTerminalCLI()
    raise SystemExit(cli.run())


if __name__ == "__main__":
    main()
