import argparse
import os
import os.path
from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement
from typing import List, Callable, Union
import re
import itertools
import urllib.request
import urllib.parse
import urllib.error
import html
import shutil
import hashlib
import subprocess

import ssl

import bs4
from bs4 import BeautifulSoup, Tag
import pylatex
from PIL import Image

from smart_quotes import get_quote_direction, get_double_quote, get_single_quote

#The directory to store generated assets. Can be changed by command line argument.
ASSET_DIR = 'assets'
#The location of the output file. Can be changed by command line argument'
OUTPUT_FILE = 'issue.xml'
#The current working directory
CURRENT_DIR: str
#273 pt, at 300 DPI
DPI = 300
IMAGE_WIDTH_DEFAULT = 1138
USER_AGENT = "curl/7.61" # 'Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:81.0) Gecko/20100101 Firefox/81.0'

# Unicode LINE SEPARATOR character
LINE_SEPARATOR = '\u2028'

XML_NS = {
    'content': 'http://purl.org/rss/1.0/modules/content/'
}

# Tags within which we should not be replacing content
VERBATIM_TAGS = ('pre', 'code')

class Article:

    def __init__(self):
        self.author = ''
        self.title = ''
        #content is stored as a beautiful soup tree
        self.content: BeautifulSoup = None

    def get_image_location(self, file: str) -> str:
        #generate a slug by trimming the title, replacing non-ascii chars, and replacing spaces
        file_prefix = re.sub(r"\W",  "", self.title[0:10].encode('ascii', errors='ignore').decode().replace(' ', '_'))
        filename = file_prefix + '_' + file
        return os.path.join(ASSET_DIR, 'img', filename)

    def get_pdf_location(self, file: str) -> str:
        file_prefix = re.sub(r"\W",  "", self.title[0:10].encode('ascii', errors='ignore').decode().replace(' ', '_'))
        filename = file_prefix + '_' + file
        return os.path.join(ASSET_DIR, 'pdf', filename)
    
    def to_xml_element(self) -> Element:
        article_tag = Element('article')
        title_tag = SubElement(article_tag, 'title')
        # encode into html entities
        title_tag.text = self.title.replace('&', '&amp;').replace('<', '&lt;') if self.title else ""
        content_tag = SubElement(article_tag, 'content')
        content_tag.text = str(self.content)
        return article_tag

def is_for_issue(article_tag: Element, issue_num: str) -> bool:
    """Returns True if the article given by the <item> tag article_tag
    belongs to the issue given by issue_num.
    """
    for category in article_tag.findall('category'):
        if category.get('domain') == 'post_tag' and category.text == issue_num:
            return True
    return False

def filter_articles(tree: ElementTree, issue_num: str) -> List[Article]:
    """Given an ElementTree parsed from an XML dump, returns a list 
    of Article instances containing all the articles tagged with issue_num.
    """ 
    root = tree.getroot()
    articles: List[Article] = []
    article_tags = root.findall('.//item')
    for article_tag in article_tags:
        if not is_for_issue(article_tag, issue_num):
            continue
        article = Article()
        #possible optimization, instead of calling find several times,
        #loop through tag children once and parse out data as we run into it
        article.title = article_tag.find('title').text
        #we will post process this later
        article.author = 'UNKNOWN AUTHOR'
        article_text_content = article_tag.find('content:encoded', XML_NS).text
        article.content = BeautifulSoup(article_text_content, 'html.parser')
        articles.append(article)
    return articles

def keep_verbatim(tag: Union[Tag, bs4.NavigableString]) -> bool:
    return tag.name in VERBATIM_TAGS or any(filter(lambda t: t.name in VERBATIM_TAGS, tag.parents))

def replace_text_with_tag(sub_text: str,
                          repl_tag: Tag,
                          text_tag: bs4.NavigableString,
                          article: Article) -> bs4.NavigableString:
    #if we can't find the parent, assume it's just the document
    parent: Tag
    if text_tag.parent == None or text_tag.parent.name == '[document]':
        parent = article.content
    else:
        parent = text_tag.parent
    tag_idx = parent.contents.index(text_tag)
    #replace the matched text with a tag
    begin, *rest = text_tag.split(sub_text, maxsplit=1)
    end: str
    if len(rest):
        end = rest[0]
    else:
        end = ""
    #convert these strings to tags
    begin = bs4.NavigableString(begin)
    end = bs4.NavigableString(end)
    text_tag.replace_with(begin)
    parent.insert(tag_idx + 1, repl_tag)
    parent.insert(tag_idx + 2, end)
    return end

