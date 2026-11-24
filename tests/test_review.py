from fractions import Fraction

from reports.history import fetch
from review.window import ClippedSpan
from survey.provenance import SourceRef
from tests.fixtures import OTHER, WorkflowCase, segment


class ReviewTests(WorkflowCase):
    def test_exact_crossing(self):
        entry = self.issue('ascending', segment('S', 0, 3, 0, 3))
        result = self.inspect('oblique', self.accept(entry), 0, 3, left=1, right=2)
        self.assertEqual(result.report.block.chainage, Fraction(3, 2))
        support, = result.report.block.supports
        self.assertEqual((support.bundle_id, support.revision_id, support.segment_id, support.source),
                         (entry.bundle_id, entry.revision_id, 'S', SourceRef('field-book', 'S')))
        self.assertEqual(result.report.status, 'blocked_confirmed')
        self.assertEqual(fetch(self.offline, result.report.report_id), (result.report, result.receipt))

    def test_rational_crossing(self):
        bundle = self.issue('thirds', segment('S', 0, 1, 0, 3))
        result = self.inspect('rational', self.accept(bundle), 0, 1)
        self.assertEqual(result.report.block.chainage, Fraction(1, 3))
        self.assertEqual(result.report.block.supports[0].segment_id, 'S')
        archived, receipt = fetch(self.offline, result.report.report_id)
        self.assertEqual(archived.block.chainage, Fraction(1, 3))
        self.assertEqual(archived.block.supports[0].source, SourceRef('field-book', 'S'))
        self.assertEqual(receipt, result.receipt)

    def test_window_endpoint(self):
        open_end = self.issue('open', segment('open', 0, 1, 0, 1))
        terminal = self.issue('terminal', segment('terminal', 0, 1, 0, 1, terminal=True))
        inside = self.issue('inside', segment('inside', 0, 2, 0, 2))
        self.accept(open_end, terminal, inside)
        ordinary = self.inspect('ordinary-end', [open_end.bundle_id], 0, 1)
        self.assertIsNone(ordinary.report.block)
        self.assertEqual(ordinary.report.status, 'needs_survey')
        self.assertEqual(ordinary.report.coverage.gaps, (ClippedSpan(Fraction(1), Fraction(1), True, True),))
        for entry, expected_segment in ((terminal, 'terminal'), (inside, 'inside')):
            with self.subTest(segment=expected_segment):
                result = self.inspect(f'closed-{expected_segment}', [entry.bundle_id], 0, 1)
                self.assertEqual(result.report.block.chainage, Fraction(1))
                self.assertEqual(result.report.block.supports[0].segment_id, expected_segment)
                self.assertTrue(result.report.earlier_covered)
        no_point = self.inspect('open-singleton', [open_end.bundle_id], 1, 1)
        yes_point = self.inspect('terminal-singleton', [terminal.bundle_id], 1, 1)
        self.assertEqual(no_point.report.status, 'needs_survey')
        self.assertEqual(yes_point.report.status, 'blocked_confirmed')
        self.assertEqual(yes_point.report.block.chainage, Fraction(1))

    def test_overlap(self):
        a = self.issue('a', segment('A', 0, 6, 0, terminal=True))
        b = self.issue('b', segment('B', 1, 4, 2))
        c = self.issue('c', segment('C', 1, 5, 1))
        ids = self.accept(a, b, c)
        first = self.inspect('overlap-one', ids).report
        second = self.inspect('overlap-two', [ids[2], ids[1], ids[0], ids[2]]).report
        self.assertEqual(first.block.chainage, Fraction(1))
        self.assertEqual(tuple(item.segment_id for item in first.block.supports), ('B', 'C'))
        self.assertEqual(first.block, second.block)
        self.assertEqual(first.request.bundle_ids, second.request.bundle_ids)
        self.assertEqual(first.coverage, second.coverage)
        self.assertEqual((first.status, second.status), ('blocked_confirmed', 'blocked_confirmed'))

    def test_gap_before_block(self):
        a, b = self.gap_bundle_pair()
        self.station.close()
        outcome = self.inspect('gap', self.accept(a, b))
        report = outcome.report
        self.assertIsNotNone(report.block, 'GAP_BEFORE_BLOCK: expected proven obstruction')
        self.assertEqual(report.block.chainage, Fraction(4), 'GAP_BEFORE_BLOCK: chainage')
        self.assertEqual([item.segment_id for item in report.block.supports], ['B'], 'GAP_BEFORE_BLOCK: evidence')
        self.assertFalse(report.earlier_covered, 'GAP_BEFORE_BLOCK: prefix')
        self.assertEqual(report.status, 'blocked_pending')
        self.assertEqual(report.coverage.gaps, (ClippedSpan(Fraction(1), Fraction(4), True, False),))

    def test_no_block(self):
        full = self.issue('full', segment('full', 0, 6, 0, terminal=True))
        open_end = self.issue('open', segment('open', 0, 6, 0))
        split = self.issue('split', segment('left', 0, 1, 0, terminal=True),
                           segment('right', 4, 6, 0, terminal=True))
        self.accept(full, open_end, split)
        cases = [
            ([full.bundle_id], 'clear', ()),
            ([open_end.bundle_id], 'needs_survey', (ClippedSpan(Fraction(6), Fraction(6), True, True),)),
            ([split.bundle_id], 'needs_survey', (ClippedSpan(Fraction(1), Fraction(4), False, False),)),
            ([], 'needs_survey', (ClippedSpan(Fraction(0), Fraction(6), True, True),)),
        ]
        for index, (ids, status, gaps) in enumerate(cases):
            with self.subTest(ids=ids):
                report = self.inspect(f'no-block-{index}', ids).report
                self.assertIsNone(report.block)
                self.assertIsNone(report.earlier_covered)
                self.assertEqual(report.status, status)
                self.assertEqual(report.coverage.gaps, gaps)

    def test_reject_mixed_lines(self):
        self.lines.register(OTHER)
        main = self.issue('a-main', segment('A', 0, 6, 0, terminal=True))
        other = self.issue('z-other', segment('B', 0, 6, 2, terminal=True), line=OTHER.line_id)
        self.accept(main, other)
        with self.assertRaisesRegex(ValueError, 'another survey line'):
            self.inspect('mixed', [other.bundle_id, main.bundle_id])
        with self.assertRaisesRegex(ValueError, 'not been accepted'):
            self.inspect('missing', [main.bundle_id, 'B:missing'])
        self.assertEqual(self.offline_counts(), (0, 0))
        self.assertEqual(self.inspect('single-line', [main.bundle_id]).report.status, 'clear')
        self.assertEqual(self.offline_counts(), (1, 1))

    def test_invalid_window(self):
        entry = self.issue('a', segment('A', 0, 6, 0, terminal=True))
        ids = self.accept(entry)
        for start, end, left, right in ((4, 1, 1, 1), (2, 2, 1, 3), (0, 6, '1/0', 1)):
            with self.subTest(start=start, end=end, left=left, right=right):
                with self.assertRaises(ValueError):
                    self.inspect('bad-window', ids, start, end, left=left, right=right)
        self.assertEqual(self.offline_counts(), (0, 0))
