"""Conservative primary-title queries for explicitly stored subtitle suffixes."""
import re


# These suffixes identify a different volume, edition, format or language;
# they must not become optional merely because metadata calls them a subtitle.
_IDENTITY_WORDS = {
    'vol', 'volume', 'book', 'part', 'edition', 'abridged', 'unabridged',
    'graphic', 'comic', 'comics', 'manga', 'illustrated', 'adaptation',
    'translation', 'translated', 'language', 'omnibus', 'anthology',
    'collection', 'companion', 'workbook', 'summary', 'revised', 'expanded',
    'updated', 'anniversary', 'definitive', 'deluxe', 'annotated', 'epub', 'mobi', 'azw', 'pdf',
    'audiobook', 'audio', 'ebook', 'paperback', 'hardcover', 'hardback',
    'english', 'french', 'german', 'spanish', 'italian', 'portuguese',
    'swedish', 'norwegian', 'danish', 'dutch', 'russian', 'polish', 'czech',
    'finnish', 'hungarian', 'turkish', 'japanese', 'chinese', 'korean',
    'arabic', 'romanian', 'greek',
}


def primary_title(book):
    """Return a shorter title only when BookSub is an exact separated suffix."""
    title = str(book.get('bookName') or '').strip()
    subtitle = str(book.get('bookSub') or '').strip()
    if (not subtitle or re.search(r'\d', subtitle)
            or set(_tokens(subtitle)) & _IDENTITY_WORDS
            or re.fullmatch(r'[IVXLCDM]+', subtitle, flags=re.I)
            or re.fullmatch(r'(?:en|eng|fr|fre|fra|de|ger|deu|es|spa|it|ita|pt|por|ru|rus|ja|jpn|zh|chi|zho|ko|kor|ar|ara)(?:[-_][A-Za-z]{2,3})?', subtitle, flags=re.I)):
        return ''
    match = re.fullmatch(r'(.+?)(?:\s*:\s*|\s+[-–—]\s+)' + re.escape(subtitle), title)
    primary = match.group(1).strip() if match else ''
    if _tokens(primary) == _tokens(book.get('authorName')):
        return ''
    return primary


def _tokens(value):
    return re.findall(r'[^\W_]+', str(value or '').casefold())


def exact_primary_result(book, result_title, formats):
    """Require the complete author and primary title, with only a format suffix."""
    primary = _tokens(primary_title(book))
    author = _tokens(book.get('authorName'))
    if not primary or len(author) < 2:
        return False
    observed = _tokens(result_title)
    format_tokens = {str(value).casefold() for value in formats}
    if observed and observed[-1] in format_tokens:
        observed = observed[:-1]
    authors = [author]
    # Anna commonly writes "Surname, Given name". Permit only that explicit
    # comma spelling, never arbitrary reordered/partial/fuzzy author tokens.
    reversed_pattern = (r'\b' + re.escape(author[-1]) + r'\s*,\s*'
                        + r'\W+'.join(re.escape(word) for word in author[:-1]) + r'\b')
    if re.search(reversed_pattern, str(result_title), flags=re.I):
        authors.append(author[-1:] + author[:-1])
    return any(observed == person + primary or observed == primary + person for person in authors)
