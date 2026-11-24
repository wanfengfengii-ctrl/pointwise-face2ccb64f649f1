from intake.catalog import AcceptedCatalog
from intake.integrity import validate_bundle


def receive(catalog: AcceptedCatalog, payload: bytes) -> str:
    return catalog.accept(validate_bundle(payload))
