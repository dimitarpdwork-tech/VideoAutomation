"""The channel's narrator persona: one character for the voice, the words and the delivery.

A persona is a short character sheet stored in the channel's settings:

    name        what the host is called behind the scenes ("The Caretaker")
    identity    who they are, in a sentence or two
    speech      how they talk: vocabulary, sentence length, rhythm, habits, what they never do
    intro       how they open a story, after the cold open
    outro       how they sign off (a recurring line works well)
    asides      none | rare | some: how often they step out of the story to comment
    gender      male | female | any: the voice, so the stories' first-person narrator matches
    age         an age range for the stories' narrator, e.g. "50-75"

The story generator writes every story for this character, and production
frames full and long videos as: cold open (the story's first paragraph, the
hook), the host's intro, the rest of the story, the host's sign-off. Shorts
and teasers stay all story: no intro, no sign-off.

Draft one from a voice description with Claude:
    python persona.py --channel main --clip designed_old_caretaker.wav
"""
import argparse
import json
import re

import delivery
from channel_config import ROOT, load_channel, update_json, CHANNELS

FIELDS = ('name', 'identity', 'speech', 'intro', 'outro')
ASIDES = {'none': 0, 'rare': 2, 'some': 5}
INTRO_WORDS, OUTRO_WORDS = 60, 45


def active(config):
    persona = config.get('persona')
    return persona if isinstance(persona, dict) and persona.get('identity') else None


def prompt_block(persona):
    """The persona, as instructions for the story writer."""
    lines = [f"Narrator persona ({persona.get('name') or 'the host'}): {persona.get('identity', '').strip()}"]
    if persona.get('speech'):
        lines.append(f"How the narrator talks: {persona['speech'].strip()}")
    gender, age = persona.get('gender') or 'any', (persona.get('age') or '').strip()
    if gender in ('male', 'female') or age:
        who = ' '.join(filter(None, [f'a {gender}' if gender in ('male', 'female') else 'a', 'first-person narrator',
                                     f'aged about {age}' if age else '']))
        lines.append(f"Every story is told by {who}, so the story fits the voice reading it. Choose the narrator's job, "
                     "life and situation to suit that age; never write a teenager's or a young person's diary for this voice.")
    lines.append('Write the whole story in this narrator\'s vocabulary and rhythm, so voice, words and delivery are one character.')
    count = ASIDES.get(persona.get('asides') or 'rare', 2)
    if count:
        lines.append(f'The host may step out of the story at most {count} time(s) for one short sentence of their own '
                     '(a dry remark, a warning to the listener), marked by starting that sentence with [aside]. '
                     'Only at a natural break, never in the middle of a scene, and never explaining the twist.')
    else:
        lines.append('The host never interrupts the story.')
    return '\n'.join(lines)


def frame_fields(persona):
    """Extra JSON fields the writer returns when a persona is active (full and long videos)."""
    intro = persona.get('intro') or 'a short welcome in the host\'s voice'
    outro = persona.get('outro') or 'a short sign-off in the host\'s voice'
    return [f'"intro": 1-3 sentences in the host\'s voice, spoken right after the opening paragraph ({intro}); '
            f'under {INTRO_WORDS} words; it must not repeat or explain the hook',
            f'"outro": 1-2 sentences in the host\'s voice after the story ends ({outro}); under {OUTRO_WORDS} words; '
            'no requests to like or subscribe']


def clean_line(text, limit):
    text = re.sub(r'\s+', ' ', delivery.strip(str(text or ''))).strip()
    words = text.split()
    if len(words) > limit:
        text = ' '.join(words[:limit]).rstrip(',;:') + '.'
    return text


def limit_asides(text, persona):
    """Keep at most the persona's number of [aside] lines; drop the rest of the markers."""
    allowed = ASIDES.get((persona or {}).get('asides') or 'none', 0)
    seen = 0

    def keep(match):
        nonlocal seen
        seen += 1
        return match.group(0) if seen <= allowed else ''
    return re.sub(r'\[\s*aside\s*\]\s*', keep, text, flags=re.I)


