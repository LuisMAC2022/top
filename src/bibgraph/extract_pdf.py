"""PDF adapter: an optional system command, never a home-grown parser.

A PDF is a page-description container, not a semantic document format. It may
carry compressed object streams, custom fonts, multi-column layout, a malformed
cross-reference table, or nothing but images. A parser written here would
appear to work on one paper and silently corrupt others, so this module shells
out to Poppler's `pdftotext` and reports honestly when it cannot.
"""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
from pathlib import Path

PAGE_BREAK = "\f"
# Below this many characters per page the text layer is effectively absent,
# which usually means a scan. OCR is a separate opt-in adapter, not this one.
SCANNED_CHARS_PER_PAGE = 60


class PdfUnsupported(Exception):
    """pdftotext is unavailable, so no honest extraction is possible."""


class PdfExtractionFailed(Exception):
    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


@dataclasses.dataclass
class PdfText:
    text: str               # reading order
    layout_text: str        # layout preserved, useful for multi-column work
    pages: int
    chars_per_page: float
    looks_scanned: bool
    warnings: list[str]


def available() -> bool:
    return shutil.which("pdftotext") is not None


def executable() -> str | None:
    return shutil.which("pdftotext")


def _run(path: Path, layout: bool, timeout: float) -> str:
    exe = executable()
    if exe is None:
        raise PdfUnsupported("pdftotext is not installed")
    args = [exe, "-q", "-enc", "UTF-8"]
    if layout:
        args.append("-layout")
    args += [str(path), "-"]
    try:
        completed = subprocess.run(
            args, capture_output=True, timeout=timeout, shell=False, check=False)
    except subprocess.TimeoutExpired as exc:
        raise PdfExtractionFailed(
            f"pdftotext timed out after {timeout}s", str(exc)) from exc
    except OSError as exc:
        raise PdfExtractionFailed(f"pdftotext could not be run: {exc}") from exc
    if completed.returncode != 0:
        raise PdfExtractionFailed(
            f"pdftotext exited {completed.returncode}",
            completed.stderr.decode("utf-8", "replace")[:2000])
    return completed.stdout.decode("utf-8", "replace")


def extract(path: Path, timeout: float = 120.0) -> PdfText:
    """Both reading-order and layout-preserving text, with a scan verdict."""
    path = Path(path)
    warnings: list[str] = []
    reading = _run(path, layout=False, timeout=timeout)
    try:
        layout = _run(path, layout=True, timeout=timeout)
    except PdfExtractionFailed as exc:
        layout = ""
        warnings.append(f"layout-preserving pass failed: {exc}")

    pages = reading.count(PAGE_BREAK) + 1 if reading else 0
    stripped = len("".join(reading.split()))
    per_page = (stripped / pages) if pages else 0.0
    scanned = pages > 0 and per_page < SCANNED_CHARS_PER_PAGE
    if scanned:
        warnings.append(
            f"only {per_page:.0f} characters per page: this is almost certainly a "
            "scanned or image-only PDF. OCR is a separate opt-in adapter and is "
            "not part of this release; the work stays in the manual queue.")
    return PdfText(text=reading, layout_text=layout, pages=pages,
                   chars_per_page=per_page, looks_scanned=scanned,
                   warnings=warnings)


def unavailable_reason() -> str:
    return ("pdftotext (Poppler) is not installed, so structured text cannot be "
            "extracted from this PDF. Install Poppler, or supply a text sidecar "
            "with `bibgraph import`. A byte-string scrape of the PDF would be "
            "silently wrong and is not attempted.")
