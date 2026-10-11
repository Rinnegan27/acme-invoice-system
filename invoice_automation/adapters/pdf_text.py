"""PDF text extraction helper."""

from __future__ import annotations

from pathlib import Path

from invoice_automation.domain.exceptions import ExtractionError


def extract_pdf_text(path: str | Path) -> str:
    """Extract text from a PDF using pdfplumber.

    Parameters
    ----------
    path : str or Path
        PDF file path.

    Returns
    -------
    str
        Concatenated page text.

    Raises
    ------
    ExtractionError
        On open/extract failure or empty extracted text.
    """
    path = Path(path)
    try:
        import pdfplumber
    except ImportError as exc:
        raise ExtractionError("pdfplumber is not installed") from exc

    try:
        chunks: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                chunks.append(text)
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize PDF failures
        raise ExtractionError(f"pdf_extract_failed: {exc}") from exc

    text = "\n".join(chunks).strip()
    if not text:
        raise ExtractionError("pdf_empty")
    return text
