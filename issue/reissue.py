import json

from issue.envelope import V1Envelope, V2Envelope, encode_envelope, encode_v2_envelope
from issue.profiles import build_profile
from issue.registry import IssueEntry, IssueRegistry
from issue.surface import build_highest_surface
from survey.provenance import require_text
from survey.revisions import RevisionStore, require_revision_id


def issued_version(payload: bytes) -> int:
    data = json.loads(payload.decode('utf-8'))
    return data['version']


def _existing(
    registry: IssueRegistry, request_id: str, revision_id: int, version: int
) -> IssueEntry | None:
    existing = registry.find_request(request_id)
    if existing is None:
        return None
    if existing.revision_id != revision_id:
        raise ValueError('issue request is already bound to another revision')
    if issued_version(existing.payload) != version:
        raise ValueError('issue request is already bound to another issue version')
    return existing


def release(revisions: RevisionStore, registry: IssueRegistry, revision_id: int, request_id: str) -> IssueEntry:
    require_revision_id(revision_id)
    require_text(request_id, 'issue request id')
    registry.db.execute('BEGIN IMMEDIATE')
    with registry.db:
        previous = _existing(registry, request_id, revision_id, 1)
        if previous is not None:
            return previous
        revision = revisions.get(revision_id)
        bundle_id = f'B:{request_id}'
        envelope = V1Envelope(bundle_id, revision.line_id, revision_id, build_profile(revision))
        entry = IssueEntry(request_id, revision_id, bundle_id, encode_envelope(envelope))
        registry.store(entry)
    return entry


def release_highest(
    revisions: RevisionStore, registry: IssueRegistry, revision_id: int, request_id: str
) -> IssueEntry:
    """Issue the highest measured surface of a fixed revision as a V2 bundle."""
    require_revision_id(revision_id)
    require_text(request_id, 'issue request id')
    registry.db.execute('BEGIN IMMEDIATE')
    with registry.db:
        previous = _existing(registry, request_id, revision_id, 2)
        if previous is not None:
            return previous
        revision = revisions.get(revision_id)
        bundle_id = f'B:{request_id}'
        surface = build_highest_surface(build_profile(revision))
        envelope = V2Envelope(bundle_id, revision.line_id, revision_id, surface)
        entry = IssueEntry(request_id, revision_id, bundle_id, encode_v2_envelope(envelope))
        registry.store(entry)
    return entry
