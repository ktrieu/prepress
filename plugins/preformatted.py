from typing import Dict, Union

import bs4
import pygments as pyg
from pygments import lexers, util

from util import LINE_SEPARATOR
from plugins.syntax_highlighting import IndFormatter

Options = Dict[str, Union[str, bool]]

# Maximum length of a line in a code block
MAX_PRE_LINE_LENGTH = 48


def highlight_code(pre_contents: str, options: Options) -> str:
    """ Add syntax highlighting to a code block
    """
    # Find lexer for the given language
    lang_name = options.get('language', options.get('lang', None))  # allow for language or lang options
    try:
        lexer = pyg.lexers.get_lexer_by_name(lang_name)
    except pyg.util.ClassNotFound:
        return pre_contents

    # Highlight the code
    formatter = IndFormatter(style='bw')
    pre_text = bs4.BeautifulSoup(pre_contents, 'html.parser').get_text().strip()
    pre_text = pyg.highlight(pre_text, lexer, formatter)
    # Strip ending whitespace
    return pre_text.rstrip()


def add_linenos(pre_contents: str, options: Options) -> str:
    """ Add line numbers to a code block
    """
    if options.get('linenos', False):
        first_line, *rest = pre_contents.split('\n')
        pre_contents = f'<mathnews-pre--lineno-start>{first_line}</mathnews-pre--lineno-start>'
        if rest:
            rest_joined = '\n'.join(rest)
            pre_contents += f'\n<mathnews-pre--lineno>{rest_joined}</mathnews-pre--lineno>'

    return pre_contents


def find_best_break(line: str, offset: int, break_estimate: int) -> int:
    """Find the best place to insert a line break based on the weight of a token
    """
    # Token weights indicate how far back the algorithm should search for a token with lower weight/higher priority
    find_best_break.map = {
        ' ': 0,
        ',': 0,
        ';': 0,
        '%': 2,
        '^': 2,
        '/': 3,
        '&': 3,
        '|': 3,
        '+': 3,
        '-': 3,
        '*': 3,
        '=': 4,
        '}': 4,
        '{': 5,
        ')': 5,
        '(': 6,
        ']': 5,
        '[': 6,
        '>': 5,
        '<': 6,
        '_': MAX_PRE_LINE_LENGTH,  # Tokens likely to appear in the middle of a word, or as punctuation, are given
        '.': MAX_PRE_LINE_LENGTH,  # highest weight/lowest priority
        '!': MAX_PRE_LINE_LENGTH,
        '?': MAX_PRE_LINE_LENGTH
    }
    break_at = MAX_PRE_LINE_LENGTH
    break_priority = float('inf')
    search_lower_lim = MAX_PRE_LINE_LENGTH // 2
    while break_estimate > search_lower_lim:
        break_candidate = line[offset + break_estimate - 1]
        if break_candidate in find_best_break.map and find_best_break.map[break_candidate] < break_priority:
            # Found a line break candidate
            break_priority = find_best_break.map[break_candidate]
            break_at = break_estimate
            # Make sure not to backtrack beyond previous limits
            search_lower_lim = max(search_lower_lim, break_estimate - break_priority)
        break_estimate -= 1

    return break_at


def wrap_lines(pre_tag: bs4.Tag) -> bs4.Tag:
    # Insert line-wraps
    # Our first step is to create a changeset for the plaintext version
    pre_text = pre_tag.get_text()
    pre_lines = pre_text.split('\n')
    changeset = []
    running_offset = 0
    for line in pre_lines:
        cur_line_start = 0
        line_len = len(line)
        max_len_offset = 0  # Leave space for the line continuation character
        while line_len - cur_line_start > MAX_PRE_LINE_LENGTH - max_len_offset:
            # find a break point
            split_at = find_best_break(line, cur_line_start, MAX_PRE_LINE_LENGTH - max_len_offset)
            cur_line_start += split_at
            changeset.append(running_offset + cur_line_start)
            max_len_offset = 1  # one less column due to line continuation character

        running_offset += line_len + 1  # add one for newline character

    # Next, we match up the offsets of each text tag in the plaintext
    text_tags = pre_tag.find_all(text=True)
    tags_offset = [0] * len(text_tags)
    running_len = 0
    for idx, text_tag in enumerate(text_tags):
        tags_offset[idx] = running_len
        running_len += len(text_tag)

    # Finally, we apply the changeset
    # We apply in reverse so that earlier changes don't mess up the offsets of later changes
    cur_changeset_idx = len(changeset) - 1
    line_end_correction = 0  # Leave out spaces at the end of lines. Has to persist between tags (see below)
    for cur_tag_idx in range(len(text_tags))[::-1]:
        cur_tag = text_tags[cur_tag_idx]
        cur_tag_offset = tags_offset[cur_tag_idx]
        sub_tags = []
        line_end = len(cur_tag) - line_end_correction

        while cur_changeset_idx >= 0 and changeset[cur_changeset_idx] >= cur_tag_offset:
            # apply changes
            change_offset = changeset[cur_changeset_idx] - cur_tag_offset
            sub_tags.append(cur_tag[change_offset:line_end])  # text after split
            # Use RIGHTWARDS ARROW WITH HOOK (↪, U+21AA) to signify line continuation
            line_cont = pre_tag.new_tag('mathnews-pre--ruby')
            line_cont.string = '\u21aa'
            sub_tags.append(line_cont)
            sub_tags.append(LINE_SEPARATOR)

            # Replace spaces at end of line with space symbol
            line_end_correction = 0
            if change_offset > 0 and cur_tag[change_offset - 1] == ' ':
                line_end_correction = 1
            elif change_offset == 0 and cur_tag_idx > 0:
                # At a tag boundary, so must check if preceding tag ends with a space. If so, set line_end_correction
                # and let it persist to the next tag
                tmp_idx = cur_tag_idx - 1
                while tmp_idx >= 0 and len(text_tags[tmp_idx]) == 0:
                    # skip over empty tags
                    tmp_idx -= 1
                if tmp_idx >= 0 and text_tags[tmp_idx][-1] == ' ':
                    line_end_correction = 1
            if line_end_correction:
                # Use OPEN BOX (␣, U+2423) to signify space
                space_symb = pre_tag.new_tag('mathnews-pre--ruby')
                space_symb.string = '\u2423'
                sub_tags.append(space_symb)

            line_end = change_offset - line_end_correction
            cur_changeset_idx -= 1

        # Add in whatever's left at the front of the current tag to the builder, then replace
        if line_end > 0:
            sub_tags.append(cur_tag[:line_end])
            line_end_correction = 0  # "used" the correction here, so reset it

        cur_tag.replace_with(*reversed(sub_tags))

    return pre_tag
