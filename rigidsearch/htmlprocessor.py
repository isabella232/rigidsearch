import re
import html5lib
import warnings
from lxml.cssselect import CSSSelector
from html5lib.ihatexml import DataLossWarning
from StringIO import StringIO

# the ihatexml module emits data loss warnings.  This in our case is okay
# because we are willing to accept the data loss that happens on the way
# from HTML to XML as we never go in reverse direction.  In particular the
# problem is XML namespaces which are not supported in HTML.
warnings.filterwarnings('ignore', category=DataLossWarning)


class ProcessingError(Exception):
    pass


def compile_selector(sel):
    return CSSSelector(sel, translator='html')


tree_walker = html5lib.getTreeWalker('lxml')


class Processor(object):

    def __init__(self, title_cleanup_regex=None,
                 content_selectors=None,
                 content_sections=None,
                 content_scoring=None,
                 ignore=None,
                 no_default_ignores=False):
        self.content_selectors = [compile_selector(sel) for sel in
                                  content_selectors or ('body',)]
        self.content_sections = [compile_selector(sel) for sel in
                                  content_sections or ('body',)]
        self.content_scoring = content_scoring
        if title_cleanup_regex is not None:
            title_cleanup_regex = re.compile(title_cleanup_regex, re.UNICODE)
        self.title_cleanup_regex = title_cleanup_regex
        self.ignore = [compile_selector(sel) for sel in ignore or ()]
        if not self.ignore and not no_default_ignores:
            self.ignore = [compile_selector(sel) for sel
                           in ['script', 'noscript', 'style', '.nocontent']]

    @classmethod
    def from_config(cls, config):
        return cls(
            title_cleanup_regex=config.get('title_cleanup_regex'),
            content_selectors=config.get('content_selectors'),
            content_sections=config.get('content_sections'),
            content_scoring=config.get('content_scoring'),
            ignore=config.get('ignore'),
            no_default_ignores=config.get('no_default_ignores', False),
        )

    def is_ignored(self, node):
        for sel in self.ignore:
            xpath = sel.path.replace('descendant-or-self::', 'self::')
            matches = node.xpath(xpath)
            if matches and matches[0] is node:
                return True
        return False

    def process_document(self, document, path):
        if isinstance(document, basestring):
            document = StringIO(document)
        doc = html5lib.parse(document, treebuilder='lxml',
                             namespaceHTMLElements=False)
        return self.process_tree(doc, path)

    def process_title_tag(self, title):
        if title is None:
            return None
        text = title.text
        if self.title_cleanup_regex is not None:
            match = self.title_cleanup_regex.search(text)
            if match is not None:
                text = match.group(1)
        return unicode(text)

    def process_content_tag(self, body):
        if body is None:
            return u''

        buf = []

        def _walk(node):
            if self.is_ignored(node):
                return

            if node.text:
                buf.append(node.text)
            for child in node:
                _walk(child)
            if node.tail:
                buf.append(node.tail)

        _walk(body)

        return u''.join(buf)

    def process_tree(self, tree, path):
        docs = []
        doc = {}

        root = tree.getroot()
        head = root.find('head')
        if head is None:
            raise ProcessingError('Document does not parse correctly.')

        title = head.find('title')
        doc['path'] = path
        doc['title'] = self.process_title_tag(title)
        priority = str(path).split("/")[0]
        if priority and priority in self.content_scoring:
            doc['priority'] = int(self.content_scoring[priority])
        else:
            doc['priority'] = 0

        buf = []
        for sel in self.content_selectors:
            for el in sel(root):
                buf.append(self.process_content_tag(el))

        doc['text'] = u''.join(buf).rstrip()
        docs.append(doc)

        for sel in self.content_sections:
            for el in sel(root):
                if el.attrib['id'] and el.attrib['id'] not in path:
                    p = str(path).split("/")[0]
                    if p and p in self.content_scoring:
                        priority = int(self.content_scoring[p])
                    else:
                        priority = 0
                    title = [w.capitalize() for w in el.attrib['id'].split("-")]
                    docs.append({
                        'path': path + "#" + el.attrib['id'],
                        'title': u' '.join(title),
                        'text': self.process_content_tag(el),
                        'priority': priority + 1
                    })
        return docs
