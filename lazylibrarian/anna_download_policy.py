"""File availability is distinct from Anna account and quota failures."""
import math
import re
import time


ANNA_PARTNER_UNAVAILABLE = "Anna partner download path is temporarily unavailable"
ANNA_FILE_RETRY_SECONDS = 6 * 60 * 60
_ANNA_FILE_RETRY_REASONS = frozenset({
    ANNA_PARTNER_UNAVAILABLE.casefold(),
    *(f"anna file api request failed (http {status})" for status in (502, 503, 504)),
})
ANNA_AUTH_FAILURES = frozenset({
    "Anna file API authentication failed (HTTP 401)",
    "Anna file API access denied (HTTP 403)",
})


def anna_account_failure(reason):
    """Stop same-cycle requests even when the user disables timed blocks."""
    if not isinstance(reason, str):
        return False
    return (reason in ANNA_AUTH_FAILURES or bool(re.fullmatch(
        r"(?:Download limit \(\d+\) reached|Error Status: (?:409|429) Anna fast-download limit reached or rate limited\.)",
        reason or "")))


def _field(row, name):
    return next((row[key] for key in row.keys() if key.casefold() == name.casefold()), None)


def anna_file_retry_due(row, now=None):
    """Only an exact, timestamped availability failure permits a later retry."""
    try:
        if (_field(row, "Status") != "Failed"
                or str(_field(row, "NZBprov") or "").casefold() != "annas"
                or str(_field(row, "DLResult") or "").casefold() not in _ANNA_FILE_RETRY_REASONS):
            return False
        completed = float(_field(row, "completed"))
        current = time.time() if now is None else now
        return (math.isfinite(completed) and completed > 0
                and current - completed >= ANNA_FILE_RETRY_SECONDS)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False


def anna_api_failure(status, payload):
    """Use fixed diagnostics; never echo server text, credentials or URLs."""
    error = payload.get("error") if isinstance(payload, dict) else None
    if status == 400 and error == "Invalid domain_index or path_index":
        return ANNA_PARTNER_UNAVAILABLE
    if status == 401:
        return "Anna file API authentication failed (HTTP 401)"
    if status == 403:
        return "Anna file API access denied (HTTP 403)"
    if status == 404:
        return "Anna file API record not found (HTTP 404)"
    return f"Anna file API request failed (HTTP {status})"
