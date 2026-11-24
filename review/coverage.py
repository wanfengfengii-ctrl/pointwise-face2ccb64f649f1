from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from review.window import ClippedSpan, Window


@dataclass(frozen=True)
class CoverageResult:
    gaps: tuple[ClippedSpan, ...]

    @property
    def complete(self) -> bool:
        return not self.gaps


def merge_coverage(spans: Iterable[ClippedSpan]) -> tuple[ClippedSpan, ...]:
    """Union measured spans, all of which have an included left endpoint."""
    merged: list[ClippedSpan] = []
    for span in sorted(spans, key=lambda item: (item.start, item.end, item.right_closed)):
        if not merged or span.start > merged[-1].end:
            merged.append(span)
            continue
        previous = merged[-1]
        if (span.end, span.right_closed) > (previous.end, previous.right_closed):
            merged[-1] = ClippedSpan(previous.start, span.end, True, span.right_closed)
    return tuple(merged)


def measure_coverage(
    window: Window, spans: Iterable[ClippedSpan], *, before: Fraction | None = None,
) -> CoverageResult:
    """Complement clipped measured spans in the closed window or its open-ended prefix."""
    if before is not None and not window.start <= before <= window.end:
        raise ValueError('coverage prefix ends outside the window')
    end = window.end if before is None else before
    end_closed = before is None
    if end == window.start and not end_closed:
        return CoverageResult(())
    gaps = []
    cursor = window.start
    cursor_uncovered = True
    for span in merge_coverage(spans):
        if span.start > end or (span.start == end and not end_closed):
            break
        if span.start > cursor:
            gaps.append(ClippedSpan(cursor, span.start, cursor_uncovered, False))
        if span.end > end or (span.end == end and (span.right_closed or not end_closed)):
            return CoverageResult(tuple(gaps))
        cursor = span.end
        cursor_uncovered = not span.right_closed
    if cursor < end or (cursor == end and end_closed and cursor_uncovered):
        gaps.append(ClippedSpan(cursor, end, cursor_uncovered, end_closed))
    return CoverageResult(tuple(gaps))
