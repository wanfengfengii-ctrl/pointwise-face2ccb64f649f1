"""Runtime verification for the highest-surface handover (V2).

``check_project.py`` runs the full unittest suite; this script adds the
end-to-end highest-surface checks the runtime manifest expects: issuance
disclosure, source-severed review, rejection of bad/foreign bundles, retry after
a failed signed publication, and pick-up under the original number after
reopening the offline archive.  It exits non-zero on any mismatch.
"""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from intake.catalog import AcceptedCatalog
from intake.receive import receive
from issue.envelope import decode_v2_envelope, fingerprint_body
from issue.registry import IssueRegistry
from issue.reissue import release, release_highest
from reports.history import fetch
from reports.publication import PublicationStore
from reports.snapshots import encode_snapshot
from review.assessment import assess, assess_highest
from survey.lines import LineStore, SurveyLine
from survey.revisions import RevisionStore

LINE = SurveyLine('JW-01', '江湾东堤', '东堤零桩')

BATCH = {
    'book': {'id': '核验簿', 'entries': {name: f'{name} 的原始记录' for name in 'ABCDEF'}},
    'segments': [
        {'segment_id': 'A', 'start': '0', 'end': '4', 'left_height': '0', 'right_height': '4',
         'terminal': True, 'quality': 'pass', 'instrument_ok': True,
         'source': {'book': '核验簿', 'entry': 'A'}},
        {'segment_id': 'B', 'start': '0', 'end': '2', 'left_height': '3', 'right_height': '3',
         'terminal': False, 'quality': 'pass', 'instrument_ok': True,
         'source': {'book': '核验簿', 'entry': 'B'}},
        {'segment_id': 'C', 'start': '2', 'end': '4', 'left_height': '2', 'right_height': '2',
         'terminal': True, 'quality': 'pass', 'instrument_ok': True,
         'source': {'book': '核验簿', 'entry': 'C'}},
        {'segment_id': 'D', 'start': '0', 'end': '4', 'left_height': '-4', 'right_height': '4',
         'terminal': True, 'quality': 'pass', 'instrument_ok': True,
         'source': {'book': '核验簿', 'entry': 'D'}},
        {'segment_id': 'F', 'start': '0', 'end': '4', 'left_height': '1', 'right_height': '1',
         'terminal': True, 'quality': 'pass', 'instrument_ok': True,
         'source': {'book': '核验簿', 'entry': 'F'}},
    ],
}


def _fail(message):
    print(f'HIGHEST_VERIFY FAIL {message}')
    raise SystemExit(1)


def _summary(report):
    data = json.loads(encode_snapshot(report))
    block = data['block']
    return (data['status'], block['chainage'] if block else None,
            tuple(item['segment_id'] for item in block['supports']) if block else (),
            tuple((gap['start'], gap['end'], gap['left_closed'], gap['right_closed'])
                  for gap in data['coverage']['gaps']))


def _station_phase(station_path):
    with closing(sqlite3.connect(station_path)) as station:
        lines = LineStore(station)
        lines.initialize([LINE])
        revisions = RevisionStore(station, lines)
        revisions.initialize()
        registry = IssueRegistry(station)
        registry.initialize()
        fixed = revisions.record(LINE.line_id, BATCH['book'], BATCH['segments'])
        entry = release_highest(revisions, registry, fixed, 'verify')
        if release_highest(revisions, registry, fixed, 'verify') != entry:
            _fail('same-number V2 reissue did not return the original bytes')
        if registry.get(entry.bundle_id) != entry:
            _fail('V2 inventory lookup by bundle id differs')
        surface = decode_v2_envelope(entry.payload).surface
        disclosed = {support.segment_id for span in surface.spans for support in span.supports}
        disclosed |= {support.segment_id for point in surface.points for support in point.supports}
        if 'F' in disclosed:
            _fail('low segment F was disclosed as highest-surface evidence')
        if 'F 的原始记录'.encode('utf-8') in entry.payload:
            _fail('station-only measurement-book entry leaked into the bundle')
        v1_revision = revisions.record(LINE.line_id, BATCH['book'], BATCH['segments'])
        v1 = release(revisions, registry, v1_revision, 'verify-v1')
    return entry, v1


