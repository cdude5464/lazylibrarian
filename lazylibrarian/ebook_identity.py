"""Conservative explicit volume identity checks for ebook titles."""
import re


_VOLUME = re.compile(r"\bvol(?:ume)?\.?\s*#?\s*(\d+(?:\.\d+)?|[ivxlcdm]+)\b", re.I)


def _volume_numbers(title):
    values = set()
    for token in _VOLUME.findall(str(title or "")):
        if token[0].isdigit():
            values.add(float(token))
        else:
            roman = token.upper()
            # Restrict Roman notation to canonical numbers; avoid word fragments.
            if not re.fullmatch(r"M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})", roman):
                continue
            numbers = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
            value = 0
            previous = 0
            for char in reversed(roman):
                number = numbers[char]
                value += -number if number < previous else number
                previous = max(previous, number)
            values.add(value)
    return values


def ebook_volume_conflict(expected_title, observed_title):
    """Reject contradictory explicit Vol/Volume identifiers, never infer a number."""
    expected = _volume_numbers(expected_title)
    observed = _volume_numbers(observed_title)
    return bool(expected and observed and expected != observed)


def ebook_graphic_volume_unverified(expected_title, observed_title):
    """An explicitly numbered graphic novel requires positive format/volume identity."""
    def graphic_novel(value):
        words = re.findall(r'[a-z]+', str(value or '').casefold())
        return any(words[index:index + 2] == ['graphic', 'novel'] for index in range(len(words) - 1))

    expected = _volume_numbers(expected_title)
    if not expected or not graphic_novel(expected_title):
        return False
    return not graphic_novel(observed_title) or _volume_numbers(observed_title) != expected


def ebook_collection_unverified(expected_title, observed_title):
    """An explicitly requested collection requires embedded collection identity.

    A constituent work from the same author does not establish that a box set
    or omnibus is present. Accept synonymous collection descriptors; ordinary
    work and edition matching remains the caller's responsibility.
    """
    collection = re.compile(
        r"\b(?:collection|omnibus|box(?:ed)?[\s-]*set|bundle|(?:collected|complete)[\s-]+works|complete[\s-]+series)\b",
        re.I,
    )
    return bool(collection.search(str(expected_title or ""))
                and not collection.search(str(observed_title or "")))


def ebook_title_count_conflict(expected_title, observed_title):
    """Reject contradictory explicit leading counts with the same title noun.

    Do not interpret years, volume identifiers, arbitrary title digits or a
    missing count as evidence of a different work.
    """
    count = re.compile(r"^\s*(\d+)\s+([a-z]+)\b", re.I)
    expected = count.search(str(expected_title or ""))
    observed = count.search(str(observed_title or ""))
    return bool(expected and observed
                and len(expected.group(1)) != 4 and len(observed.group(1)) != 4
                and expected.group(2).casefold() == observed.group(2).casefold()
                and int(expected.group(1)) != int(observed.group(1)))


def ebook_audio_edition_conflict(expected_title):
    """An ebook cannot prove an explicitly requested audio edition."""
    # A bare 'audiobook' can be the subject of a genuine ebook handbook.
    return bool(re.search(r"\baudio[\s-]+collection\b|\baudio[\s-]*book[\s-]+edition\b|[\[(]audio[\s-]*book[\])]",
                          str(expected_title or ""), re.I))
