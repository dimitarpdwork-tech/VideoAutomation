"""Find one atmospheric, free-licence photo per story for its background.

Sources, in order:
  1. Pexels (free API key from pexels.com/api; save it in the dashboard Settings).
     Pexels photos may be used free for commercial videos; attribution is not required.
  2. Openverse, limited to CC0 and public-domain images (no key needed). These
     need no attribution either.

Each image is used once across all channels, so no two videos share a picture.
Where every image came from (page, photographer, licence) is recorded next to
it and in output/shared/images_used.json, in case anyone ever asks.

Search phrase: the story's own "image_query" (written by the story generator),
then the channel's image keywords (Settings), then its theme.
"""
import io
import json
import os
import random
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from channel_config import ROOT, SHARED, read_json, update_json, write_json

IMAGES = SHARED / 'images'
USED = SHARED / 'images_used.json'
KEY_FILE = ROOT / 'credentials' / 'pexels_api_key.txt'
MIN_WIDTH = 1600
MAX_BYTES = 30_000_000
USER_AGENT = 'StoryShortsStudio/1.0 (background image search)'


class NoImage(RuntimeError):
    pass


def credit_line(image_path):
    """A one-line credit for the description, when the image's source asks for one.

    Pexels' licence needs no credit, but its API guidelines ask apps to link to
    Pexels and credit the photographer where possible. Openverse CC0/public-domain
    images need nothing.
    """
    record = read_json(Path(image_path).with_suffix('.json'), {}) or {}
    if record.get('source') != 'Pexels':
        return ''
    who = f" by {record['author']}" if record.get('author') else ''
    return f"Background photo{who} on Pexels: {record.get('page') or 'https://www.pexels.com'}"


def pexels_key():
    key = os.environ.get('PEXELS_API_KEY', '').strip()
    if not key and KEY_FILE.is_file():
        key = KEY_FILE.read_text(encoding='utf-8').strip()
    return key


def _get(url, headers=None, limit=MAX_BYTES):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('file too large')
        return data, response.headers.get('Content-Type', '')


def search_pexels(query, orientation, key):
    params = urllib.parse.urlencode({'query': query, 'orientation': orientation, 'size': 'large', 'per_page': 30})
    data, _ = _get(f'https://api.pexels.com/v1/search?{params}', {'Authorization': key})
    results = []
    for photo in json.loads(data).get('photos', []):
        src = photo.get('src') or {}
        # A compressed 4K copy instead of the 30-60 MB original: 3,840 px wide (about 2,560 tall) is
        # enough for 1080p and for a sharp vertical crop of the same photo for the teaser Short.
        size = 'h=3840' if orientation == 'portrait' else 'w=3840'
        url = (src['original'] + ('&' if '?' in src['original'] else '?') + f'auto=compress&cs=tinysrgb&{size}'
               if src.get('original') else src.get('large2x'))
        results.append({'id': f"pexels:{photo['id']}", 'url': url,
                        'page': photo.get('url'), 'author': photo.get('photographer'),
                        'license': 'Pexels License (free commercial use, no attribution required)',
                        'width': photo.get('width') or 0, 'height': photo.get('height') or 0})
    return results


def search_openverse(query, orientation):
    params = urllib.parse.urlencode({'q': query, 'license': 'cc0,pdm', 'page_size': 30, 'mature': 'false',
                                     'size': 'large', 'aspect_ratio': 'tall' if orientation == 'portrait' else 'wide'})
    data, _ = _get(f'https://api.openverse.org/v1/images/?{params}')
    results = []
    for image in json.loads(data).get('results', []):
        if (image.get('license') or '').lower() not in ('cc0', 'pdm'):
            continue
        results.append({'id': f"openverse:{image['id']}", 'url': image.get('url'), 'page': image.get('foreign_landing_url'),
                        'author': image.get('creator'), 'license': (image.get('license') or '').upper() + ' (public domain)',
                        'width': image.get('width') or 0, 'height': image.get('height') or 0})
    return results


