"""Shared Galatiq corpus file selection (matches Control Centre Capture)."""

from __future__ import annotations

from pathlib import Path

_RANK = {".txt": 0, ".json": 1, ".csv": 2, ".xml": 3, ".pdf": 4}


def sample_paths(data_dir: str | Path) -> list[Path]:
    """One file per invoice stem (prefer txt > json > csv > xml > pdf)."""
    data_dir = Path(data_dir)
    if not data_dir.exists():
        return []
    best: dict[str, Path] = {}
    for path in data_dir.iterdir():
        if not path.is_file():
            continue
        # Case CLI alias (invoice1.txt) duplicates INV-1001 — keep for brief path only.
        if path.stem.lower() in {"invoice1", "invoice"}:
            continue
        # Intentional unparseable stress files (still in --all / golden suite).
        if path.stem.lower().endswith("_bad"):
            continue
        suffix = path.suffix.lower()
        if suffix not in _RANK:
            continue
        stem = path.stem.replace("_revised", "")
        prev = best.get(stem)
        if prev is None or _RANK[suffix] < _RANK[prev.suffix.lower()]:
            best[stem] = path
        elif _RANK[suffix] == _RANK[prev.suffix.lower()] and "_revised" not in path.stem:
            best[stem] = path
    return sorted(best.values(), key=lambda p: p.name)


def resolve_files(data_dir: str | Path, names: tuple[str, ...]) -> list[Path]:
    """Resolve invoice filenames under data_dir; skip missing quietly."""
    root = Path(data_dir)
    out: list[Path] = []
    for name in names:
        path = root / name
        if path.is_file():
            out.append(path.resolve())
    return out
