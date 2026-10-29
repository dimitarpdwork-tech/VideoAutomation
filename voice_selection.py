"""Choose a narrator voice from first-person clues, with an auditable reason."""
import re


# Voices per accent family; a channel's default voice decides the family, so a
# British channel stays British when the narrator's gender switches the voice.
FAMILIES = {'a': {'male': 'am_michael', 'female': 'af_heart'},
            'b': {'male': 'bm_george', 'female': 'bf_emma'}}


def voice_for(gender, default, male=None, female=None):
    chosen = male if gender == 'male' else female
    if chosen:
        return chosen
    family = FAMILIES.get(default[:1], FAMILIES['a'])
    # Keep the channel default when it already has the wanted gender.
    if len(default) > 1 and default[1] == ('m' if gender == 'male' else 'f'):
        return default
    return family[gender]


def narrator_gender(story):
    """('male' | 'female' | None, reason) from the story's first-person clues."""
    override = story.get('narrator_gender', '').lower()
    text = story.get('title', '') + '. ' + story.get('text', '')
    # Quoted characters must not determine the narrator's identity.
    text = re.sub(r'"[^"\n]*"|“[^”\n]*”', '', text)
    explicit = set()
    if override in ('male', 'female'):
        explicit.add(override)
    age_patterns = [r'\b(?:i(?: am|[’\x27]m)?|my)\s*[\[(]?\s*(\d{1,2})\s*([mf])\b',
                    r'^\s*[\[(]?\s*(\d{1,2})\s*([mf])\b']
    for content in (text, story.get('text', '')):
        for pattern in age_patterns:
            for match in re.finditer(pattern, content, re.I):
                explicit.add('male' if match[2].lower() == 'm' else 'female')
    for gender, pattern in [('male', r'\bi(?: am|[’\x27]m) (?:a |an )?(?:man|male|guy|husband|father)\b'),
                            ('female', r'\bi(?: am|[’\x27]m) (?:a |an )?(?:woman|female|wife|mother)\b')]:
        if re.search(pattern, text, re.I): explicit.add(gender)
    if len(explicit) == 1:
        gender = explicit.pop()
        return gender, 'explicit ' + gender + ' narrator clue'
    if len(explicit) > 1:
        return None, 'conflicting clues; channel default'
    # Relationship inference is a fallback requested for this project, not certainty.
    has_partner_f = bool(re.search(r'\bmy (?:girlfriend|gf|wife)\b', text, re.I))
    has_partner_m = bool(re.search(r'\bmy (?:boyfriend|bf|husband)\b', text, re.I))
    if has_partner_f and not has_partner_m:
        return 'male', 'relationship inference: my girlfriend/gf/wife'
    if has_partner_m and not has_partner_f:
        return 'female', 'relationship inference: my boyfriend/bf/husband'
    return None, 'no clear narrator clue; channel default'


def select_voice(story, default='af_heart', male=None, female=None):
    """Kokoro voice ID for the story's narrator, with the reason."""
    gender, reason = narrator_gender(story)
    return (voice_for(gender, default, male, female) if gender else default), reason


def select_clip(story, default='', male=None, female=None):
    """Chatterbox reference clip for the story's narrator ('' = built-in voice).

    Without a male/female clip for the narrator's gender, the channel's clip is kept:
    a channel sounds like one narrator unless you set both.
    """
    gender, reason = narrator_gender(story)
    chosen = {'male': male, 'female': female}.get(gender) if gender else None
    return (chosen or default or ''), (reason if chosen else reason + '; channel narrator clip')
