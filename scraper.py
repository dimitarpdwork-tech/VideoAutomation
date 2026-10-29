r"""Collect top stories from a subreddit into a channel's stories folder.

Run: python scraper.py --subreddit stories --time all --scrolls 5

Chrome opens; finish any access checks yourself, then press Enter. Stories are
saved as JSON with their source URL, author and upvote count. The description
builder uses the author for credit lines; the story generator uses upvotes to
learn which themes are popular. Respect Reddit's terms and the authors' rights.
"""
import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from channel_config import paths

FEED_SCRIPT = """posts => posts.map(post => ({
    id: post.getAttribute('id'),
    title: post.getAttribute('post-title'),
    author: post.getAttribute('author'),
    score: Number(post.getAttribute('score')) || null,
    comments: Number(post.getAttribute('comment-count')) || null,
    text: (post.querySelector('shreddit-post-text-body, [slot="text-body"], [id$="-post-rtjson-content"]')?.innerText || '').trim(),
    permalink: post.getAttribute('permalink') || post.querySelector('a[slot="title"]')?.getAttribute('href')
}))"""
BODY_SELECTORS = ('shreddit-post-text-body', '[slot="text-body"]', '[id$="-post-rtjson-content"]', '.md')
SKIP_TEXT = ('', '[removed]', '[deleted]')


def story_id_from(permalink):
    if '/comments/' not in (permalink or ''):
        return None
    story_id = permalink.split('/comments/', 1)[1].split('/', 1)[0]
    return story_id if story_id.isalnum() else None


def _number(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def absolute(permalink):
    return 'https://www.reddit.com' + permalink if permalink.startswith('/') else permalink


def read_body(post):
    for selector in BODY_SELECTORS:
        for element in post.locator(selector).all():
            text = element.inner_text().strip()
            if text not in SKIP_TEXT:
                return text
    return ''


def save(stories_dir, story, overwrite):
    destination = stories_dir / f"{story['id']}.json"
    used = [stories_dir / f"{story['id']}{suffix}.json" for suffix in ('_used', '_review')]
    if any(p.exists() for p in used) or (destination.exists() and not overwrite):
        return False
    destination.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding='utf-8')
    return True


def collect(args, stories_dir):
    from playwright.sync_api import sync_playwright
    from seleniumbase import sb_cdp

    prefix = f'https://www.reddit.com/r/{args.subreddit}/comments/'
    sb = sb_cdp.Chrome(incognito=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(sb.get_endpoint_url())
            page = browser.contexts[0].pages[0]
            page.goto(f'https://www.reddit.com/r/{args.subreddit}/top/?t={args.time}')
            time.sleep(2)
            input('Once Reddit has loaded (complete any checks in the browser), press Enter to start collecting...')
            page.locator('shreddit-post').first.wait_for(state='attached', timeout=30000)

            # Keep snapshots while scrolling, including posts Reddit later unloads.
            candidates = {}
            for scroll in range(args.scrolls + 1):
                for post in page.locator('shreddit-post').evaluate_all(FEED_SCRIPT):
                    key = post['id'] or post['permalink']
                    if key:
                        candidates[key] = post
                print(f'Found {len(candidates)} posts; scroll {scroll}/{args.scrolls}.', flush=True)
                if scroll < args.scrolls:
                    page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
                    page.wait_for_timeout(int(args.scroll_wait * 1000))

            # Feed text can be truncated, so open every post for the full text.
            detail = browser.contexts[0].new_page()
            saved, seen = 0, set()
            try:
                for post in candidates.values():
                    url = absolute(post['permalink'] or '')
                    story_id = story_id_from(url)
                    if not url.startswith(prefix) or not story_id or story_id in seen:
                        continue
                    seen.add(story_id)
                    try:
                        response = detail.goto(url, wait_until='domcontentloaded', timeout=60000)
                        if response and response.status in (403, 429):
                            print(f'Reddit restricted access (HTTP {response.status}); stopping.', flush=True)
                            break
                        element = detail.locator('shreddit-post').first
                        element.wait_for(state='attached', timeout=15000)
                        text = read_body(element)
                        if not text:
                            print(f'Skipped {story_id}: no story text.', flush=True)
                            continue
                        story = {
                            'id': story_id,
                            'title': post['title'] or element.get_attribute('post-title'),
                            'author': post.get('author') or element.get_attribute('author'),
                            'text': text, 'text_source': 'post_page', 'url': url,
                            'subreddit': args.subreddit,
                            'score': post.get('score') or _number(element.get_attribute('score')),
                            'comments': post.get('comments') or _number(element.get_attribute('comment-count')),
                            'collected_at': datetime.now(timezone.utc).isoformat(),
                        }
                        if save(stories_dir, story, overwrite=True):
                            saved += 1
                            print(f'Saved {story_id}', flush=True)
                        time.sleep(2)
                    except Exception as exc:  # one bad post should not stop the run
                        print(f'Could not read {story_id}: {exc}', flush=True)
            finally:
                if not detail.is_closed():
                    detail.close()
            print(f'Checked {len(seen)} posts; saved {saved} full stories to {stories_dir}.', flush=True)
    finally:
        sb.quit()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--subreddit', default='stories', help='Subreddit name without r/ (default: stories)')
    parser.add_argument('--time', default='all', choices=['hour', 'day', 'week', 'month', 'year', 'all'])
    parser.add_argument('--scrolls', type=int, default=5, help='How many times to scroll the feed')
    parser.add_argument('--scroll-wait', type=float, default=7, help='Seconds to wait after each scroll')
    parser.add_argument('--channel', default='main', help='Profile whose stories folder receives the files')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_]{2,21}', args.subreddit):
        parser.error('Invalid subreddit name')
    if not 0 <= args.scrolls <= 100:
        parser.error('scrolls must be between 0 and 100')
    stories_dir = paths(args.channel)['stories']
    stories_dir.mkdir(parents=True, exist_ok=True)
    try:
        collect(args, stories_dir)
    except Exception as exc:
        raise SystemExit(f'Collection stopped: {exc}. Stories already saved are kept.')


if __name__ == '__main__':
    main()
