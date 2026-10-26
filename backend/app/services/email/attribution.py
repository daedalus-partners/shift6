"""Conservative article attribution: retain publisher evidence and abstain on conflicts."""
from __future__ import annotations
import json
import re
from urllib.parse import urlsplit


def clean_name(value):
    if not isinstance(value, str):
        return None
    value = re.sub(r"\s+", " ", value).strip()
    if not 2 <= len(value) <= 160 or re.search(r"https?://|@|[<>\n]", value):
        return None
    return value


def names(value):
    if isinstance(value, list):
        return [name for item in value for name in names(item)]
    if isinstance(value, dict):
        value = value.get('name')
    name = clean_name(value)
    return [name] if name else []


def identity(value):
    return re.sub(r"[^\w]", "", value.casefold())


def choose(candidates):
    """Each candidate is a whole byline, possibly multiple authors. Never choose a winner on conflict."""
    candidates = [c for c in candidates if c['names']]
    groups = {tuple(sorted(identity(n) for n in c['names'])) for c in candidates}
    if len(groups) != 1:
        return {'names': [], 'status': 'conflicting' if groups else 'unavailable', 'evidence': candidates}
    return {'names': candidates[0]['names'], 'status': 'source_identified', 'evidence': candidates}


def same_page(left, right):
    def key(url):
        p = urlsplit(url)
        return (p.hostname or '').removeprefix('www.'), p.path.rstrip('/')
    return key(left) == key(right)


def extract_attribution(soup, page_url):
    publications, authors = [], []
    for prop in ['og:site_name']:
        for meta in soup.find_all('meta', attrs={'property': prop}):
            if value := clean_name(meta.get('content')):
                publications.append({'names': [value], 'source': prop})
    for meta in soup.find_all('meta', attrs={'name': re.compile(r'^author$', re.I)}):
        if value := clean_name(meta.get('content')):
            authors.append({'names': [value], 'source': 'meta author'})

    articles = []
    def walk(node):
        if isinstance(node, list):
            for item in node: walk(item)
        elif isinstance(node, dict):
            types = node.get('@type', [])
            types = [types] if isinstance(types, str) else types
            if any(t in {'Article', 'NewsArticle', 'BlogPosting', 'ReportageNewsArticle', 'AnalysisNewsArticle'} for t in types):
                articles.append(node)
            # Only traverse the graph, never recommendation/item-list objects.
            if '@graph' in node: walk(node['@graph'])
    for script in soup.find_all('script', type='application/ld+json'):
        try: walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError): pass
    matched = []
    for article in articles:
        main = article.get('mainEntityOfPage')
        main = main.get('@id') if isinstance(main, dict) else main
        urls = [u for u in [article.get('url'), main, article.get('@id')] if isinstance(u, str) and u.startswith('http')]
        if any(same_page(u, page_url) for u in urls): matched.append(article)
        elif not urls and len(articles) == 1: matched.append(article)
    for article in matched:
        if values := names(article.get('publisher')):
            publications.append({'names': values, 'source': 'Article JSON-LD publisher'})
        if values := names(article.get('author')):
            authors.append({'names': values, 'source': 'Article JSON-LD author'})

    # Article-scoped rel=author links form one multi-author byline, not unrelated footer links.
    article = soup.find('article')
    if article:
        values = [clean_name(n.get_text(' ', strip=True)) for n in article.select('[rel~="author"]')]
        values = list(dict.fromkeys(v for v in values if v))
        if values:
            authors.append({'names': values, 'source': 'article rel=author byline'})
        elif node := article.select_one('[itemprop="author"]'):
            name_node = node.select_one('[itemprop="name"]')
            if value := clean_name((name_node or node).get_text(' ', strip=True)):
                authors.append({'names': [value], 'source': 'article author microdata'})
    # Accept a visible standalone 'By Name' only inside the article/main, never prose or a footer.
    scope = article or soup.find('main')
    if scope:
        for node in scope.select('.byline, [class="article-author"], [class="author-name"]'):
            text = node.get_text(' ', strip=True)
            match = re.fullmatch(r'By\s+([^\d:|]{2,100})', text, re.I)
            if match and len(match[1].split()) <= 8:
                if value := clean_name(match[1]):
                    authors.append({'names': [value], 'source': 'visible article byline'})
    return {'publication': choose(publications), 'journalist': choose(authors)}


def pasted_attribution(text):
    publications, authors = [], []
    for line in text.splitlines()[:12]:
        if match := re.fullmatch(r'\s*(?:Publication|Publisher|Outlet):\s*(.+?)\s*', line, re.I):
            if value := clean_name(match[1]):
                publications.append({'names': [value], 'source': 'explicit publication line in pasted text'})
        if match := re.fullmatch(r'\s*(?:By|Byline:|Author:)\s+(.+?)\s*', line, re.I):
            if value := clean_name(match[1]):
                authors.append({'names': [value], 'source': 'explicit byline in pasted text'})
    return {'publication': choose(publications), 'journalist': choose(authors)}
