"""Write new, original fictional stories for a channel with the Claude API.

Three ways to write (chosen automatically, or with --mode):
  concepts  Take the most-upvoted story collected from Reddit that has not been
            used yet, keep only its core idea (the concept) and write a new story
            around it: new narrator, characters, setting, events and ending. The
            result is checked against the source so it cannot be a retelling.
            Each collected story lends its concept once.
  themes    Write from the themes that perform best (your channel's views and
            average watch percentage, Reddit upvotes). Only titles are shown to
            the model, never story texts.
  auto      concepts while unused collected stories exist, then themes.

Long-format channels (2-3 hour sleep videos) get a chaptered story: an outline
first, then one chapter at a time, so a long text stays coherent.

Every result opens with a hook, may carry a few delivery cues for the narrator
([pause], [tense], [whisper] ...; see delivery.py), suggests a search phrase for
its background image, and is compared against your whole library (originality
guard).

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

import delivery
import variety
from channel_config import ROOT, CHANNELS, load_channel, paths, read_json, write_json, update_json

KEY_FILE = ROOT / 'credentials' / 'anthropic_api_key.txt'
SHINGLE = 5
MAX_OVERLAP = 0.04         # share of the new story's 5-word sequences found in any one existing story
MAX_SOURCE_OVERLAP = 0.015 # stricter against the story whose concept was borrowed
SOURCE_RUN = 8             # no 8-word sequence may be shared with the concept source
MAX_TITLE_SIMILARITY = 0.72
MAX_SOURCE_TITLE_SIMILARITY = 0.55
ATTEMPTS = 3
SOURCE_WORDS = 6000        # longer sources are cut before being sent
CUE_DENSITY = 40           # at most one delivery cue per this many words, or all cues are dropped
WORDS_PER_CHAPTER = 1800

BASE_RULES = """Rules for every story:
- Original fiction. Invented first names only; no real people, no real tragedies or crimes, brands only in passing.
- Hook first: the very first sentence (under 25 words) drops the listener into the most gripping moment, fact or question of the story. Never open with greetings, "So", "This happened", "I never believed", "Let me tell you", or any preamble. The title and the first sentence must not repeat each other.
- Clear escalation and a satisfying payoff near the end.
- Advertiser-friendly: no graphic violence or gore, no sexual content, no slurs, no self-harm, mild language at most.
- Written for the ear: short sentences, natural speech, no lists, headings, emojis or Reddit jargon (no AITA, TL;DR, "edit:", ages like "(25F)").
- Title: under 90 characters, curiosity-driven and honest about the story, no ALL CAPS, no emojis.
- Delivery cues for the narrator, used sparingly (at most one per 80 words): [pause] right before a reveal; [tense], [whisper] or [urgent] at the start of a sentence that needs that delivery. Never inside quotation marks, never two in a row.
- image_query: a 3-6 word stock-photo search for ONE atmospheric background image that fits the story: a place, object or landscape, no people, no faces, no gore (e.g. "abandoned farmhouse at night").

Reply with one JSON object inside <json></json> tags and nothing else."""

GENRES = {
    'horror': """You write original first-person horror stories for narrated videos, in the tradition of r/nosleep and late-night radio.
Grounded, plausible and slow-burning: an ordinary person, a specific place, small wrong details that pile up, dread over gore. The ending lingers or turns the story on its head.""",
    'sleep': """You write calm, slow, richly descriptive stories that help listeners fall asleep, often about history and daily life in the past.
Gentle pace, soft sensory detail, no cliffhangers, no violence described, nothing startling. Only state historical facts that are well established and widely known; avoid exact figures and dates unless certain, and describe everyday life impressionistically rather than inventing documented events. Delivery cues: only [pause] and [calm]. The first sentence still invites the listener in, but softly.""",
    'drama': """You write original, realistic first-person stories for narrated storytime videos.
