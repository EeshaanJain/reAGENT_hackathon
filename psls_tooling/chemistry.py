"""Chemical identifier helpers for perturbation dataset ingestion."""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pubchempy as pcp
from rdkit import Chem
from rdkit.Chem import SaltRemover, inchi

INCHIKEY_PATTERN = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")


@dataclass(frozen=True)
class StructureResult:
    """Result of canonicalizing and conditionally desalting a SMILES string."""

    original_smiles: str | None
    canonical_smiles: str | None
    inchikey: str | None
    status: str
    desalted: bool
    removed_fragments: tuple[str, ...] = ()
    parent_candidate_smiles: str | None = None
    parent_candidate_inchikey: str | None = None


@dataclass(frozen=True)
class LookupResult:
    """Result returned by an optional external identifier resolver."""

    inchikey: str | None
    source: str | None
    status: str


FallbackResolver = Callable[[pd.Series], LookupResult]


def normalize_inchikey(value: object) -> str | None:
    """Return a normalized full InChIKey, or ``None`` when invalid."""
    if value is None or value is pd.NA:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        return None
    normalized = str(value).strip().upper()
    return normalized if INCHIKEY_PATTERN.fullmatch(normalized) else None


def is_valid_inchikey(value: object) -> bool:
    """Return whether ``value`` is a full, syntactically valid InChIKey."""
    return normalize_inchikey(value) is not None


def _canonical_smiles(mol: Chem.Mol) -> str:
    return Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)


def _inchikey(mol: Chem.Mol) -> str | None:
    try:
        return normalize_inchikey(inchi.MolToInchiKey(mol))
    except (RuntimeError, ValueError):
        return None


def _fragment_smiles(mol: Chem.Mol) -> list[str]:
    fragments = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=True)
    return [_canonical_smiles(fragment) for fragment in fragments]


def _removed_fragment_smiles(original: Chem.Mol, retained: Chem.Mol) -> list[str]:
    original_fragments = Counter(_fragment_smiles(original))
    retained_fragments = Counter(_fragment_smiles(retained))
    return list((original_fragments - retained_fragments).elements())


def standardize_smiles(
    value: object,
    *,
    max_removed_heavy_atoms: int = 12,
    max_removed_parent_ratio: float = 0.5,
    salt_remover: SaltRemover.SaltRemover | None = None,
) -> StructureResult:
    """Canonicalize SMILES and remove only recognized, sufficiently small salts.

    A recognized fragment is retained when it exceeds either configured size
    guard. This avoids silently collapsing mixtures or large, potentially
    functional counterions into a parent structure.
    """
    if value is None or value is pd.NA:
        return StructureResult(None, None, None, "missing_smiles", False)
    try:
        if bool(pd.isna(value)):
            return StructureResult(None, None, None, "missing_smiles", False)
    except (TypeError, ValueError):
        return StructureResult(None, None, None, "invalid_smiles", False)

    original_smiles = str(value).split(" |", maxsplit=1)[0].strip()
    if not original_smiles:
        return StructureResult(original_smiles, None, None, "missing_smiles", False)

    mol = Chem.MolFromSmiles(original_smiles)
    if mol is None:
        return StructureResult(original_smiles, None, None, "invalid_smiles", False)

    canonical_original = _canonical_smiles(mol)
    original_fragments = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=True)
    if len(original_fragments) == 1:
        return StructureResult(
            original_smiles,
            canonical_original,
            _inchikey(mol),
            "single_component",
            False,
        )

    remover = salt_remover or SaltRemover.SaltRemover()
    try:
        retained, _ = remover.StripMolWithDeleted(mol, dontRemoveEverything=True)
    except (RuntimeError, ValueError):
        return StructureResult(
            original_smiles,
            canonical_original,
            _inchikey(mol),
            "desalting_error",
            False,
        )

    retained_fragments = Chem.GetMolFrags(retained, asMols=True, sanitizeFrags=True)
    if len(retained_fragments) != 1 or len(retained_fragments) >= len(original_fragments):
        return StructureResult(
            original_smiles,
            canonical_original,
            _inchikey(mol),
            "multicomponent_preserved",
            False,
            parent_candidate_smiles=_canonical_smiles(retained),
            parent_candidate_inchikey=_inchikey(retained),
        )

    removed_smiles = _removed_fragment_smiles(mol, retained)
    retained_heavy_atoms = retained.GetNumHeavyAtoms()
    removed_molecules = [Chem.MolFromSmiles(smiles) for smiles in removed_smiles]
    exceeds_guard = any(
        fragment is None
        or fragment.GetNumHeavyAtoms() > max_removed_heavy_atoms
        or retained_heavy_atoms == 0
        or fragment.GetNumHeavyAtoms() / retained_heavy_atoms > max_removed_parent_ratio
        for fragment in removed_molecules
    )

    candidate_smiles = _canonical_smiles(retained)
    candidate_inchikey = _inchikey(retained)
    if exceeds_guard:
        return StructureResult(
            original_smiles,
            canonical_original,
            _inchikey(mol),
            "large_fragment_preserved",
            False,
            tuple(removed_smiles),
            candidate_smiles,
            candidate_inchikey,
        )

    return StructureResult(
        original_smiles,
        candidate_smiles,
        candidate_inchikey,
        "desalted",
        True,
        tuple(removed_smiles),
        candidate_smiles,
        candidate_inchikey,
    )


