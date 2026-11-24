import sqlite3

from reports.history import fetch
from tests.fixtures import WorkflowCase, segment


class ReportTests(WorkflowCase):
    def setUp(self):
        super().setUp()
        entry = self.issue('report-evidence', segment('A', 0, 6, 0, terminal=True))
        self.ids = self.accept(entry)
        self.first = self.inspect('original', self.ids)

    def test_publication_failure(self):
        self.offline.execute('''
            CREATE TRIGGER reject_receipt BEFORE INSERT ON report_receipts
            BEGIN SELECT RAISE(ABORT, 'receipt storage unavailable'); END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt storage unavailable'):
            self.inspect('failed', self.ids)
        self.assertFalse(self.offline.in_transaction)
        self.assertEqual(self.offline_counts(), (1, 1))
        with self.assertRaises(KeyError):
            fetch(self.offline, 'RPT:failed')
        self.assertEqual(fetch(self.offline, self.first.report.report_id), (self.first.report, self.first.receipt))

    def test_retry_after_rollback(self):
        self.offline.executescript('''
            CREATE TABLE required_commit_token (token INTEGER PRIMARY KEY);
            CREATE TABLE commit_guard (
                token INTEGER REFERENCES required_commit_token(token) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER fail_commit AFTER INSERT ON report_receipts
            BEGIN INSERT INTO commit_guard VALUES (1); END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
            self.inspect('retry', self.ids)
        self.assertFalse(self.offline.in_transaction)
        self.assertEqual(self.offline_counts(), (1, 1))
        self.assertEqual(self.offline.execute('SELECT count(*) FROM commit_guard').fetchone()[0], 0)
        self.assertEqual(fetch(self.offline, self.first.report.report_id), (self.first.report, self.first.receipt))
        with self.assertRaises(KeyError):
            fetch(self.offline, 'RPT:retry')
        self.offline.execute('DROP TRIGGER fail_commit')
        retry = self.inspect('retry', self.ids)
        self.assertEqual(self.inspect('retry', self.ids), retry)
        self.assertEqual(self.offline_counts(), (2, 2))
        self.assertEqual(fetch(self.offline, retry.report.report_id), (retry.report, retry.receipt))

    def test_request_binding_and_unknown_history(self):
        with self.assertRaisesRegex(ValueError, 'different inputs'):
            self.inspect('original', self.ids, 0, 5)
        with self.assertRaises(KeyError):
            fetch(self.offline, 'RPT:unknown')
        self.assertEqual(self.offline_counts(), (1, 1))
