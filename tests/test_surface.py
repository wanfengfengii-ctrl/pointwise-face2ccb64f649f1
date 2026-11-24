import json
import sqlite3
from dataclasses import replace
from fractions import Fraction

from intake.receive import receive
from issue.envelope import (
    decode_v2_envelope, encode_v2_envelope, fingerprint_body,
)
from issue.reissue import release, release_highest
from issue.surface import HighestSurface, SurfacePoint, SurfaceSpan, SurfaceSupport
from reports.history import fetch
from review.window import ClippedSpan
from survey.provenance import SourceRef
from tests.fixtures import LINE, WorkflowCase, book, segment


def highest(case, request, *rows, line=LINE.line_id):
    revision = case.revisions.record(line, book(*(row['segment_id'] for row in rows)), rows)
    return release_highest(case.revisions, case.registry, revision, request)


class HighestSurfaceTests(WorkflowCase):
    def accept_highest(self, *entries):
        return tuple(receive(self.catalog, entry.payload) for entry in entries)

    def inspect_highest(self, request, bundle_ids, start=0, end=6, *, left=1, right=None,
                        line=LINE.line_id):
        from review.assessment import assess_highest
        return assess_highest(
            self.catalog, self.archive, request_id=request, line_id=line, bundle_ids=bundle_ids,
            start=start, end=end, left_height=left, right_height=left if right is None else right,
        )

    def main_bundle(self):
        rows = [
            segment('A', 0, 4, 0, 4, terminal=True),
            segment('B', 0, 2, 3, 3),
            segment('C', 2, 4, 2, 2, terminal=True),
            segment('D', 0, 4, -4, 4, terminal=True),
            segment('F', 0, 4, 1, 1, terminal=True),
        ]
        revision = self.revisions.record(LINE.line_id, book(*(row['segment_id'] for row in rows)), rows)
        return release_highest(self.revisions, self.registry, revision, 'h-main')

    # -- issuance -----------------------------------------------------------

    def test_release_is_version_two_and_discloses_only_high_surface(self):
        entry = self.main_bundle()
        self.assertEqual(json.loads(entry.payload)['version'], 2)
        self.assertEqual(decode_v2_envelope(entry.payload).revision_id, entry.revision_id)
        self.assertEqual(self.registry.get(entry.bundle_id), entry)
        self.assertNotIn(b'Field note for F', entry.payload)
        surface = decode_v2_envelope(entry.payload).surface
        self.assertEqual([(span.start, span.end) for span in surface.spans],
                         [(Fraction(0), Fraction(2)), (Fraction(2), Fraction(4))])
        self.assertEqual({point.chainage for point in surface.points},
                         {Fraction(2), Fraction(4)})
        self.assertEqual({support.segment_id for support in surface.points[0].supports} - {'A'},
                         {'C'})
        self.assertEqual({support.segment_id for support in surface.points[1].supports} - {'A'},
                         {'D'})

    def test_low_evidence_not_carried(self):
        entry = self.main_bundle()
        surface = decode_v2_envelope(entry.payload).surface
        disclosed = {support.segment_id for span in surface.spans for support in span.supports}
        disclosed |= {support.segment_id for point in surface.points for support in point.supports}
        self.assertNotIn('F', disclosed)
        self.assertEqual(disclosed, {'A', 'B', 'C', 'D'})

    def test_repeat_and_conflicting_release(self):
        original = highest(self, 'h-replay', segment('A', 0, 1, 0))
        repeated = release_highest(self.revisions, self.registry, original.revision_id, 'h-replay')
        self.assertEqual(repeated, original)
        self.station.close()
        self.open_station()
        self.assertEqual(release_highest(self.revisions, self.registry, original.revision_id, 'h-replay'),
                         original)
        self.assertEqual(self.station_counts(), (1, 1))
        corrected = self.revisions.correct(original.revision_id, book('A'), [segment('A', 0, 1, 2)])
        with self.assertRaisesRegex(ValueError, 'another revision'):
            release_highest(self.revisions, self.registry, corrected, 'h-replay')
        self.assertEqual(self.station_counts(), (2, 1))

    def test_version_namespace_is_shared(self):
        row = segment('A', 0, 1, 0)
        v1 = self.issue('shared', row)
        with self.assertRaisesRegex(ValueError, 'another issue version'):
            release_highest(self.revisions, self.registry, v1.revision_id, 'shared')
        self.assertEqual(self.registry.get(v1.bundle_id), v1)
        v2 = highest(self, 'shared-two', row)
        with self.assertRaisesRegex(ValueError, 'another issue version'):
            release(self.revisions, self.registry, v2.revision_id, 'shared-two')
        self.station_counts()

    def test_empty_surface_still_issues(self):
        entry = highest(self, 'h-missing', segment('M', 0, 3, 99, 99, quality='fail'))
        surface = decode_v2_envelope(entry.payload).surface
        self.assertEqual((surface.spans, surface.points), ((), ()))
        self.accept_highest(entry)

    # -- intake -------------------------------------------------------------

    def mutated(self, payload, mutate):
        data = json.loads(payload)
        mutate(data)
        data['digest'] = fingerprint_body(data['body'])
        return json.dumps(data).encode('utf-8')

    def test_accept_replay_and_rejects(self):
        entry = highest(self, 'h-intake', segment('A', 0, 6, 0, terminal=True))
        self.assertEqual(self.accept_highest(entry), (entry.bundle_id,))
        formatted = json.dumps(json.loads(entry.payload), indent=2).encode('utf-8')
        self.assertEqual(receive(self.catalog, formatted), entry.bundle_id)
        self.assertEqual(self.catalog.get(entry.bundle_id).payload, entry.payload)

        def bad_digest(data):
            data['body']['surface']['spans'][0]['left_height'] = '9'
        stale = json.loads(entry.payload)
        bad_digest(stale)
        stale['digest'] = fingerprint_body(stale['body'])
        stale['body']['surface']['spans'][0]['left_height'] = '8'
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            receive(self.catalog, json.dumps(stale).encode('utf-8'))
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            receive(self.catalog, json.dumps({**json.loads(entry.payload),
                                              'digest': '0' * 64}).encode('utf-8'))

        def bad_binding(data):
            data['body']['revision_id'] += 1
        with self.assertRaisesRegex(ValueError, 'body binding'):
            receive(self.catalog, self.mutated(entry.payload, bad_binding))

        def bad_domain(data):
            data['body']['surface']['spans'][0]['end'] = '0'
        with self.assertRaisesRegex(ValueError, 'invalid highest-surface span domain'):
            receive(self.catalog, self.mutated(entry.payload, bad_domain))
        self.assertEqual(self.catalog.get(entry.bundle_id).payload, entry.payload)

    def test_reject_conflicting_height_and_source(self):
        payload = self.main_bundle().payload

        def contradictory_point(data):
            data['body']['surface']['points'].append({
                'chainage': '3', 'height': '99',
                'supports': [{'segment_id': 'A', 'source': {'book': 'field-book', 'entry': 'A'}}],
            })
        with self.assertRaisesRegex(ValueError, 'conflicting highest height'):
            receive(self.catalog, self.mutated(payload, contradictory_point))

        def contradictory_source(data):
            data['body']['surface']['points'][0]['supports'].append({
                'segment_id': 'A', 'source': {'book': 'other-book', 'entry': 'A'},
            })
        with self.assertRaisesRegex(ValueError, 'conflicting original segment source'):
            receive(self.catalog, self.mutated(payload, contradictory_source))

        def duplicate_support(data):
            support = data['body']['surface']['spans'][0]['supports'][0]
            data['body']['surface']['spans'][0]['supports'].append(dict(support))
        with self.assertRaisesRegex(ValueError, 'duplicate surface support'):
            receive(self.catalog, self.mutated(payload, duplicate_support))

    def test_same_id_different_body_rejected(self):
        entry = self.main_bundle()
        self.accept_highest(entry)
        changed = self.mutated(entry.payload, lambda data: data['body']['surface']['spans'][0].update(
            {'left_height': '7'}))
        with self.assertRaisesRegex(ValueError, 'conflicting content'):
            receive(self.catalog, changed)
        self.assertEqual(self.catalog.get(entry.bundle_id).payload, entry.payload)

    # -- review -------------------------------------------------------------

    def test_pass_case_signs_only_highest_ties(self):
        ids = self.accept_highest(self.main_bundle())
        low = self.inspect_highest('h-edge-low', ids, 2, 2, left=1)
        self.assertEqual(low.report.status, 'blocked_confirmed')
        self.assertEqual(low.report.block.chainage, Fraction(2))
        self.assertEqual(tuple(item.segment_id for item in low.report.block.supports), ('A', 'C'))
        clear = self.inspect_highest('h-edge-high', ids, 2, 2, left=Fraction(5, 2))
        self.assertEqual((clear.report.status, clear.report.block), ('clear', None))
        self.assertEqual(fetch(self.offline, low.report.report_id),
                         (low.report, low.receipt))

    def test_end_point_tie(self):
        ids = self.accept_highest(self.main_bundle())
        result = self.inspect_highest('h-end', ids, 0, 4, left=4)
        self.assertEqual(result.report.block.chainage, Fraction(4))
        self.assertEqual(tuple(item.segment_id for item in result.report.block.supports), ('A', 'D'))

    def test_crossing_surface_and_point_tie(self):
        y = highest(self, 'h-y', segment('Y', 0, 3, 3, 0, terminal=True))
        x = highest(self, 'h-x', segment('X', 0, 3, 0, 3, terminal=True))
        t = highest(self, 'h-t', segment('T', 0, 3, Fraction(3, 2), Fraction(3, 2), terminal=True))
        g = highest(self, 'h-g', segment('G', 1, 2, 2, 2, terminal=True))
        ids = self.accept_highest(y, x, t, g)
        result = self.inspect_highest('h-cross', ids[:3], Fraction(3, 2), Fraction(3, 2), left=Fraction(3, 2))
        self.assertEqual(result.report.block.chainage, Fraction(3, 2))
        self.assertEqual(tuple(item.segment_id for item in result.report.block.supports), ('T', 'X', 'Y'))
        higher = self.inspect_highest('h-cross-higher', ids, Fraction(3, 2), Fraction(3, 2),
                                      left=Fraction(3, 2))
        self.assertEqual(tuple(item.segment_id for item in higher.report.block.supports), ('G',))
        inside = self.inspect_highest('h-inside', ids[:3], Fraction(5, 4), 3,
                                      left=Fraction(7, 3), right=Fraction(7, 3))
        self.assertEqual(inside.report.block.chainage, Fraction(7, 3))
        self.assertEqual(tuple(item.segment_id for item in inside.report.block.supports), ('X',))

    def test_gap_and_missing(self):
        p = highest(self, 'h-p', segment('P', 0, 1, 0))
        q = highest(self, 'h-q', segment('Q', 2, 3, 2, 2, terminal=True))
        m = highest(self, 'h-m', segment('M', 0, 3, 99, 99, quality='fail'))
        ids = self.accept_highest(p, q, m)
        gapped = self.inspect_highest('h-gap', ids[:2], 0, 3)
        self.assertEqual(gapped.report.status, 'blocked_pending')
        self.assertEqual(gapped.report.block.chainage, Fraction(2))
        self.assertEqual(gapped.report.coverage.gaps,
                         (ClippedSpan(Fraction(1), Fraction(2), True, False),))
        empty = self.inspect_highest('h-missing', ids[2:], 0, 3)
        self.assertEqual(empty.report.status, 'needs_survey')
        self.assertIsNone(empty.report.block)
        self.assertEqual(empty.report.coverage.gaps,
                         (ClippedSpan(Fraction(0), Fraction(3), True, True),))

    def test_point_window_requires_equal_heights(self):
        entry = highest(self, 'h-point', segment('A', 0, 6, 3, terminal=True))
        ids = self.accept_highest(entry)
        with self.assertRaisesRegex(ValueError, 'point window'):
            self.inspect_highest('h-bad-point', ids, 2, 2, left=1, right=2)
        self.assertEqual(self.offline_counts(), (0, 0))

    def test_reject_mixed_versions_wrong_line_and_unknown(self):
        v2 = highest(self, 'h-v2', segment('A', 0, 6, 0, terminal=True))
        v1 = self.issue('h-v1', segment('B', 0, 6, 2, terminal=True))
        self.accept(v2, v1)
        with self.assertRaisesRegex(ValueError, 'not a version 2'):
            self.inspect_highest('h-mix', [v1.bundle_id], 0, 6)
        from review.assessment import assess
        with self.assertRaisesRegex(ValueError, 'not a version 1'):
            assess(self.catalog, self.archive, request_id='h-mix-v1', line_id=LINE.line_id,
                   bundle_ids=[v2.bundle_id], start=0, end=6, left_height=1, right_height=1)
        with self.assertRaisesRegex(ValueError, 'not been accepted'):
            self.inspect_highest('h-unknown', ['B:ghost'], 0, 6)
        with self.assertRaisesRegex(ValueError, 'another survey line'):
            self.inspect_highest('h-line', [v2.bundle_id], 0, 6, line='JW-99')
        with self.assertRaisesRegex(ValueError, 'at least one accepted version 2'):
            self.inspect_highest('h-empty', [], 0, 6)
        self.assertEqual(self.offline_counts(), (0, 0))

    def test_publication_rollback_retry_and_original_fetch(self):
        entry = highest(self, 'h-fail', segment('A', 0, 6, 0, terminal=True))
        ids = self.accept_highest(entry)
        good = self.inspect_highest('h-good', ids, 0, 6, left=1)
        self.offline.execute('''
            CREATE TRIGGER reject_receipt BEFORE INSERT ON report_receipts
            BEGIN SELECT RAISE(ABORT, 'receipt storage unavailable'); END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt storage unavailable'):
            self.inspect_highest('h-retry', ids, 0, 6, left=1)
        self.assertFalse(self.offline.in_transaction)
        self.assertEqual(self.offline_counts(), (1, 1))
        with self.assertRaises(KeyError):
            fetch(self.offline, 'RPT:h-retry')
        self.offline.execute('DROP TRIGGER reject_receipt')
        retried = self.inspect_highest('h-retry', ids, 0, 6, left=1)
        self.assertEqual(self.inspect_highest('h-retry', ids, 0, 6, left=1), retried)
        self.offline.close()
        self.open_offline()
        self.assertEqual(fetch(self.offline, good.report.report_id), (good.report, good.receipt))
        self.assertEqual(fetch(self.offline, retried.report.report_id),
                         (retried.report, retried.receipt))
        self.assertEqual(self.offline_counts(), (2, 2))