def framed_text(story):
    """Story text with the host's intro after the cold open and the sign-off at the end."""
    text = story.get('text', '').strip()
    intro, outro = (story.get('intro') or '').strip(), (story.get('outro') or '').strip()
    if not intro and not outro:
        return text
    paragraphs = [p for p in re.split(r'\n\s*\n', text) if p.strip()]
    if len(paragraphs) > 1:
        opening, rest = paragraphs[0], '\n\n'.join(paragraphs[1:])
    else:  # one block: the first two sentences are the cold open
        sentences = re.split(r'(?<=[.!?…])\s+', text)
        opening, rest = ' '.join(sentences[:2]), ' '.join(sentences[2:])
    parts = [opening]
    if intro:
        parts.append('[pause] ' + intro)
    parts.append(('[pause] ' if intro else '') + rest)
    if outro:
        parts.append('[pause] ' + outro)
    return '\n\n'.join(p for p in parts if p.strip())


DRAFT_PROMPT = """You are creating the narrator persona for a narrated horror-story YouTube channel called "{channel}".
The narrator's voice was designed from this description:
"{description}"

Invent the character behind that voice: who they are, how they talk, how they open and close each story. They host
original fiction (never claim the stories are true). Keep it subtle and atmospheric, never campy. The host must not
name a real person or claim a real-world identity.

Reply with one JSON object inside <json></json> tags with these fields:
"name": a short behind-the-scenes label such as "The Caretaker",
"identity": 1-2 sentences on who the host is,
"speech": 2-3 sentences on vocabulary, sentence length, rhythm, verbal habits and what they never do,
"intro": how they open a story after the cold open, with one example line in quotes,
"outro": how they sign off, with a recurring sign-off line in quotes,
"asides": "none", "rare" or "some",
"gender": "male", "female" or "any" (match the voice),
"age": an age range for the narrators of the stories that fits the voice, like "50-75",
"expressiveness": a number from 0.3 to 0.8 (how theatrical the reading should be; calm voices 0.35-0.5),
"voice_character": one of "natural", "deep", "uncanny", "tape", "room"."""


def draft(description, config, client):
    """A persona dict drafted by Claude from the voice description."""
    response = client.messages.create(
        model=config.get('generator_model') or 'claude-sonnet-5-5', max_tokens=1200,
        messages=[{'role': 'user', 'content': DRAFT_PROMPT.format(channel=config.get('name') or 'the channel',
                                                                   description=description)}])
    text = ''.join(block.text for block in response.content if getattr(block, 'type', '') == 'text')
    match = re.search(r'<json>\s*(\{.*\})\s*</json>', text, re.S) or re.search(r'(\{.*\})', text, re.S)
    if not match:
        raise RuntimeError('The reply contained no persona.')
    data = json.loads(match.group(1))
    persona = {key: str(data.get(key) or '').strip()[:600] for key in FIELDS}
    persona['asides'] = data.get('asides') if data.get('asides') in ASIDES else 'rare'
    persona['gender'] = data.get('gender') if data.get('gender') in ('male', 'female', 'any') else 'any'
    persona['age'] = re.sub(r'[^0-9\- ]', '', str(data.get('age') or ''))[:12]
    persona['voice_description'] = description[:500]
    extras = {}
    try:
        extras['expressiveness'] = min(0.8, max(0.3, float(data.get('expressiveness'))))
    except (TypeError, ValueError):
        pass
    if data.get('voice_character') in ('natural', 'deep', 'uncanny', 'tape', 'room'):
        extras['voice_character'] = data['voice_character']
    if not persona['identity']:
        raise RuntimeError('The persona came back empty; try again.')
    return persona, extras


def main():
    import story_generator
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--channel', default='main')
    parser.add_argument('--clip', help='A designed narrator clip in voices/ (its description is used)')
    parser.add_argument('--description', help='Or describe the narrator yourself')
    args = parser.parse_args()
    config = load_channel(args.channel)
    description = args.description
    if args.clip:
        sidecar = ROOT / 'voices' / (args.clip.rsplit('.', 1)[0] + '.json')
        try:
            description = json.loads(sidecar.read_text(encoding='utf-8')).get('description')
        except (OSError, json.JSONDecodeError):
            description = None
    if not description:
        raise SystemExit('No voice description: design the voice in the dashboard first, or describe the narrator.')
    import anthropic
    key = story_generator.api_key()
    if not key:
        raise SystemExit('Add your Claude API key in Settings first.')
    persona, extras = draft(description, config, anthropic.Anthropic(api_key=key))
    if args.clip:
        persona['voice_clip'] = args.clip

    def save(current):
        current['persona'] = persona
        current.update(extras)
    update_json(CHANNELS / args.channel / 'config.json', save, {})
    print(f'Persona "{persona["name"] or "host"}" saved: {persona["identity"]}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(f'Persona drafting stopped: {exc}')
