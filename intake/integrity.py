from dataclasses import dataclass

from issue.envelope import V1Envelope, V2Envelope, decode_any_envelope, encode_envelope, encode_v2_envelope


@dataclass(frozen=True)
class ValidatedBundle:
    envelope: V1Envelope | V2Envelope
    payload: bytes
    canonical: bytes

    @property
    def version(self) -> int:
        return 1 if isinstance(self.envelope, V1Envelope) else 2


def validate_bundle(payload: bytes) -> ValidatedBundle:
    envelope = decode_any_envelope(payload)
    canonical = encode_envelope(envelope) if isinstance(envelope, V1Envelope) else encode_v2_envelope(envelope)
    return ValidatedBundle(envelope, payload, canonical)
