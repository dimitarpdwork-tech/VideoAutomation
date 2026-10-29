"""Build YouTube title, description and tags for one story video.

Kept free of third-party imports so production and upload can both use it.
"""
import re

import delivery

TITLE_LIMIT = 100
DESCRIPTION_LIMIT = 4900   # YouTube allows 5000 bytes; leave headroom.
TAGS_LIMIT = 450           # YouTube allows 500 characters across all tags.
HOOK_LIMIT = 220


def _clean(text):
    text = re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)', r'\1', delivery.strip(text or ''))
    return re.sub(r'\s+', ' ', text.replace('<', '').replace('>', '')).strip()


def hook(story):
    """First sentence or two of the story, as a teaser for the description."""
    text = _clean(story.get('text', ''))
    sentences = re.split(r'(?<=[.!?])\s+', text)
    teaser = ''
    for sentence in sentences:
        candidate = (teaser + ' ' + sentence).strip()
        if len(candidate) > HOOK_LIMIT:
            break
        teaser = candidate
    if not teaser:
        teaser = text[:HOOK_LIMIT].rsplit(' ', 1)[0] + '…' if len(text) > HOOK_LIMIT else text
    return teaser


def credit(story):
    """Attribution line for stories collected from somewhere else."""
    url = story.get('url') or ''
    if not url:
        return ''
    author = (story.get('author') or '').strip()
    who = f' by u/{author}' if author and not author.startswith('u/') else (f' by {author}' if author else '')
    return f'Original story{who}: {url}'


def normalize_hashtags(values):
    tags = []
    for value in values or []:
        word = re.sub(r'[^\w]', '', str(value).lstrip('#'))
        if word and ('#' + word).lower() not in (t.lower() for t in tags):
            tags.append('#' + word)
    return tags[:15]  # YouTube ignores all hashtags when there are more than 15.


def title_for(story):
    title = _clean(story.get('title', '')).rstrip('.')
    if len(title) > TITLE_LIMIT:
        title = title[:TITLE_LIMIT - 1].rsplit(' ', 1)[0] + '…'
    return title


TEMPLATES = {
    'short': ('description_template', '{hook}\n\n{credit}\n\n{fiction_note}\n\n{hashtags}'),
    'teaser': ('teaser_description_template', '{hook}\n\n\u25b6 Full story: {full_url}\n\n{hashtags}'),
    'full': ('full_description_template', '{hook}\n\n{credit}\n\n{fiction_note}\n\n{hashtags}'),
}
FULL_URL = '{full_url}'  # filled in at upload time, once the full video has an ID


def build(story, config, kind='short'):
    """Return {'title', 'description', 'tags'} ready for the YouTube API.

    kind: 'short' (standalone Short), 'teaser' (Short pointing to the full
    video) or 'full' (the long horizontal video, which gets no #shorts tag).
    """
    hashtags = normalize_hashtags(config.get('hashtags'))
    if kind == 'full':
        hashtags = [tag for tag in hashtags if tag.lower() != '#shorts']
    fields = {
        'title': title_for(story),
        'hook': hook(story),
        'credit': credit(story) if config.get('credit_source', True) else '',
        'fiction_note': (config.get('fiction_note') or '') if story.get('fiction') else '',
        'hashtags': ' '.join(hashtags),
        'category': config.get('story_category', ''),
        'full_url': FULL_URL,
    }
    key, fallback = TEMPLATES[kind]
    template = config.get(key) or fallback
    if kind == 'teaser' and FULL_URL not in template:
        template += '\n\n\u25b6 Full story: {full_url}'
    try:
        description = template.format(**fields)
    except (KeyError, IndexError, ValueError):
        description = fallback.format(**fields)
    description = re.sub(r'\n{3,}', '\n\n', description.replace('<', '').replace('>', '')).strip()
    while len(description.encode('utf-8')) > DESCRIPTION_LIMIT:
        description = description[:-50]
    tags, used = [], 0
    for tag in config.get('tags') or []:
        tag = _clean(str(tag)).strip(',')
        if tag and tag.lower() not in (t.lower() for t in tags) and used + len(tag) + 1 <= TAGS_LIMIT:
            tags.append(tag)
            used += len(tag) + 1
    return {'title': fields['title'], 'description': description, 'tags': tags}
