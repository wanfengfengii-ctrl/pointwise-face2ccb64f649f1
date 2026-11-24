from fractions import Fraction

from issue.reissue import release
from reports.history import fetch
from review.window import ClippedSpan
from survey.provenance import SourceRef
from tests.fixtures import WorkflowCase, book, segment


class HandoverTests(WorkflowCase):
    def test_supplement_and_history(self):
        a, b = self.gap_bundle_pair()
        self.station.close()
        ids = self.accept(a, b)
        before = self.inspect('before-supplement', ids)
        self.open_station()
        c = self.issue('supplement', segment('C', 1, 4, 0))
        self.station.close()
        c_ids = self.accept(c)
        after = self.inspect('after-supplement', (*ids, *c_ids))
        omitted = self.inspect('omitted-supplement', ids)
        self.assertEqual(before.report.block.chainage, Fraction(4))
        self.assertEqual(before.report.block, after.report.block)
        self.assertEqual(before.report.block.supports[0].source, SourceRef('field-book', 'B'))
        self.assertFalse(before.report.earlier_covered)
        self.assertEqual(before.report.coverage.gaps, (ClippedSpan(Fraction(1), Fraction(4), True, False),))
        self.assertTrue(after.report.earlier_covered)
        self.assertEqual(after.report.coverage.gaps, ())
        self.assertEqual(omitted.report.status, 'blocked_pending')
        self.offline.close()
        self.open_offline()
        self.assertEqual(fetch(self.offline, before.report.report_id), (before.report, before.receipt))
        self.assertEqual(fetch(self.offline, after.report.report_id), (after.report, after.receipt))

    def test_evidence_binding(self):
        a, b = self.gap_bundle_pair()
        c = self.issue('supplement', segment('C', 1, 4, 0))
        slope = self.issue('true-slope', segment('S', 1, 4, 0, 2))
        self.station.close()
        self.accept(a, b, c, slope)
        for entry, name, start, end, height, terminal in (
            (a, 'A', 0, 1, 0, False), (b, 'B', 4, 6, 2, True), (c, 'C', 1, 4, 0, False),
        ):
            with self.subTest(name=name):
                envelope = self.catalog.get(entry.bundle_id).envelope
                evidence, = envelope.profile.segments
                self.assertEqual(envelope.revision_id, entry.revision_id)
                self.assertEqual((evidence.segment_id, evidence.start, evidence.end, evidence.terminal),
                                 (name, Fraction(start), Fraction(end), terminal))
                self.assertEqual((evidence.left_height, evidence.right_height), (Fraction(height), Fraction(height)))
                self.assertEqual(evidence.source, SourceRef('field-book', name))
        gap = self.inspect('gap-control', [a.bundle_id, b.bundle_id]).report
        joined = self.inspect('true-slope-control', [a.bundle_id, b.bundle_id, slope.bundle_id]).report
        self.assertEqual((gap.block.chainage, gap.block.supports[0].segment_id), (Fraction(4), 'B'))
        self.assertEqual((joined.block.chainage, joined.block.supports[0].segment_id), (Fraction(5, 2), 'S'))
        self.assertFalse(gap.earlier_covered)
        self.assertTrue(joined.earlier_covered)

    def test_quality_correction(self):
        a, b = self.gap_bundle_pair()
        bad = self.issue('instrument-unchecked', segment('C', 1, 4, 0, instrument_ok=False))
        original_ids = self.accept(a, b, bad)
        rejected = self.catalog.get(bad.bundle_id).envelope.profile
        self.assertEqual(rejected.segments, ())
        missing, = rejected.missing
        self.assertEqual((missing.start, missing.end, missing.terminal, missing.reason),
                         (Fraction(1), Fraction(4), False, 'instrument_check'))
        self.assertEqual(missing.source, SourceRef('field-book', 'C'))
        first = self.inspect('uncertified', original_ids)
        valid_id = self.revisions.correct(bad.revision_id, book('C'), [segment('C', 1, 4, 0)])
        valid = release(self.revisions, self.registry, valid_id, 'instrument-corrected')
        self.assertFalse(self.revisions.get(bad.revision_id).dispositions[0].usable)
        self.assertTrue(self.revisions.get(valid_id).dispositions[0].usable)
        self.station.close()
        valid_ids = self.accept(valid)
        second = self.inspect('certified', (*original_ids, *valid_ids))
        self.assertEqual(second.report.block, first.report.block)
        self.assertEqual(first.report.status, 'blocked_pending')
        self.assertEqual(second.report.status, 'blocked_confirmed')
        self.assertEqual(fetch(self.offline, first.report.report_id), (first.report, first.receipt))

    def test_original_receipt_after_reopen(self):
        a, b = self.gap_bundle_pair()
        one = self.inspect('shift-one', self.accept(a, b))
        follow_up = self.revisions.correct(b.revision_id, book('B'), [segment('B', 4, 6, 0, terminal=True)])
        newer = release(self.revisions, self.registry, follow_up, 'corrected-late')
        two = self.inspect('shift-two', (a.bundle_id, *self.accept(newer)))
        self.assertEqual(one.report.status, 'blocked_pending')
        self.assertEqual(two.report.status, 'needs_survey')
        self.assertNotEqual(one.receipt, two.receipt)
        self.station.close()
        self.offline.close()
        self.open_offline()
        for original in (two, one, one, two):
            self.assertEqual(fetch(self.offline, original.report.report_id), (original.report, original.receipt))
        self.assertEqual(self.offline_counts(), (2, 2))
