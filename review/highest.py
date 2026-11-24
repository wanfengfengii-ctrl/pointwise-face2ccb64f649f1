"""Review a sight line against the highest measured surface of V2 bundles.

The selected bundles carry only the highest measured surface.  Their measured
positions are joined: at every chainage the common highest height is the maximum
over the selected surfaces, and the supports signed at a hit are exactly the
original segment records that reach that common height.  Lower segments and
missing segments were kept at the station and cannot appear here.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from issue.surface import SurfacePoint, SurfaceSpan, SurfaceSupport
from review.intersection import BlockEvidence, BlockSupport
from review.request import SightLine
from review.window import ClippedSpan, clip_span


@dataclass(frozen=True)
class _TaggedSpan:
    bundle_id: str
    revision_id: int
    span: SurfaceSpan


@dataclass(frozen=True)
class _TaggedPoint:
    bundle_id: str
    revision_id: int
    point: SurfacePoint


def coalesce(selection) -> tuple[list[_TaggedSpan], list[_TaggedPoint]]:
    spans = []
    points = []
    for bundle in selection.bundles:
        surface = bundle.envelope.surface
        for span in surface.spans:
            spans.append(_TaggedSpan(bundle.bundle_id, bundle.envelope.revision_id, span))
        for point in surface.points:
            points.append(_TaggedPoint(bundle.bundle_id, bundle.envelope.revision_id, point))
    return spans, points


def _span_line(span: SurfaceSpan) -> tuple[Fraction, Fraction]:
    slope = (span.right_height - span.left_height) / (span.end - span.start)
    return slope, span.left_height - slope * span.start


def _height(tagged: _TaggedSpan, chainage: Fraction) -> Fraction:
    return tagged.span.line_height(chainage)


def _combined_height(spans, points, chainage: Fraction):
    values = [_height(item, chainage) for item in spans if item.span.covers(chainage)]
    values.extend(point.point.height for point in points if point.point.chainage == chainage)
    if not values:
        return None
    return max(values)


def _measured(spans, points, chainage: Fraction) -> bool:
    if any(item.span.covers(chainage) for item in spans):
        return True
    return any(point.point.chainage == chainage for point in points)


def _supports_at(spans, points, chainage: Fraction, height: Fraction) -> tuple[BlockSupport, ...]:
    found = set()
    for item in spans:
        if item.span.covers(chainage) and item.span.height_at(chainage) == height:
            for support in item.span.supports:
                found.add(BlockSupport(item.bundle_id, item.revision_id, support.segment_id, support.source))
    for item in points:
        if item.point.chainage == chainage and item.point.height == height:
            for support in item.point.supports:
                found.add(BlockSupport(item.bundle_id, item.revision_id, support.segment_id, support.source))
    return tuple(sorted(found))


def _crossings(spans, low: Fraction, high: Fraction) -> list[Fraction]:
    found = []
    for index, first in enumerate(spans):
        first_slope, first_intercept = _span_line(first.span)
        for second in spans[index + 1:]:
            second_slope, second_intercept = _span_line(second.span)
            if first_slope == second_slope:
                continue
            crossing = (second_intercept - first_intercept) / (first_slope - second_slope)
            if crossing <= low or crossing >= high:
                continue
            first_low, first_high = first.span.start, first.span.end
            second_low, second_high = second.span.start, second.span.end
            if first_low < crossing < first_high and second_low < crossing < second_high:
                found.append(crossing)
    return found


def _breakpoints(spans, points, window) -> list[Fraction]:
    low, high = window.start, window.end
    values = {low, high}
    for item in spans:
        for edge in (item.span.start, item.span.end):
            if low <= edge <= high:
                values.add(edge)
    for item in points:
        if low <= item.point.chainage <= high:
            values.add(item.point.chainage)
    values.update(_crossings(spans, low, high))
    return sorted(values)


def _active_line(spans, chainage: Fraction):
    best = None
    winner = None
    for item in spans:
        if not item.span.start < chainage < item.span.end:
            continue
        value = _height(item, chainage)
        if best is None or value > best:
            best = value
            winner = item
    return winner


def _first_in_interval(item: _TaggedSpan, sight: SightLine, low: Fraction, high: Fraction):
    slope, intercept = _span_line(item.span)
    sight_width = sight.window.end - sight.window.start
    sight_slope = Fraction(0) if not sight_width else (sight.right_height - sight.left_height) / sight_width
    sight_intercept = sight.left_height - sight_slope * sight.window.start
    delta_slope = slope - sight_slope
    delta_intercept = intercept - sight_intercept
    if delta_slope <= 0:
        return None
    crossing = -delta_intercept / delta_slope
    if low < crossing < high:
        return crossing
    return None


def earliest_highest_block(
    sight: SightLine, spans, points
) -> BlockEvidence | None:
    window = sight.window
    ordered = _breakpoints(spans, points, window)
    candidates: list[Fraction] = []
    for chainage in ordered:
        height = _combined_height(spans, points, chainage)
        if height is None or not _measured(spans, points, chainage):
            continue
        if height >= sight.height_at(chainage):
            candidates.append(chainage)
    for low, high in zip(ordered, ordered[1:]):
        if low >= high:
            continue
        middle = (low + high) / 2
        winner = _active_line(spans, middle)
        if winner is None:
            continue
        crossing = _first_in_interval(winner, sight, low, high)
        if crossing is not None:
            candidates.append(crossing)
    if not candidates:
        return None
    hit = min(candidates)
    height = _combined_height(spans, points, hit)
    return BlockEvidence(hit, _supports_at(spans, points, hit, height))


def measured_spans(window, spans, points) -> tuple[ClippedSpan, ...]:
    """Union of measured domains as clipped spans, for coverage complementing.

    A surface span begins either at a segment end or at an interior crossing, so
    its left end is always a measured chainage; only the right end can be absent
    from the measured domain.  The window cut itself is always measured.
    """
    clipped = []
    for item in spans:
        span = item.span
        start = max(window.start, span.start)
        end = min(window.end, span.end)
        if start > end:
            continue
        right_closed = span.right_closed if end == span.end else True
        if start == end and not right_closed:
            continue
        clipped.append(ClippedSpan(start, end, True, right_closed))
    for item in points:
        chainage = item.point.chainage
        if window.start <= chainage <= window.end:
            clipped.append(ClippedSpan(chainage, chainage, True, True))
    return tuple(clipped)
