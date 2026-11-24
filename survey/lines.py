import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from survey.provenance import require_text


@dataclass(frozen=True)
class SurveyLine:
    line_id: str
    name: str
    datum: str

    def __post_init__(self) -> None:
        require_text(self.line_id, 'line id')
        require_text(self.name, 'line name')
        require_text(self.datum, 'line datum')


class LineStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def initialize(self, defaults: Iterable[SurveyLine] = ()) -> None:
        with self.db:
            self.db.execute('''
                CREATE TABLE IF NOT EXISTS survey_lines (
                    line_id TEXT PRIMARY KEY, name TEXT NOT NULL, datum TEXT NOT NULL
                )
            ''')
            self.db.executemany('''
                INSERT INTO survey_lines VALUES (?, ?, ?)
                ON CONFLICT(line_id) DO NOTHING
            ''', ((line.line_id, line.name, line.datum) for line in defaults))

    def register(self, line: SurveyLine) -> SurveyLine:
        """Register a line or update its display name under the same datum."""
        with self.db:
            result = self.db.execute('''
                INSERT INTO survey_lines VALUES (?, ?, ?)
                ON CONFLICT(line_id) DO UPDATE SET name = excluded.name
                WHERE survey_lines.datum = excluded.datum
            ''', (line.line_id, line.name, line.datum))
            if result.rowcount == 0:
                raise ValueError('a registered line keeps its original datum')
        return line

    def get(self, line_id: str) -> SurveyLine:
        require_text(line_id, 'line id')
        row = self.db.execute('''
            SELECT line_id, name, datum FROM survey_lines WHERE line_id = ?
        ''', (line_id,)).fetchone()
        if row is None:
            raise KeyError(line_id)
        return SurveyLine(*row)
