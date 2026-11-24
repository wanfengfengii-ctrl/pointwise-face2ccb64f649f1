from collections.abc import Iterable
from dataclasses import dataclass

from intake.catalog import AcceptedBundle, AcceptedCatalog
from survey.provenance import require_text


def normalize_bundle_ids(bundle_ids: Iterable[str]) -> tuple[str, ...]:
    if isinstance(bundle_ids, (str, bytes, dict)):
        raise ValueError('bundle ids require a collection of individual ids')
    try:
        return tuple(sorted({require_text(bundle_id, 'bundle id') for bundle_id in bundle_ids}))
    except TypeError as exc:
        raise ValueError('bundle ids require a collection of individual ids') from exc


@dataclass(frozen=True)
class SelectedBundles:
    line_id: str
    bundles: tuple[AcceptedBundle, ...]


def select_bundles(catalog: AcceptedCatalog, line_id: str, bundle_ids: Iterable[str]) -> SelectedBundles:
    require_text(line_id, 'line id')
    selected = []
    for bundle_id in normalize_bundle_ids(bundle_ids):
        try:
            bundle = catalog.get(bundle_id)
        except KeyError as exc:
            raise ValueError(f'bundle has not been accepted: {bundle_id}') from exc
        if bundle.line_id != line_id:
            raise ValueError(f'bundle belongs to another survey line: {bundle_id}')
        selected.append(bundle)
    return SelectedBundles(line_id, tuple(selected))
