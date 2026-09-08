from __future__ import annotations

import unittest

from mini_gl.benchmark import run_ingestion_benchmark, run_soak_benchmark


class SyntheticBenchmarkTests(unittest.TestCase):
    def test_bounded_benchmark_reports_resources_and_preserves_sources(self) -> None:
        result = run_ingestion_benchmark(file_count=25, file_size=256)
        self.assertEqual(result["fixture"], "generated-synthetic-only")
        self.assertEqual(result["created"], 25)
        self.assertEqual(result["documents"], 25)
        self.assertEqual(result["lexical_chunks"], 25)
        self.assertTrue(result["source_unchanged"])
        self.assertGreater(result["wall_ms"], 0)
        self.assertGreater(result["python_peak_mib"], 0)

    def test_benchmark_rejects_unbounded_requests(self) -> None:
        for files, size in (
            (0, 1),
            (5_001, 1),
            (1, 0),
            (1, 10 * 1024 * 1024 + 1),
            (100, 1024 * 1024),
        ):
            with self.subTest(files=files, size=size), self.assertRaises(ValueError):
                run_ingestion_benchmark(files, size)

    def test_short_soak_keeps_integrity_and_sources(self) -> None:
        result = run_soak_benchmark(cycles=3, file_count=10)
        self.assertEqual(result["integrity"], "ok")
        self.assertEqual(result["cycles"], 3)
        self.assertTrue(result["source_unchanged"])
        self.assertGreater(result["events"], 0)

    def test_soak_rejects_unbounded_requests(self) -> None:
        for cycles, files in ((0, 1), (101, 1), (1, 0), (1, 501)):
            with self.subTest(cycles=cycles, files=files), self.assertRaises(ValueError):
                run_soak_benchmark(cycles, files)