def save_image(data, target):
    """Validate and store as a JPEG no wider than 3840 px; return (width, height)."""
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        image = image.convert('RGB')
        if image.width < MIN_WIDTH and image.height < MIN_WIDTH:
            raise ValueError('image too small')
        if image.width > 3840:
            image = image.resize((3840, round(image.height * 3840 / image.width)))
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.part')
        image.save(temporary, 'JPEG', quality=92)
        os.replace(temporary, target)
        return image.size


def queries_for(story, config, rng=random):
    keywords = [k for k in (config.get('image_keywords') or []) if isinstance(k, str) and k.strip()]
    rng.shuffle(keywords)
    first = [story.get('image_query')] if story.get('image_query') else []
    theme = [re.sub(r'\bfor sleep\b', '', config.get('story_category') or '', flags=re.I).strip() or 'dark atmospheric']
    seen, result = set(), []
    for query in first + keywords + theme:
        key = query.lower().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(query.strip())
    return result[:6]


def pick(story, config, channel, story_key, orientation='landscape', log=print, searchers=None):
    """Path of the story's background image, downloading one the first time."""
    target = IMAGES / channel / f'{re.sub(r"[^A-Za-z0-9_-]", "_", story_key)[:80]}.jpg'
    if target.is_file():
        return target
    key = pexels_key()
    if searchers is None:
        searchers = ([('Pexels', lambda q: search_pexels(q, orientation, key))] if key else []) + \
                    [('Openverse', lambda q: search_openverse(q, orientation))]
    used = read_json(USED, {}) or {}
    problems = []
    for query in queries_for(story, config):
        for name, search in searchers:
            try:
                results = search(query)
            except Exception as exc:  # offline, rate limit, bad key: try the next source
                if name == 'Openverse' and '401' in str(exc):
                    problems.append('Openverse now needs an account, so it was skipped')
                elif name == 'Pexels' and '401' in str(exc):
                    problems.append('Pexels refused the API key; check it in Settings')
                else:
                    problems.append(f'{name}: {exc}')
                continue
            for result in results:
                if not result.get('url') or result['id'] in used or max(result['width'], result['height']) < MIN_WIDTH:
                    continue
                try:
                    data, content_type = _get(result['url'])
                    if content_type and not content_type.startswith('image/'):
                        continue
                    size = save_image(data, target)
                except Exception as exc:
                    problems.append(f'{name} download: {exc}')
                    continue
                record = {**{k: result[k] for k in ('page', 'author', 'license')}, 'source': name, 'query': query,
                          'channel': channel, 'story': story_key, 'size': list(size),
                          'saved_at': datetime.now(timezone.utc).isoformat()}
                update_json(USED, lambda rows: rows.update({result['id']: record}), {})
                write_json(target.with_suffix('.json'), {'id': result['id'], **record})
                log(f'Background image: "{query}" from {name} ({result.get("page") or result["id"]}).')
                return target
    detail = '; '.join(dict.fromkeys(problems))[:300]
    raise NoImage('No unused free image found for this story' + (f' ({detail})' if detail else '') +
                  '. Add a free Pexels API key in Settings, add image keywords, or use background clips.')


def main():
    """Command line used by production when it runs in an environment without Pillow."""
    import argparse
    import sys
    from channel_config import load_channel
    parser = argparse.ArgumentParser(description='Pick a background image for one story.')
    parser.add_argument('--channel', required=True)
    parser.add_argument('--story', required=True, type=Path, help='Story JSON file')
    parser.add_argument('--key', required=True, help='Name the image is saved under')
    parser.add_argument('--orientation', choices=['landscape', 'portrait'], default='landscape')
    args = parser.parse_args()
    story = read_json(args.story, {}) or {}
    try:
        path = pick(story, load_channel(args.channel), args.channel, args.key, args.orientation,
                    log=lambda m: print(m, file=sys.stderr, flush=True))
    except NoImage as exc:
        print(json.dumps({'error': str(exc)}), flush=True)
        return
    print(json.dumps({'path': str(path)}), flush=True)


if __name__ == '__main__':
    main()
