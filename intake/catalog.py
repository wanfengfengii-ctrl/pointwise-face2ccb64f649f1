import sqlite3
from dataclasses import dataclass

from intake.integrity import ValidatedBundle, validate_bundle
from issue.envelope import V1Envelope


@dataclass(frozen=True)
class AcceptedBundle:
    envelope: V1Envelope
    payload: bytes

    @property
    def bundle_id(self) -> str:
        return self.envelope.bundle_id

    @property
    def line_id(self) -> str:
        return self.envelope.line_id


class AcceptedCatalog:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def initialize(self) -> None:
        with self.db:
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS accepted_bundles (
                    bundle_id TEXT PRIMARY KEY,
                    line_id TEXT NOT NULL,
                    revision_id INTEGER NOT NULL,
                    payload BLOB NOT NULL,
                    canonical BLOB NOT NULL
                )
            ''')

    def accept(self, validated: ValidatedBundle) -> str:
        envelope = validated.envelope
        self.db.execute('BEGIN IMMEDIATE')
        with self.db:
            existing = self.db.execute('''
                SELECT canonical FROM accepted_bundles WHERE bundle_id = ?
            ''', (envelope.bundle_id,)).fetchone()
            if existing is not None:
                if existing[0] != validated.canonical:
                    raise ValueError('conflicting content for an accepted bundle id')
            else:
                self.db.execute('INSERT INTO accepted_bundles VALUES (?, ?, ?, ?, ?)', (
                    envelope.bundle_id, envelope.line_id, envelope.revision_id,
                    validated.payload, validated.canonical,
                ))
        return envelope.bundle_id

    def get(self, bundle_id: str) -> AcceptedBundle:
        row = self.db.execute('''
            SELECT line_id, revision_id, payload FROM accepted_bundles WHERE bundle_id = ?
        ''', (bundle_id,)).fetchone()
        if row is None:
            raise KeyError(bundle_id)
        line_id, revision_id, payload = row
        envelope = validate_bundle(payload).envelope
        if (envelope.bundle_id, envelope.line_id, envelope.revision_id) != (bundle_id, line_id, revision_id):
            raise ValueError('stored bundle identity mismatch')
        return AcceptedBundle(envelope, payload)
