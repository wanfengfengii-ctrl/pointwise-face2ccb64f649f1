import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from survey.lines import LineStore
from survey.observations import MeasurementBook, Observation, read_observations
from survey.quality import QualityDisposition, classify_observation


def require_revision_id(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError('revision id must be a positive integer')
    return value


@dataclass(frozen=True)
class SurveyRevision:
    revision_id: int
    line_id: str
    parent_id: int | None
    book: MeasurementBook
    observations: tuple[Observation, ...]
    dispositions: tuple[QualityDisposition, ...]


class RevisionStore:
    def __init__(self, db: sqlite3.Connection, lines: LineStore):
        self.db = db
        self.lines = lines

    def initialize(self) -> None:
        self.db.execute('PRAGMA foreign_keys = ON')
        with self.db:
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS survey_revisions (
                    revision_id INTEGER PRIMARY KEY,
                    line_id TEXT NOT NULL REFERENCES survey_lines(line_id),
                    parent_id INTEGER REFERENCES survey_revisions(revision_id),
                    measurement_book TEXT NOT NULL,
                    observations TEXT NOT NULL,
                    dispositions TEXT NOT NULL
                )
            ''')

    def record(self, line_id: str, book: dict, rows: Iterable[dict]) -> int:
        return self._archive(line_id, None, book, rows)

    def correct(self, revision_id: int, book: dict, rows: Iterable[dict]) -> int:
        parent = self.get(revision_id)
        return self._archive(parent.line_id, parent.revision_id, book, rows)

    def _archive(self, line_id: str, parent_id: int | None, raw_book: dict, rows: Iterable[dict]) -> int:
        line = self.lines.get(line_id)
        book = MeasurementBook.from_data(raw_book)
        observations = read_observations(line, book, rows)
        dispositions = tuple(classify_observation(row) for row in observations)
        with self.db:
            cursor = self.db.execute('''
                INSERT INTO survey_revisions
                    (line_id, parent_id, measurement_book, observations, dispositions)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                line_id, parent_id, json.dumps(book.to_data()),
                json.dumps([row.to_data() for row in observations]),
                json.dumps([item.reason for item in dispositions]),
            ))
            revision_id = cursor.lastrowid
        return revision_id

    def get(self, revision_id: int) -> SurveyRevision:
        require_revision_id(revision_id)
        if revision_id > 2**63 - 1:
            raise KeyError(revision_id)
        row = self.db.execute('''
            SELECT line_id, parent_id, measurement_book, observations, dispositions
            FROM survey_revisions WHERE revision_id = ?
        ''', (revision_id,)).fetchone()
        if row is None:
            raise KeyError(revision_id)
        line_id, parent_id, stored_book, stored_rows, stored_decisions = row
        book = MeasurementBook.from_data(json.loads(stored_book))
        observations = read_observations(self.lines.get(line_id), book, json.loads(stored_rows))
        dispositions = tuple(QualityDisposition(reason) for reason in json.loads(stored_decisions))
        return SurveyRevision(revision_id, line_id, parent_id, book, observations, dispositions)
