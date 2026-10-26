"""Find public LinkedIn accounts and matching publisher posts without inventing URLs."""
import asyncio
import re
from urllib.parse import urlsplit, urlunsplit, quote

from ..email.exa import exa_search, EXA_API_KEY


def linkedin_url(url, kind):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        if parsed.scheme != 'https' or not (host == 'linkedin.com' or host.endswith('.linkedin.com')) or parsed.username or parsed.password:
            return None
        prefixes = ('/company/', '/showcase/') if kind == 'Publication' else ('/in/',) if kind == 'Journalist' else ('/posts/', '/feed/update/')
        if not parsed.path.startswith(prefixes): return None
        return urlunsplit(('https', 'www.linkedin.com', parsed.path.rstrip('/') + ('/' if kind != 'post' else ''), '', ''))
    except ValueError:
        return None


def normalized(text):
    return ' '.join(re.findall(r'\w+', (text or '').casefold()))


def search_link(name, publication='', posts=False):
    query = ' '.join(p for p in [name, publication] if p)
    return 'https://www.linkedin.com/search/results/' + ('content/' if posts else 'all/') + '?keywords=' + quote(query, safe='')


def account_matches(results, name, role, publication, domain):
    matches = {}
    for item in results:
        url = linkedin_url(item.get('url', ''), role)
        if not url: continue
        text = (item.get('title') or '') + '\n' + (item.get('text') or '')
        if normalized(name) not in normalized(text): continue
        # A publisher account should point to the source website. Journalists need an affiliation match.
        associated = domain and re.search(r'(?<![\w.-])(?:www\.)?' + re.escape(domain) + r'(?![\w.-])', text, re.I)
        if role == 'Journalist':
            associated = bool(publication and normalized(publication) in normalized(text))
        matches[url] = {'name': name, 'url': url, 'role': role,
            'reason': 'Public account names the source website' if role == 'Publication' and associated else 'Public account matches the name and publication' if associated else 'Name matched; identity needs checking',
            'status': 'matched' if associated else 'candidate', 'evidence_url': item.get('url', ''), 'evidence': text[:600]}
    values = list(matches.values())
    strong = [m for m in values if m['status'] == 'matched']
    if len(strong) > 1:
        for match in strong:
            match['status'] = 'candidate'
            match['reason'] = 'Multiple matching accounts; choose the correct one'
    return values[:3]


def post_matches(results, title, article_url, publication, accounts):
    matches = []
    title_tokens = set(normalized(title.split('|')[0]).split()) - {'the','a','an','and','of','in','for','to','with','on','by'}
    publisher_slugs = {urlsplit(a['url']).path.strip('/').split('/')[-1] for a in accounts if a['role'] == 'Publication' and a['status'] in {'matched', 'saved'}}
    for item in results:
        url = linkedin_url(item.get('url', ''), 'post')
        if not url: continue
        text = (item.get('title') or '') + '\n' + (item.get('text') or '')
        path = urlsplit(url).path
        # A related post from somebody else is not the publication's original.
        owned = any(path.startswith('/posts/' + slug + '_') for slug in publisher_slugs)
        exact = bool(article_url and article_url.rstrip('/') in text)
        overlap = len(title_tokens & set(normalized(text).split())) / max(len(title_tokens), 1)
        if not owned or not (exact or (len(title_tokens) >= 3 and overlap >= .8)):
            continue
        matches.append({'url': url, 'title': item.get('title') or publication + ' LinkedIn post',
            'status': 'article_link_matched' if exact else 'headline_matched',
            'reason': 'Publisher account and article URL match' if exact else 'Publisher account and headline match — confirm the story',
            'excerpt': (item.get('text') or '')[:500]})
    return matches[:3]


async def discover(source, payload, profile):
    publication, journalist = payload.publication, payload.journalist
    domain = (urlsplit(payload.url).hostname or '').removeprefix('www.')
    accounts = []
    for contact in profile.contacts:
        if (contact.role == 'Publication' and normalized(contact.name) == normalized(publication)) or (contact.role == 'Journalist' and normalized(contact.name) in normalized(journalist)):
            accounts.append({**contact.model_dump(), 'status': 'saved', 'reason': 'Saved client account', 'evidence_url': contact.url})
    lookup = {'accounts': accounts, 'posts': [], 'status': 'not_configured' if not EXA_API_KEY else 'searched',
        'publication_search': search_link(publication) if publication else None,
        'journalist_search': search_link(journalist, publication) if journalist else None,
        'post_search': search_link(source.get('title', ''), publication, posts=True)}
    if not EXA_API_KEY: return lookup
    author_names = source.get('attribution', {}).get('journalist', {}).get('names', [])[:3]
    queries = []
    if publication:
        queries.append(('Publication', publication, f'"{publication}" LinkedIn company showcase {domain}'))
    for name in author_names:
        queries.append(('Journalist', name, f'site:linkedin.com/in/ "{name}" "{publication}"'))
    if publication and source.get('title'):
        queries.append(('post', publication, f'site:linkedin.com/posts "{publication}" "{source["title"][:160]}"'))
    try:
        results = await asyncio.wait_for(asyncio.gather(*(exa_search(q, 5) for _, _, q in queries)), timeout=18)
    except Exception:
        lookup['status'] = 'unavailable'
        return lookup
    post_results = []
    for (role, name, _), items in zip(queries, results):
        if role == 'post':
            post_results.extend(items)
        else:
            for match in account_matches(items, name, role, publication, domain):
                if not any(a['url'] == match['url'] for a in accounts): accounts.append(match)
    # A second publisher-scoped lookup avoids confusing third-party coverage with the original.
    publisher = next((a for a in accounts if a['role'] == 'Publication' and a['status'] in {'saved','matched'}), None)
    if publisher:
        slug = urlsplit(publisher['url']).path.strip('/').split('/')[-1]
        try:
            post_results.extend(await asyncio.wait_for(exa_search(f'site:linkedin.com/posts/{slug} "{source.get("title", "")[:160]}"', 4), timeout=12))
        except Exception: pass
    lookup['posts'] = post_matches(post_results, source.get('title', ''), payload.url, publication, accounts)
    return lookup
