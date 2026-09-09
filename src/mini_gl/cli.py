"""Command-line interface for phase-one ingestion."""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
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
    resume = subparsers.add_parser(
        "resume", help="Restart a failed or interrupted sync from the committed snapshot"
    )
    resume.add_argument("source_id")
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
    vector_index = subparsers.add_parser(
        "vector-index", help="Build the offline engineering vector index"
    )
    vector_index.add_argument("source_id")
    vector_index.add_argument(
        "--provider",
        choices=("deterministic", "bge-small-zh", "multilingual-e5"),
        default="deterministic",
    )
    incremental = subparsers.add_parser(
        "index-sync", help="Incrementally update lexical and local vector indexes"
    )
    incremental.add_argument("source_id")
    incremental.add_argument(
        "--provider",
        choices=("deterministic", "bge-small-zh", "multilingual-e5"),
        default="deterministic",
    )
    hybrid = subparsers.add_parser("hybrid-search", help="Run local lexical/vector fusion")
    hybrid.add_argument("source_id")
    hybrid.add_argument("query")
    hybrid.add_argument("--limit", type=int, default=10)
    hybrid.add_argument(
        "--provider",
        choices=("deterministic", "bge-small-zh", "multilingual-e5"),
        default="deterministic",
    )
    ask = subparsers.add_parser("ask", help="Ask a grounded question using a local chat model")
    ask.add_argument("source_id")
    ask.add_argument("query")
    ask.add_argument("--model", required=True)
    ask.add_argument(
        "--endpoint", default="http://127.0.0.1:11434/v1/chat/completions"
    )
    ask.add_argument("--limit", type=int, default=10)
    ask.add_argument("--file-type", choices=(".txt", ".md"))
    ask.add_argument("--updated-after")
    ask.add_argument(
        "--provider",
        choices=("deterministic", "bge-small-zh", "multilingual-e5"),
        default="bge-small-zh",
    )
    serve = subparsers.add_parser("serve", help="Open the local knowledge workspace")
    serve.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost"))
    serve.add_argument("--port", type=int, default=8765)
    chat_import = subparsers.add_parser(
        "chat-import", help="Import a provider-neutral versioned chat JSON export"
    )
    chat_import.add_argument("path", type=Path)
    chat_import.add_argument(
        "--confirm-authorized",
        action="store_true",
        help="Confirm that you are authorized to use this export",
    )
    chat_convert = subparsers.add_parser(
        "chat-convert", help="Convert a synthetic QQ/WeChat export to neutral JSON"
    )
    chat_convert.add_argument("format", choices=("qq", "wechat"))
    chat_convert.add_argument("source", type=Path)
    chat_convert.add_argument("destination", type=Path)
    backup = subparsers.add_parser("backup", help="Create a verified SQLite snapshot")
    backup.add_argument("destination", type=Path)
    restore = subparsers.add_parser("restore", help="Restore a snapshot to a new database path")
    restore.add_argument("backup", type=Path)
    restore.add_argument("destination", type=Path)
    revoke = subparsers.add_parser(
        "revoke", help="Remove a source registration and all derived application data"
    )
    revoke.add_argument("source_id")
    revoke.add_argument("--confirm", required=True)
    benchmark = subparsers.add_parser(
        "benchmark-ingestion", help="Run a bounded synthetic ingestion benchmark"
    )
    benchmark.add_argument("--files", type=int, default=500)
    benchmark.add_argument("--file-size", type=int, default=1024)
    soak = subparsers.add_parser(
        "benchmark-soak", help="Run repeated synthetic synchronization and indexing"
    )
    soak.add_argument("--cycles", type=int, default=20)
    soak.add_argument("--files", type=int, default=100)
    commands = (
        register,
        sync,
        resume,
        status,
        index,
        search,
        vector_index,
        incremental,
        hybrid,
        ask,
        serve,
        chat_import,
        chat_convert,
        backup,
        revoke,
    )
    for command in commands:
        command.add_argument("--db", type=Path, default=DEFAULT_DB)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "serve":
            from mini_gl.web import serve

            serve(args.db, args.host, args.port)
            return 0
        if args.command == "chat-convert":
            from mini_gl.adapters import convert_export

            print(
                json.dumps(
                    convert_export(args.format, args.source, args.destination),
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command in {"backup", "restore"}:
            from mini_gl.maintenance import backup_database, restore_database

            result = (
                backup_database(args.db, args.destination)
                if args.command == "backup"
                else restore_database(args.backup, args.destination)
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "benchmark-ingestion":
            from mini_gl.benchmark import run_ingestion_benchmark

            print(
                json.dumps(
                    run_ingestion_benchmark(args.files, args.file_size),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "benchmark-soak":
            from mini_gl.benchmark import run_soak_benchmark

            print(
                json.dumps(
                    run_soak_benchmark(args.cycles, args.files),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        with SQLiteStore(args.db) as store:
            service = IngestionService(store)
            if args.command == "chat-import":
                from mini_gl.chat_import import ChatImportService

                print(
                    json.dumps(
                        ChatImportService(store).import_file(
                            args.path, authorized=args.confirm_authorized
                        ),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            elif args.command == "register":
                source = service.register(args.root, args.max_size, args.max_depth)
                print(json.dumps({"source_id": source.source_id, "root": str(source.root_path)}))
            elif args.command == "sync":
                print(json.dumps(service.sync(args.source_id), sort_keys=True))
            elif args.command == "resume":
                print(json.dumps(service.resume(args.source_id), sort_keys=True))
            elif args.command == "status":
                print(json.dumps(store.status(args.source_id), ensure_ascii=False, indent=2))
            elif args.command == "revoke":
                if args.confirm != args.source_id[-8:]:
                    raise ValueError("Confirmation must match the final 8 characters of source ID")
                print(json.dumps(store.revoke_source(args.source_id), sort_keys=True))
            elif args.command in {"index", "search"}:
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
            else:
                from mini_gl.indexing.embeddings import (
                    DeterministicLocalEmbedding,
                    EmbeddingProvider,
                    load_bge_provider,
                    load_e5_provider,
                )
                from mini_gl.retrieval.hybrid import HybridSearchService, TokenOverlapReranker
                from mini_gl.retrieval.lexical import LexicalSearchService
                from mini_gl.retrieval.vector import VectorSearchService

                lexical = LexicalSearchService(store)
                providers: dict[str, Callable[[], EmbeddingProvider]] = {
                    "bge-small-zh": load_bge_provider,
                    "multilingual-e5": load_e5_provider,
                    "deterministic": DeterministicLocalEmbedding,
                }
                provider = providers[args.provider]()
                vector = VectorSearchService(store, provider)
                if args.command == "vector-index":
                    print(json.dumps(vector.rebuild(args.source_id), sort_keys=True))
                elif args.command == "index-sync":
                    print(
                        json.dumps(
                            {
                                "lexical": lexical.sync(args.source_id),
                                "vector": vector.sync(args.source_id),
                            },
                            sort_keys=True,
                        )
                    )
                elif args.command == "hybrid-search":
                    results = HybridSearchService(
                        lexical, vector, TokenOverlapReranker()
                    ).search(args.query, args.source_id, args.limit)
                    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
                else:
                    from mini_gl.generation import LocalOpenAIChatModel, RAGService
                    from mini_gl.generation.context import ContextBuilder

                    hybrid_retrieval = HybridSearchService(
                        lexical, vector, TokenOverlapReranker()
                    )
                    model = LocalOpenAIChatModel(args.endpoint, args.model)
                    answer = RAGService(
                        hybrid_retrieval, ContextBuilder(store), model
                    ).answer(
                        args.query,
                        args.source_id,
                        limit=args.limit,
                        file_type=args.file_type,
                        updated_after=args.updated_after,
                    )
                    print(json.dumps(asdict(answer), ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}))
        return 1