def resize_image(image_path: str):
    """Resizes the image at image_path to a standard size so they don't import
    into InDesign at giant size.
    """
    image: Image.Image = Image.open(image_path)
    w = image.width
    h = image.height
    scale_factor = IMAGE_WIDTH_DEFAULT / w
    image.resize((int(w * scale_factor), int(h * scale_factor))).save(image_path, dpi=(DPI, DPI))

#this is illegal or whatever, but I am the law.
urllib.request.URLopener.version = USER_AGENT

# we have an expired root cert, until that's replaced, disable SSL
ssl._create_default_https_context = ssl._create_unverified_context

def download_images(article: Article) -> Article:
    """Looks through the article content for image tags and downloads them locally and saves
    them as an asset. Then, it changes the link text to point to the local copy instead of 
    the web copy.
    """
    img_tag: Tag
    for img_tag in article.content.find_all('img'):
        # try block because sometimes images without sources get added (don't ask me why)
        try:
            url = img_tag.attrs['src']
        except:
            continue
        filename = os.path.basename(urllib.parse.urlparse(url).path)
        local_path = article.get_image_location(filename)
        print(f"Downloading {local_path}\t{url}", flush=True)
        try:
            urllib.request.urlretrieve(url, local_path)
            #resize the image to a reasonable size
            resize_image(local_path)
            #InDesign recognizes <link href=""> tags for images
            img_tag.name = 'link'
            img_tag.attrs['href'] = 'file://' + local_path
        except urllib.error.HTTPError as e:
            print(f'Error downloading image {url}. Reason: {e}')
            input("[Enter] to continue...")
        except FileNotFoundError as e:
            print(f'Error downloading image {url}. Reason: {e}')
            input("[Enter] to continue...")
    return article

class Preview(pylatex.base_classes.Environment):
    packages = [pylatex.Package('preview', ['active', 'tightpage', 'pdftex'])]
    escape = False
    content_separator = "\n"

def compile_latex_str(latex: str, filename: str, display: bool = False):
    """Compiles the string latex into a PDF, and saves it to filename.
    """
    document = pylatex.Document()
    document.packages.append(pylatex.Package('amsmath'))
    document.packages.append(pylatex.Package('amssymb'))
    document.packages.append(pylatex.Package('amsfonts'))
    document.preamble.append(pylatex.Command('thispagestyle', 'empty'))
    # People seem to think \Z, \R and \Q exist, even though they don't. Just add them in to avoid problems.
    document.preamble.append(pylatex.NoEscape(r'\newcommand{\Z}{\mathbb{Z}}'))
    document.preamble.append(pylatex.NoEscape(r'\newcommand{\R}{\mathbb{R}}'))
    document.preamble.append(pylatex.NoEscape(r'\newcommand{\Q}{\mathbb{Q}}'))
    with document.create(Preview()):
        document.append(pylatex.NoEscape((r'\[' if display else r'\(') + latex + (r'\]' if display else r'\)')))
    document.generate_pdf(filename, compiler='pdflatex')
    print(f"{filename}\t{latex}", flush=True)

def compile_latex(article: Article) -> Article:
    """Looks through the article content for embedded LaTeX and compiles it into
    PDFs, and adds the proper tags so they show up on import.
    """
    text_tag: bs4.NavigableString
    #matches LaTeX inside one or two dollar signs
    inline_regex = r'\\[([]([\s\S]+?)\\[)\]]'
    # Compiled regex
    p = re.compile(inline_regex)
    # Memo to store validity and compile status of latex
    latex_valid_memo: Dict[str, bool] = dict()
    latex_compiled_memo: Dict[str, bool] = dict()
    for text_tag in article.content.find_all(text=True):
        if keep_verbatim(text_tag): continue

        for match in p.finditer(text_tag):
            # if this is invalid latex, skip
            if latex_valid_memo.get(match[1], True) == False: continue

            latex = match[1]
            # just use the hash of the latex for a unique filename, this should probably never collide
            # NOTE: sha1 is used for speed; we do not use the built-in `hash` function as it is non-deterministic across runs.
            #       We do NOT need to care about security risks, since we are solely concerned with uniqueness.
            filename = article.get_pdf_location(hashlib.sha1(match[0].encode('utf-8')).hexdigest())
            if match[0] not in latex_compiled_memo:
                try:
                    compile_latex_str(latex, filename, display=(match[0][1] == '['))
                    latex_valid_memo[latex] = True
                    latex_compiled_memo[match[0]] = True
                except subprocess.CalledProcessError:
                    latex_valid_memo[latex] = False
                    input("[Enter] to continue...")
                    continue
            link_tag = Tag(name='link', attrs={'href': 'file://' + filename + '.pdf'})
            #set the current tag to the new end tag
            text_tag = replace_text_with_tag(match[0], link_tag, text_tag, article=article)
    return article

