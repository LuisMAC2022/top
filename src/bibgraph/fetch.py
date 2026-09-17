"""Strict acquisition: request only what is asked for, validate every byte.

Failure is loud and three-way: a concise line on stderr, a structured event in
reports/fetch-<run-id>.jsonl, and a nonzero exit when a required asset failed.
No access control is ever circumvented: 401/403, logins, challenges and
paywalls are recorded as gates, never worked around.
"""

from __future__ import annotations

import dataclasses
import email.utils
import ipaddress
import os
import socket
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path
from typing import Callable

from . import util
from .model import Asset, Corpus, Work
from .store import Store
from .util import Workspace

DEFAULT_USER_AGENT = (
    f"bibgraph/{util.GENERATOR_VERSION} (local research pipeline; "
    "+set BIBGRAPH_CONTACT_EMAIL for a contact address)"
)
REDIRECT_CODES = (301, 302, 303, 307, 308)
RETRYABLE_STATUS = (429, 500, 502, 503, 504)
MAX_REDIRECTS = 5
MAX_BYTES = 64 * 1024 * 1024
MIN_CONTENT_BYTES = 512
# A sequence entry or a short web page is legitimately small; an article's full
# text is not. A single global floor would reject the former as a stub response.
MIN_CONTENT_BYTES_BY_WORK_TYPE = {"sequence": 96, "web_page": 96, "notes": 256}
CONNECT_TIMEOUT = 20.0
ROBOTS_MAX_BYTES = 512 * 1024
ROBOTS_TTL_SECONDS = 24 * 3600

# Statuses an artifact can end in. "downloaded" is the only success.
STATUS_DOWNLOADED = "downloaded"
STATUS_METADATA_ONLY = "metadata_only"
STATUS_MANUAL_REQUIRED = "manual_required"
STATUS_FAILED = "failed"
STATUS_NOT_REQUESTED = "not_requested"
STATUS_SKIPPED_CACHED = "cached"

MAGIC = {
    "application/pdf": b"%PDF-",
}
HTML_SNIFF = (b"<!doctype html", b"<html", b"<head", b"<body")


