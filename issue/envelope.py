import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction

from issue.profiles import MissingSpan, ProfileEvidence, SegmentEvidence, validate_profile
from issue.surface import HighestSurface, SurfacePoint, SurfaceSpan, SurfaceSupport
from survey.metres import encode_metres, parse_metres
from survey.provenance import parse_source_ref, require_text
from survey.revisions import require_revision_id


@dataclass(frozen=True)
class V1Envelope:
    bundle_id: str
    line_id: str
    revision_id: int
    profile: ProfileEvidence


@dataclass(frozen=True)
class V2Envelope:
    bundle_id: str
    line_id: str
    revision_id: int
    surface: HighestSurface


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


# ---------------------------------------------------------------------------
# Version 2: highest measured surface.
# ---------------------------------------------------------------------------

_SURFACE_SPAN_FIELDS = {
    'start', 'end', 'left_closed', 'right_closed', 'left_height', 'right_height', 'supports',
}
_SURFACE_POINT_FIELDS = {'chainage', 'height', 'supports'}


def _support_data(support: SurfaceSupport) -> dict:
    return {'segment_id': support.segment_id, 'source': support.source.to_data()}


def _read_supports(value: object) -> tuple[SurfaceSupport, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError('surface support requires at least one original segment record')
    supports = []
    seen = set()
    for row in value:
        _expect_fields(row, {'segment_id', 'source'}, 'surface support')
        segment_id = require_text(row['segment_id'], 'segment id')
        source = parse_source_ref(row['source'])
        key = (segment_id, source)
        if key in seen:
            raise ValueError('duplicate surface support record')
        seen.add(key)
        supports.append(SurfaceSupport(segment_id, source))
    return tuple(sorted(supports))


def _surface_data(surface: HighestSurface) -> dict:
    return {
        'spans': [
            {
                'start': encode_metres(span.start), 'end': encode_metres(span.end),
                'left_closed': span.left_closed, 'right_closed': span.right_closed,
                'left_height': encode_metres(span.left_height),
                'right_height': encode_metres(span.right_height),
                'supports': [_support_data(support) for support in span.supports],
            }
            for span in surface.spans
        ],
        'points': [
            {
                'chainage': encode_metres(point.chainage),
                'height': encode_metres(point.height),
                'supports': [_support_data(support) for support in point.supports],
            }
            for point in surface.points
        ],
    }


def _read_surface(body: dict) -> HighestSurface:
    surface = body['surface']
    _expect_fields(surface, {'spans', 'points'}, 'surface')
    if not isinstance(surface['spans'], list) or not isinstance(surface['points'], list):
        raise ValueError('surface requires arrays of spans and points')
    spans = []
    for row in surface['spans']:
        _expect_fields(row, _SURFACE_SPAN_FIELDS, 'surface span')
        start = _wire_metres(row['start'])
        end = _wire_metres(row['end'])
        if start >= end:
            raise ValueError('invalid highest-surface span domain')
        for flag in ('left_closed', 'right_closed'):
            if type(row[flag]) is not bool:
                raise ValueError('surface span closure requires boolean flags')
        spans.append(SurfaceSpan(
            start, end, row['left_closed'], row['right_closed'],
            _wire_metres(row['left_height']), _wire_metres(row['right_height']),
            _read_supports(row['supports']),
        ))
    points = []
    for row in surface['points']:
        _expect_fields(row, _SURFACE_POINT_FIELDS, 'surface point')
        points.append(SurfacePoint(
            _wire_metres(row['chainage']), _wire_metres(row['height']),
            _read_supports(row['supports']),
        ))
    result = HighestSurface(tuple(spans), tuple(points))
    _validate_surface(result)
    return result


def _span_interval(span: SurfaceSpan) -> tuple:
    return (span.start, span.left_closed, span.end, span.right_closed)


def _overlap(first: tuple, second: tuple):
    """Return the closed-domain overlap of two interval tuples, or None."""
    low = max(first[0], second[0])
    high = min(first[2], second[2])
    if low > high:
        return None
    low_closed = (first[1] if first[0] == low else True) and (second[1] if second[0] == low else True)
    high_closed = (first[3] if first[2] == high else True) and (second[3] if second[2] == high else True)
    if low == high and not (low_closed and high_closed):
        return None
    return (low, high)


def _affine_height(span: SurfaceSpan, chainage: Fraction) -> Fraction:
    width = span.end - span.start
    return span.left_height + (span.right_height - span.left_height) * (
        (chainage - span.start) / width
    )


def _validate_surface(surface: HighestSurface) -> None:
    """Reject self-contradictory evidence storable bytes could otherwise carry."""
    sources: dict[str, object] = {}
    for support in (*[s for span in surface.spans for s in span.supports],
                     *[s for point in surface.points for s in point.supports]):
        known = sources.get(support.segment_id)
        if known is None:
            sources[support.segment_id] = support.source
        elif known != support.source:
            raise ValueError('conflicting original segment source in one surface')

    claims = [(span.start, span.left_closed, span.end, span.right_closed, span)
              for span in surface.spans]
    for index, first in enumerate(claims):
        for second in claims[index + 1:]:
            overlap = _overlap(first[:4], second[:4])
            if overlap is None:
                continue
            low, high = overlap
            if low == high:
                if _affine_height(first[4], low) != _affine_height(second[4], low):
                    raise ValueError('conflicting highest height at one measurement point')
                continue
            sample = (low + high) / 2
            if _affine_height(first[4], sample) != _affine_height(second[4], sample):
                raise ValueError('conflicting highest height over a measurement domain')

    for point in surface.points:
        for span in surface.spans:
            if not span.covers(point.chainage):
                continue
            if _affine_height(span, point.chainage) != point.height:
                raise ValueError('conflicting highest height at one measurement point')
    for index, first in enumerate(surface.points):
        for second in surface.points[index + 1:]:
            if first.chainage == second.chainage and first.height != second.height:
                raise ValueError('conflicting highest height at one measurement point')


def encode_v2_envelope(envelope: V2Envelope) -> bytes:
    identity = _identity(envelope)
    body = {**identity, 'surface': _surface_data(envelope.surface)}
    return _canonical({'version': 2, **identity, 'body': body, 'digest': fingerprint_body(body)})


def _parse_outer(payload: bytes) -> dict:
    if not isinstance(payload, bytes):
        raise ValueError('station bundle must be bytes')
    try:
        return json.loads(payload.decode('utf-8'), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('invalid station bundle JSON') from exc


_IDENTITY_FIELDS = {'bundle_id', 'line_id', 'revision_id'}


def _read_identity(outer: dict) -> tuple[str, str, int]:
    bundle_id = require_text(outer['bundle_id'], 'bundle id')
    line_id = require_text(outer['line_id'], 'line id')
    revision_id = require_revision_id(outer['revision_id'])
    return bundle_id, line_id, revision_id


def _check_binding(outer: dict, body_fields: set[str]) -> dict:
    body = outer['body']
    _expect_fields(body, _IDENTITY_FIELDS | body_fields, 'body')
    require_revision_id(body['revision_id'])
    if any(body[key] != outer[key] for key in _IDENTITY_FIELDS):
        raise ValueError('bundle identity does not match body binding')
    if not isinstance(outer['digest'], str) or outer['digest'] != fingerprint_body(body):
        raise ValueError('station bundle digest mismatch')
    return body


def decode_envelope(payload: bytes) -> V1Envelope:
    outer = _parse_outer(payload)
    _expect_fields(outer, _IDENTITY_FIELDS | {'version', 'body', 'digest'}, 'envelope')
    if type(outer['version']) is not int or outer['version'] != 1:
        raise ValueError('unsupported station bundle version')
    body = _check_binding(outer, {'segments', 'missing'})
    return V1Envelope(*_read_identity(outer), _read_profile(body))


def decode_v2_envelope(payload: bytes) -> V2Envelope:
    outer = _parse_outer(payload)
    _expect_fields(outer, _IDENTITY_FIELDS | {'version', 'body', 'digest'}, 'envelope')
    if type(outer['version']) is not int or outer['version'] != 2:
        raise ValueError('unsupported station bundle version')
    body = _check_binding(outer, {'surface'})
    return V2Envelope(*_read_identity(outer), _read_surface(body))


def decode_any_envelope(payload: bytes):
    """Decode a version 1 or version 2 station bundle by its outer version."""
    outer = _parse_outer(payload)
    _expect_fields(outer, _IDENTITY_FIELDS | {'version', 'body', 'digest'}, 'envelope')
    version = outer['version']
    if type(version) is not int or version not in (1, 2):
        raise ValueError('unsupported station bundle version')
    if version == 1:
        body = _check_binding(outer, {'segments', 'missing'})
        return V1Envelope(*_read_identity(outer), _read_profile(body))
    body = _check_binding(outer, {'surface'})
    return V2Envelope(*_read_identity(outer), _read_surface(body))