Everyday realism: families, workplaces, neighbours, weddings, roommates, travel, school, money. Concrete sensory details and a twist or payoff the listener did not see coming.""",
}


class GenerationError(RuntimeError):
    pass


def api_key():
    key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not key and KEY_FILE.is_file():
        key = KEY_FILE.read_text(encoding='utf-8').strip()
    return key


def genre(config):
    category = (config.get('story_category') or '').lower()
    if config.get('video_format') == 'long' or 'sleep' in category:
        return 'sleep'
    if any(word in category for word in ('horror', 'scary', 'creepy', 'nosleep', 'paranormal', 'true crime')):
        return 'horror'
    return 'drama'


def system_prompt(config):
    return GENRES[genre(config)] + '\n\n' + BASE_RULES


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
    """This channel's uploads ranked by views, with average % watched where known.

    Returns [(title, views)] or [(title, views, percent)] rows.
    """
    channel_paths = paths(channel)
    history = read_json(channel_paths['credentials'] / 'upload_history.json', {})
    videos = read_json(channel_paths['output'] / 'youtube_insights.json', {}).get('videos', {})
    ranked = {}
    for row in history.values():
        stats = videos.get(row.get('video_id') or '', {})
        if row.get('title') and stats.get('viewCount') is not None:
            previous = ranked.get(row['title'])
            if not previous or stats['viewCount'] > previous[0]:
                ranked[row['title']] = (stats['viewCount'], stats.get('averageViewPercentage'))
    rows = sorted(ranked.items(), key=lambda item: -item[1][0])[:limit]
    return [(title, views) if percent is None else (title, views, percent) for title, (views, percent) in rows]


def reddit_performance(stories, limit=15):
    """Collected Reddit titles ranked by upvotes; without scores, collection order (top of all time)."""
    scraped = [s for s in stories if s.get('text_source') == 'post_page' and s.get('title')]
    scored = [s for s in scraped if isinstance(s.get('score'), (int, float))]
    if scored:
        return [(s['title'], int(s['score'])) for s in sorted(scored, key=lambda s: -s['score'])[:limit]]
    return [(s['title'], None) for s in scraped[:limit]]


def concept_sources(channel):
    """Unused collected stories in this channel's folder, most upvoted first: [(path, story)]."""
    folder = paths(channel)['stories']
    found = []
    for path in sorted(folder.glob('*.json')) if folder.is_dir() else []:
        if path.stem.endswith(('_used', '_review')):
            continue
        try:
            story = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, json.JSONDecodeError):
            continue
        if (isinstance(story, dict) and story.get('text_source') == 'post_page' and story.get('text', '').strip()
                and not story.get('concept_used_by')):
            found.append((path, story))
    return sorted(found, key=lambda row: -(row[1].get('score') or 0))


def _words(text):
    return re.findall(r"[a-z0-9']+", delivery.strip(text).lower())


def shingles(text, size=SHINGLE):
    words = _words(text)
    return {tuple(words[i:i + size]) for i in range(max(0, len(words) - size + 1))}


def originality_problem(candidate, stories, inspiration_titles, source=None):
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
    if source:
        if SequenceMatcher(None, title, (source.get('title') or '').lower()).ratio() > MAX_SOURCE_TITLE_SIMILARITY:
            return 'the title is too close to the source story; invent a new one'
        overlap = len(mine & shingles(source['text'])) / len(mine)
        if overlap > MAX_SOURCE_OVERLAP:
            return f'{overlap:.1%} of the wording matches the source story; write every sentence fresh'
        shared = shingles(candidate['text'], SOURCE_RUN) & shingles(source['text'], SOURCE_RUN)
        if shared:
            return f'it repeats a phrase from the source ("{" ".join(next(iter(shared)))}"); write every sentence fresh'
    return None


def length_target(config, length):
    if length == 'auto':
        length = {'funnel': 'full', 'long': 'long'}.get(config.get('video_format'), 'short')
    if length == 'long':
        low, high = config.get('full_min_words', 3000), config.get('full_max_words', 25000)
        target = min(max(config.get('long_target_words', 12000), low), high)
        return length, int(target * 0.9), int(target * 1.1)
    if length == 'full':
        low = max(config.get('full_min_words', 300), 900)
        high = max(low + 200, min(config.get('full_max_words', 2400), 1500))
        return length, low, high
    low = max(config.get('min_words', 1), 120)
    high = max(low + 30, min(config.get('max_words', 400), 175))
    return length, low, high


def _performance_lines(own, reddit):
    lines = []
    if own:
        lines.append('Your channel\'s best-performing videos (title - views, average watched):')
        for row in own:
            watched = f', {row[2]:.0f}% watched' if len(row) > 2 and row[2] is not None else ''
            lines.append(f'- {row[0]} - {row[1]:,} views{watched}')
        lines.append('')
    if reddit:
        lines.append('Popular stories elsewhere (title - upvotes). Learn the themes, do not reuse the plots:')
        lines += [f'- {title}' + (f' - {score:,} upvotes' if score is not None else '') for title, score in reddit]
        lines.append('')
    return lines


