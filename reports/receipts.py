import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    report_id: str
    request_id: str


def make_receipt(report_id: str, request_id: str) -> Receipt:
    return Receipt(f'ACK:{report_id}', report_id, request_id)


def append_receipt(db: sqlite3.Connection, receipt: Receipt) -> None:
    db.execute('''
        INSERT INTO report_receipts (receipt_id, report_id, request_id) VALUES (?, ?, ?)
    ''', (receipt.receipt_id, receipt.report_id, receipt.request_id))


def receipt_from_row(row: tuple[str, str, str]) -> Receipt:
    return Receipt(*row)
