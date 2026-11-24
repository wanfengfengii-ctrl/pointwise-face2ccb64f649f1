import sqlite3

from issue.envelope import decode_envelope
from issue.reissue import release
from survey.lines import SurveyLine
from tests.fixtures import LINE, WorkflowCase, book, segment


class IssueTests(WorkflowCase):
    def test_repeat_release(self):
        original = self.issue('morning', segment('A', 0, 1, 0))
        repeated = release(self.revisions, self.registry, original.revision_id, 'morning')
        self.assertEqual(repeated, original)
        self.assertEqual(self.registry.get(original.bundle_id), original)
        self.station.close()
        self.open_station()
        self.assertEqual(release(self.revisions, self.registry, original.revision_id, 'morning'), original)
        self.assertEqual(self.station_counts(), (1, 1))

    def test_initialization_preserves_inventory(self):
        original = self.issue('inventory', segment('A', 0, 1, 0))
        updated = SurveyLine(LINE.line_id, '资料员更正后的东堤名', LINE.datum)
        self.lines.register(updated)
        self.accept(original)
        self.inspect('existing-report', [original.bundle_id])
        self.open_station()
        self.open_offline()
        self.assertEqual(self.lines.get(LINE.line_id), updated)
        self.assertEqual(self.registry.get(original.bundle_id), original)
        self.assertEqual(self.catalog.get(original.bundle_id).payload, original.payload)
        self.assertEqual(self.station_counts(), (1, 1))
        self.assertEqual(self.offline_counts(), (1, 1))

    def test_corrected_revision_reissue(self):
        original = self.issue('morning', segment('A', 0, 1, '1/4'))
        corrected_id = self.revisions.correct(original.revision_id, book('A'), [segment('A', 0, 1, 2)])
        replacement = release(self.revisions, self.registry, corrected_id, 'corrected')
        self.assertNotEqual(replacement.bundle_id, original.bundle_id)
        self.assertEqual(decode_envelope(replacement.payload).revision_id, corrected_id)
        self.assertEqual(self.revisions.get(corrected_id).parent_id, original.revision_id)
        self.assertEqual(release(self.revisions, self.registry, original.revision_id, 'morning'), original)
        with self.assertRaisesRegex(ValueError, 'already bound'):
            release(self.revisions, self.registry, corrected_id, 'morning')
        self.assertEqual(self.station_counts(), (2, 2))

    def test_release_failure(self):
        original = self.issue('original', segment('A', 0, 1, 0))
        with self.assertRaises(KeyError):
            release(self.revisions, self.registry, 999, 'unknown')
        self.station.execute('''
            CREATE TRIGGER fail_issue BEFORE INSERT ON issued_bundles
            BEGIN SELECT RAISE(ABORT, 'issue storage unavailable'); END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'issue storage unavailable'):
            release(self.revisions, self.registry, original.revision_id, 'retry')
        self.assertEqual(self.station_counts(), (1, 1))
        self.assertIsNone(self.registry.find_request('retry'))
        self.assertEqual(self.registry.get(original.bundle_id), original)
        self.station.execute('DROP TRIGGER fail_issue')
        self.assertEqual(release(self.revisions, self.registry, original.revision_id, 'retry').revision_id,
                         original.revision_id)
        self.assertEqual(self.station_counts(), (1, 2))

    def test_reject_reversed_span(self):
        self.issue('existing', segment('A', 0, 1, 0))
        with self.assertRaisesRegex(ValueError, 'increasing chainage'):
            self.record(segment('valid', 0, 4, 0), segment('invalid', 4, 1, 0))
        self.assertEqual(self.station_counts(), (1, 1))

    def test_invalid_source(self):
        original = self.issue('existing', segment('A', 0, 1, 0))
        for raw_book in (book('another-entry'), {'id': 'another-book', 'entries': {'C': 'note'}}):
            with self.subTest(raw_book=raw_book):
                with self.assertRaisesRegex(ValueError, 'source entry is absent'):
                    self.revisions.correct(original.revision_id, raw_book, [segment('C', 1, 4, 0)])
        self.assertEqual(self.station_counts(), (1, 1))
        self.assertEqual(self.registry.get(original.bundle_id), original)
