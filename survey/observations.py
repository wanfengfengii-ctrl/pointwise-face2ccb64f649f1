from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from survey.lines import SurveyLine
from survey.metres import encode_metres, parse_metres
from survey.provenance import SourceRef, parse_source_ref, require_text, validate_source_ref


@dataclass(frozen=True)
class MeasurementBook:
    book_id: str
    entries: tuple[tuple[str, str], ...]

    @classmethod
    def from_data(cls, data: object) -> 'MeasurementBook':
        if not isinstance(data, dict) or data.keys() != {'id', 'entries'}:
            raise ValueError('measurement book requires id and entries')
        book_id = require_text(data['id'], 'book id')
        if not isinstance(data['entries'], dict):
            raise ValueError('measurement book entries must be an object')
        entries = []
        for entry_id, note in data['entries'].items():
            require_text(entry_id, 'entry id')
            if not isinstance(note, str) or not note.strip():
                raise ValueError('each measurement entry requires an original note')
            entries.append((entry_id, note))
        return cls(book_id, tuple(sorted(entries)))

    def to_data(self) -> dict:
        return {'id': self.book_id, 'entries': dict(self.entries)}


@dataclass(frozen=True)
class Observation:
    segment_id: str
    start: Fraction
    end: Fraction
    left_height: Fraction
    right_height: Fraction
    terminal: bool
    quality: str
    instrument_ok: bool
    source: SourceRef

    def to_data(self) -> dict:
        return {
            'segment_id': self.segment_id,
            'start': encode_metres(self.start),
            'end': encode_metres(self.end),
            'left_height': encode_metres(self.left_height),
            'right_height': encode_metres(self.right_height),
            'terminal': self.terminal,
            'quality': self.quality,
            'instrument_ok': self.instrument_ok,
            'source': self.source.to_data(),
        }


def read_observations(
    line: SurveyLine, book: MeasurementBook, rows: Iterable[dict]
) -> tuple[Observation, ...]:
    fields = {
        'segment_id', 'start', 'end', 'left_height', 'right_height',
        'terminal', 'quality', 'instrument_ok', 'source',
    }
    try:
        records = iter(rows)
    except TypeError as exc:
        raise ValueError('observations must be an iterable of segment records') from exc
    if isinstance(rows, (str, bytes, dict)):
        raise ValueError('observations must be an iterable of segment records')
    entry_ids = dict(book.entries).keys()
    seen = set()
    observations = []
    for row in records:
        if not isinstance(row, dict) or row.keys() != fields:
            raise ValueError('invalid original segment fields')
        segment_id = require_text(row['segment_id'], 'segment id')
        if segment_id in seen:
            raise ValueError(f'duplicate segment {segment_id} on {line.line_id}')
        start = parse_metres(row['start'])
        end = parse_metres(row['end'])
        if start >= end:
            raise ValueError(f'segment {segment_id} requires increasing chainage')
        left_height = parse_metres(row['left_height'])
        right_height = parse_metres(row['right_height'])
        if type(row['terminal']) is not bool or type(row['instrument_ok']) is not bool:
            raise ValueError('terminal and instrument_ok require boolean values')
        if row['quality'] not in ('pass', 'fail'):
            raise ValueError('quality requires pass or fail')
        source = parse_source_ref(row['source'])
        validate_source_ref(source, book.book_id, entry_ids)
        observations.append(Observation(
            segment_id, start, end, left_height, right_height, row['terminal'],
            row['quality'], row['instrument_ok'], source,
        ))
        seen.add(segment_id)
    return tuple(observations)