def pubchem_lookup(query: object, *, namespace: str = "name") -> LookupResult:
    """Resolve a unique PubChem result without choosing an arbitrary first hit."""
    if query is None or query is pd.NA or not str(query).strip():
        return LookupResult(None, None, "missing_query")
    try:
        compounds = pcp.get_compounds(query, namespace)
    except (pcp.PubChemHTTPError, pcp.BadRequestError, TimeoutError, ConnectionError, ValueError):
        return LookupResult(None, None, "lookup_error")

    keys = {key for compound in compounds if (key := normalize_inchikey(compound.inchikey))}
    if len(keys) == 1:
        return LookupResult(keys.pop(), f"pubchem_{namespace}", "resolved")
    if len(keys) > 1:
        return LookupResult(None, f"pubchem_{namespace}", "ambiguous")
    return LookupResult(None, f"pubchem_{namespace}", "not_found")


def chembl_name_lookup(database: str | Path, names: list[str]) -> dict[str, LookupResult]:
    """Resolve unambiguous ChEMBL preferred names or synonyms from a local database."""
    path = Path(database).resolve()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    results: dict[str, LookupResult] = {}
    query = """
        SELECT cs.standard_inchi_key
        FROM molecule_dictionary AS md
        JOIN compound_structures AS cs ON md.molregno = cs.molregno
        LEFT JOIN molecule_synonyms AS ms ON md.molregno = ms.molregno
        WHERE md.pref_name = ? COLLATE NOCASE OR ms.synonyms = ? COLLATE NOCASE
    """
    try:
        cursor = connection.cursor()
        for name in dict.fromkeys(str(item).strip() for item in names if str(item).strip()):
            cursor.execute(query, (name, name))
            keys = {key for row in cursor.fetchall() if (key := normalize_inchikey(row[0]))}
            if len(keys) == 1:
                results[name] = LookupResult(keys.pop(), "chembl_name", "resolved")
            elif len(keys) > 1:
                results[name] = LookupResult(None, "chembl_name", "ambiguous")
            else:
                results[name] = LookupResult(None, "chembl_name", "not_found")
    finally:
        connection.close()
    return results


def resolve_compounds(
    compounds: pd.DataFrame,
    *,
    inchikey_col: str | None = "inchikey",
    smiles_col: str | None = "SMILES",
    fallback_resolver: FallbackResolver | None = None,
) -> pd.DataFrame:
    """Resolve a unique-compound table using identifiers, structures, then a fallback."""
    resolved_rows: list[dict[str, Any]] = []
    for _, row in compounds.iterrows():
        key = normalize_inchikey(row.get(inchikey_col)) if inchikey_col else None
        source = "provided_inchikey" if key else None
        chemical_status = "provided_inchikey" if key else "unresolved"
        structure = StructureResult(None, None, None, "not_attempted", False)

        if not key and smiles_col:
            structure = standardize_smiles(row.get(smiles_col))
            key = structure.inchikey
            if key:
                source = "smiles_rdkit"
                chemical_status = structure.status

        if not key and fallback_resolver:
            lookup = fallback_resolver(row)
            key = normalize_inchikey(lookup.inchikey)
            source = lookup.source
            chemical_status = lookup.status

        resolved = row.to_dict()
        resolved.update(
            {
                "inchikey": key,
                "inchikey_source": source,
                "chemical_status": chemical_status,
                "canonical_smiles": structure.canonical_smiles,
                "desalted": structure.desalted,
                "removed_fragments": "|".join(structure.removed_fragments),
                "parent_candidate_smiles": structure.parent_candidate_smiles,
                "parent_candidate_inchikey": structure.parent_candidate_inchikey,
            }
        )
        resolved_rows.append(resolved)
    return pd.DataFrame(resolved_rows, index=compounds.index)


def drop_unresolved_treatments(
    adata: Any,
    *,
    inchikey_col: str = "inchikey",
    control_col: str = "control",
    name_col: str = "sm_name_original",
) -> tuple[Any, dict[str, Any]]:
    """Drop unresolved treated cells and return an auditable loss summary."""
    normalized = adata.obs[inchikey_col].map(normalize_inchikey)
    control = adata.obs[control_col].eq(True)
    unresolved = ~control & normalized.isna()
    names = adata.obs.loc[unresolved, name_col] if name_col in adata.obs else pd.Series(dtype=object)
    report = {
        "cells_before": int(adata.n_obs),
        "cells_removed": int(unresolved.sum()),
        "cells_after": int((~unresolved).sum()),
        "unresolved_compounds": sorted(names.dropna().astype(str).unique().tolist()),
    }
    result = adata[~unresolved].copy()
    result.obs[inchikey_col] = result.obs[inchikey_col].map(normalize_inchikey)
    return result, report


def structure_result_dict(result: StructureResult) -> dict[str, Any]:
    """Convert a structure result into a JSON-serializable dictionary."""
    return asdict(result)
