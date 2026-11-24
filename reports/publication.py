import sqlite3

from reports.audit import verify_report_receipt
from reports.history import fetch
from reports.receipts import Receipt, append_receipt, make_receipt
from reports.snapshots import ReportSnapshot, encode_snapshot


class PublicationStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def initialize(self) -> None:
        self.db.execute('PRAGMA foreign_keys = ON')
        with self.db:
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS publications (
                    report_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                    snapshot TEXT NOT NULL, UNIQUE (report_id, request_id)
                )
            ''')
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS report_receipts (
                    receipt_id TEXT PRIMARY KEY, report_id TEXT NOT NULL UNIQUE,
                    request_id TEXT NOT NULL UNIQUE,
                    FOREIGN KEY (report_id, request_id)
                        REFERENCES publications (report_id, request_id)
                )
            ''')


def publish(store: PublicationStore, report: ReportSnapshot) -> tuple[ReportSnapshot, Receipt]:
    db = store.db
    db.execute('BEGIN IMMEDIATE')
    with db:
        request_id = report.request.request_id
        existing = db.execute('SELECT report_id FROM publications WHERE request_id = ?', (request_id,)).fetchone()
        if existing is not None:
            previous_report, previous_receipt = fetch(db, existing[0])
            if previous_report.request != report.request:
                raise ValueError('review request is already bound to different inputs')
            return previous_report, previous_receipt
        receipt = make_receipt(report.report_id, request_id)
        verify_report_receipt(report, receipt)
        db.execute('INSERT INTO publications VALUES (?, ?, ?)', (
            report.report_id, request_id, encode_snapshot(report),
        ))
        append_receipt(db, receipt)
    return report, receipt
