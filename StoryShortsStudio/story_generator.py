"""Generate new, original fictional stories based on what performs well.

What it learns from (titles and numbers only, never story texts):
  - your channel's own videos, ranked by YouTube views;
  - collected Reddit stories, ranked by upvotes.
The AI is told to write a completely new story on themes that work, with new
characters, events and details. Every result is compared against all stories
in your library and rejected if it overlaps too much (originality guard).

Needs a Claude API key: set ANTHROPIC_API_KEY, or save it in the dashboard
(stored locally in credentials/anthropic_api_key.txt).

Run: python story_generator.py --channel main --count 5
"""
import argparse
import json
import os
import re
import secrets
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from channel_config import ROOT, CHANNELS, load_channel, paths, read_json, write_json

KEY_FILE = ROOT / 'credentials' / 'anthropic_api_key.txt'
SHINGLE = 5
MAX_OVERLAP = 0.04       # share of the new story's 5-word sequences found in any one existing story
MAX_TITLE_SIMILARITY = 0.72
ATTEMPTS = 3

SYSTEM = """You write original, realistic first-person stories for narrated storytime videos.

Rules:
- Write a completely new story: new characters, setting, events and details. The popular titles you are shown only tell you which themes, emotions and conflicts audiences respond to. Never retell, paraphrase, continue or combine any of them.
- Everyday realism: families, workplaces, neighbours, weddings, roommates, travel, school, money. Concrete sensory details. Invented first names only; no real people, no real tragedies or crimes, brands only in passing.
- The first sentence is a hook that makes the listener need to know what happens.
- Clear escalation and a satisfying twist or payoff near the end.
- Advertiser-friendly: no graphic violence, no sexual content, no slurs, mild language at most.
- Written for the ear: short sentences, natural speech, no lists, headings, emojis or Reddit jargon (no AITA, TL;DR, "edit:", ages like "(25F)").
- Title: under 90 characters, curiosity-driven and honest about the story, no ALL CAPS, no emojis.

Reply with one JSON object inside <json></json> tags and nothing else."""


class GenerationError(RuntimeError):
    pass


def api_key():
    key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not key and KEY_FILE.is_file():
        key = KEY_FILE.read_text(encoding='utf-8').strip()
    return key


def all_story_files():
    folders = [ROOT / 'stories'] + sorted(p / 'stories' for p in CHANNELS.glob('*') if (p / 'stories').is_dir())
    seen = set()
    for folder in folders:
        for path in sorted(folder.glob('*.json')) if folder.is_dir() else []:
            if path.resolve() not in seen:
                seen.add(path.resolve())
                yield path


def library():
    stories = []
    for path in all_story_files():
        try:
            story = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(story, dict) and story.get('text'):
            stories.append(story)
    return stories


def own_channel_performance(channel, limit=12):
    """Titles of this channel's uploads ranked by views (from the insights cache)."""
    channel_paths = paths(channel)
    history = read_json(channel_paths['credentials'] / 'upload_history.json', {})
    views = read_json(channel_paths['output'] / 'youtube_insights.json', {}).get('videos', {})
    ranked = {}
    for row in history.values():
        stats = views.get(row.get('video_id') or '', {})
        if row.get('title') and stats.get('viewCount') is not None:
            ranked[row['title']] = max(ranked.get(row['title'], 0), stats['viewCount'])
    return sorted(ranked.items(), key=lambda item: -item[1])[:limit]


def reddit_performance(stories, limit=15):
    """Collected Reddit titles ranked by upvotes; without scores, collection order (top of all time)."""
    scraped = [s for s in stories if s.get('text_source') == 'post_page' and s.get('title')]
    scored = [s for s in scraped if isinstance(s.get('score'), (int, float))]
    if scored:
        return [(s['title'], int(s['score'])) for s in sorted(scored, key=lambda s: -s['score'])[:limit]]
    return [(s['title'], None) for s in scraped[:limit]]


def shingles(text):
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {tuple(words[i:i + SHINGLE]) for i in range(max(0, len(words) - SHINGLE + 1))}


def originality_problem(candidate, stories, inspiration_titles):
    """Return a reason if the candidate is too close to existing material, else None."""
    mine = shingles(candidate['text'])
    if not mine:
        return 'empty story'
    title = candidate['title'].lower()
    for other_title in inspiration_titles + [s.get('title', '') for s in stories]:
        if other_title and SequenceMatcher(None, title, other_title.lower()).ratio() > MAX_TITLE_SIMILARITY:
            return f'title too close to "{other_title}"'
    for story in stories:
        overlap = len(mine & shingles(story['text'])) / len(mine)
        if overlap > MAX_OVERLAP:
            return f'text overlaps {overlap:.0%} with "{story.get("title", "an existing story")}"'
    return None


def length_target(config, length):
    if length == 'auto':
        length = 'full' if config.get('video_format') == 'funnel' else 'short'
    if length == 'full':
        low = max(config.get('full_min_words', 300), 900)
        high = max(low + 200, min(config.get('full_max_words', 2400), 1500))
        return length, low, high
    low = max(config.get('min_words', 1), 120)
    high = max(low + 30, min(config.get('max_words', 400), 175))
    return length, low, high


