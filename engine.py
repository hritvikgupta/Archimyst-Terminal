"""Backward-compatible engine module.

This module preserves historical imports while delegating implementation
into the class-based core service layer.
"""

from core.search.engine_service import ArchCodeEngine, ArchCodeSearchEngineService


__all__ = ["ArchCodeEngine", "ArchCodeSearchEngineService"]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ArchCode Terminal Indexer")
    parser.add_argument("--index", type=str, help="Directory to index")
    parser.add_argument("--search", type=str, help="Query to search")
    parser.add_argument("--limit", type=int, default=5, help="Number of results")

    args = parser.parse_args()

    try:
        engine = ArchCodeEngine()

        if args.index:
            engine.index_directory(args.index)

        if args.search:
            print(f"\nSearching for: '{args.search}'")
            results = engine.search(args.search, limit=args.limit)

            for i, res in enumerate(results):
                print(f"\n--- Result {i+1} (Score: {res['score']:.4f}) ---")
                print(
                    f"File: {res['file_path']} (Lines {res['start_line']}-{res['end_line']})"
                )
                print(f"Symbol: {res['symbol_name']}")
                print("-" * 20)
                content_lines = res["content"].split("\n")
                preview = "\n".join(content_lines[:5])
                print(preview)
                if len(content_lines) > 5:
                    print("...")

    except ValueError as ve:
        print(f"Configuration Error: {ve}")
    except Exception as e:
        print(f"An error occurred: {e}")
