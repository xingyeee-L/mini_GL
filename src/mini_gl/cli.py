"""Command-line interface for phase-one ingestion."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from mini_gl.ingestion import IngestionService
from mini_gl.security.paths import DEFAULT_MAX_DEPTH, DEFAULT_MAX_FILE_SIZE
from mini_gl.storage.sqlite import SQLiteStore

DEFAULT_DB = Path("data/mini_gl.sqlite3")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mini_gl")
    subparsers = parser.add_subparsers(dest="command", required=True)
    register = subparsers.add_parser("register", help="Register an authorized local root")
    register.add_argument("root", type=Path)
    register.add_argument("--max-size", type=int, default=DEFAULT_MAX_FILE_SIZE)
    register.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    sync = subparsers.add_parser("sync", help="Synchronize one registered source")
    sync.add_argument("source_id")
    status = subparsers.add_parser("status", help="Show privacy-safe ingestion status")
    status.add_argument("source_id", nargs="?")
    index = subparsers.add_parser("index", help="Rebuild the local lexical index")
    index.add_argument("source_id", nargs="?")
    search = subparsers.add_parser("search", help="Search indexed documents")
    search.add_argument("query")
    search.add_argument("--source-id")
    search.add_argument("--file-type", choices=(".txt", ".md"))
    search.add_argument("--updated-after")
    search.add_argument("--limit", type=int, default=10)
    serve = subparsers.add_parser("serve", help="Open the local visual acceptance console")
    serve.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost"))
    serve.add_argument("--port", type=int, default=8765)
    for command in (register, sync, status, index, search, serve):
        command.add_argument("--db", type=Path, default=DEFAULT_DB)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "serve":
            from mini_gl.web import serve

            serve(args.db, args.host, args.port)
            return 0
        with SQLiteStore(args.db) as store:
            service = IngestionService(store)
            if args.command == "register":
                source = service.register(args.root, args.max_size, args.max_depth)
                print(json.dumps({"source_id": source.source_id, "root": str(source.root_path)}))
            elif args.command == "sync":
                print(json.dumps(service.sync(args.source_id), sort_keys=True))
            elif args.command == "status":
                print(json.dumps(store.status(args.source_id), ensure_ascii=False, indent=2))
            else:
                from mini_gl.retrieval.lexical import LexicalSearchService

                retrieval = LexicalSearchService(store)
                if args.command == "index":
                    print(json.dumps(retrieval.rebuild(args.source_id), sort_keys=True))
                else:
                    result = retrieval.search(
                        args.query,
                        source_id=args.source_id,
                        file_type=args.file_type,
                        updated_after=args.updated_after,
                        limit=args.limit,
                    )
                    print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}))
        return 1
