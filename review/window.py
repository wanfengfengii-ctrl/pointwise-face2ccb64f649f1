from dataclasses import dataclass
from fractions import Fraction

from issue.profiles import SegmentEvidence
from survey.metres import parse_metres


@dataclass(frozen=True)
class Window:
    start: Fraction
    end: Fraction


@dataclass(frozen=True)
class ClippedSpan:
    start: Fraction
    end: Fraction
    left_closed: bool
    right_closed: bool


def make_window(start: object, end: object) -> Window:
    left, right = parse_metres(start), parse_metres(end)
    if left > right:
        raise ValueError('review window requires ordered endpoints')
    return Window(left, right)


def clip_span(window: Window, segment: SegmentEvidence) -> ClippedSpan | None:
    start = max(window.start, segment.start)
    end = min(window.end, segment.end)
    right_closed = end < segment.end or segment.terminal
    if start > end or (start == end and not right_closed):
        return None
    return ClippedSpan(start, end, True, right_closed)
