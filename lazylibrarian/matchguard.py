#  This file is part of Lazylibrarian.
#
#  Lazylibrarian is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import re

from lazylibrarian.formatter import unaccented


_GENERIC_EBOOK_TOKENS = {
    "a",
    "an",
    "and",
    "at",
    "book",
    "books",
    "by",
    "ed",
    "edition",
    "ebook",
    "ebooks",
    "for",
    "from",
    "in",
    "novel",
    "of",
    "on",
    "or",
    "part",
    "retail",
    "series",
    "standalone",
    "the",
    "to",
    "vol",
    "volume",
    "with",
}

_ALLOWED_EBOOK_PHRASES = (
    ("barnes", "noble", "classics"),
    ("dover", "thrift", "editions"),
    ("dover", "thrift"),
    ("everyman", "library"),
    ("modern", "library"),
    ("oxford", "world", "classics"),
    ("penguin", "classic"),
    ("penguin", "classics"),
    ("penguin", "modern", "classics"),
    ("signet", "classics"),
    ("wordsworth", "classics"),
)


def match_tokens(value: str) -> list[str]:
    """Return normalized alphanumeric tokens for source/title comparisons."""
    return re.findall(r"[a-z0-9]+", unaccented(value or "", only_ascii=False).lower())


_EDGE_IGNORABLE_EBOOK_TOKENS = {
    "ebook",
    "ebooks",
    "retail",
    "standalone",
}


def _is_edge_noise(token: str, edge_ignorable: set[str]) -> bool:
    return token in edge_ignorable or token.isdigit()


def _remove_allowed_edge_phrases(tokens: list[str], edge_ignorable: set[str]) -> list[str]:
    keep = [True] * len(tokens)
    for phrase in _ALLOWED_EBOOK_PHRASES:
        phrase_len = len(phrase)
        if not phrase_len or phrase_len > len(tokens):
            continue
        for index in range(0, len(tokens) - phrase_len + 1):
            if tuple(tokens[index:index + phrase_len]) != phrase:
                continue

            before = tokens[:index]
            after = tokens[index + phrase_len:]
            is_prefix = (
                all(_is_edge_noise(token, edge_ignorable) for token in before)
                and bool(after)
                and after[0] not in _GENERIC_EBOOK_TOKENS
                and after[0] not in edge_ignorable
            )
            is_suffix = (
                all(_is_edge_noise(token, edge_ignorable) for token in after)
                and bool(before)
                and before[-1] not in _GENERIC_EBOOK_TOKENS
                and before[-1] not in edge_ignorable
            )
            if is_prefix or is_suffix:
                for phrase_index in range(index, index + phrase_len):
                    keep[phrase_index] = False

    return [token for index, token in enumerate(tokens) if keep[index]]


def significant_extra_words(
    result_title: str,
    *,
    author: str = "",
    title: str = "",
    subtitle: str = "",
    format_words: str = "",
    prefer_words: str = "",
) -> list[str]:
    """Words in a candidate title that are not explained by the requested book."""
    allowed: set[str] = set()
    for value in (author, title, subtitle, format_words, prefer_words):
        allowed.update(match_tokens(value))

    edge_ignorable = set(match_tokens(format_words))
    edge_ignorable.update(match_tokens(prefer_words))
    edge_ignorable.update(_EDGE_IGNORABLE_EBOOK_TOKENS)

    extra = []
    seen = set()
    for token in _remove_allowed_edge_phrases(match_tokens(result_title), edge_ignorable):
        if (
            token in seen
            or token in allowed
            or token in _GENERIC_EBOOK_TOKENS
            or token.isdigit()
            or len(token) <= 1
        ):
            continue
        extra.append(token)
        seen.add(token)
    return extra


def weak_author_extra_title_words(
    result_title: str,
    *,
    author: str,
    title: str,
    author_match: float,
    match_ratio: int,
    subtitle: str = "",
    format_words: str = "",
    prefer_words: str = "",
) -> list[str]:
    """Detect the short-title subset trap when author evidence is weak."""
    if author_match >= match_ratio:
        return []
    return significant_extra_words(
        result_title,
        author=author,
        title=title,
        subtitle=subtitle,
        format_words=format_words,
        prefer_words=prefer_words,
    )
