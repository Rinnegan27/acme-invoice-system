"""Shared pytest fixtures / env defaults for offline CI."""

from __future__ import annotations

import os

# Durable PaymentPermit HMAC — required by PolicyEngine (no silent default secret).
os.environ.setdefault("GALATIQ_PERMIT_SECRET", "test-secret-for-ci-ok")
