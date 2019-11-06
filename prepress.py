import argparse
import os.path
from xml.etree import ElementTree
from xml.etree.ElementTree import Element
from typing import List

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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='article export for mathNEWS')
    parser.add_argument('issue', help='the issue number to export for, e.g, v141i3')
    parser.add_argument('xml', help='location of the XML file')
    args = parser.parse_args()
    if not os.path.isfile(args.xml):
        print(f'{args.xml} does not exist.')
        exit(1)
    print('Parsing XML...')
    tree = ElementTree.parse(args.xml)
    print('Filtering articles...')
    articles = filter_articles(tree, args.issue)
    print('Post-processing articles...')
