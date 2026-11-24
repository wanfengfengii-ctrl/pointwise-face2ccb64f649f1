from collections.abc import Iterable
from dataclasses import dataclass

from intake.catalog import AcceptedCatalog
from intake.selection import select_bundles, select_highest
from reports.publication import PublicationStore, publish
from reports.receipts import Receipt
from reports.snapshots import ReportSnapshot, build_snapshot
from review.coverage import measure_coverage
from review.highest import coalesce, earliest_highest_block, measured_spans
from review.intersection import earliest_block
from review.request import make_request
from review.window import clip_span


@dataclass(frozen=True)
class Assessment:
    report: ReportSnapshot
    receipt: Receipt


def assess(
    catalog: AcceptedCatalog, archive: PublicationStore, *,
    request_id: str, line_id: str, bundle_ids: Iterable[str], start: object,
    end: object, left_height: object, right_height: object,
) -> Assessment:
    request = make_request(request_id, line_id, bundle_ids, start, end, left_height, right_height)
    selection = select_bundles(catalog, request.line_id, request.bundle_ids, version=1)
    evidence = tuple(
        (bundle.bundle_id, bundle.envelope.revision_id, segment)
        for bundle in selection.bundles
        for segment in bundle.envelope.profile.segments
    )
    block = earliest_block(request.sight, evidence)
    window = request.sight.window
    coverage = measure_coverage(
        window,
        (clipped for _, _, segment in evidence if (clipped := clip_span(window, segment)) is not None),
        before=block.chainage if block is not None else None,
    )
    snapshot = build_snapshot(request, block, coverage)
    report, receipt = publish(archive, snapshot)
    return Assessment(report, receipt)


def assess_highest(
    catalog: AcceptedCatalog, archive: PublicationStore, *,
    request_id: str, line_id: str, bundle_ids: Iterable[str], start: object,
    end: object, left_height: object, right_height: object,
) -> Assessment:
    request = make_request(request_id, line_id, bundle_ids, start, end, left_height, right_height)
    selection = select_highest(catalog, request.line_id, request.bundle_ids)
    spans, points = coalesce(selection)
    block = earliest_highest_block(request.sight, spans, points)
    window = request.sight.window
    coverage = measure_coverage(
        window, measured_spans(window, spans, points),
        before=block.chainage if block is not None else None,
    )
    snapshot = build_snapshot(request, block, coverage)
    report, receipt = publish(archive, snapshot)
    return Assessment(report, receipt)
