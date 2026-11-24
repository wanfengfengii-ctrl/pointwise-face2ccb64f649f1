import sqlite3

from reports.audit import verify_report_receipt
from reports.receipts import Receipt, receipt_from_row
from reports.snapshots import ReportSnapshot, decode_snapshot
from survey.provenance import require_text


def fetch(db: sqlite3.Connection, report_id: str) -> tuple[ReportSnapshot, Receipt]:
    require_text(report_id, 'report id')
    row = db.execute('''
        SELECT p.snapshot, p.request_id, r.receipt_id, r.report_id, r.request_id
        FROM publications AS p
        LEFT JOIN report_receipts AS r ON r.report_id = p.report_id
        WHERE p.report_id = ?
    ''', (report_id,)).fetchone()
    if row is None:
        raise KeyError(report_id)
    report = decode_snapshot(row[0])
    if (report.report_id, report.request.request_id) != (report_id, row[1]) or row[2] is None:
        raise ValueError('incomplete or inconsistent publication record')
    receipt = receipt_from_row(tuple(row[2:]))
    verify_report_receipt(report, receipt)
    return report, receipt
