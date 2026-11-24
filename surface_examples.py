"""Input fixtures and expected observations for the highest-surface handover."""

import json
import sqlite3
from contextlib import closing

from intake.catalog import AcceptedCatalog
from intake.receive import receive
from issue.registry import IssueRegistry
from issue.reissue import release
from reports.history import fetch
from reports.publication import PublicationStore
from review.assessment import assess
from survey.lines import LineStore
from survey.revisions import RevisionStore
from tests.fixtures import LINE, book, segment


BATCHES = {
    "main": (
        ("A", 0, 4, 0, 4, True, "pass"),
        ("B", 0, 2, 3, 3, False, "pass"),
        ("C", 2, 4, 2, 2, True, "pass"),
        ("D", 0, 4, -4, 4, True, "pass"),
        ("F", 0, 4, 1, 1, True, "pass"),
    ),
    "cross": (
        ("T", 0, 3, "3/2", "3/2", True, "pass"),
        ("X", 0, 3, 0, 3, True, "pass"),
        ("Y", 0, 3, 3, 0, True, "pass"),
    ),
    "higher": (("G", 1, 2, 2, 2, True, "pass"),),
    "gap": (("P", 0, 1, 0, 0, False, "pass"), ("Q", 2, 3, 2, 2, True, "pass")),
    "missing": (("M", 0, 3, 99, 99, True, "fail"),),
}

# Each result is (status, first point, source segment ids, gaps).
# Each gap is (start, end, left closed, right closed).
CASES = (
    ("edge-low", ("main",), (2, 2, 1, 1), ("blocked_confirmed", "2", ("A", "C"), ())),
    ("edge-high", ("main",), (2, 2, "5/2", "5/2"), ("clear", None, (), ())),
    ("end", ("main",), (0, 4, 4, 4), ("blocked_confirmed", "4", ("A", "D"), ())),
    ("cross", ("cross",), ("3/2", "3/2", "3/2", "3/2"),
     ("blocked_confirmed", "3/2", ("T", "X", "Y"), ())),
    ("cross-higher", ("cross", "higher"), ("3/2", "3/2", "3/2", "3/2"),
     ("blocked_confirmed", "3/2", ("G",), ())),
    ("inside", ("cross",), ("5/4", 3, "7/3", "7/3"), ("blocked_confirmed", "7/3", ("X",), ())),
    ("gap", ("gap",), (0, 3, 1, 1), ("blocked_pending", "2", ("Q",), (("1", "2", True, False),))),
    ("missing", ("missing",), (0, 3, 1, 1), ("needs_survey", None, (), (("0", "3", True, True),))),
)

V1_SOURCES = {"edge-low": ("A", "C", "F"), "cross-higher": ("T", "X", "Y", "G")}


def record_samples(revisions):
    revision_ids = {}
    for batch, rows in BATCHES.items():
        observations = [
            segment(name, start, end, left, right, terminal=terminal, quality=quality)
            for name, start, end, left, right, terminal, quality in rows
        ]
        revision_ids[batch] = revisions.record(LINE.line_id, book(*(row[0] for row in rows)), observations)
    return revision_ids


def check_v1():
    with closing(sqlite3.connect(":memory:")) as station:
        lines = LineStore(station)
        lines.initialize([LINE])
        revisions = RevisionStore(station, lines)
        revisions.initialize()
        registry = IssueRegistry(station)
        registry.initialize()
        entries = {
            batch: release(revisions, registry, revision, f"baseline-surface-{batch}")
            for batch, revision in record_samples(revisions).items()
        }
    with closing(sqlite3.connect(":memory:")) as offline:
        catalog = AcceptedCatalog(offline)
        archive = PublicationStore(offline)
        catalog.initialize()
        archive.initialize()
        ids = {batch: receive(catalog, entry.payload) for batch, entry in entries.items()}
        for name, batches, sight, expected_v2 in CASES:
            start, end, left, right = sight
            result = assess(catalog, archive, request_id=name, line_id=LINE.line_id,
                            bundle_ids=[ids[batch] for batch in batches],
                            start=start, end=end, left_height=left, right_height=right)
            report = result.report
            block = report.block
            actual_gaps = tuple((str(gap.start), str(gap.end), gap.left_closed, gap.right_closed)
                                for gap in report.coverage.gaps)
            actual = (report.status, str(block.chainage) if block else None,
                      tuple(item.segment_id for item in block.supports) if block else (), actual_gaps)
            status, hit, sources, gaps = expected_v2
            expected = (status, hit, V1_SOURCES.get(name, sources), gaps)
            if actual != expected or fetch(offline, report.report_id) != (report, result.receipt):
                raise AssertionError(f"{name}: expected {expected!r}, got {actual!r} or different stored result")
            print("POINTWISE_SURFACE_V1 " + json.dumps({"case": name, "actual": actual}, ensure_ascii=False))


if __name__ == "__main__":
    check_v1()
