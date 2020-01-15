import argparse
import os
import os.path
from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement
from typing import List, Callable
import re
import itertools
import urllib.request
import urllib.parse
import urllib.error
import html
import shutil

import bs4
from bs4 import BeautifulSoup, Tag
import pylatex
from PIL import Image

#The directory to store generated assets. Can be changed by command line argument.
ASSET_DIR = 'assets'
#The location of the output file. Can be changed by command line argument'
OUTPUT_FILE = 'issue.xml'
#The current working directory
CURRENT_DIR: str
#273 pt, at 300 DPI
DPI = 300
IMAGE_WIDTH_DEFAULT = 1138


XML_NS = {
    'content': 'http://purl.org/rss/1.0/modules/content/'
}

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
        #automatically add a newline to the title so content will start on a newline
        title_tag.text = self.title.replace('&', '&amp;') + '\n'
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

def resize_image(image_path: str):
    """Resizes the image at image_path to a standard size so they don't import
    into InDesign at giant size.
    """
    image: Image.Image = Image.open(image_path)
    w = image.width
    h = image.height
    scale_factor = IMAGE_WIDTH_DEFAULT / w
    image.resize((int(w * scale_factor), int(h * scale_factor))).save(image_path, dpi=(DPI, DPI))

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/78.0.3904.108 Safari/537.36'
#this is illegal or whatever, but I am the law.
urllib.request.URLopener.version = USER_AGENT

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
        print(local_path)
        print(url)
        try:
            urllib.request.urlretrieve(url, local_path)
            #resize the image to a reasonable size
            resize_image(local_path)
            #InDesign recognizes <link href=""> tags for images
            img_tag.name = 'link'
            img_tag.attrs['href'] = 'file://' + local_path
        except urllib.error.HTTPError as e:
            print(f'Error downloading image {url}. Reason: {e}')
        except FileNotFoundError as e:
            print(f'Error downloading image {url}. Reason: {e}')
    return article

def compile_latex_str(latex: str, filename: str, display: bool = False):
    """Compiles the string latex into a PDF, and saves it to filename.
    """
    print(f"{filename} {latex}", flush=True) # DEBUG
    document = pylatex.Document()
    document.packages.append(pylatex.Package('amsmath'))
    document.packages.append(pylatex.Package('amssymb'))
    document.packages.append(pylatex.Package('amsfonts'))
    document.append(pylatex.NoEscape(r'\thispagestyle{empty}'))
    document.append(pylatex.NoEscape((r'\[' if display else r'\(') + latex + (r'\]' if display else r'\)')))
    document.generate_pdf(filename, compiler='pdflatex', clean_tex=False)

def compile_latex(article: Article) -> Article:
    """Looks through the article content for embedded LaTeX and compiles it into
    PDFs, and adds the proper tags so they show up on import.
    """
    text_tag: bs4.NavigableString
    #matches LaTeX inside one or two dollar signs
    inline_regex = r'\\[([]([\s\S]+?)\\[)\]]'
    for text_tag in article.content.find_all(text=True):
        # Memo to store validity and compile status of latex
        # note: compile_latex_str is asynchronous, could possibly result in race condition
        latex_valid_memo: Dict[str, bool] = dict()
        latex_compiled_memo: Dict[str, bool] = dict()
        # Compiled regex
        p = re.compile(inline_regex)
        for match in p.finditer(text_tag):
            # if this is invalid latex, skip
            if latex_valid_memo.get(match[1], True) == False: continue

            latex = match[1]
            #just use the hash of the latex for a unique filename, this should probably never collide
            filename = article.get_pdf_location(str(hash(match[0])))
            if match[0] not in latex_compiled_memo:
                print(latex_compiled_memo, flush=True) # DEBUG
                try:
                    compile_latex_str(latex, filename, display=(match[0][1] == '['))
                    latex_valid_memo[latex] = True
                    latex_compiled_memo[match[0]] = True
                except:
                    latex_valid_memo[latex] = False
                    raise
                    #continue
            #if we can't find the parent, assume it's just the document
            parent: Tag
            if text_tag.parent == None or text_tag.parent.name == '[document]':
                parent = article.content
            else:
                parent = text_tag.parent
            tag_idx = parent.contents.index(text_tag)
            #replace the matched latex with a link tag
            begin, *rest = text_tag.split(match[0])[:2]
            end: str
            if len(rest):
                end = rest[0]
            else:
                # problem: can remove text sometimes
                end = ""
            #convert these strings to tags
            begin = bs4.NavigableString(begin)
            end = bs4.NavigableString(end)
            text_tag.replace_with(begin)
            #the latex compiler will automatically add a .pdf so we have to add one too
            link_tag = Tag(name='link', attrs={'href': 'file://' + filename + '.pdf'})
            parent.insert(tag_idx + 1, link_tag)
            parent.insert(tag_idx + 2, end)
            #set the current tag to the new end tag
            text_tag = end
    return article

def replace_ellipses(article: Article) -> Article:
    """Replaces "..." with one single ellipse character
    """
    text_tag: bs4.NavigableString
    for text_tag in article.content.find_all(text=True):
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

def add_smart_quotes(article: Article) -> Article:
    """Replaces regular quotes with smart quotes. This function assumes quotes are not nested
    and will simply convert pairs of quotes into left and right quotes.
    """
    text_tag: bs4.NavigableString
    for text_tag in article.content.find_all(text=True):
        #\1 will sub in the first matched group
        new_tag = re.sub(r'"([^"]*)"', r'“\1”', text_tag)
        text_tag.replace_with(new_tag)
    return article

def remove_extraneous_spaces(article: Article) -> Article:
    """Removes extraneous spaces after punctuation.
    """
    text_tag: bs4.NavigableString
    for text_tag in article.content.find_all(text=True):
        new_tag = re.sub(r'(?<=[.,;?!‽]) +', ' ', text_tag)
        text_tag.replace_with(new_tag)
    return article

"""POST_PROCESS is a list of functions that take Article instances and return Article instances. 

For each article we parse, every function in this list will be applied to it in order, and the 
result saved back to the article list.

Use this to make any changes to articles you need before export, as well as to generate assets.
"""
POST_PROCESS: List[Callable[[Article], Article]] = [
    download_images,
    compile_latex,
    replace_ellipses,
    replace_dashes,
    add_smart_quotes,
    remove_extraneous_spaces
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
    ASSET_DIR = args.assets
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
        transformed = "\n".join([line for line in html.unescape(ElementTree.tostring(root, encoding='unicode')).split("\n") if line.strip() != ''])
        transformed = "</article>\n<article>".join([article for article in transformed.split("</article><article>")])
        transformed = "</title>\n<content>".join([article for article in transformed.split("\n</title><content>")])
        output_file.write(transformed)
    print('Issue written.')
