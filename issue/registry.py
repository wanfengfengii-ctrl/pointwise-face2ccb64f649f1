import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class IssueEntry:
    request_id: str
    revision_id: int
    bundle_id: str
    payload: bytes


class IssueRegistry:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def initialize(self) -> None:
        with self.db:
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS issued_bundles (
                    request_id TEXT PRIMARY KEY,
                    revision_id INTEGER NOT NULL REFERENCES survey_revisions(revision_id),
                    bundle_id TEXT NOT NULL UNIQUE,
                    payload BLOB NOT NULL
                )
            ''')

    def find_request(self, request_id: str) -> IssueEntry | None:
        row = self.db.execute('''
            SELECT request_id, revision_id, bundle_id, payload
            FROM issued_bundles WHERE request_id = ?
        ''', (request_id,)).fetchone()
        return IssueEntry(*row) if row is not None else None

    def get(self, bundle_id: str) -> IssueEntry:
        row = self.db.execute('''
            SELECT request_id, revision_id, bundle_id, payload
            FROM issued_bundles WHERE bundle_id = ?
        ''', (bundle_id,)).fetchone()
        if row is None:
            raise KeyError(bundle_id)
        return IssueEntry(*row)

    def store(self, entry: IssueEntry) -> None:
        """Append the original issue under the transaction owned by release."""
        if not self.db.in_transaction:
            raise RuntimeError('issue storage requires an open transaction')
        self.db.execute('INSERT INTO issued_bundles VALUES (?, ?, ?, ?)', (
            entry.request_id, entry.revision_id, entry.bundle_id, entry.payload,
        ))
