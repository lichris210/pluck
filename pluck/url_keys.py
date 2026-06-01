"""Pure URL-key derivation utilities for schema and result caching."""

import re
from urllib.parse import urlparse, urlencode, parse_qsl

# Matches purely numeric segments or UUID/hash-like IDs (hex 8+ chars, or
# mixed alphanum 6+ chars that look like generated IDs).
_ID_RE = re.compile(
    r'^(?:'
    r'\d+'                          # pure numeric: 12345
    r'|[0-9a-f]{8,}'               # lowercase hex ID: a3f9c2d1...
    r'|[0-9A-Fa-f]{8,}'            # mixed-case hex
    r'|[A-Za-z0-9_-]{20,}'        # long opaque slug (20+ chars)
    r')$'
)


def _strip_scheme(url: str) -> str:
    parsed = urlparse(url)
    # Normalise: lowercase host, drop fragment, keep path
    host = (parsed.hostname or "").lower()
    if parsed.port and parsed.port not in (80, 443):
        host = f"{host}:{parsed.port}"
    return host + parsed.path


def _collapse_ids(path: str) -> str:
    """Replace ID-like segments in *path* with '*'."""
    segments = path.split("/")
    collapsed = []
    for seg in segments:
        if seg and _ID_RE.match(seg):
            collapsed.append("*")
        else:
            collapsed.append(seg)
    return "/".join(collapsed)


def schema_key(url: str) -> str:
    """Return a normalised domain + path-pattern string for schema caching.

    Numeric and opaque-ID path segments are collapsed to '*'.
    Query params and fragments are dropped.
    Example: https://www.linkedin.com/jobs/12345 → linkedin.com/jobs/*
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    # Strip 'www.' prefix so www.linkedin.com == linkedin.com
    if host.startswith("www."):
        host = host[4:]
    if parsed.port and parsed.port not in (80, 443):
        host = f"{host}:{parsed.port}"

    path = parsed.path.rstrip("/") or "/"
    path = _collapse_ids(path)

    return host + path


def results_key(url: str) -> str:
    """Return a normalised full-URL string for result caching.

    Scheme is stripped, query params are sorted, fragment is dropped,
    trailing slash is removed.
    Example: https://example.com/page?b=2&a=1#frag → example.com/page?a=1&b=2
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.port and parsed.port not in (80, 443):
        host = f"{host}:{parsed.port}"

    path = parsed.path.rstrip("/") or "/"

    # Sort query params for stable keys
    sorted_query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))

    key = host + path
    if sorted_query:
        key += "?" + sorted_query
    return key
