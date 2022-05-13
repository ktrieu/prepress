import enum
from string import ascii_letters

class QuoteDir(enum.Enum):
    Left = 'left',
    Right = 'right',
    Straight = 'straight'

# Quotes only really start with varieties of left brackets
LEFT_PUNCTUATION = { '(', '{', '<' }
# But they can be ended with any of the standard sentence enders
RIGHT_PUNCTUATION = { ')', '}', '>', '.', ',', '?', '!', ':', ';' }

DOUBLE_QUOTES = {
    QuoteDir.Left: '“',
    QuoteDir.Right: '”',
    QuoteDir.Straight: '"'
}

SINGLE_QUOTES = {
    QuoteDir.Left: '‘',
    QuoteDir.Right: '’',
    QuoteDir.Straight: '\''
}

def get_quote_direction(before: str, after: str):
    # double quotes can occur at the beginning/end of strings
    if before is None:
        return QuoteDir.Left
    if after is None:
        return QuoteDir.Right

    # double quotes can occur before/after spaces
    if before.isspace():
        return QuoteDir.Left
    # ditto for the right
    if after.isspace():
        return QuoteDir.Right

    # double quotes can occur before/after punctuation
    if before in LEFT_PUNCTUATION:
        return QuoteDir.Left
    if after in RIGHT_PUNCTUATION:
        return QuoteDir.Right

    # single quotes can appear within contractions
    if before in ascii_letters and after in ascii_letters:
        return QuoteDir.Right

    return QuoteDir.Straight

def get_double_quote(dir: QuoteDir):
    return DOUBLE_QUOTES[dir]

def get_single_quote(dir: QuoteDir):
    return SINGLE_QUOTES[dir]
