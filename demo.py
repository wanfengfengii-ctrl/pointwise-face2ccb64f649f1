import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from intake.catalog import AcceptedCatalog
from intake.receive import receive
from issue.registry import IssueRegistry
from issue.reissue import release, release_highest
from reports.history import fetch
from reports.publication import PublicationStore
from reports.snapshots import encode_snapshot
from review.assessment import assess, assess_highest
from survey.lines import LineStore, SurveyLine
from survey.revisions import RevisionStore


def issue_batch(revisions, registry, line_id, name, batch):
    revision = revisions.record(line_id, batch['book'], batch['segments'])
    return release(revisions, registry, revision, f'shift-{name}')


def issue_highest_batch(revisions, registry, line_id, name, batch):
    revision = revisions.record(line_id, batch['book'], batch['segments'])
    return release_highest(revisions, registry, revision, f'shift-{name}')


def review_summary(report):
    data = json.loads(encode_snapshot(report))
    block = data['block']
    return {
        'status': data['status'],
        'chainage': block['chainage'] if block is not None else None,
        'segments': [item['segment_id'] for item in block['supports']] if block is not None else [],
        'earlier_covered': data['earlier_covered'],
        'gaps': data['coverage']['gaps'],
    }


def highest_scenario(sample):
    """Issue the highest measured surface as V2, review it, and refetch later."""
    line = SurveyLine(**sample['line'])
    with TemporaryDirectory(prefix='jiangwan-highest-') as directory:
        station_path = Path(directory) / 'station.sqlite'
        offline_path = Path(directory) / 'offline.sqlite'
        with closing(sqlite3.connect(station_path)) as station:
            lines = LineStore(station)
            lines.initialize([line])
            revisions = RevisionStore(station, lines)
            revisions.initialize()
            registry = IssueRegistry(station)
            registry.initialize()
            issued = [
                issue_highest_batch(revisions, registry, line.line_id, name, sample['batches'][name])
                for name in ('A', 'B')
            ]
        with closing(sqlite3.connect(offline_path)) as offline:
            catalog = AcceptedCatalog(offline)
            archive = PublicationStore(offline)
            catalog.initialize()
            archive.initialize()
            selected = [receive(catalog, entry.payload) for entry in issued]
            outcome = assess_highest(
                catalog, archive, request_id='highest-morning', line_id=line.line_id,
                bundle_ids=selected, **sample['window'],
            )
        with closing(sqlite3.connect(offline_path)) as reopened:
            restored = fetch(reopened, outcome.report.report_id)
    summary = review_summary(outcome.report)
    if summary != {'status': 'blocked_pending', 'chainage': '4', 'segments': ['B'],
                   'earlier_covered': False,
                   'gaps': [{'start': '1', 'end': '4', 'left_closed': True, 'right_closed': False}]}:
        raise RuntimeError(f'HIGHEST_SURFACE_MISMATCH actual={summary!r}')
    if restored != (outcome.report, outcome.receipt):
        raise RuntimeError('HIGHEST_SURFACE_HISTORY_MISMATCH: reopened archive differs')
    print('POINTWISE_HIGHEST ' + json.dumps({
        'status': summary['status'], 'chainage': summary['chainage'],
        'segments': summary['segments'], 'gaps': summary['gaps'],
        'receipt_id': outcome.receipt.receipt_id,
    }, sort_keys=True, ensure_ascii=False))
    return summary


def main():
    sample_path = Path(__file__).resolve().parent / 'samples' / 'shift.json'
    sample = json.loads(sample_path.read_text(encoding='utf-8'))
    line = SurveyLine(**sample['line'])
    with TemporaryDirectory(prefix='jiangwan-shift-') as directory:
        station_path = Path(directory) / 'station.sqlite'
        offline_path = Path(directory) / 'offline.sqlite'
        with closing(sqlite3.connect(station_path)) as station:
            lines = LineStore(station)
            lines.initialize([line])
            revisions = RevisionStore(station, lines)
            revisions.initialize()
            registry = IssueRegistry(station)
            registry.initialize()
            a = issue_batch(revisions, registry, line.line_id, 'A', sample['batches']['A'])
            b = issue_batch(revisions, registry, line.line_id, 'B', sample['batches']['B'])
        with closing(sqlite3.connect(offline_path)) as offline:
            catalog = AcceptedCatalog(offline)
            archive = PublicationStore(offline)
            catalog.initialize()
            archive.initialize()
            selected = [receive(catalog, entry.payload) for entry in (a, b)]
            initial = assess(catalog, archive, request_id='morning', line_id=line.line_id,
                             bundle_ids=selected, **sample['window'])
            with closing(sqlite3.connect(station_path)) as station:
                revisions = RevisionStore(station, LineStore(station))
                c = issue_batch(revisions, IssueRegistry(station), line.line_id, 'C', sample['batches']['C'])
            selected.append(receive(catalog, c.payload))
            supplemented = assess(catalog, archive, request_id='supplement', line_id=line.line_id,
                                  bundle_ids=selected, **sample['window'])
        with closing(sqlite3.connect(offline_path)) as reopened:
            old_history = fetch(reopened, initial.report.report_id)
            new_history = fetch(reopened, supplemented.report.report_id)

    expected = [
        {'status': 'blocked_pending', 'chainage': '4', 'segments': ['B'], 'earlier_covered': False,
         'gaps': [{'start': '1', 'end': '4', 'left_closed': True, 'right_closed': False}]},
        {'status': 'blocked_confirmed', 'chainage': '4', 'segments': ['B'], 'earlier_covered': True, 'gaps': []},
    ]
    actual = [review_summary(initial.report), review_summary(supplemented.report)]
    downstream_expected = {'reports': expected, 'receipt_ids': ['ACK:RPT:morning', 'ACK:RPT:supplement'],
                           'original_pairs': [True, True]}
    downstream_actual = {
        'reports': [review_summary(old_history[0]), review_summary(new_history[0])],
        'receipt_ids': [old_history[1].receipt_id, new_history[1].receipt_id],
        'original_pairs': [old_history == (initial.report, initial.receipt),
                           new_history == (supplemented.report, supplemented.receipt)],
    }
    if actual != expected or downstream_actual != downstream_expected:
        raise RuntimeError(f'SUPPLEMENT_HANDOVER_MISMATCH actual={actual!r} history={downstream_actual!r}')
    scenario = {
        'case_id': 'v5',
        'input': {'window': sample['window'], 'batches': sample['batches'],
                  'selected': [selected[:2], selected]},
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': ['survey/revisions.py', 'issue/profiles.py', 'issue/reissue.py', 'intake/receive.py',
                       'review/intersection.py', 'review/coverage.py', 'review/assessment.py',
                       'reports/publication.py', 'reports/history.py'],
        'oracle': '0 < 1 on A and C, 2 >= 1 on B from metre 4. A alone leaves [1,4); A and C cover [0,4).',
    }
    print('POINTWISE_SCENARIO ' + json.dumps(scenario, sort_keys=True, ensure_ascii=False))
    highest_scenario(sample)


if __name__ == '__main__':
    main()
