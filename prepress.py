import argparse
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

import bs4
from bs4 import BeautifulSoup, Tag

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
        file_prefix = self.title[0:10].encode('ascii', errors='ignore').decode().replace(' ', '_')
        filename = file_prefix + '_' + file
        return os.path.join(ASSET_DIR, 'img', filename)

    def get_pdf_location(self, file: str) -> str:
        file_prefix = self.title[0:10].encode('ascii', errors='ignore').decode().replace(' ', '_')
        filename = file_prefix + '_' + file
        return os.path.join(ASSET_DIR, 'pdf', filename)
    
    def to_xml_element(self) -> Element:
        article_tag = Element('article')
        title_tag = SubElement(article_tag, 'title')
        title_tag.text = self.title
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

def download_images(article: Article) -> Article:
    """Looks through the article content for image tags and downloads them locally and saves
    them as an asset. Then, it changes the link text to point to the local copy instead of 
    the web copy.
    """
    img_tag: Tag
    for img_tag in article.content.find_all('img'):
        url = img_tag.attrs['src']
        filename = os.path.basename(urllib.parse.urlparse(url).path)
        local_path = article.get_image_location(filename)
        try:
            urllib.request.urlretrieve(url, local_path)
            #InDesign recognizes <link href=""> tags for images
            img_tag.name = 'link'
            img_tag.attrs['href'] = 'file://' + local_path
        except urllib.error.HTTPError as e:
            print(f'Error downloading image {url}. Reason: {e}')
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
    """
    text_tag: bs4.NavigableString
    for text_tag in article.content.find_all(text=True):
        new_tag = text_tag.replace(' - ', ' — ')
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

"""POST_PROCESS is a list of functions that take Article instances and return Article instances. 

For each article we parse, every function in this list will be applied to it in order, and the 
result saved back to the article list.

Use this to make any changes to articles you need before export, as well as to generate assets.
"""
POST_PROCESS: List[Callable[[Article], Article]] = [
    download_images,
    replace_ellipses,
    replace_dashes,
    add_smart_quotes
]

#The directory to store generated assets. Can be changed by command line argument.
ASSET_DIR = 'assets'
#The location of the output file. Can be changed by command line argument'
OUTPUT_FILE = 'issue.xml'

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
    ASSET_DIR = args.assets
    create_asset_dirs()
    OUTPUT_FILE = args.xml_output
    if not os.path.isfile(args.xml_dump):
        print(f'{args.xml_dump} does not exist.')
        exit(1)
    print('Parsing XML...')
    tree = ElementTree.parse(args.xml_dump)
    print('Filtering articles...')
    articles = filter_articles(tree, args.issue)
    print('Post-processing articles...')
    for process in POST_PROCESS:
        print(f'Running post-process pass: {process.__name__}')
        articles = map(process, articles)
    print(f'Writing issue to {OUTPUT_FILE}...')
    root = Element('issue')
    for article in articles:
        root.append(article.to_xml_element())
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as output_file:
        output_file.write(html.unescape(ElementTree.tostring(root, encoding='unicode')))
    print('Issue written.')
