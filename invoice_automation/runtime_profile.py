"""Runtime master-data profiles (prod default vs case corpus).

Notes
-----
``GALATIQ_PROFILE`` selects inventory hardening:

* ``prod`` (default) — strict catalog prices, PO coverage, no soft bands.
* ``case`` (alias ``corpus``) — soft price bands only; matches the case README
  corpus and scenario-proof matrix.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

ProfileName = Literal["prod", "case"]

_ALIASES: dict[str, ProfileName] = {
    "prod": "prod",
    "production": "prod",
    "case": "case",
    "corpus": "case",
    "demo": "case",
}

DEFAULT_PROFILE: ProfileName = "prod"


@dataclass(frozen=True)
class MasterDataFlags:
    """Inventory validation flags for one runtime profile."""

    profile: ProfileName
    require_price_check: bool
    require_po: bool
    soft_price_bands: bool


_PROFILE_FLAGS: dict[ProfileName, MasterDataFlags] = {
    "prod": MasterDataFlags(
        profile="prod",
        require_price_check=True,
        require_po=True,
        soft_price_bands=False,
    ),
    "case": MasterDataFlags(
        profile="case",
        require_price_check=False,
        require_po=False,
        soft_price_bands=True,
    ),
}


def normalize_profile(name: str | None) -> ProfileName:
    """Map a profile string to ``prod`` or ``case``.

    Parameters
    ----------
    name : str or None
        Raw profile. None or blank uses ``GALATIQ_PROFILE``, then ``prod``.

    Returns
    -------
    ProfileName
        Normalized profile name.
    """
    raw = (name if name is not None else os.environ.get("GALATIQ_PROFILE", "")).strip().lower()
    if not raw:
        return DEFAULT_PROFILE
    if raw not in _ALIASES:
        known = ", ".join(sorted(_ALIASES))
        raise ValueError(f"Unknown GALATIQ_PROFILE={raw!r}; expected one of: {known}")
    return _ALIASES[raw]


def resolve_master_data(
    *,
    profile: str | None = None,
    require_price_check: bool | None = None,
    require_po: bool | None = None,
    soft_price_bands: bool | None = None,
) -> MasterDataFlags:
    """Resolve master-data flags from profile plus optional overrides.

    Parameters
    ----------
    profile : str or None
        Profile name. None reads ``GALATIQ_PROFILE`` (default ``prod``).
    require_price_check : bool or None
        Override strict catalog checks when not None.
    require_po : bool or None
        Override PO coverage when not None.
    soft_price_bands : bool or None
        Override soft bands when not None.

    Returns
    -------
    MasterDataFlags
        Effective flags for ``SqliteInventoryRepository``.
    """
    base = _PROFILE_FLAGS[normalize_profile(profile)]
    price = base.require_price_check if require_price_check is None else require_price_check
    po = base.require_po if require_po is None else require_po
    soft = base.soft_price_bands if soft_price_bands is None else soft_price_bands
    if price:
        soft = False
    return MasterDataFlags(
        profile=base.profile,
        require_price_check=price,
        require_po=po,
        soft_price_bands=soft,
    )
