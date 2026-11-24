from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from issue.profiles import SegmentEvidence
from review.request import SightLine
from review.window import clip_span
from survey.provenance import SourceRef


@dataclass(frozen=True, order=True)
class BlockSupport:
    bundle_id: str
    revision_id: int
    segment_id: str
    source: SourceRef


@dataclass(frozen=True)
class BlockEvidence:
    chainage: Fraction
    supports: tuple[BlockSupport, ...]


def first_span_hit(segment: SegmentEvidence, sight: SightLine) -> Fraction | None:
    span = clip_span(sight.window, segment)
    if span is None:
        return None
    left_delta = segment.height_at(span.start) - sight.height_at(span.start)
    if left_delta >= 0:
        return span.start
    right_delta = segment.height_at(span.end) - sight.height_at(span.end)
    if right_delta < 0 or (right_delta == 0 and not span.right_closed):
        return None
    return span.start - left_delta * (span.end - span.start) / (right_delta - left_delta)


def earliest_block(
    sight: SightLine, evidence: Iterable[tuple[str, int, SegmentEvidence]]
) -> BlockEvidence | None:
    first = None
    supports = set()
    for bundle_id, revision_id, segment in evidence:
        hit = first_span_hit(segment, sight)
        if hit is None or (first is not None and hit > first):
            continue
        if first is None or hit < first:
            first = hit
            supports.clear()
        supports.add(BlockSupport(bundle_id, revision_id, segment.segment_id, segment.source))
    if first is None:
        return None
    return BlockEvidence(first, tuple(sorted(supports)))
