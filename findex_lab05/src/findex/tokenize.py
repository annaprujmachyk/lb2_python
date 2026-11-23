"""Streaming Unicode tokenization.

Policy: apostrophes and hyphens separate tokens; digits are included in tokens;
underscore is also a separator. NFC normalization precedes casefolding.
"""

import re
import unicodedata
from collections.abc import Iterator

# Unicode alphanumerics but not underscore. \w is Unicode aware in Python 3.
WORD_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)


def tokenize(text: str) -> Iterator[str]:
    """Yield normalized Unicode tokens without building a match list."""
    normalized = unicodedata.normalize("NFC", text).casefold()
    for match in WORD_RE.finditer(normalized):
        yield match.group()