def build_prompt(config, length, low, high, own, reddit, avoid_titles, feedback=None):
    lines = [f"Channel theme: {config.get('story_category') or 'General stories'}.", '']
    if own:
        lines.append('Your channel\'s best-performing videos (title - views):')
        lines += [f'- {title} - {views:,} views' for title, views in own]
        lines.append('')
    if reddit:
        lines.append('Popular stories elsewhere (title - upvotes). Learn the themes, do not reuse the plots:')
        lines += [f'- {title}' + (f' - {score:,} upvotes' if score is not None else '') for title, score in reddit]
        lines.append('')
    if avoid_titles:
        lines.append('Already written for this channel; choose a different situation:')
        lines += [f'- {title}' for title in avoid_titles[-30:]]
        lines.append('')
    lines.append(f'Write one new story of {low}-{high} words.')
    fields = ['"title": string', '"text": string (paragraphs separated by blank lines)',
              '"theme": short label for the theme you drew on', '"narrator": "male" or "female"']
    if length == 'full':
        lines.append('Also choose where a 40-second teaser should stop: the number of opening sentences '
                     '(about 70-100 words) that end on a cliffhanger, right before something important is revealed.')
        fields.append('"teaser_sentences": integer')
    lines.append('JSON fields: ' + ', '.join(fields) + '.')
    if feedback:
        lines.append(f'\nYour previous attempt was rejected: {feedback}. Write something clearly different.')
    return '\n'.join(lines)


def parse_reply(text, length):
    match = re.search(r'<json>\s*(\{.*\})\s*</json>', text, re.S) or re.search(r'(\{.*\})', text, re.S)
    if not match:
        raise GenerationError('reply contained no JSON')
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise GenerationError(f'reply JSON was invalid ({exc})') from exc
    title = re.sub(r'\s+', ' ', str(data.get('title', ''))).strip().strip('"')
    story_text = str(data.get('text', '')).strip()
    if not title or len(title) > 100 or re.search(r'[<>]', title):
        raise GenerationError('missing or invalid title')
    if len(re.findall(r'\w+', story_text)) < 60:
        raise GenerationError('story too short')
    result = {'title': title, 'text': story_text, 'theme': str(data.get('theme', ''))[:80]}
    if data.get('narrator') in ('male', 'female'):
        result['narrator_gender'] = data['narrator']
    if length == 'full':
        try:
            sentences = int(data.get('teaser_sentences') or 0)
        except (TypeError, ValueError):
            sentences = 0
        if sentences > 0:
            result['teaser_sentences'] = max(2, sentences)
    return result


def ask_model(client, model, prompt, length):
    response = client.messages.create(
        model=model, max_tokens=4000 if length == 'full' else 1200, system=SYSTEM,
        messages=[{'role': 'user', 'content': prompt}])
    return ''.join(block.text for block in response.content if getattr(block, 'type', '') == 'text')


def generate(channel, count, length='auto', client=None, log=print):
    config = load_channel(channel)
    if client is None:
        key = api_key()
        if not key:
            raise GenerationError('No Claude API key. Add one in the dashboard Settings or set ANTHROPIC_API_KEY.')
        import anthropic
        client = anthropic.Anthropic(api_key=key)
    length, low, high = length_target(config, length)
    stories = library()
    own = own_channel_performance(channel)
    reddit = reddit_performance(stories)
    inspiration_titles = [t for t, _ in own] + [t for t, _ in reddit]
    if not own and not reddit:
        log('No performance data yet (no uploads with views, no collected stories); writing from the channel theme.')
    avoid = [s['title'] for s in stories if s.get('text_source') == 'generated']
    folder = paths(channel)['stories']
    folder.mkdir(parents=True, exist_ok=True)
    created = []
    for number in range(1, count + 1):
        feedback = None
        for attempt in range(1, ATTEMPTS + 1):
            prompt = build_prompt(config, length, low, high, own, reddit, avoid, feedback)
            try:
                reply = ask_model(client, config.get('generator_model') or 'claude-sonnet-5-5', prompt, length)
            except Exception as exc:  # authentication, network, rate limits: stop with a clear reason
                status = getattr(exc, 'status_code', None)
                hint = {401: ' Check the API key in Settings.', 404: ' Check the model name in Settings.',
                        429: ' Rate limit reached; try again in a minute.'}.get(status, '')
                raise GenerationError(f'Claude API error: {exc}.{hint} {len(created)} story(ies) were saved.') from exc
            try:
                candidate = parse_reply(reply, length)
            except GenerationError as exc:
                feedback = str(exc)
                log(f'Story {number}: attempt {attempt} unusable ({exc}).')
                continue
            problem = originality_problem(candidate, stories, inspiration_titles)
            if problem:
                feedback = problem
                log(f'Story {number}: attempt {attempt} rejected by originality check ({problem}).')
                continue
            story_id = 'gen_' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S') + secrets.token_hex(2)
            story = {'id': story_id, **candidate, 'text_source': 'generated', 'fiction': True,
                     'inspired_by': inspiration_titles[:30],
                     'model': config.get('generator_model'), 'generated_at': datetime.now(timezone.utc).isoformat()}
            write_json(folder / f'{story_id}.json', story)
            stories.append(story)
            avoid.append(story['title'])
            created.append(story)
            words = len(re.findall(r'\w+', story['text']))
            log(f'Story {number}: "{story["title"]}" ({words} words, theme: {story.get("theme") or "-"})')
            break
        else:
            log(f'Story {number}: gave up after {ATTEMPTS} attempts.')
    log(f'Generated {len(created)} of {count} stories into {folder}.')
    return created


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--channel', default='main')
    parser.add_argument('--count', type=int, default=5)
    parser.add_argument('--length', choices=['auto', 'short', 'full'], default='auto',
                        help='auto follows the channel format: Shorts or full videos')
    args = parser.parse_args()
    if not 1 <= args.count <= 50:
        parser.error('count must be between 1 and 50')
    try:
        created = generate(args.channel, args.count, args.length, log=lambda m: print(m, flush=True))
    except Exception as exc:
        raise SystemExit(f'Story generation stopped: {exc}')
    if not created:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
