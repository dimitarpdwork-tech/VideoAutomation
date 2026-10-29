"""Make story text sound natural when read aloud.

- strip_meta: drops Reddit-only lines (edits thanking voters, TL;DR spoilers).
- expand_shorthand: AITA, TIFU, MIL, "(25F)" and similar become spoken words.
- clean_language: optional advertiser-friendly wording. YouTube limits ads on
  videos with strong profanity, especially early in the video.
"""
import re

_META_LINE = re.compile(
    r'(?im)^\s*(?:\*\*)?(?:edit|update|eta|ps)\s*\d*\s*[:\-].*\b(?:upvote|award|gold|karma|comment|replies|blew up|thank)\w*.*$')
_TLDR_LINE = re.compile(r'(?im)^[ \t]*(?:\*\*)?tl\s*;?\s*dr\b[^\n]*$')

# Upper-case forms only, so ordinary words ("so", "bf" in a word) are untouched.
# Abbreviations that are also ordinary words when shouted (SO, TIL, ETA, OP,
# DD, DS) are handled only in context below.
SHORTHAND = {
    'AITA': 'Am I the jerk', 'WIBTA': 'Would I be the jerk', 'AITAH': 'Am I the jerk',
    'TIFU': 'Today I messed up', 'NTA': 'not the jerk', 'YTA': 'you are the jerk',
    'MIL': 'mother-in-law', 'FIL': 'father-in-law', 'SIL': 'sister-in-law', 'BIL': 'brother-in-law',
    'DH': 'my husband', 'DW': 'my wife',
    'BF': 'boyfriend', 'GF': 'girlfriend', 'BFF': 'best friend', 'LDR': 'long-distance relationship',
    'IMO': 'in my opinion', 'TBH': 'to be honest', 'IRL': 'in real life', 'FWIW': 'for what it is worth',
    'IDK': "I don't know", 'NGL': 'not gonna lie', 'HOA': 'H O A',
}
_SHORTHAND_RE = re.compile(r'(?<![\w/])(' + '|'.join(sorted(SHORTHAND, key=len, reverse=True)) + r')(?![\w/])')
# "my SO", "her SO's", "my DD (7)" -> words; "TIL" only as an opener.
_CONTEXT = [
    (re.compile(r"\b([Mm]y|[Hh]is|[Hh]er|[Tt]heir|[Yy]our|[Oo]ur)\s+SO\b"), r'\1 partner'),
    (re.compile(r"\b([Mm]y|[Hh]is|[Hh]er|[Tt]heir|[Yy]our|[Oo]ur)\s+DD\b"), r'\1 daughter'),
    (re.compile(r"\b([Mm]y|[Hh]is|[Hh]er|[Tt]heir|[Yy]our|[Oo]ur)\s+DS\b"), r'\1 son'),
    (re.compile(r'^(\s*)TIL\b'), r'\1Today I learned'),
    (re.compile(r'\bTIL that\b'), 'Today I learned that'),
]
_LOWER = {'bf': 'boyfriend', 'gf': 'girlfriend', 'tbh': 'to be honest', 'idk': "I don't know",
          'imo': 'in my opinion', 'ngl': 'not gonna lie', 'w/': 'with', 'w/o': 'without', 'b/c': 'because'}
_LOWER_RE = re.compile(r'(?<![\w/])(' + '|'.join(re.escape(k) for k in sorted(_LOWER, key=len, reverse=True)) + r')(?![\w])')
# "(25F)", "[25 m]", "(F25)" -> ", 25," ; the narrator voice already reflects gender.
_AGE_RE = re.compile(r'\s*[\[(]\s*(?:(\d{1,2})\s*([MFmf])|([MFmf])\s*(\d{1,2}))\s*[\])]')
_AGE_BARE_RE = re.compile(r'\b(I|me|my \w+|[A-Z][a-z]+)\s+(\d{1,2})\s*([MF])\b')

STRONG = {
    r'motherf\w*': 'jerk', r'f+u+c+k+(?:ing|in|ed|er|s)?': {'ing': 'freaking', 'in': 'freaking', 'ed': 'messed',
                                                            'er': 'jerk', 's': 'messes', '': 'heck'},
    r'bullshit': 'nonsense', r'shit(?:ty|ting|s)?': {'ty': 'crappy', 'ting': 'kidding', 's': 'things', '': 'crap'},
    r'ass(?:hole|holes)': {'hole': 'jerk', 'holes': 'jerks'}, r'bitch(?:es|ing|y)?': {'es': 'jerks', 'ing': 'complaining', 'y': 'rude', '': 'jerk'},
    r'dick(?:head)?': 'jerk', r'cunt': 'jerk', r'goddamn(?:ed)?': 'darn', r'damn(?:ed|it)?': 'darn',
    r'bastard': 'jerk', r'slut': 'jerk', r'whore': 'jerk', r'piss(?:ed)?': {'ed': 'ticked', '': 'annoy'},
}


def strip_meta(text):
    """Drop TL;DR lines (spoilers) and Reddit thank-you edits. Never removes story text
    beyond those lines, so a story that opens with a TL;DR keeps its body."""
    text = _TLDR_LINE.sub('', text)
    return _META_LINE.sub('', text)


def expand_shorthand(text):
    text = _AGE_RE.sub(lambda m: f', {m.group(1) or m.group(4)},', text)
    text = _AGE_BARE_RE.sub(lambda m: f'{m.group(1)}, {m.group(2)},', text)
    text = re.sub(r',\s*,', ',', text)
    text = re.sub(r',(\s*[.!?])', r'\1', text)
    for pattern, replacement in _CONTEXT:
        text = pattern.sub(replacement, text)
    text = _SHORTHAND_RE.sub(lambda m: SHORTHAND[m.group(1)], text)
    text = _LOWER_RE.sub(lambda m: _LOWER[m.group(1).lower()], text)
    return text.replace(' & ', ' and ')


def _match_case(original, replacement):
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def clean_language(text):
    for pattern, replacement in STRONG.items():
        def swap(match, replacement=replacement):
            word = match.group(0)
            if isinstance(replacement, dict):
                lowered = word.lower()
                suffix = next((s for s in sorted(replacement, key=len, reverse=True) if s and lowered.endswith(s)), '')
                if pattern.startswith('ass(') and not suffix:
                    suffix = 'holes' if lowered.endswith('holes') else 'hole'
                choice = replacement.get(suffix, replacement.get('', 'darn'))
            else:
                choice = replacement
            return _match_case(word, choice)
        if pattern.startswith('dick'):
            # Leave the name: "Dick" mid-sentence, or followed by a capitalised surname.
            def swap(match, swap=swap):
                start, word = match.start(), match.group(0)
                before = text[:start].rstrip()
                after = text[match.end():match.end() + 2]
                if word[:1].isupper() and ((before and before[-1] not in '.!?"\u201c') or re.match(r' [A-Z]', after)):
                    return word
                return swap(match)
        text = re.sub(r'(?i)\b' + pattern + r'\b', swap, text)
    return re.sub(r'(?i)\b(a)n (jerk|crap|darn|heck|freaking|nonsense)\b', r'\1 \2', text)


def for_narration(text, clean=False):
    text = expand_shorthand(text)
    return clean_language(text) if clean else text
