from issue.envelope import V1Envelope, encode_envelope
from issue.profiles import build_profile
from issue.registry import IssueEntry, IssueRegistry
from survey.provenance import require_text
from survey.revisions import RevisionStore, require_revision_id


def release(revisions: RevisionStore, registry: IssueRegistry, revision_id: int, request_id: str) -> IssueEntry:
    require_revision_id(revision_id)
    require_text(request_id, 'issue request id')
    registry.db.execute('BEGIN IMMEDIATE')
    with registry.db:
        existing = registry.find_request(request_id)
        if existing is not None:
            if existing.revision_id != revision_id:
                raise ValueError('issue request is already bound to another revision')
            return existing
        revision = revisions.get(revision_id)
        bundle_id = f'B:{request_id}'
        envelope = V1Envelope(bundle_id, revision.line_id, revision_id, build_profile(revision))
        entry = IssueEntry(request_id, revision_id, bundle_id, encode_envelope(envelope))
        registry.store(entry)
    return entry
