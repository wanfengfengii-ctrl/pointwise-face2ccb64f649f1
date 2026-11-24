import json
from dataclasses import dataclass

from review.coverage import CoverageResult
from review.intersection import BlockEvidence, BlockSupport
from review.request import ReviewRequest, make_request
from review.window import ClippedSpan
from survey.metres import encode_metres, parse_metres
from survey.provenance import parse_source_ref


@dataclass(frozen=True)
class ReportSnapshot:
    report_id: str
    request: ReviewRequest
    status: str
    block: BlockEvidence | None
    coverage: CoverageResult

    @property
    def earlier_covered(self) -> bool | None:
        return None if self.block is None else self.coverage.complete


def build_snapshot(
    request: ReviewRequest, block: BlockEvidence | None, coverage: CoverageResult
) -> ReportSnapshot:
    if block is None:
        status = 'clear' if coverage.complete else 'needs_survey'
    else:
        status = 'blocked_confirmed' if coverage.complete else 'blocked_pending'
    return ReportSnapshot(f'RPT:{request.request_id}', request, status, block, coverage)


def _encode_request(request: ReviewRequest) -> dict:
    sight = request.sight
    return {
        'request_id': request.request_id,
        'line_id': request.line_id,
        'bundle_ids': list(request.bundle_ids),
        'start': encode_metres(sight.window.start),
        'end': encode_metres(sight.window.end),
        'left_height': encode_metres(sight.left_height),
        'right_height': encode_metres(sight.right_height),
    }


def _encode_block(block: BlockEvidence | None) -> dict | None:
    if block is None:
        return None
    return {
        'chainage': encode_metres(block.chainage),
        'supports': [
            {'bundle_id': support.bundle_id, 'revision_id': support.revision_id,
             'segment_id': support.segment_id, 'source': support.source.to_data()}
            for support in block.supports
        ],
    }


def encode_snapshot(report: ReportSnapshot) -> str:
    data = {
        'report_id': report.report_id,
        'request': _encode_request(report.request),
        'status': report.status,
        'earlier_covered': report.earlier_covered,
        'block': _encode_block(report.block),
        'coverage': {
            'complete': report.coverage.complete,
            'gaps': [
                {'start': encode_metres(gap.start), 'end': encode_metres(gap.end),
                 'left_closed': gap.left_closed, 'right_closed': gap.right_closed}
                for gap in report.coverage.gaps
            ],
        },
    }
    return json.dumps(data, sort_keys=True, separators=(',', ':'))


def _decode_block(data: dict | None) -> BlockEvidence | None:
    if data is None:
        return None
    supports = tuple(
        BlockSupport(row['bundle_id'], row['revision_id'], row['segment_id'], parse_source_ref(row['source']))
        for row in data['supports']
    )
    return BlockEvidence(parse_metres(data['chainage']), supports)


def decode_snapshot(payload: str) -> ReportSnapshot:
    data = json.loads(payload)
    request = make_request(**data['request'])
    coverage = CoverageResult(tuple(
        ClippedSpan(parse_metres(gap['start']), parse_metres(gap['end']),
                    gap['left_closed'], gap['right_closed'])
        for gap in data['coverage']['gaps']
    ))
    return ReportSnapshot(data['report_id'], request, data['status'], _decode_block(data['block']), coverage)
