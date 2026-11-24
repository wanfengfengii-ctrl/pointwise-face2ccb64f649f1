from dataclasses import dataclass

from issue.envelope import V1Envelope, decode_envelope, encode_envelope


@dataclass(frozen=True)
class ValidatedBundle:
    envelope: V1Envelope
    payload: bytes
    canonical: bytes


def validate_bundle(payload: bytes) -> ValidatedBundle:
    envelope = decode_envelope(payload)
    return ValidatedBundle(envelope, payload, encode_envelope(envelope))
