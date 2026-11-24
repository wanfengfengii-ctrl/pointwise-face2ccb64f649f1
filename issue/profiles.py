from dataclasses import dataclass
from fractions import Fraction

from survey.provenance import SourceRef, parse_source_ref, require_text
from survey.revisions import SurveyRevision


@dataclass(frozen=True)
class SegmentEvidence:
    segment_id: str
    start: Fraction
    end: Fraction
    terminal: bool
    source: SourceRef
    left_height: Fraction
    right_height: Fraction

    def height_at(self, chainage: Fraction) -> Fraction:
        """Evaluate the segment line, including its right-side limit."""
        return self.left_height + (self.right_height - self.left_height) * (
            (chainage - self.start) / (self.end - self.start)
        )


@dataclass(frozen=True)
class MissingSpan:
    segment_id: str
    start: Fraction
    end: Fraction
    terminal: bool
    source: SourceRef
    reason: str


@dataclass(frozen=True)
class ProfileEvidence:
    segments: tuple[SegmentEvidence, ...]
    missing: tuple[MissingSpan, ...]


def build_profile(revision: SurveyRevision) -> ProfileEvidence:
    segments = []
    missing = []
    for row, decision in zip(revision.observations, revision.dispositions, strict=True):
        bounds = (row.segment_id, row.start, row.end, row.terminal, row.source)
        if decision.usable:
            segments.append(SegmentEvidence(*bounds, row.left_height, row.right_height))
        else:
            missing.append(MissingSpan(*bounds, decision.reason))
    return ProfileEvidence(
        tuple(sorted(segments, key=lambda segment: segment.segment_id)),
        tuple(sorted(missing, key=lambda segment: segment.segment_id)),
    )


def validate_profile(profile: ProfileEvidence) -> None:
    seen = set()
    for row in (*profile.segments, *profile.missing):
        require_text(row.segment_id, 'segment id')
        if row.segment_id in seen:
            raise ValueError('duplicate segment in profile')
        seen.add(row.segment_id)
        if not isinstance(row.start, Fraction) or not isinstance(row.end, Fraction):
            raise ValueError('invalid segment bounds')
        if row.start >= row.end or type(row.terminal) is not bool:
            raise ValueError('invalid segment bounds or terminal flag')
        parse_source_ref(row.source.to_data())
    for row in profile.segments:
        if not isinstance(row.left_height, Fraction) or not isinstance(row.right_height, Fraction):
            raise ValueError('invalid evidence height')
    for row in profile.missing:
        if row.reason not in ('survey_flag', 'instrument_check'):
            raise ValueError('invalid missing-span reason')
