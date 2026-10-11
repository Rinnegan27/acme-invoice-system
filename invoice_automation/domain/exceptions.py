"""Domain-specific exception hierarchy.

Parameters
----------
None
    Module defines exception classes only.
"""

from __future__ import annotations


class InvoiceDomainError(Exception):
    """Base for all invoice domain errors."""


class ExtractionError(InvoiceDomainError):
    """Failed to extract structured invoice data."""


class ValidationError(InvoiceDomainError):
    """Inventory or data-integrity failure."""


class ApprovalRejected(InvoiceDomainError):
    """VP or policy rejected the invoice."""


class PaymentError(InvoiceDomainError):
    """Payment gateway or saga failure."""