def _offline_phase(offline_path, entry, v1):
    with closing(sqlite3.connect(offline_path)) as offline:
        catalog = AcceptedCatalog(offline)
        archive = PublicationStore(offline)
        catalog.initialize()
        archive.initialize()
        accepted = receive(catalog, entry.payload)
        receive(catalog, v1.payload)
        try:
            assess_highest(catalog, archive, request_id='bad-mixed', line_id=LINE.line_id,
                           bundle_ids=[accepted, 'B:verify-v1'], start=0, end=4,
                           left_height=1, right_height=1)
        except ValueError:
            pass
        else:
            _fail('mixed V1 bundle was accepted into a highest-surface review')
        try:
            assess_highest(catalog, archive, request_id='bad-line', line_id='JW-99',
                           bundle_ids=[accepted], start=0, end=4, left_height=1, right_height=1)
        except ValueError:
            pass
        else:
            _fail('wrong-line selection was accepted')

        def mutate(mutator):
            data = json.loads(entry.payload)
            mutator(data)
            data['digest'] = fingerprint_body(data['body'])
            return json.dumps(data).encode('utf-8')

        broken_payloads = (
            b'not json',
            json.dumps({**json.loads(entry.payload), 'digest': '0' * 64}).encode('utf-8'),
            mutate(lambda data: data['body']['surface']['spans'][0].update({'left_height': '42'})),
        )
        for broken in broken_payloads:
            try:
                receive(catalog, broken)
            except ValueError:
                pass
            else:
                _fail('a broken or conflicting V2 bundle was accepted')

        low = assess_highest(catalog, archive, request_id='low', line_id=LINE.line_id,
                             bundle_ids=[accepted], start=2, end=2, left_height=1, right_height=1)
        if _summary(low.report)[:3] != ('blocked_confirmed', '2', ('A', 'C')):
            _fail(f'2 m at height 1 signed {_summary(low.report)[:3]!r}')
        clear = assess_highest(catalog, archive, request_id='clear', line_id=LINE.line_id,
                               bundle_ids=[accepted], start=2, end=2,
                               left_height='5/2', right_height='5/2')
        if _summary(clear.report)[:2] != ('clear', None):
            _fail(f'2 m at height 5/2 did not sign clear: {_summary(clear.report)[:2]!r}')
        end = assess_highest(catalog, archive, request_id='end', line_id=LINE.line_id,
                             bundle_ids=[accepted], start=0, end=4, left_height=4, right_height=4)
        if _summary(end.report)[:3] != ('blocked_confirmed', '4', ('A', 'D')):
            _fail(f'4 m horizontal sight signed {_summary(end.report)[:3]!r}')
        assess(catalog, archive, request_id='v1-still-runs', line_id=LINE.line_id,
               bundle_ids=['B:verify-v1'], start=0, end=4, left_height=1, right_height=1)

        offline.execute('''
            CREATE TRIGGER fail_receipt BEFORE INSERT ON report_receipts
            BEGIN SELECT RAISE(ABORT, 'receipt storage unavailable'); END
        ''')
        try:
            assess_highest(catalog, archive, request_id='retry', line_id=LINE.line_id,
                           bundle_ids=[accepted], start=0, end=4, left_height=1, right_height=1)
        except sqlite3.IntegrityError:
            pass
        else:
            _fail('failed publication did not raise')
        if offline.execute('SELECT count(*) FROM publications WHERE request_id = ?',
                           ('retry',)).fetchone()[0]:
            _fail('failed publication left a report behind')
        offline.execute('DROP TRIGGER fail_receipt')
        retried = assess_highest(catalog, archive, request_id='retry', line_id=LINE.line_id,
                                 bundle_ids=[accepted], start=0, end=4, left_height=1, right_height=1)
        if retried.report.report_id != 'RPT:retry':
            _fail('retry did not publish under the original request number')
    return low, end, retried


def run():
    directory = TemporaryDirectory(prefix='jiangwan-verify-')
    try:
        station_path = Path(directory.name) / 'station.sqlite'
        offline_path = Path(directory.name) / 'offline.sqlite'
        entry, v1 = _station_phase(station_path)
        low, end, retried = _offline_phase(offline_path, entry, v1)
        with closing(sqlite3.connect(offline_path)) as reopened:
            restored = fetch(reopened, retried.report.report_id)
            v1_report = fetch(reopened, 'RPT:v1-still-runs')
        if restored != (retried.report, retried.receipt):
            _fail('reopened archive did not return the original report and receipt')
        if v1_report[1].receipt_id != 'ACK:RPT:v1-still-runs':
            _fail('original V1 report could not be picked up after reopening')
    finally:
        directory.cleanup()
    print('HIGHEST_VERIFY PASS '
          + json.dumps({'bundle': entry.bundle_id, 'report': retried.report.report_id,
                        'receipt': retried.receipt.receipt_id,
                        'low': _summary(low.report), 'end': _summary(end.report)},
                       sort_keys=True, ensure_ascii=False))


if __name__ == '__main__':
    run()