def replace_inline_code(article: Article) -> Article:
    """Replaces Markdown-style inline code with actual code tags
    """
    text_tag: bs4.NavigableString
    p = re.compile(r'`([\s\S]+?)`')
    for text_tag in article.content.find_all(text=True):
        if keep_verbatim(text_tag): continue

        for match in p.finditer(text_tag):
            code = match[1]
            code_tag = Tag(name='code')
            code_tag.string = code
            text_tag = replace_text_with_tag(match[0], code_tag, text_tag, article=article)

    return article

def replace_ellipses(article: Article) -> Article:
    """Replaces "..." with one single ellipse character
    """
    text_tag: bs4.NavigableString
    for text_tag in article.content.find_all(text=True):
        if keep_verbatim(text_tag): continue

        new_tag = text_tag.replace('...', '…')
        text_tag.replace_with(new_tag)
    return article

def replace_dashes(article: Article) -> Article:
    """Replaces hyphens used as spacing, that is, when they are surrounded with spaces,
    with em dashes.
    Also replaces hyphens in numeric ranges with en dashes.
    """
    text_tag: bs4.NavigableString
    for text_tag in article.content.find_all(text=True):
        if keep_verbatim(text_tag): continue

        new_tag = re.sub(r'(?<=\d) ?--? ?(?=\d)', '–', text_tag) \
            .replace(' - ', '—') \
            .replace(' --- ', '—') \
            .replace('---', '—') \
            .replace(' -- ', '—') \
            .replace('--', '—') \
            .replace(' — ', '—') \
            .replace('—', ' — ')
        text_tag.replace_with(new_tag)
    return article

def replace_smart_quotes(s: str):
    # create an array so we can modify this string
    char_array = list(s)
    
    for idx, char in enumerate(char_array):
        before = None if idx == 0 else char_array[idx - 1]
        after = None if idx == len(char_array) - 1 else char_array[idx + 1]
        direction = get_quote_direction(before, after)
        if char == '"':
            char_array[idx] = get_double_quote(direction)
        if char == '\'':
            char_array[idx] = get_single_quote(direction)

    return ''.join(char_array)
    
def add_smart_quotes(article: Article) -> Article:
    """Replaces regular quotes with smart quotes. Works on double and single quotes."""
    text_tags: List[bs4.NavigableString] = list(article.content.find_all(text=True))
    # some hackery here: breaks between text tags might lead to invalid quotes
    # example: "|<em>text</em>|" will make the first quote a right quote, since
    # it's at the end of its text tag.
    # To avoid this, we glue the first character in the following tag
    # and the last character in the previous tag to the current tag.

    for idx, tag in enumerate(text_tags):
        if keep_verbatim(tag):
            continue

        before_tag = None if idx == 0 else text_tags[idx - 1]
        after_tag = None if idx == len(text_tags) - 1 else text_tags[idx + 1]

        glued_tag = tag
        if before_tag is not None:
            glued_tag = before_tag[-1] + glued_tag
        if after_tag is not None:
            glued_tag = glued_tag + after_tag[0]

        replaced = replace_smart_quotes(glued_tag)

        # and remove the characters we glued on
        if before_tag is not None:
            replaced = replaced[1:]
        if after_tag is not None:
            replaced = replaced[:-1]
            
        tag.replace_with(replaced)

    return article

def remove_extraneous_spaces(article: Article) -> Article:
    """Removes extraneous spaces after punctuation.
    """
    text_tag: bs4.NavigableString
    for text_tag in article.content.find_all(text=True):
        if keep_verbatim(text_tag): continue

        new_tag = re.sub(r'(?<=[.,;?!‽]) +', ' ', text_tag)
        text_tag.replace_with(new_tag)
    return article

def replace_newlines(article: Article) -> Article:
    """Replaces newlines with the Unicode LINE SEPARATOR character (U+2028). This preserves
    them in InDesign, which will treat newlines as paragraph breaks otherwise.
    """
    text_tag: bs4.NavigableString
    for text_tag in article.content.find_all(text=True):
        if keep_verbatim(text_tag):
            # Verbatim tags are simple
            new_tag = re.sub('\n', LINE_SEPARATOR, text_tag)
            text_tag.replace_with(new_tag)
        elif text_tag != '\n':
            # Non-verbatim tags must be handled separately, and we must make sure it's not a
            # double line-break (i.e. paragraph break)
            new_tag = re.sub('(?<!\n)\n(?!\n)', LINE_SEPARATOR, text_tag)
            text_tag.replace_with(new_tag)
            pass
    return article

