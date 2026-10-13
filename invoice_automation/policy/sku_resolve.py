"""Generic catalog SKU resolution by confidence tier.

Notes
-----
This module does not encode product-specific aliases. Callers pass the
live catalog. Matching uses compact equality, relative edit distance,
short unique prefixes/initials, variant suffixes, and ambiguity ties.
Soft issue codes escalate to VP; ``none`` leaves the raw SKU for
inventory ``unknown_item``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from invoice_automation.domain.models import LineItem
from invoice_automation.policy.invariants import SKU_TYPO_REVIEW_PREFIX

# Soft escalation when an unlisted variant of a known catalog SKU is billed.
SKU_VARIANT_REVIEW_PREFIX = "sku_variant_review"

_COMPACT = re.compile(r"[\s_-]+")
_HAS_DIGIT = re.compile(r"\d")
_ILLEGAL_CHAR = re.compile(r"[^A-Za-z0-9._\s-]")

# Relative edit-distance ceiling for a unique fuzzy match.
_REL_DIST_MAX = 0.34
# Compact forms at or below this length are abbreviations, not silent catalog codes.
# Unique initials map with UNIQUE_CLOSE → VP soft escalate (W-A → WidgetA).
# Digit OCR tokens (Widg3tA) never take this path — they stay unknown_item.
_ABBREV_MAX_LEN = 3
_ITEM_LINE = re.compile(r"(?im)^\s*Item\s*:\s*([^\n]+)")


class MatchConfidence(str, Enum):
    """Catalog match confidence for one extracted SKU."""

    EXACT = "exact"
    UNIQUE_CLOSE = "unique_close"
    AMBIGUOUS = "ambiguous"
    VARIANT = "variant"
    NONE = "none"


@dataclass(frozen=True)
class CatalogMatch:
    """Result of resolving one raw SKU against a catalog."""

    resolved: str
    confidence: MatchConfidence
    candidates: tuple[str, ...] = ()


def compact_sku(raw: str) -> str:
    """Lowercase SKU with spaces/underscores/hyphens removed."""
    return _COMPACT.sub("", str(raw or "")).casefold()


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (ca != cb)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def _initials(sku: str) -> str:
    """Build initials from PascalCase / separators (WidgetA → wa)."""
    text = str(sku or "")
    parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", text)
    if len(parts) >= 2:
        return "".join(p[0] for p in parts if p).casefold()
    compact = compact_sku(text)
    if len(compact) >= 2:
        return compact[0] + compact[-1]
    return compact


def _rel_dist(dist: int, a: str, b: str) -> float:
    denom = max(len(a), len(b), 1)
    return dist / denom


class CatalogResolver:
    """Confidence-tier SKU matcher against an arbitrary catalog.

    Parameters
    ----------
    catalog : sequence of str
        Known inventory SKU codes (from seed / DB).
    """

    def __init__(self, catalog: Sequence[str]) -> None:
        self.catalog: tuple[str, ...] = tuple(dict.fromkeys(str(s) for s in catalog if s))

    def resolve(self, raw: str) -> CatalogMatch:
        """Resolve one extracted SKU.

        Parameters
        ----------
        raw : str
            Extracted line SKU / description fragment.

        Returns
        -------
        CatalogMatch
            Resolved code (may equal ``raw``) and confidence tier.
        """
        text = str(raw or "").strip()
        if not text:
            return CatalogMatch(resolved=text, confidence=MatchConfidence.NONE)
        if text in self.catalog:
            return CatalogMatch(resolved=text, confidence=MatchConfidence.EXACT)
        if _ILLEGAL_CHAR.search(text):
            return CatalogMatch(resolved=text, confidence=MatchConfidence.NONE)

        compact = compact_sku(text)
        exact = [sku for sku in self.catalog if compact == compact_sku(sku)]
        if len(exact) == 1:
            return CatalogMatch(resolved=exact[0], confidence=MatchConfidence.EXACT)
        if len(exact) > 1:
            return CatalogMatch(
                resolved=exact[0],
                confidence=MatchConfidence.AMBIGUOUS,
                candidates=tuple(exact),
            )

        # Catalog prefix + extra suffix → variant of a known SKU.
        for sku in sorted(self.catalog, key=len, reverse=True):
            if text.startswith(sku) and len(text) > len(sku):
                return CatalogMatch(
                    resolved=sku,
                    confidence=MatchConfidence.VARIANT,
                    candidates=(sku,),
                )

        # Digits: refuse fuzzy (OCR leetspeak / alternate product codes).
        if _HAS_DIGIT.search(text):
            return CatalogMatch(resolved=text, confidence=MatchConfidence.NONE)

        ranked = sorted(
            ((sku, _levenshtein(compact, compact_sku(sku))) for sku in self.catalog),
            key=lambda row: (row[1], row[0]),
        )
        if not ranked:
            return CatalogMatch(resolved=text, confidence=MatchConfidence.NONE)

        best_d = ranked[0][1]
        ties = [sku for sku, d in ranked if d == best_d]
        within = [
            (sku, d)
            for sku, d in ranked
            if _rel_dist(d, compact, compact_sku(sku)) <= _REL_DIST_MAX
        ]

        # Ambiguous: multiple catalog SKUs equally close within threshold.
        if len(ties) > 1 and best_d <= 2 and any(sku in dict(within) for sku in ties):
            # Same-length single-sub ties are alternate product codes, not roots.
            if all(len(compact) == len(compact_sku(sku)) for sku in ties):
                return CatalogMatch(resolved=text, confidence=MatchConfidence.NONE)
            return CatalogMatch(
                resolved=ties[0],
                confidence=MatchConfidence.AMBIGUOUS,
                candidates=tuple(ties),
            )

        # Short abbreviations: unique initials → VP soft escalate (not silent auto-pay).
        # Example: W-A → WidgetA (UNIQUE_CLOSE). Ambiguous or unmatched → leave raw.
        if len(compact) <= _ABBREV_MAX_LEN:
            init_hits = [sku for sku in self.catalog if _initials(sku) == compact]
            if len(init_hits) == 1:
                return CatalogMatch(
                    resolved=init_hits[0],
                    confidence=MatchConfidence.UNIQUE_CLOSE,
                    candidates=(init_hits[0],),
                )
            if len(init_hits) > 1:
                return CatalogMatch(
                    resolved=init_hits[0],
                    confidence=MatchConfidence.AMBIGUOUS,
                    candidates=tuple(init_hits),
                )
            return CatalogMatch(resolved=text, confidence=MatchConfidence.NONE)

        # Unique close fuzzy (fat-finger / truncation / phonetic spacing).
        if len(within) == 1:
            sku, dist = within[0]
            # Same-length single substitution → different product code.
            if dist == 1 and len(compact) == len(compact_sku(sku)):
                return CatalogMatch(resolved=text, confidence=MatchConfidence.NONE)
            # Refuse expansions where the query is a tiny fraction of the catalog name.
            if len(compact) * 2 < len(compact_sku(sku)):
                return CatalogMatch(resolved=text, confidence=MatchConfidence.NONE)
            return CatalogMatch(
                resolved=sku,
                confidence=MatchConfidence.UNIQUE_CLOSE,
                candidates=(sku,),
            )
        if len(within) > 1:
            # Prefer unique best among those under threshold.
            best = min(within, key=lambda row: (row[1], row[0]))
            peers = [s for s, d in within if d == best[1]]
            if len(peers) == 1:
                return CatalogMatch(
                    resolved=peers[0],
                    confidence=MatchConfidence.UNIQUE_CLOSE,
                    candidates=(peers[0],),
                )
            return CatalogMatch(
                resolved=peers[0],
                confidence=MatchConfidence.AMBIGUOUS,
                candidates=tuple(peers),
            )

        # Alias-style prefix: compact starts with catalog compact + alpha suffix.
        prefix_hits: list[str] = []
        for sku in sorted(self.catalog, key=lambda s: len(compact_sku(s)), reverse=True):
            csku = compact_sku(sku)
            if compact.startswith(csku) and compact != csku and len(compact) <= len(csku) + 8:
                suffix = compact[len(csku) :]
                if suffix.isalpha():
                    prefix_hits.append(sku)
        if len(prefix_hits) == 1:
            return CatalogMatch(
                resolved=prefix_hits[0],
                confidence=MatchConfidence.UNIQUE_CLOSE,
                candidates=(prefix_hits[0],),
            )
        if len(prefix_hits) > 1:
            return CatalogMatch(
                resolved=prefix_hits[0],
                confidence=MatchConfidence.AMBIGUOUS,
                candidates=tuple(prefix_hits),
            )

        return CatalogMatch(resolved=text, confidence=MatchConfidence.NONE)

    def soft_issue(self, raw: str, match: CatalogMatch) -> str | None:
        """Map a match confidence to a soft escalation issue, if any."""
        if match.confidence is MatchConfidence.EXACT:
            return None
        if match.confidence is MatchConfidence.NONE:
            return None
        if match.confidence is MatchConfidence.VARIANT:
            return f"{SKU_VARIANT_REVIEW_PREFIX}:{raw}"
        if match.confidence is MatchConfidence.AMBIGUOUS:
            joined = ",".join(match.candidates) if match.candidates else match.resolved
            return f"{SKU_TYPO_REVIEW_PREFIX}:{raw}→ambiguous:{joined}"
        # UNIQUE_CLOSE → VP typo review.
        return f"{SKU_TYPO_REVIEW_PREFIX}:{raw}→{match.resolved}"


def _is_abbrev_expansion(short_compact: str, catalog_sku: str) -> bool:
    """Return True when catalog_sku looks like an expansion of a short abbrev."""
    csku = compact_sku(catalog_sku)
    if not short_compact or len(short_compact) > _ABBREV_MAX_LEN:
        return False
    if csku == short_compact:
        return False
    return csku.startswith(short_compact) or _initials(catalog_sku) == short_compact


def undo_digit_sku_expansions(
    raw_text: str,
    items: Sequence[LineItem],
    catalog: Sequence[str] | None = None,
) -> tuple[LineItem, ...]:
    """Revert LLM maps of digit-bearing source tokens back to the document SKU.

    Parameters
    ----------
    raw_text : str
        Original invoice text.
    items : sequence of LineItem
        Extracted lines (may already be catalog codes).
    catalog : sequence of str or None
        Catalog codes.

    Returns
    -------
    tuple of LineItem
        Items with digit-OCR tokens restored so validation can ``unknown_item``.

    Notes
    -----
    ``Widg3tA`` must not silently become ``WidgetA``. Digits in the source
    token are treated as a different product code, not a fat-finger fix.
    """
    cat = set(catalog or DEFAULT_CATALOG)
    digit_tokens: list[str] = []
    for m in _ITEM_LINE.finditer(raw_text or ""):
        token = m.group(1).strip().split()[0].strip("\"'")
        if token and _HAS_DIGIT.search(token):
            digit_tokens.append(token)
    if not digit_tokens:
        return tuple(items)

    out: list[LineItem] = []
    used: set[str] = set()
    for item in items:
        restored = None
        if item.sku in cat:
            for token in digit_tokens:
                key = compact_sku(token)
                if key in used:
                    continue
                # Same line mapped away from a digit-bearing source identity.
                if compact_sku(token) != compact_sku(item.sku):
                    restored = token
                    used.add(key)
                    break
        if restored is not None:
            out.append(LineItem(sku=restored, quantity=item.quantity, unit_price=item.unit_price))
        else:
            out.append(item)
    return tuple(out)


def soft_issues_from_source_items(
    raw_text: str,
    items: Sequence[LineItem],
    catalog: Sequence[str] | None = None,
) -> list[str]:
    """Soft-escalate when ``Item:`` text uniquely maps to a billed catalog SKU.

    Parameters
    ----------
    raw_text : str
        Original invoice text.
    items : sequence of LineItem
        Resolved line items (catalog codes after extract).
    catalog : sequence of str or None
        Catalog codes.

    Returns
    -------
    list of str
        Soft ``sku_typo_review`` / ``sku_variant_review`` codes for VP.

    Notes
    -----
    Exact compact matches (``Widget A`` → ``WidgetA``) stay silent auto-pay.
    Alias / unique-close phrases (``Widget Alpha`` → ``WidgetA``) escalate.
    Short unique-initial abbreviations (``W-A`` → ``WidgetA``) escalate too.
    """
    resolver = CatalogResolver(catalog or DEFAULT_CATALOG)
    present = {item.sku for item in items}
    issues: list[str] = []
    seen: set[str] = set()
    for m in _ITEM_LINE.finditer(raw_text or ""):
        token = m.group(1).strip()
        if not token:
            continue
        match = resolver.resolve(token)
        if match.resolved not in present:
            continue
        issue = resolver.soft_issue(token, match)
        if issue and issue not in seen:
            seen.add(issue)
            issues.append(issue)
    return issues


def undo_abbreviation_expansions(
    raw_text: str,
    items: Sequence[LineItem],
    catalog: Sequence[str] | None = None,
) -> tuple[LineItem, ...]:
    """Revert LLM expansions of short abbreviations back to the document token.

    Parameters
    ----------
    raw_text : str
        Original invoice text (source of ``Item:`` lines).
    items : sequence of LineItem
        Extracted lines (may already be catalog codes).
    catalog : sequence of str or None
        Catalog codes used to detect expansions.

    Returns
    -------
    tuple of LineItem
        Items with short abbreviations restored when the model over-expanded them.

    Notes
    -----
    Compact forms ≤ 3 characters are restored to the document token when the
    model over-expanded them. ``CatalogResolver`` then maps unique initials
    with ``UNIQUE_CLOSE`` so VP reviews (``W-A`` → ``WidgetA``). Digit OCR
    tokens use ``undo_digit_sku_expansions`` instead and stay hard-reject.
    """
    cat = set(catalog or DEFAULT_CATALOG)
    shorts: list[str] = []
    for m in _ITEM_LINE.finditer(raw_text or ""):
        token = m.group(1).strip().split()[0].strip("\"'")
        if token and len(compact_sku(token)) <= _ABBREV_MAX_LEN:
            shorts.append(token)
    if not shorts:
        return tuple(items)

    out: list[LineItem] = []
    used: set[str] = set()
    for item in items:
        restored = None
        if item.sku in cat:
            for short in shorts:
                sc = compact_sku(short)
                if sc in used:
                    continue
                if _is_abbrev_expansion(sc, item.sku):
                    restored = short
                    used.add(sc)
                    break
        if restored is not None:
            out.append(LineItem(sku=restored, quantity=item.quantity, unit_price=item.unit_price))
        else:
            out.append(item)
    return tuple(out)


# Default catalog from case seed (tests / workers without an explicit list).
DEFAULT_CATALOG: tuple[str, ...] = ("WidgetA", "WidgetB", "GadgetX", "FakeItem")

# Back-compat name used by older imports / docs.
CATALOG_SKUS: frozenset[str] = frozenset(DEFAULT_CATALOG)


def resolve_sku(
    raw: str,
    catalog: Sequence[str] | None = None,
) -> tuple[str, str | None]:
    """Resolve one SKU; return ``(sku, soft_issue_or_none)``.

    Parameters
    ----------
    raw : str
        Extracted SKU text.
    catalog : sequence of str or None
        Catalog codes. Defaults to case-seed SKUs.
    """
    resolver = CatalogResolver(catalog or DEFAULT_CATALOG)
    match = resolver.resolve(raw)
    issue = resolver.soft_issue(raw, match)
    return match.resolved, issue


def resolve_line_items(
    items: Sequence[LineItem],
    catalog: Sequence[str] | None = None,
) -> tuple[tuple[LineItem, ...], list[str]]:
    """Resolve all line SKUs; collect soft escalation issues for VP.

    Parameters
    ----------
    items : sequence of LineItem
        Extracted lines (SKUs may be raw or already catalog codes).
    catalog : sequence of str or None
        Catalog codes. Defaults to case-seed SKUs.

    Returns
    -------
    tuple of (tuple of LineItem, list of str)
        Resolved items and unique soft issue codes (may be empty).
    """
    resolver = CatalogResolver(catalog or DEFAULT_CATALOG)
    out: list[LineItem] = []
    soft: list[str] = []
    seen: set[str] = set()
    for item in items:
        match = resolver.resolve(item.sku)
        issue = resolver.soft_issue(item.sku, match)
        out.append(LineItem(sku=match.resolved, quantity=item.quantity, unit_price=item.unit_price))
        if issue and issue not in seen:
            seen.add(issue)
            soft.append(issue)
    return tuple(out), soft
