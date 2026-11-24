"""Highest measured surface carried by a version 2 station bundle.

Only usable original segments take part.  For every measured chainage the
surface records the exact highest measured rational height together with the
original segment records that reach it; lower segments and missing segments stay
at the station.  A segment that only reaches the surface at a single chainage
(for example the closed right end of a segment that rises to a crossing) is kept
as a point tie, never as a range.  Every boundary value is taken from the
segments that actually measure that chainage, so an open original endpoint
contributes no measured value of its own.

Span shape (the wire format repeats the same fields)::

    start, end              exact rational text, start < end
    left_closed, right_closed   whether each end is a measured chainage
    left_height, right_height   exact rational text; affine on the span
    supports                original segment records reaching the surface

Point ties are separate records holding a single ``chainage`` and ``height``
with their own supports.  Both ends of a span therefore distinguish open and
closed attribution, and a point tie is distinguishable from a span by its shape.
"""

from dataclasses import dataclass
from fractions import Fraction

from issue.profiles import ProfileEvidence, SegmentEvidence
from survey.provenance import SourceRef


@dataclass(frozen=True, order=True)
class SurfaceSupport:
    segment_id: str
    source: SourceRef


@dataclass(frozen=True)
class SurfacePoint:
    chainage: Fraction
    height: Fraction
    supports: tuple[SurfaceSupport, ...]


@dataclass(frozen=True)
class SurfaceSpan:
    start: Fraction
    end: Fraction
    left_closed: bool
    right_closed: bool
    left_height: Fraction
    right_height: Fraction
    supports: tuple[SurfaceSupport, ...]

    def covers(self, chainage: Fraction) -> bool:
        if chainage < self.start or chainage > self.end:
            return False
        if chainage == self.start and not self.left_closed:
            return False
        if chainage == self.end and not self.right_closed:
            return False
        return True

    def line_height(self, chainage: Fraction) -> Fraction:
        """Evaluate the affine relation anywhere in ``[start, end]``."""
        width = self.end - self.start
        if not width:
            return self.left_height
        return self.left_height + (self.right_height - self.left_height) * (
            (chainage - self.start) / width
        )

    def height_at(self, chainage: Fraction) -> Fraction:
        if not self.covers(chainage):
            raise ValueError('chainage is outside the highest-surface span')
        return self.line_height(chainage)


@dataclass(frozen=True)
class HighestSurface:
    spans: tuple[SurfaceSpan, ...] = ()
    points: tuple[SurfacePoint, ...] = ()

    def height_at(self, chainage: Fraction):
        if not isinstance(chainage, Fraction):
            return None
        for span in self.spans:
            if span.covers(chainage):
                return span.height_at(chainage)
        for point in self.points:
            if point.chainage == chainage:
                return point.height
        return None

    def supports_at(self, chainage: Fraction, height: Fraction) -> tuple[SurfaceSupport, ...]:
        found = set()
        for span in self.spans:
            if span.covers(chainage) and span.height_at(chainage) == height:
                found.update(span.supports)
        for point in self.points:
            if point.chainage == chainage and point.height == height:
                found.update(point.supports)
        return tuple(sorted(found))


def _covers(segment: SegmentEvidence, chainage: Fraction) -> bool:
    if chainage < segment.start or chainage > segment.end:
        return False
    if chainage == segment.end and not segment.terminal:
        return False
    return True


def _support(segment: SegmentEvidence) -> SurfaceSupport:
    return SurfaceSupport(segment.segment_id, segment.source)


def _attaining(segments, chainage: Fraction):
    """Segments that measure this chainage and reach its highest value."""
    covering = [segment for segment in segments if _covers(segment, chainage)]
    if not covering:
        return None
    height = max(segment.height_at(chainage) for segment in covering)
    return (height, tuple(sorted(
        (segment for segment in covering if segment.height_at(chainage) == height),
        key=lambda segment: segment.segment_id,
    )))


def _ids(active) -> tuple[str, ...]:
    return tuple(segment.segment_id for segment in active)


def _merge_runs(runs):
    merged = []
    for start, end, active in runs:
        if merged and merged[-1][1] == start and _ids(merged[-1][2]) == _ids(active):
            merged[-1] = (merged[-1][0], end, active)
        else:
            merged.append((start, end, active))
    return merged


def _critical_points(segments):
    critical = set()
    for segment in segments:
        critical.add(segment.start)
        critical.add(segment.end)
    for index, first in enumerate(segments):
        for second in segments[index + 1:]:
            low = max(first.start, second.start)
            high = min(first.end, second.end)
            if low > high:
                continue
            slope_a = (first.right_height - first.left_height) / (first.end - first.start)
            slope_b = (second.right_height - second.left_height) / (second.end - second.start)
            if slope_a == slope_b:
                continue
            intercept_a = first.left_height - slope_a * first.start
            intercept_b = second.left_height - slope_b * second.start
            crossing = (intercept_b - intercept_a) / (slope_a - slope_b)
            if low <= crossing <= high:
                critical.add(crossing)
    return sorted(critical)


def build_highest_surface(profile: ProfileEvidence) -> HighestSurface:
    segments = tuple(profile.segments)
    if not segments:
        return HighestSurface()

    ordered = _critical_points(segments)
    runs = []
    for start, end in zip(ordered, ordered[1:]):
        if start >= end:
            continue
        middle = (start + end) / 2
        values = [(segment, segment.height_at(middle))
                  for segment in segments if segment.start < middle < segment.end]
        if not values:
            continue
        highest = max(value for _, value in values)
        active = tuple(sorted((segment for segment, value in values if value == highest),
                              key=lambda segment: segment.segment_id))
        runs.append((start, end, active))

    attaining = {chainage: _attaining(segments, chainage) for chainage in ordered}

    spans = []
    for start, end, active in _merge_runs(runs):
        active_ids = _ids(active)
        left_found = attaining[start]
        right_found = attaining[end]
        left_closed = left_found is not None and _ids(left_found[1]) == active_ids
        right_closed = right_found is not None and _ids(right_found[1]) == active_ids
        spans.append(SurfaceSpan(
            start, end, left_closed, right_closed,
            active[0].height_at(start), active[0].height_at(end),
            tuple(sorted(_support(segment) for segment in active)),
        ))

    points = []
    for chainage in ordered:
        found = attaining[chainage]
        if found is None:
            continue
        height, active = found
        represented = set()
        for span in spans:
            if span.covers(chainage):
                represented.update(support.segment_id for support in span.supports)
        extra = [segment for segment in active if segment.segment_id not in represented]
        if extra:
            points.append(SurfacePoint(
                chainage, height,
                tuple(sorted(_support(segment) for segment in extra)),
            ))
    return HighestSurface(tuple(spans), tuple(points))