def _fields(length):
    fields = ['"title": string', '"text": string (paragraphs separated by blank lines)',
              '"theme": short label for the theme or concept', '"narrator": "male" or "female"',
              '"image_query": string']
    if length == 'full':
        fields.append('"teaser_sentences": integer')
    return fields


def build_prompt(config, length, low, high, own, reddit, avoid_titles, feedback=None):
    lines = [f"Channel theme: {config.get('story_category') or 'General stories'}.", '']
    lines += _performance_lines(own, reddit)
    if avoid_titles:
        lines.append('Already written for this channel; choose a different situation:')
        lines += [f'- {title}' for title in avoid_titles[-30:]]
        lines.append('')
    lines.append(f'Write one new story of {low}-{high} words.')
    if length == 'full':
        lines.append('Also choose where a 40-second teaser should stop: the number of opening sentences '
                     '(about 70-100 words) that end on a cliffhanger, right before something important is revealed.')
    lines.append('JSON fields: ' + ', '.join(_fields(length)) + '.')
    if feedback:
        lines.append(f'\nYour previous attempt was rejected: {feedback}. Write something clearly different.')
    return '\n'.join(lines)


def build_concept_prompt(config, length, low, high, source, avoid_titles, feedback=None):
    words = delivery.strip(source['text']).split()
    text = ' '.join(words[:SOURCE_WORDS]) + (' […]' if len(words) > SOURCE_WORDS else '')
    lines = [f"Channel theme: {config.get('story_category') or 'General stories'}.", '',
             'Below is a popular story. Use it ONLY for its core concept: the basic premise in one sentence '
             '(for example "a night guard notices the building\'s cameras show a floor that no longer exists").',
             'Then write a completely new, original story on that premise:',
             '- a different narrator, different characters and names, a different place and setting;',
             '- a different sequence of events, different scares or turns, and a different ending;',
             '- no sentence, phrase, name or unusual detail taken from the source.',
             'Someone who read the source must not recognise your story as a retelling of it.', '',
             f'<source title="{(source.get("title") or "").replace(chr(34), "")}">', text, '</source>', '']
    if avoid_titles:
        lines.append('Already written for this channel; choose different titles and situations:')
        lines += [f'- {title}' for title in avoid_titles[-30:]]
        lines.append('')
    lines.append(f'Write one new story of {low}-{high} words.')
    if length == 'full':
        lines.append('Also choose where a 40-second teaser should stop: the number of opening sentences '
                     '(about 70-100 words) that end on a cliffhanger, right before something important is revealed.')
    lines.append('JSON fields: ' + ', '.join(_fields(length)) + ', "concept": the one-sentence premise you kept.')
    if feedback:
        lines.append(f'\nYour previous attempt was rejected: {feedback}.')
    return '\n'.join(lines)


def _json(text):
    match = re.search(r'<json>\s*(\{.*\})\s*</json>', text, re.S) or re.search(r'(\{.*\})', text, re.S)
    if not match:
        raise GenerationError('reply contained no JSON')
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise GenerationError(f'reply JSON was invalid ({exc})') from exc


