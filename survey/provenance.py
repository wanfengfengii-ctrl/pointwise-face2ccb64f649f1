from collections.abc import Collection
from dataclasses import dataclass


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or '\x00' in value:
        raise ValueError(f'invalid {field}')
    try:
        value.encode('utf-8')
    except UnicodeError as exc:
        raise ValueError(f'invalid {field}') from exc
    return value


@dataclass(frozen=True, order=True)
class SourceRef:
    book: str
    entry: str

    def to_data(self) -> dict:
        return {'book': self.book, 'entry': self.entry}


def parse_source_ref(data: object) -> SourceRef:
    if not isinstance(data, dict) or data.keys() != {'book', 'entry'}:
        raise ValueError('source requires a book and an entry')
    return SourceRef(require_text(data['book'], 'book'), require_text(data['entry'], 'entry'))


def validate_source_ref(ref: SourceRef, book_id: str, entry_ids: Collection[str]) -> None:
    if ref.book != book_id or ref.entry not in entry_ids:
        raise ValueError('source entry is absent from the submitted measurement book')
