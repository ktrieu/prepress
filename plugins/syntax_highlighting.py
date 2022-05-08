import enum
from pygments.formatter import Formatter
from util import html_escape

class SyntaxHighlightType(enum.Enum):
    Bold = 'strong'
    Italic = 'em'
    BoldItalic = 'em2'
    Underline = 'u'

# Automatically generate the tag names
SYNTAX_HIGHLIGHT_PREFIX = 'mathnews--code-'
SYNTAX_HIGHLIGHT_TAGS = { member: SYNTAX_HIGHLIGHT_PREFIX + member.value for member in SyntaxHighlightType }

def get_syntax_highlight_tag_name(tag_type: SyntaxHighlightType) -> str:
    return SYNTAX_HIGHLIGHT_TAGS[tag_type]

def is_highlighted(text: str) -> bool:
    return any(tag in text for tag in SYNTAX_HIGHLIGHT_TAGS.values())

class IndFormatter(Formatter):
    """InDesign compatible formatter, based on https://pygments.org/docs/formatterdevelopment/#html-3-2-formatter
    """

    def __init__(self, **options):
        Formatter.__init__(self, **options)

        # create a dict of (start, end) tuples that wrap the
        # value of a token so that we can use it in the format
        # method later
        self.styles = {}

        # we iterate over the `_styles` attribute of a style item
        # that contains the parsed style values.
        for token, style in self.style:
            start = end = ''
            tag_type = None
            # a style item is a tuple in the following form:
            if style['bold'] and style['italic']:
                tag_type = SyntaxHighlightType.BoldItalic
            elif style['bold']:
                tag_type = SyntaxHighlightType.Bold
            elif style['italic']:
                tag_type = SyntaxHighlightType.Italic
            elif style['underline'] or style['border']:
                tag_type = SyntaxHighlightType.Underline

            if tag_type != None:
                start = f'<{get_syntax_highlight_tag_name(tag_type)}>'
                end = f'</{get_syntax_highlight_tag_name(tag_type)}>'

            self.styles[token] = (start, end)

    def format_unencoded(self, tokensource, outfile):
        # lastval is a string we use for caching
        # because it's possible that an lexer yields a number
        # of consecutive tokens with the same token type.
        # to minimize the size of the generated html markup we
        # try to join the values of same-type tokens here
        lastval = ''
        lasttype = None

        for ttype, value in tokensource:
            value = html_escape(value)
            # if the token type doesn't exist in the stylemap
            # we try it with the parent of the token type
            # eg: parent of Token.Literal.String.Double is
            # Token.Literal.String
            while ttype not in self.styles:
                ttype = ttype.parent
            if ttype == lasttype:
                # the current token type is the same of the last
                # iteration. cache it
                lastval += value
            else:
                # not the same token as last iteration, but we
                # have some data in the buffer. wrap it with the
                # defined style and write it to the output file
                if lastval:
                    stylebegin, styleend = self.styles[lasttype]
                    outfile.write(stylebegin + lastval + styleend)
                # set lastval/lasttype to current values
                lastval = value
                lasttype = ttype

        # if something is left in the buffer, write it to the
        # output file, then close the opened <pre> tag
        if lastval:
            stylebegin, styleend = self.styles[lasttype]
            outfile.write(stylebegin + lastval + styleend)
