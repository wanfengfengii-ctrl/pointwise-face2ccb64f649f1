from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from intake.selection import normalize_bundle_ids
from review.window import Window, make_window
from survey.metres import parse_metres
from survey.provenance import require_text


@dataclass(frozen=True)
class SightLine:
    window: Window
    left_height: Fraction
    right_height: Fraction

    def height_at(self, chainage: Fraction) -> Fraction:
        if not self.window.start <= chainage <= self.window.end:
            raise ValueError('chainage is outside the sight line window')
        width = self.window.end - self.window.start
        if not width:
            return self.left_height
        return self.left_height + (self.right_height - self.left_height) * (
            (chainage - self.window.start) / width
        )


@dataclass(frozen=True)
class ReviewRequest:
    request_id: str
    line_id: str
    bundle_ids: tuple[str, ...]
    sight: SightLine


def make_request(
    request_id: str, line_id: str, bundle_ids: Iterable[str],
    start: object, end: object, left_height: object, right_height: object,
) -> ReviewRequest:
    require_text(request_id, 'review request id')
    require_text(line_id, 'line id')
    window = make_window(start, end)
    left, right = parse_metres(left_height), parse_metres(right_height)
    if window.start == window.end and left != right:
        raise ValueError('point window requires equal sight heights')
    return ReviewRequest(request_id, line_id, normalize_bundle_ids(bundle_ids), SightLine(window, left, right))
