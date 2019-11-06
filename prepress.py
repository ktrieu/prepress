import argparse
import os.path
from xml.etree import ElementTree
from xml.etree.ElementTree import Element
from typing import List, Callable
import re
import itertools
import urllib.request
import urllib.parse
import urllib.error

XML_NS = {
    'content': 'http://purl.org/rss/1.0/modules/content/'
}

class Article:

    def __init__(self):
        self.author = ''
        self.title = ''
        #content is stored as HTML
        self.content = ''

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
        article.content = article_tag.find('content:encoded', XML_NS).text
        articles.append(article)
    return articles

def download_images(article: Article):
    """Looks through the article content for image tags and downloads them locally and saves
    them as an asset. Then, it changes the link text to point to the local copy instead of 
    the web copy.
    """
    #generate a slug to make file names more human readable
    file_prefix = article.title[0:10].encode('ascii', errors='ignore').decode().replace(' ', '_')
    #a regex *should* be ok, and it would be wasteful to start up a whole HTML parser for each article
    image_regex = r'src="([^"]*)"'
    #matches is a nested list, so we have to unpack it
    urls = re.findall(image_regex, article.content)
    for url in urls:
        filename = os.path.basename(urllib.parse.urlparse(url).path)
        local_path = get_image_location(file_prefix + '_' + filename)
        try:
            urllib.request.urlretrieve(url, local_path)
            #we have to add the src here or it might replace the url when mentioned in text
            #we add the file:// so InDesign will load it properly
            article.content = article.content.replace('src="' + url, 'src="file://' + local_path)
            print(article.content)
        except urllib.error.HTTPError as e:
            print(f'Error downloading image {url}. Reason: {e}')
    return article

"""POST_PROCESS is a list of functions that take Article instances and return Article instances. 

For each article we parse, every function in this list will be applied to it in order, and the 
result saved back to the article list.

Use this to make any changes to articles you need before export, as well as to generate assets.
"""
POST_PROCESS: List[Callable[[Article], Article]] = [
    download_images
]

#The directory to store generated assets. Can be changed by command line argument.
ASSET_DIR = 'assets'

def create_asset_dirs():
    if not os.path.isdir(os.path.join(ASSET_DIR, 'img')):
        os.makedirs(os.path.join(ASSET_DIR, 'img'))
    if not os.path.isdir(os.path.join(ASSET_DIR, 'pdf')):
        os.makedirs(os.path.join(ASSET_DIR, 'pdf'))


def get_image_location(file: str):
    """Given an image filename, returns a path to store it."""
    return os.path.join(ASSET_DIR, 'img', file)

def get_pdf_location(file: str):
    """Given a PDF filename, returns a path to store it."""
    return os.path.join(ASSET_DIR, 'pdf', file)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='article export for mathNEWS')
    parser.add_argument('issue', help='the issue number to export for, e.g, v141i3')
    parser.add_argument('xml', help='location of the XML file')
    parser.add_argument('-a', '--assets',
        help='a folder to store asset files to',
        default='assets')
    args = parser.parse_args()
    ASSET_DIR = args.assets
    create_asset_dirs()
    if not os.path.isfile(args.xml):
        print(f'{args.xml} does not exist.')
        exit(1)
    print('Parsing XML...')
    tree = ElementTree.parse(args.xml)
    print('Filtering articles...')
    articles = filter_articles(tree, args.issue)
    print('Post-processing articles...')
    for process in POST_PROCESS:
        print(f'Running post-process pass: {process.__name__}')
        articles = map(process, articles)
    list(articles)
