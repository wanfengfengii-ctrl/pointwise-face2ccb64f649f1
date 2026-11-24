import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction

from issue.profiles import MissingSpan, ProfileEvidence, SegmentEvidence, validate_profile
from survey.metres import encode_metres, parse_metres
from survey.provenance import parse_source_ref, require_text
from survey.revisions import require_revision_id


@dataclass(frozen=True)
class V1Envelope:
    bundle_id: str
    line_id: str
    revision_id: int
    profile: ProfileEvidence


def _canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def fingerprint_body(body: dict) -> str:
    return hashlib.sha256(_canonical(body)).hexdigest()


def _identity(envelope: V1Envelope) -> dict:
    return {
        'bundle_id': require_text(envelope.bundle_id, 'bundle id'),
        'line_id': require_text(envelope.line_id, 'line id'),
        'revision_id': require_revision_id(envelope.revision_id),
    }


def _range_data(row: SegmentEvidence | MissingSpan) -> dict:
    return {
        'segment_id': row.segment_id,
        'start': encode_metres(row.start),
        'end': encode_metres(row.end),
        'terminal': row.terminal,
        'source': row.source.to_data(),
    }


def encode_envelope(envelope: V1Envelope) -> bytes:
    identity = _identity(envelope)
    validate_profile(envelope.profile)
    body = {
        **identity,
        'segments': [
            {**_range_data(row), 'left_height': encode_metres(row.left_height),
             'right_height': encode_metres(row.right_height)}
            for row in envelope.profile.segments
        ],
        'missing': [{**_range_data(row), 'reason': row.reason} for row in envelope.profile.missing],
    }
    return _canonical({'version': 1, **identity, 'body': body, 'digest': fingerprint_body(body)})


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key {key!r}')
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f'nonfinite JSON constant {value}')


def _expect_fields(data: object, fields: set[str], name: str) -> None:
    if not isinstance(data, dict) or data.keys() != fields:
        raise ValueError(f'invalid {name} fields')


def _wire_metres(value: object) -> Fraction:
    parsed = parse_metres(value)
    if value != encode_metres(parsed):
        raise ValueError('station bundles require canonical rational text')
    return parsed


def _range_from_data(row: dict) -> tuple:
    return (
        require_text(row['segment_id'], 'segment id'),
        _wire_metres(row['start']), _wire_metres(row['end']), row['terminal'],
        parse_source_ref(row['source']),
    )


def _read_profile(body: dict) -> ProfileEvidence:
    fields = {'segment_id', 'start', 'end', 'terminal', 'source'}
    if not isinstance(body['segments'], list) or not isinstance(body['missing'], list):
        raise ValueError('profile requires arrays of segments and missing spans')
    segments = []
    for row in body['segments']:
        _expect_fields(row, fields | {'left_height', 'right_height'}, 'segment')
        segments.append(SegmentEvidence(
            *_range_from_data(row), _wire_metres(row['left_height']), _wire_metres(row['right_height']),
        ))
    missing = []
    for row in body['missing']:
        _expect_fields(row, fields | {'reason'}, 'missing span')
        missing.append(MissingSpan(*_range_from_data(row), row['reason']))
    result = ProfileEvidence(tuple(segments), tuple(missing))
    validate_profile(result)
    return result


def decode_envelope(payload: bytes) -> V1Envelope:
    if not isinstance(payload, bytes):
        raise ValueError('station bundle must be bytes')
    try:
        outer = json.loads(payload.decode('utf-8'), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('invalid station bundle JSON') from exc
    identity_fields = {'bundle_id', 'line_id', 'revision_id'}
    _expect_fields(outer, identity_fields | {'version', 'body', 'digest'}, 'envelope')
    if type(outer['version']) is not int or outer['version'] != 1:
        raise ValueError('unsupported station bundle version')
    bundle_id = require_text(outer['bundle_id'], 'bundle id')
    line_id = require_text(outer['line_id'], 'line id')
    revision_id = require_revision_id(outer['revision_id'])
    body = outer['body']
    _expect_fields(body, identity_fields | {'segments', 'missing'}, 'body')
    require_revision_id(body['revision_id'])
    if any(body[key] != outer[key] for key in identity_fields):
        raise ValueError('bundle identity does not match body binding')
    if not isinstance(outer['digest'], str) or outer['digest'] != fingerprint_body(body):
        raise ValueError('station bundle digest mismatch')
    return V1Envelope(bundle_id, line_id, revision_id, _read_profile(body))
