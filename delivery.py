"""Delivery cues: how a line should be read, written into the story text.

Stories may contain a few bracketed cues:

    [pause]    a beat of silence before what follows
    [tense]    read the next sentence slower and more intense
    [whisper]  read the next sentence hushed and quieter
    [urgent]   read the next sentence faster, more alarmed
    [calm]     read the next sentence gently (sleep stories)
    [aside]    the host steps out of the story for a sentence (narrator persona)

The story generator adds them sparingly. Chatterbox uses them to vary its
delivery; Kokoro cannot act, so it simply drops them. They never appear in
captions, titles or descriptions.

While a script is cleaned, cues travel as private-use characters, which contain
no letters, so duplicate detection and word counts ignore them.
"""
import re

CUES = ('pause', 'tense', 'whisper', 'urgent', 'calm', 'aside')
_MARK = {cue: chr(0xE000 + index) for index, cue in enumerate(CUES)}
_CUE_OF = {mark: cue for cue, mark in _MARK.items()}
_BRACKET = re.compile(r'\[\s*(' + '|'.join(CUES) + r')\s*\]', re.I)
_MARKS = re.compile('[' + ''.join(_MARK.values()) + ']')
# A paragraph break: where a person telling the story takes a breath. Travels like a cue.
BREAK = chr(0xE010)
_ANY = re.compile('[' + ''.join(_MARK.values()) + BREAK + ']')


def strip(text):
    """Text without any cues, for captions, titles, descriptions and counts."""
    text = _ANY.sub(' ', _BRACKET.sub(' ', text or ''))
    text = re.sub(r'[ \t]{2,}', ' ', re.sub(r' +([.,!?;:])', r'\1', text))
    return re.sub(r'(?m)^[ \t]+|[ \t]+$', '', text).strip()


def to_marks(text):
    """Replace bracket cues with private-use characters that survive cleanup."""
    text = re.sub(r'\n[ \t]*\n\s*', f' {BREAK} ', (text or '').strip())
    return _BRACKET.sub(lambda m: f' {_MARK[m.group(1).lower()]} ', text)


def remove_marks(text):
    return re.sub(r'\s{2,}', ' ', _ANY.sub(' ', text)).strip()


def sentences(script):
    """Split a marked script into [(cue or None, text, pause_before, new_paragraph)] by sentence.

    A sentence cue lasts for one sentence. [pause] adds silence before the
    sentence that follows it; new_paragraph is True for a paragraph's first sentence.
    """
    pieces = re.split(r'(?<=[.!?…"”])\s+', script)
    result = []
    for piece in pieces:
        cue, pause, paragraph = None, False, BREAK in piece
        for mark in _MARKS.findall(piece):
            name = _CUE_OF[mark]
            if name == 'pause':
                pause = True
            else:
                cue = name
        text = remove_marks(piece)
        if not re.search(r'\w', text):
            # A cue alone (e.g. "[pause]" at the very end) carries over to the next sentence.
            if pause or cue or paragraph:
                result.append((cue, '', pause, paragraph))
            continue
        result.append((cue, text, pause, paragraph))
    merged = []
    for cue, text, pause, paragraph in result:
        if merged and not merged[-1][1]:
            previous_cue, _, previous_pause, previous_paragraph = merged.pop()
            cue, pause, paragraph = cue or previous_cue, pause or previous_pause, paragraph or previous_paragraph
        merged.append((cue, text, pause, paragraph))
    rows = [row for row in merged if row[1]]
    if rows:
        rows[0] = (*rows[0][:3], False)
    return rows


def segments(script):
    """[(cue or None, text, pause_before)] by sentence (see sentences())."""
    return [(cue, text, pause) for cue, text, pause, _ in sentences(script)]


def count(text):
    return len(_BRACKET.findall(text or '')) + len(_MARKS.findall(text or ''))
