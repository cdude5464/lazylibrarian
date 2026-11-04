"""Safe network diagnostics: log origins, never authentication or signed paths."""
import re
from urllib.parse import urlsplit


def provider_log_origin(value):
    """Return only a URL origin, omitting userinfo, path, query and fragment."""
    try:
        text = str(value)
        parsed = urlsplit(text if "://" in text else "//" + text)
        host = parsed.hostname
        if not host or not re.fullmatch(r"[a-zA-Z0-9._:-]+", host):
            return "[provider]"
        if ":" in host:
            host = "[" + host + "]"
        port = ":" + str(parsed.port) if parsed.port else ""
        scheme = parsed.scheme + "://" if parsed.scheme else ""
        return scheme + host + port
    except (ValueError, TypeError):
        return "[provider]"


def provider_error_category(value):
    """Classify failures with fixed labels, without echoing provider response text."""
    text = str(value).lower()
    for tokens, label in (
        (("cookie",), "authentication-cookie"),
        (("login", "log in", "sign in", "unauthorized", "401"), "authentication-required"),
        (("429", "too many requests", "rate limit"), "rate-limit"),
        (("403", "forbidden", "ddos-guard", "cloudflare"), "access-denied"),
        (("timeout", "timed out"), "timeout"),
        (("toomanyredirects", "too many redirects"), "redirect-limit"),
        (("connectionerror", "connection refused", "name resolution"), "connection-failure"),
    ):
        if any(token in text for token in tokens):
            return label
    return "provider-error"
