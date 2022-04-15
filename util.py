from bs4 import Tag

# Unicode LINE SEPARATOR character
LINE_SEPARATOR = '\u2028'
# Tags within which we should not be replacing content
VERBATIM_TAGS = ('pre', 'code')


def keep_verbatim(tag: Tag) -> bool:
    return tag.name in VERBATIM_TAGS or any(filter(lambda t: t.name in VERBATIM_TAGS, tag.parents))
