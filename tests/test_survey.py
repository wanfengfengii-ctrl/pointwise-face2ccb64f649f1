from fractions import Fraction

from issue.envelope import decode_envelope
from survey.lines import SurveyLine
from survey.provenance import SourceRef
from tests.fixtures import LINE, WorkflowCase, book, segment


class SurveyTests(WorkflowCase):
    def test_register_and_archive_original_metres(self):
        entry = self.issue('measured', segment('S', '-0.5', '+1.50', '-1/3', '6/4', terminal=True))
        revision = self.revisions.get(entry.revision_id)
        row, = revision.observations
        self.assertEqual((row.start, row.end, row.left_height, row.right_height),
                         (Fraction(-1, 2), Fraction(3, 2), Fraction(-1, 3), Fraction(3, 2)))
        self.assertEqual(row.source, SourceRef('field-book', 'S'))
        self.assertEqual(revision.book.to_data(), book('S'))
        self.assertTrue(revision.dispositions[0].usable)
        self.assertEqual(decode_envelope(entry.payload).profile.segments[0].start, Fraction(-1, 2))
        self.assertNotIn(b'Field note for S', entry.payload)

    def test_reject_bad_metres_and_unregistered_line(self):
        for invalid in (True, 1.5, '1/0', '1e3', None):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, 'invalid metre value'):
                    self.record(segment('A', 0, 6, invalid))
        with self.assertRaises(KeyError):
            self.record(segment('A', 0, 6, 0), line='unregistered')
        self.assertEqual(self.station_counts(), (0, 0))

    def test_fixed_datum_and_quality_flag(self):
        with self.assertRaisesRegex(ValueError, 'original datum'):
            self.lines.register(SurveyLine(LINE.line_id, '改名', 'another datum'))
        self.assertEqual(self.lines.get(LINE.line_id), LINE)
        rejected = self.issue('quality', segment('A', 0, 1, 8, quality='fail'))
        profile = decode_envelope(rejected.payload).profile
        self.assertEqual(profile.segments, ())
        self.assertEqual(profile.missing[0].reason, 'survey_flag')
        self.assertEqual(profile.missing[0].source, SourceRef('field-book', 'A'))
