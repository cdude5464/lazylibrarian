"""Explicit operator-approved edition exceptions for exact ebook torrents."""
import json
import os
import re
import unicodedata

from lazylibrarian.filesystem import DIRS


def _identity(value):
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def filter_edition_reject_words(words, download_id, author, title):
    """Only relax approved edition words; never format, language or content gates."""
    original = list(words)
    if not all(isinstance(value, str) for value in (download_id, author, title)):
        return original
    if (not DIRS.DATADIR or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", download_id or "")
            or not _identity(author) or not _identity(title)):
        return original
    try:
        path = os.path.join(DIRS.DATADIR, "ebook-edition-exceptions.json")
        with open(path, encoding="utf-8") as handle:
            document = handle.read(65537)
        if len(document) > 65536:
            return original
        data = json.loads(document)
        if data.get("schema") != "ebook-edition-exceptions-v1":
            return original
        matches = [item for item in data["entries"] if
                   item["download_id"].lower() == download_id.lower()
                   and _identity(item["author"]) == _identity(author)
                   and _identity(item["title"]) == _identity(title)]
        if len(matches) != 1 or matches[0].get("approved") is not True:
            return original
        allowed = matches[0]["allowed_words"]
        if not isinstance(allowed, list) or not allowed or any(word != "anniversary" for word in allowed):
            return original
        return [word for word in original if word.strip().casefold() not in allowed]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return original