def add_footnotes(article: Article) -> Article:
    """Replaces footnotes in <sup></sup> tags, [\d] format, or *, **, etc."""
    text_tag: bs4.NavigableString
    inline_regex = re.compile(r'\[(\d*)\]')
    footnote_counter = 1  # is the expected number of the next footnote
    for text_tag in article.content.find_all(text=True):
        if keep_verbatim(text_tag): continue

        for match in inline_regex.finditer(text_tag):
            # Check match for provided numbering -- if it exists, then use it
            footnote_num = footnote_counter
            if len(match[1]):
                footnote_num = int(match[1])
            sup_tag = Tag(name='sup')
            sup_tag.string = str(footnote_num)
            text_tag = replace_text_with_tag(match[0], sup_tag, text_tag, article=article)
            # Only auto-increment if blank or explicitly incremented
            if len(match[1]) == 0 or footnote_num == footnote_counter:
                footnote_counter += 1
    return article

"""POST_PROCESS is a list of functions that take Article instances and return Article instances.

For each article we parse, every function in this list will be applied to it in order, and the 
result saved back to the article list.

Use this to make any changes to articles you need before export, as well as to generate assets.
"""
POST_PROCESS: List[Callable[[Article], Article]] = [
    download_images,
    compile_latex,
    replace_inline_code,
    replace_newlines,
    replace_ellipses,
    replace_dashes,
    add_smart_quotes,
    remove_extraneous_spaces,
    add_footnotes
]

def create_asset_dirs():
    if not os.path.isdir(os.path.join(ASSET_DIR, 'img')):
        os.makedirs(os.path.join(ASSET_DIR, 'img'))
    if not os.path.isdir(os.path.join(ASSET_DIR, 'pdf')):
        os.makedirs(os.path.join(ASSET_DIR, 'pdf'))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='article export for mathNEWS')
    parser.add_argument('issue', help='the issue number to export for, e.g, v141i3')
    parser.add_argument('xml_dump', help='location of the XML dump to read from')
    parser.add_argument('-o', '--xml_output', 
        help='location of the file to output to',
        default='issue.xml')
    parser.add_argument('-a', '--assets',
        help='a folder to store asset files to',
        default='assets')
    args = parser.parse_args()
    CURRENT_DIR = os.getcwd()
    if os.path.isabs(args.assets):
        ASSET_DIR = args.assets
    else:
        ASSET_DIR = os.path.join(CURRENT_DIR, args.assets)
    shutil.rmtree(ASSET_DIR, ignore_errors=True)
    create_asset_dirs()
    OUTPUT_FILE = args.xml_output
    if not os.path.isfile(args.xml_dump):
        print(f'{args.xml_dump} does not exist.')
        exit(1)
    print('Parsing XML...', flush=True)
    tree = ElementTree.parse(args.xml_dump)
    print('Filtering articles...', flush=True)
    articles = filter_articles(tree, args.issue)
    print('Post-processing articles...', flush=True)
    for process in POST_PROCESS:
        print(f'Post-process pass: {process.__name__}', flush=True)
        articles = map(process, articles)
    print(f'Post-processing...', flush=True)
    root = Element('issue')
    for article in articles:
        root.append(article.to_xml_element())
    print(f'Writing to {OUTPUT_FILE}...', flush=True)
    os.chdir(CURRENT_DIR)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as output_file:
        # do some processing first
        # Remove extraneous lines
        transformed = "\n".join([line for line in html.unescape(ElementTree.tostring(root, encoding='unicode')).split("\n") if line.strip() != ''])
        # Separate articles cleanly
        transformed = "</article>\n<article>".join([article for article in transformed.split("</article><article>")])
        # Separate title and content cleanly
        transformed = "</title>\n<content>".join([article for article in transformed.split("</title><content>")])
        # Remove extraneous items from beginnings of lists
        transformed = "<ul>".join([thing for thing in transformed.split("<ul>\n")])
        transformed = "<ol>".join([thing for thing in transformed.split("<ol>\n")])
        # Separate tags and regular content cleanly
        transformed = re.sub(f'(?<=>){LINE_SEPARATOR}|{LINE_SEPARATOR}(?=<)', '\n', transformed)
        output_file.write(transformed)
    print('Issue written.')
