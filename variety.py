"""Warn when a new video looks too much like the channel's recent ones.

YouTube judges a channel's recent uploads together; titles that follow one
pattern, or stories that open the same way, read as mass production. This
check runs when a batch is planned and its warnings are shown during review.
It never blocks anything: you decide.
"""
import re
from difflib import SequenceMatcher

from channel_config import paths, read_json

RECENT = 30
TITLE_LIMIT = 0.75      # titles this similar to a recent one get a warning
OPENING_LIMIT = 0.7     # first sentences this similar get a warning
PATTERN_SHARE = 0.3     # more than this share of recent titles starting the same way is a pattern


def _norm(text):
    return ' '.join(re.findall(r"[a-z0-9']+", (text or '').lower()))


def first_sentence(text):
    match = re.split(r'(?<=[.!?])\s+', (text or '').strip(), maxsplit=1)
    return match[0][:200] if match else ''


SLOW_OPENERS = re.compile(
    r"^\W*(?:so\b|ok(?:ay)?\b|hi\b|hello\b|hey\b|this (?:is|happened|story)\b|let me\b|before i (?:start|begin)\b|"
    r"i (?:never|always|don'?t usually) (?:thought|believed|post|do)\b|throwaway\b|long post\b|first (?:time )?post\b|"
    r"english is not\b|sorry for\b|i'?ve been (?:lurking|reading)\b|disclaimer\b)", re.I)
HOOK_WORDS = 28


def hook_problem(text):
    """Why the story's opening is not a hook, or None. Viewers decide in the first seconds."""
    import delivery
    first = first_sentence(delivery.strip(text or ''))
    if not first:
        return 'the story is empty'
    if SLOW_OPENERS.match(first):
        return f'it opens with a slow, generic line ("{first[:60]}") instead of a hook'
    if len(re.findall(r"\w+", first)) > HOOK_WORDS:
        return f'the first sentence is too long to work as a hook (keep it under {HOOK_WORDS - 3} words)'
    return None


def recent_items(channel, limit=RECENT):
    """Titles and openings of the channel's latest planned or uploaded videos."""
    rows = []
    for plan in sorted(paths(channel)['videos'].glob('*/batch.json')):
        for item in read_json(plan, []) or []:
            if item.get('status') == 'complete':
                rows.append({'title': item.get('title', ''), 'opening': item.get('opening', '')})
    return rows[-limit:]


def opening_words(title, count=2):
    return ' '.join(_norm(title).split()[:count])


def check(title, opening, recent):
    """Warnings (plain sentences) for one new video against recent ones."""
    warnings = []
    new_title, new_opening = _norm(title), _norm(opening)
    for row in recent:
        if new_title and SequenceMatcher(None, new_title, _norm(row['title'])).ratio() >= TITLE_LIMIT:
            warnings.append(f'Title is very close to a recent one: "{row["title"]}".')
            break
    for row in recent:
        if new_opening and row.get('opening') and \
                SequenceMatcher(None, new_opening, _norm(row['opening'])).ratio() >= OPENING_LIMIT:
            warnings.append('The story opens almost the same way as a recent video.')
            break
    start = opening_words(title)
    if start and len(recent) >= 5:
        same = sum(1 for row in recent if opening_words(row['title']) == start)
        if (same + 1) / (len(recent) + 1) > PATTERN_SHARE:
            warnings.append(f'{same} of the last {len(recent)} titles also start with "{start}"; vary the pattern.')
    return warnings
