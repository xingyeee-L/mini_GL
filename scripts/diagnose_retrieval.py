"""Run the expanded synthetic retrieval benchmark and explain every miss."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from mini_gl.ingestion import IngestionService
from mini_gl.retrieval.evaluation import EvaluationQuery, diagnose, evaluate
from mini_gl.retrieval.lexical import LexicalSearchService
from mini_gl.storage.sqlite import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic" / "retrieval_benchmark.json"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    benchmark = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        allowed = base / "allowed"
        restricted = base / "restricted"
        allowed.mkdir()
        restricted.mkdir()
        for document in benchmark["documents"]:
            target = allowed if document["scope"] == "allowed" else restricted
            (target / document["title"]).write_text(document["content"], encoding="utf-8")
        with SQLiteStore(base / "benchmark.sqlite3") as store:
            ingestion = IngestionService(store)
            allowed_source = ingestion.register(allowed)
            restricted_source = ingestion.register(restricted)
            ingestion.sync(allowed_source.source_id)
            ingestion.sync(restricted_source.source_id)
            search = LexicalSearchService(store)
            search.rebuild()
            cases = [
                EvaluationQuery(
                    item["query"],
                    frozenset(item["relevant"]),
                    frozenset(item.get("forbidden", [])),
                )
                for item in benchmark["queries"]
            ]
            report = {
                "metrics": evaluate(search, cases, source_id=allowed_source.source_id),
                "queries": diagnose(search, cases, source_id=allowed_source.source_id),
            }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
