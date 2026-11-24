import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from intake.catalog import AcceptedCatalog
from intake.receive import receive
from issue.registry import IssueRegistry
from issue.reissue import release
from reports.publication import PublicationStore
from review.assessment import assess
from survey.lines import LineStore, SurveyLine
from survey.revisions import RevisionStore


LINE = SurveyLine('JW-01', '江湾东堤', '东堤零桩')
OTHER = SurveyLine('JW-02', '江湾西堤', '西堤零桩')


def segment(name, start, end, left, right=None, *, terminal=False, quality='pass', instrument_ok=True):
    return {
        'segment_id': name, 'start': start, 'end': end, 'left_height': left,
        'right_height': left if right is None else right,
        'terminal': terminal, 'quality': quality, 'instrument_ok': instrument_ok,
        'source': {'book': 'field-book', 'entry': name},
    }


def book(*names):
    return {'id': 'field-book', 'entries': {name: f'Field note for {name}' for name in names}}


class WorkflowCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='jiangwan-tests-')
        self.addCleanup(directory.cleanup)
        self.station_path = Path(directory.name) / 'station.sqlite'
        self.offline_path = Path(directory.name) / 'offline.sqlite'
        self.open_station()
        self.open_offline()

    def open_station(self):
        self.station = sqlite3.connect(self.station_path)
        self.addCleanup(self.station.close)
        self.lines = LineStore(self.station)
        self.lines.initialize([LINE])
        self.revisions = RevisionStore(self.station, self.lines)
        self.revisions.initialize()
        self.registry = IssueRegistry(self.station)
        self.registry.initialize()

    def open_offline(self):
        self.offline = sqlite3.connect(self.offline_path)
        self.addCleanup(self.offline.close)
        self.catalog = AcceptedCatalog(self.offline)
        self.catalog.initialize()
        self.archive = PublicationStore(self.offline)
        self.archive.initialize()

    def record(self, *rows, line=LINE.line_id):
        return self.revisions.record(line, book(*(row['segment_id'] for row in rows)), rows)

    def issue(self, name, *rows, line=LINE.line_id):
        revision = self.record(*rows, line=line)
        return release(self.revisions, self.registry, revision, name)

    def accept(self, *entries):
        return tuple(receive(self.catalog, entry.payload) for entry in entries)

    def inspect(self, request, bundle_ids, start=0, end=6, *, left=1, right=None, line=LINE.line_id):
        return assess(self.catalog, self.archive, request_id=request, line_id=line, bundle_ids=bundle_ids,
                      start=start, end=end, left_height=left, right_height=left if right is None else right)

    def station_counts(self):
        return (
            self.station.execute('SELECT count(*) FROM survey_revisions').fetchone()[0],
            self.station.execute('SELECT count(*) FROM issued_bundles').fetchone()[0],
        )

    def offline_counts(self):
        return (
            self.offline.execute('SELECT count(*) FROM publications').fetchone()[0],
            self.offline.execute('SELECT count(*) FROM report_receipts').fetchone()[0],
        )

    def gap_bundle_pair(self):
        a = self.issue('early', segment('A', 0, 1, 0))
        b = self.issue('late', segment('B', 4, 6, 2, terminal=True))
        return a, b
