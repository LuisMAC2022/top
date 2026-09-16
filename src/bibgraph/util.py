"""Small shared helpers: determinism, hashing, atomic writes, path safety.

Standard library only.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "1.0"
GENERATOR = "bibgraph"
GENERATOR_VERSION = "0.1.0"

# Process exit codes. Precedence is highest-number-wins-first: see resolve_exit_code.
EXIT_OK = 0
EXIT_INCOMPLETE = 2       # a required acquisition/extraction did not complete
EXIT_INVALID_MANIFEST = 3  # config could not be validated; nothing else ran
EXIT_INTEGRITY = 4        # bytes arrived but failed integrity/type validation

# The plan lists these codes but never says which wins when several apply.
# Fixed order, most-diagnostic first: a bad manifest explains everything after
# it, and an integrity failure is more specific than "incomplete".
_EXIT_PRECEDENCE = (EXIT_INVALID_MANIFEST, EXIT_INTEGRITY, EXIT_INCOMPLETE, EXIT_OK)


def resolve_exit_code(codes: Iterable[int]) -> int:
    """Collapse several failure codes into the single documented exit status."""
    seen = {int(c) for c in codes}
    for code in _EXIT_PRECEDENCE:
        if code in seen:
            return code
    return EXIT_OK


def now_utc() -> _dt.datetime:
    """UTC now, overridable via SOURCE_DATE_EPOCH for reproducible builds."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        try:
            return _dt.datetime.fromtimestamp(int(epoch), tz=_dt.timezone.utc)
        except (ValueError, OSError):
            pass
    return _dt.datetime.now(tz=_dt.timezone.utc)


def now_iso() -> str:
    return now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, fixed separators, trailing newline."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def content_hash(obj: Any) -> str:
    """Hash of a structure's canonical form, ignoring volatile meta blocks."""
    return sha256_bytes(canonical_json(strip_volatile(obj)).encode("utf-8"))


def strip_volatile(obj: Any) -> Any:
    """Drop fields that legitimately change between otherwise identical runs."""
    volatile = {"generated_at", "run_id", "duration_ms", "fetched_at"}
    if isinstance(obj, dict):
        return {k: strip_volatile(v) for k, v in obj.items() if k not in volatile}
    if isinstance(obj, list):
        return [strip_volatile(v) for v in obj]
    return obj


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_atomic(path: Path, obj: Any) -> None:
    write_text_atomic(path, canonical_json(obj))


def write_text_atomic(path: Path, text: str) -> None:
    """Write via a temp file in the same directory, then rename.

    Never leaves a partial file at the final path, which the acquisition
    contract requires and which the rest of the pipeline relies on.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False, suffix=".tmp"
    )
    try:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(handle.name, path)
    except BaseException:
        handle.close()
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def write_jsonl_atomic(path: Path, rows: Iterable[Any]) -> None:
    body = "".join(
        json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows
    )
    write_text_atomic(Path(path), body)


def read_jsonl(path: Path) -> list:
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def safe_path_segment(value: str) -> str:
    """Turn an arbitrary identifier into one safe filesystem/URL segment.

    Rejects traversal outright rather than silently sanitising it, so a
    malformed identifier is a visible error instead of a surprising path.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("path segment must be a non-empty string")
    if value in (".", "..") or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"unsafe path segment: {value!r}")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    if not slug or not _SAFE_SEGMENT.match(slug):
        raise ValueError(f"path segment reduced to nothing: {value!r}")
    return slug[:120]


def normalize_text(value: str) -> str:
    """NFC normalise and collapse whitespace. Conservative on purpose."""
    if value is None:
        return ""
    value = unicodedata.normalize("NFC", value)
    value = value.replace(" ", " ")
    return re.sub(r"[ \t]+", " ", value).strip()


def normalize_for_match(value: str) -> str:
    """Aggressive normalisation used only for comparing titles/citations."""
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def local_id(basis: str) -> str:
    return "local:" + sha256_bytes(normalize_for_match(basis).encode("utf-8"))


def derived_header(inputs: dict[str, str], command: str) -> dict:
    """Standard provenance block required on every derived artifact."""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
        "command": command,
        "input_hashes": dict(sorted(inputs.items())),
    }


@dataclasses.dataclass(frozen=True)
class Workspace:
    """Resolved locations for one project root."""

    root: Path

    @classmethod
    def from_root(cls, root: str | Path | None = None) -> "Workspace":
        return cls(root=Path(root or ".").resolve())

    @property
    def config(self) -> Path: return self.root / "config"

    @property
    def corpus_file(self) -> Path: return self.config / "corpus.json"

    @property
    def dependencies_file(self) -> Path: return self.config / "dependencies.json"

    @property
    def profile_file(self) -> Path: return self.config / "reading-profile.json"

    @property
    def ranking_file(self) -> Path: return self.config / "ranking.json"

    @property
    def stopwords_file(self) -> Path: return self.config / "stopwords.txt"

    @property
    def private(self) -> Path: return self.root / "private"

    @property
    def raw(self) -> Path: return self.private / "raw"

    @property
    def text(self) -> Path: return self.private / "text"

    @property
    def manual_import(self) -> Path: return self.private / "manual-import"

    @property
    def data(self) -> Path: return self.root / "data"

    @property
    def documents(self) -> Path: return self.data / "documents"

    @property
    def state_db(self) -> Path: return self.data / "state.sqlite3"

    @property
    def cache(self) -> Path: return self.root / "cache" / "http"

    @property
    def reports(self) -> Path: return self.root / "reports"

    @property
    def annotations(self) -> Path: return self.root / "annotations"

    @property
    def site_src(self) -> Path: return self.root / "site-src"

    @property
    def build_site(self) -> Path: return self.root / "build" / "site"

    @property
    def publish(self) -> Path: return self.root / "publish"

    def ensure(self) -> None:
        for path in (self.data, self.documents, self.reports, self.annotations,
                     self.cache, self.private, self.raw, self.text, self.manual_import):
            path.mkdir(parents=True, exist_ok=True)