def tidy_cues(text):
    """Drop every cue when the model overused them; a few cues help, many sound like acting."""
    words = len(_words(text))
    if delivery.count(text) > max(1, words // CUE_DENSITY):
        return delivery.strip(text)
    return text


def parse_reply(text, length):
    data = _json(text)
    title = re.sub(r'\s+', ' ', str(data.get('title', ''))).strip().strip('"')
    story_text = tidy_cues(str(data.get('text', '')).strip())
    if not title or len(title) > 100 or re.search(r'[<>]', title):
        raise GenerationError('missing or invalid title')
    if len(_words(story_text)) < 60:
        raise GenerationError('story too short')
    problem = variety.hook_problem(story_text)
    if problem:
        raise GenerationError(problem)
    result = {'title': title, 'text': story_text, 'theme': str(data.get('theme', ''))[:80]}
    if data.get('narrator') in ('male', 'female'):
        result['narrator_gender'] = data['narrator']
    query = re.sub(r'[^\w\s\-]', '', str(data.get('image_query') or '')).strip()
    if query:
        result['image_query'] = ' '.join(query.split()[:8])
    if data.get('concept'):
        result['concept'] = str(data['concept'])[:300]
    if length == 'full':
        try:
            sentences = int(data.get('teaser_sentences') or 0)
        except (TypeError, ValueError):
            sentences = 0
        if sentences > 0:
            result['teaser_sentences'] = max(2, sentences)
    return result


def ask_model(client, model, prompt, length, system=None, max_tokens=None):
    response = client.messages.create(
        model=model, max_tokens=max_tokens or (4000 if length == 'full' else 1200), system=system or BASE_RULES,
        messages=[{'role': 'user', 'content': prompt}])
    return ''.join(block.text for block in response.content if getattr(block, 'type', '') == 'text')


def write_long(client, model, config, low, high, own, reddit, avoid, feedback, log):
    """Outline, then one chapter per call: a coherent story of thousands of words."""
    target = (low + high) // 2
    chapters = max(3, round(target / WORDS_PER_CHAPTER))
    system = system_prompt(config)
    lines = [f"Channel theme: {config.get('story_category') or 'General stories'}.", '']
    lines += _performance_lines(own, reddit)
    if avoid:
        lines += ['Already written for this channel; choose a different subject:'] + [f'- {t}' for t in avoid[-30:]] + ['']
    lines += [f'Plan one long story of about {target:,} words in {chapters} chapters. Do not write it yet.',
              'JSON fields: "title": string, "premise": two sentences, "narrator": "male" or "female", '
              '"image_query": string, "theme": short label, '
              f'"chapters": list of {chapters} objects with "heading" and "summary" (3-4 sentences each).']
    if feedback:
        lines.append(f'\nThe previous attempt was rejected: {feedback}. Choose something clearly different.')
    outline = _json(ask_model(client, model, '\n'.join(lines), 'long', system, 3000))
    plan = outline.get('chapters') or []
    if not isinstance(plan, list) or len(plan) < 2:
        raise GenerationError('the outline had no chapters')
    title = re.sub(r'\s+', ' ', str(outline.get('title', ''))).strip().strip('"')
    if not title or len(title) > 100 or re.search(r'[<>]', title):
        raise GenerationError('missing or invalid title')
    overview = '\n'.join(f'{i}. {c.get("heading", "")}: {c.get("summary", "")}' for i, c in enumerate(plan, 1))
    per_chapter = max(400, target // len(plan))
    texts, previous = [], ''
    for number, chapter in enumerate(plan, 1):
        log(f'  Writing chapter {number}/{len(plan)}: {chapter.get("heading", "")}')
        prompt = '\n'.join([
            f'Story title: {title}', f'Premise: {outline.get("premise", "")}', 'Outline:', overview, '',
            (f'The previous chapter ended with: "{previous}"' if previous else 'This is the opening chapter: its first '
             'sentence must invite the listener in.'),
            f'Write chapter {number} of {len(plan)} ("{chapter.get("heading", "")}"), about {per_chapter} words.',
            'Continue seamlessly; no chapter heading, no recap of earlier chapters'
            + ('; bring the story to a soft, settled close.' if number == len(plan) else '.'),
            'Reply with the chapter text only, inside <text></text> tags.'])
        reply = ask_model(client, model, prompt, 'long', system, max(3000, per_chapter * 3))
        match = re.search(r'<text>(.*?)</text>', reply, re.S)
        chapter_text = (match.group(1) if match else reply).strip()
        if len(_words(chapter_text)) < per_chapter * 0.4:
            raise GenerationError(f'chapter {number} came back too short')
        texts.append(chapter_text)
        previous = ' '.join(chapter_text.split()[-60:])
    story = {'title': title, 'text': tidy_cues('\n\n'.join(texts)), 'theme': str(outline.get('theme', ''))[:80]}
    if outline.get('narrator') in ('male', 'female'):
        story['narrator_gender'] = outline['narrator']
    query = re.sub(r'[^\w\s\-]', '', str(outline.get('image_query') or '')).strip()
    if query:
        story['image_query'] = ' '.join(query.split()[:8])
    problem = variety.hook_problem(story['text'])
    if problem:
        raise GenerationError(problem)
    return story


def _client():
    key = api_key()
    if not key:
        raise GenerationError('No Claude API key. Add one in the dashboard Settings or set ANTHROPIC_API_KEY.')
    import anthropic
    return anthropic.Anthropic(api_key=key)


def _api_error(exc, created):
    status = getattr(exc, 'status_code', None)
    hint = {401: ' Check the API key in Settings.', 404: ' Check the model name in Settings.',
            429: ' Rate limit reached; try again in a minute.'}.get(status, '')
    return GenerationError(f'Claude API error: {exc}.{hint} {len(created)} story(ies) were saved.')


def generate(channel, count, length='auto', client=None, log=print, mode='auto'):
    config = load_channel(channel)
    client = client or _client()
    length, low, high = length_target(config, length)
    model = config.get('generator_model') or 'claude-sonnet-5-5'
    stories = library()
    own = own_channel_performance(channel)
    reddit = reddit_performance(stories)
    inspiration_titles = [row[0] for row in own] + [t for t, _ in reddit]
    avoid = [s['title'] for s in stories if s.get('text_source') == 'generated']
    sources = concept_sources(channel) if mode in ('auto', 'concepts') and length != 'long' else []
    if mode == 'concepts' and not sources:
        log('No unused collected stories in this channel to borrow concepts from; writing from themes instead.')
    elif not sources and not own and not reddit:
        log('No performance data yet (no uploads with views, no collected stories); writing from the channel theme.')
    folder = paths(channel)['stories']
    folder.mkdir(parents=True, exist_ok=True)
    system = system_prompt(config)
    created = []
    for number in range(1, count + 1):
        source_path, source = sources.pop(0) if sources else (None, None)
        if source:
            log(f'Story {number}: borrowing the concept of "{source.get("title", source_path.stem)}" '
                f'({source.get("score") or "?"} upvotes).')
        feedback = None
        for attempt in range(1, ATTEMPTS + 1):
            try:
                if length == 'long':
                    candidate = write_long(client, model, config, low, high, own, reddit, avoid, feedback, log)
                else:
                    prompt = (build_concept_prompt(config, length, low, high, source, avoid, feedback) if source
                              else build_prompt(config, length, low, high, own, reddit, avoid, feedback))
                    candidate = parse_reply(ask_model(client, model, prompt, length, system), length)
            except GenerationError as exc:
                feedback = str(exc)
                log(f'Story {number}: attempt {attempt} unusable ({exc}).')
                continue
            except Exception as exc:  # authentication, network, rate limits: stop with a clear reason
                raise _api_error(exc, created) from exc
            problem = originality_problem(candidate, stories, inspiration_titles, source)
            if problem:
                feedback = problem
                log(f'Story {number}: attempt {attempt} rejected by originality check ({problem}).')
                continue
            story_id = 'gen_' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S') + secrets.token_hex(2)
            story = {'id': story_id, **candidate, 'text_source': 'generated', 'fiction': True,
                     'inspired_by': inspiration_titles[:30], 'mode': 'concept' if source else
                     ('long' if length == 'long' else 'themes'),
                     'model': model, 'generated_at': datetime.now(timezone.utc).isoformat()}
            if source:
                # Kept privately so the same concept is never used twice; never shown in descriptions.
                story['concept_source'] = source.get('id') or source_path.stem
            write_json(folder / f'{story_id}.json', story)
            if source:
                update_json(source_path, lambda s: s.update(
                    concept_used_by=(s.get('concept_used_by') or []) + [story_id],
                    concept_used_at=datetime.now(timezone.utc).isoformat()), {})
            stories.append(story)
            avoid.append(story['title'])
            created.append(story)
            words = len(_words(story['text']))
            log(f'Story {number}: "{story["title"]}" ({words:,} words, '
                f'{"concept" if source else "theme"}: {story.get("concept") or story.get("theme") or "-"})')
            break
        else:
            log(f'Story {number}: gave up after {ATTEMPTS} attempts.')
            if source:
                sources.append((source_path, source))  # try its concept again later
    log(f'Generated {len(created)} of {count} stories into {folder}.')
    return created


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--channel', default='main')
    parser.add_argument('--count', type=int, default=5)
    parser.add_argument('--length', choices=['auto', 'short', 'full', 'long'], default='auto',
                        help='auto follows the channel format: Shorts, full videos or long videos')
    parser.add_argument('--mode', choices=['auto', 'concepts', 'themes'], default='auto')
    args = parser.parse_args()
    if not 1 <= args.count <= 50:
        parser.error('count must be between 1 and 50')
    try:
        created = generate(args.channel, args.count, args.length, log=lambda m: print(m, flush=True), mode=args.mode)
    except Exception as exc:
        raise SystemExit(f'Story generation stopped: {exc}')
    if not created:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