class FetchError(Exception):
    """A fetch failed. `kind` distinguishes integrity from availability."""

    def __init__(self, reason: str, kind: str = "availability",
                 http_status: int | None = None, retryable: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.kind = kind          # "availability" | "integrity" | "policy"
        self.http_status = http_status
        self.retryable = retryable


@dataclasses.dataclass
class FetchConfig:
    user_agent: str = DEFAULT_USER_AGENT
    contact: str | None = None
    timeout: float = CONNECT_TIMEOUT
    max_bytes: int = MAX_BYTES
    min_bytes: int = MIN_CONTENT_BYTES
    max_redirects: int = MAX_REDIRECTS
    max_attempts: int = 3
    backoff_base: float = 2.0
    allow_http: bool = False
    allow_private_hosts: tuple[str, ...] = ()
    respect_robots: bool = True
    delay_between_requests: float = 1.0

    @classmethod
    def from_env(cls, **overrides) -> "FetchConfig":
        contact = os.environ.get("BIBGRAPH_CONTACT_EMAIL")
        agent = os.environ.get("BIBGRAPH_USER_AGENT")
        if not agent:
            agent = (f"bibgraph/{util.GENERATOR_VERSION} (local research pipeline; {contact})"
                     if contact else DEFAULT_USER_AGENT)
        config = cls(user_agent=agent, contact=contact)
        for key, value in overrides.items():
            setattr(config, key, value)
        return config


@dataclasses.dataclass
class Response:
    status: int
    final_url: str
    redirects: list[dict]
    headers: dict[str, str]
    body_path: Path
    sha256: str
    bytes: int
    media_type: str | None


# ---------------------------------------------------------------------------
# URL policy
# ---------------------------------------------------------------------------


def check_url(url: str, config: FetchConfig) -> urllib.parse.ParseResult:
    """Reject anything outside the declared transport policy, loudly."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("https", "http"):
        raise FetchError(f"unsupported scheme {parsed.scheme!r}", kind="policy")
    if parsed.scheme == "http" and not config.allow_http:
        raise FetchError("plain http is not approved for this run", kind="policy")
    if parsed.username or parsed.password or "@" in (parsed.netloc.split("/")[0]):
        raise FetchError("credentials embedded in URL are refused", kind="policy")
    if not parsed.hostname:
        raise FetchError("URL has no host", kind="policy")

    host = parsed.hostname
    if host in config.allow_private_hosts:
        return parsed
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise FetchError(f"host does not resolve: {host} ({exc})") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (address.is_private or address.is_loopback or address.is_link_local
                or address.is_reserved or address.is_multicast):
            raise FetchError(
                f"{host} resolves to the non-public address {address}; "
                "add it to allow_private_hosts to permit this",
                kind="policy",
            )
    return parsed


# ---------------------------------------------------------------------------
# The fetcher
# ---------------------------------------------------------------------------


class Fetcher:
    def __init__(self, config: FetchConfig, store: Store | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 opener: urllib.request.OpenerDirector | None = None):
        self.config = config
        self.store = store
        self.sleep = sleep
        self.opener = opener or self._build_opener()
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last_request_at = 0.0

    def _build_opener(self) -> urllib.request.OpenerDirector:
        context = ssl.create_default_context()
        return urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context),
            _NoRedirect(),
        )

    # -- robots ------------------------------------------------------------

    def robots_allows(self, url: str) -> tuple[bool, str]:
        """RFC 9309 crawl guidance. Never treated as authentication.

        The plan says to use urllib.robotparser, but RobotFileParser.read()
        opens its own connection with no timeout and no size cap, which would
        break the bounded-request rule this module exists to enforce. The file
        is fetched through the same bounded path as everything else and handed
        to parse() instead.
        """
        if not self.config.respect_robots:
            return True, "robots checking disabled for this run"
        parsed = urllib.parse.urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            self._robots[origin] = self._load_robots(origin)
        parser = self._robots[origin]
        if parser is None:
            # No robots.txt, or it could not be retrieved: RFC 9309 treats an
            # unreachable or absent file as "no restrictions".
            return True, "no robots.txt available; treated as unrestricted"
        allowed = parser.can_fetch(self.config.user_agent, url)
        return allowed, ("allowed by robots.txt" if allowed else "disallowed by robots.txt")

    def _load_robots(self, origin: str) -> urllib.robotparser.RobotFileParser | None:
        robots_url = origin + "/robots.txt"
        try:
            response = self._single_request(
                robots_url, max_bytes=ROBOTS_MAX_BYTES, accept="text/plain")
        except (FetchError, urllib.error.URLError, OSError):
            return None
        try:
            text = response.body_path.read_text(encoding="utf-8", errors="replace")
        finally:
            response.body_path.unlink(missing_ok=True)
        if response.status != 200:
            return None
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(text.splitlines())
        if self.store:
            self.store.cache_put(
                robots_url, fetched_at=util.now_iso(), status=response.status,
                expires_at=None, body_path=None,
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"))
        return parser

    # -- transport ---------------------------------------------------------

    def _throttle(self) -> None:
        if self.config.delay_between_requests <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.config.delay_between_requests - elapsed
        if remaining > 0 and self._last_request_at:
            self.sleep(remaining)
        self._last_request_at = time.monotonic()

    def _single_request(self, url: str, max_bytes: int | None = None,
                        accept: str | None = None) -> Response:
        """One bounded request, following redirects manually so hops are recorded."""
        config = self.config
        limit = max_bytes if max_bytes is not None else config.max_bytes
        redirects: list[dict] = []
        current = url
        origin_host = urllib.parse.urlsplit(url).hostname

        for hop in range(config.max_redirects + 1):
            check_url(current, config)
            self._throttle()
            headers = {"User-Agent": config.user_agent,
                       "Accept": accept or "*/*",
                       "Accept-Encoding": "identity"}
            if config.contact:
                headers["From"] = config.contact
            request = urllib.request.Request(current, headers=headers, method="GET")
            try:
                response = self.opener.open(request, timeout=config.timeout)
            except urllib.error.HTTPError as exc:
                if exc.code in REDIRECT_CODES:
                    location = exc.headers.get("Location")
                    exc.close()
                    if not location:
                        raise FetchError(f"{exc.code} redirect without Location",
                                         http_status=exc.code) from exc
                    target = urllib.parse.urljoin(current, location)
                    redirects.append({"from": current, "to": target, "status": exc.code})
                    current = target
                    continue
                detail = f"HTTP {exc.code} {exc.reason}"
                retry_after = parse_retry_after(exc.headers.get("Retry-After"))
                exc.close()
                error = FetchError(
                    detail, http_status=exc.code,
                    retryable=exc.code in RETRYABLE_STATUS,
                )
                error.retry_after = retry_after
                raise error from exc
            except (urllib.error.URLError, socket.timeout, TimeoutError, ssl.SSLError) as exc:
                raise FetchError(f"transport error: {exc}", retryable=True) from exc

            with response:
                final_host = urllib.parse.urlsplit(response.geturl()).hostname
                headers_out = {k.lower(): v for k, v in response.headers.items()}
                declared = response.headers.get_content_type()
                body_path, digest, size = self._stream_to_temp(response, limit)
                return Response(
                    status=response.status,
                    final_url=response.geturl(),
                    redirects=redirects,
                    headers={**headers_out,
                             "x-host-changed": str(final_host != origin_host).lower()},
                    body_path=body_path,
                    sha256=digest,
                    bytes=size,
                    media_type=declared,
                )
        raise FetchError(f"redirect chain exceeded {config.max_redirects} hops")

    def _stream_to_temp(self, response, limit: int) -> tuple[Path, str, int]:
        import hashlib

        digest = hashlib.sha256()
        total = 0
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".part")
        try:
            while True:
                chunk = response.read(1 << 16)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise FetchError(
                        f"response exceeded the {limit} byte cap", kind="integrity")
                digest.update(chunk)
                handle.write(chunk)
            handle.close()
        except BaseException:
            handle.close()
            Path(handle.name).unlink(missing_ok=True)
            raise
        declared_length = response.headers.get("Content-Length")
        if declared_length and declared_length.isdigit() and int(declared_length) != total:
            Path(handle.name).unlink(missing_ok=True)
            raise FetchError(
                f"truncated body: Content-Length {declared_length}, read {total}",
                kind="integrity")
        return Path(handle.name), digest.hexdigest(), total

    def fetch(self, url: str, expected_media_type: str | None = None,
              min_bytes: int | None = None) -> Response:
        """Bounded request with retry on transient conditions only."""
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._single_request(url)
            except FetchError as exc:
                # 401/403/404 are gates or absences, not transient conditions.
                if exc.retryable and attempt < self.config.max_attempts:
                    self.sleep(self._backoff(attempt, exc))
                    continue
                raise
            try:
                validate_payload(response, expected_media_type,
                                 min_bytes if min_bytes is not None else self.config.min_bytes)
            except FetchError:
                response.body_path.unlink(missing_ok=True)
                raise
            return response

    def _backoff(self, attempt: int, exc: FetchError) -> float:
        """Honour Retry-After when the server sent one; bounded either way."""
        retry_after = getattr(exc, "retry_after", None)
        if retry_after is not None:
            return min(float(retry_after), 300.0)
        return min(self.config.backoff_base ** attempt, 60.0)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 3xx as HTTPError so the caller records every hop itself."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    delta = when.timestamp() - util.now_utc().timestamp()
    return max(delta, 0.0)


def sniff_media_type(head: bytes) -> str | None:
    lowered = head[:256].lower()
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if any(marker in lowered for marker in HTML_SNIFF):
        return "text/html"
    if head.startswith(b"<?xml"):
        return "application/xml"
    return None


def validate_payload(response: Response, expected: str | None, min_bytes: int) -> None:
    """Status, size, declared type and magic bytes must all agree."""
    if response.status != 200:
        raise FetchError(f"unexpected final status {response.status}",
                         http_status=response.status)
    if response.bytes < min_bytes:
        raise FetchError(
            f"body is {response.bytes} bytes, below the {min_bytes} byte minimum",
            kind="integrity")

    with open(response.body_path, "rb") as handle:
        head = handle.read(1024)
    sniffed = sniff_media_type(head)

    if expected:
        magic = MAGIC.get(expected)
        if magic and not head.startswith(magic):
            # The classic failure: an HTML login or paywall page served for a
            # PDF URL. Named explicitly because it is the common case.
            if sniffed == "text/html":
                raise FetchError(
                    f"expected {expected} but received an HTML page "
                    "(login, paywall or error page), not the document",
                    kind="integrity")
            raise FetchError(
                f"expected {expected} but the magic bytes do not match",
                kind="integrity")
        if not magic and response.media_type and expected not in response.media_type:
            if sniffed and expected not in sniffed:
                raise FetchError(
                    f"expected {expected}, server declared {response.media_type}, "
                    f"content looks like {sniffed}",
                    kind="integrity")


# ---------------------------------------------------------------------------
# Corpus-level acquisition
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class AssetOutcome:
    alias: str
    work_id: str
    asset_id: str
    role: str
    intent: str
    requested_url: str | None
    status: str
    reason: str | None = None
    final_url: str | None = None
    redirects: list[dict] = dataclasses.field(default_factory=list)
    http_status: int | None = None
    media_type: str | None = None
    bytes: int | None = None
    sha256: str | None = None
    path: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    attempts: int = 0
    kind: str | None = None

    def as_event(self) -> dict:
        row = dataclasses.asdict(self)
        # Local absolute paths never leave the machine; store a repo-relative one.
        return row


def artifact_path(ws: Workspace, work: Work, asset: Asset, media_type: str | None) -> Path:
    suffix = {"application/pdf": ".pdf", "text/html": ".html",
              "application/xml": ".xml", "text/plain": ".txt"}.get(media_type or "", ".bin")
    return (ws.raw / util.safe_path_segment(work.primary_alias)
            / (util.safe_path_segment(asset.id) + suffix))


def fetch_corpus(ws: Workspace, corpus: Corpus, store: Store, config: FetchConfig,
                 aliases: list[str] | None = None, keep_going: bool = True,
                 require_fulltext_all: bool = False,
                 fetcher: Fetcher | None = None,
                 run_id: str | None = None,
                 on_event: Callable[[AssetOutcome], None] | None = None) -> list[AssetOutcome]:
    """Acquire requested assets. Returns one outcome per asset considered."""
    run_id = run_id or util.now_utc().strftime("%Y%m%dT%H%M%SZ")
    fetcher = fetcher or Fetcher(config, store=store)
    outcomes: list[AssetOutcome] = []
    selected = set(aliases) if aliases else None

    for work in corpus.works:
        if selected and not (set(work.aliases) & selected):
            continue
        for asset in work.assets:
            outcome = _fetch_one(ws, work, asset, store, config, fetcher, run_id)
            outcomes.append(outcome)
            if on_event:
                on_event(outcome)
            store.record_artifact({
                "asset_id": asset.id, "work_id": work.id, "alias": work.primary_alias,
                "role": asset.role, "intent": asset.intent,
                "requested_url": asset.url or "", "final_url": outcome.final_url,
                "status": outcome.status, "http_status": outcome.http_status,
                "media_type": outcome.media_type, "bytes": outcome.bytes,
                "sha256": outcome.sha256, "path": outcome.path, "etag": outcome.etag,
                "last_modified": outcome.last_modified, "attempts": outcome.attempts,
                "reason": outcome.reason, "fetched_at": util.now_iso(),
            })
            if outcome.status == STATUS_FAILED and asset.is_required and not keep_going:
                return outcomes
    return outcomes


def _fetch_one(ws: Workspace, work: Work, asset: Asset, store: Store,
               config: FetchConfig, fetcher: Fetcher, run_id: str) -> AssetOutcome:
    base = AssetOutcome(
        alias=work.primary_alias, work_id=work.id, asset_id=asset.id,
        role=asset.role, intent=asset.intent, requested_url=asset.url,
        status=STATUS_NOT_REQUESTED,
    )
    started = util.now_iso()

    if asset.intent == "ignore":
        base.reason = "intent=ignore"
        return base
    if asset.intent == "manual":
        base.status = STATUS_MANUAL_REQUIRED
        base.reason = ("intent=manual: this route is a preview, borrow or purchase. "
                       "Supply a legally obtained copy with `bibgraph import`.")
        return base
    if asset.intent == "metadata_only":
        base.status = STATUS_METADATA_ONLY
        base.reason = "intent=metadata_only: catalogue metadata only, no full text requested"
        return base
    if not work.rights.local_storage_allowed:
        base.status = STATUS_MANUAL_REQUIRED
        base.reason = (f"rights.local_storage_allowed=false for access={work.rights.access}; "
                       "refusing to store a local copy")
        return base

    allowed, robots_reason = fetcher.robots_allows(asset.url or "")
    if not allowed:
        base.status = STATUS_FAILED
        base.kind = "policy"
        base.reason = robots_reason
        store.log_attempt(run_id, asset.id, started, "robots-disallowed", None, robots_reason)
        return base

    # An unchanged input should not produce a request.
    previous = store.get_artifact(asset.id)
    if previous and previous["status"] == STATUS_DOWNLOADED and previous["path"]:
        existing = Path(previous["path"])
        if not existing.is_absolute():
            existing = ws.root / existing
        if existing.exists() and util.sha256_file(existing) == previous["sha256"]:
            base.status = STATUS_DOWNLOADED
            base.reason = "unchanged; existing verified artifact reused"
            for field in ("final_url", "http_status", "media_type", "bytes",
                          "sha256", "path", "etag", "last_modified"):
                setattr(base, field, previous[field])
            base.attempts = previous["attempts"] or 0
            return base

    floor = asset.min_bytes if asset.min_bytes is not None else \
        MIN_CONTENT_BYTES_BY_WORK_TYPE.get(work.work_type, config.min_bytes)
    try:
        response = fetcher.fetch(asset.url or "",
                                 expected_media_type=asset.expected_media_type,
                                 min_bytes=floor)
    except FetchError as exc:
        base.status = STATUS_FAILED
        base.kind = exc.kind
        base.http_status = exc.http_status
        base.reason = exc.reason
        base.attempts = store.attempt_count(asset.id) + 1
        store.log_attempt(run_id, asset.id, started, f"failed:{exc.kind}",
                          exc.http_status, exc.reason)
        return base

    media_type = response.media_type or sniff_media_type(
        response.body_path.read_bytes()[:1024])
    destination = artifact_path(ws, work, asset, media_type)
    # Atomic: the temp file is only installed after validation passed.  The
    # helper also handles /tmp and the workspace being separate filesystems.
    util.move_file_atomic(response.body_path, destination)

    base.status = STATUS_DOWNLOADED
    base.final_url = response.final_url
    base.redirects = response.redirects
    base.http_status = response.status
    base.media_type = media_type
    base.bytes = response.bytes
    base.sha256 = response.sha256
    base.path = str(destination.relative_to(ws.root))
    base.etag = response.headers.get("etag")
    base.last_modified = response.headers.get("last-modified")
    base.attempts = store.attempt_count(asset.id) + 1
    if response.headers.get("x-host-changed") == "true":
        base.reason = (f"final host differs from the requested host: {response.final_url}")
    store.log_attempt(run_id, asset.id, started, "downloaded", response.status, None)
    return base


def import_local(ws: Workspace, corpus: Corpus, store: Store, alias: str,
                 source: Path, role: str = "fulltext") -> AssetOutcome:
    """Register a legally obtained local copy. Provenance is user_supplied."""
    work = corpus.by_alias().get(alias)
    if work is None:
        raise FetchError(f"unknown alias {alias}", kind="policy")
    source = Path(source)
    if not source.is_file():
        raise FetchError(f"not a file: {source}", kind="policy")
    with source.open("rb") as handle:
        head = handle.read(1024)
    media_type = sniff_media_type(head) or "application/octet-stream"
    asset_id = f"{util.safe_path_segment(alias)}-user-supplied"
    suffix = {"application/pdf": ".pdf", "text/html": ".html",
              "application/xml": ".xml"}.get(media_type, source.suffix or ".bin")
    destination = ws.manual_import / util.safe_path_segment(alias) / (asset_id + suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=str(destination.parent)) as handle:
        handle.write(source.read_bytes())
        temp = Path(handle.name)
    os.replace(temp, destination)
    digest = util.sha256_file(destination)

    outcome = AssetOutcome(
        alias=alias, work_id=work.id, asset_id=asset_id, role=role,
        intent="manual", requested_url=None, status=STATUS_DOWNLOADED,
        reason="user_supplied: provenance is a local file, not a verified download",
        media_type=media_type, bytes=destination.stat().st_size, sha256=digest,
        path=str(destination.relative_to(ws.root)), attempts=0,
    )
    store.record_artifact({
        "asset_id": asset_id, "work_id": work.id, "alias": alias, "role": role,
        "intent": "manual", "requested_url": "user_supplied",
        "final_url": None, "status": STATUS_DOWNLOADED, "http_status": None,
        "media_type": media_type, "bytes": outcome.bytes, "sha256": digest,
        "path": outcome.path, "etag": None, "last_modified": None,
        "attempts": 0, "reason": outcome.reason, "fetched_at": util.now_iso(),
    })
    return outcome


def summarize(outcomes: list[AssetOutcome], corpus: Corpus | None = None) -> dict:
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    required_failures = [o for o in outcomes
                         if o.status == STATUS_FAILED and o.intent == "required"]
    integrity_failures = [o for o in outcomes if o.kind == "integrity"]
    missing_fulltext = [o for o in outcomes
                        if o.role == "fulltext" and o.status != STATUS_DOWNLOADED]
    return {
        "counts": dict(sorted(counts.items())),
        "required_failures": [o.asset_id for o in required_failures],
        "integrity_failures": [o.asset_id for o in integrity_failures],
        "fulltext_not_downloaded": [o.asset_id for o in missing_fulltext],
        "works_without_fulltext": works_without_fulltext(outcomes, corpus),
    }


def works_without_fulltext(outcomes: list[AssetOutcome],
                           corpus: Corpus | None) -> list[str]:
    """Aliases with no verified full text on disk.

    Counted per work, not per asset: a work whose only route is a preview,
    borrow or purchase page has no fulltext asset at all, and that is exactly
    the gated case `--require-fulltext-all` exists to surface. Collections hold
    no text of their own and are judged through their members.
    """
    have = {o.alias for o in outcomes
            if o.role == "fulltext" and o.status == STATUS_DOWNLOADED}
    if corpus is None:
        return sorted({o.alias for o in outcomes} - have)
    return sorted(
        w.primary_alias for w in corpus.works
        if w.work_type != "collection" and w.primary_alias not in have
    )


def exit_code_for(outcomes: list[AssetOutcome], require_fulltext_all: bool = False,
                  corpus: Corpus | None = None) -> int:
    summary = summarize(outcomes, corpus)
    codes = []
    if summary["integrity_failures"]:
        codes.append(util.EXIT_INTEGRITY)
    if summary["required_failures"]:
        codes.append(util.EXIT_INCOMPLETE)
    if require_fulltext_all and summary["works_without_fulltext"]:
        codes.append(util.EXIT_INCOMPLETE)
    return util.resolve_exit_code(codes)
