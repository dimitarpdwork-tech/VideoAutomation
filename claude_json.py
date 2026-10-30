"""Ask Claude for a JSON object reliably.

The reply comes back through a forced tool call, so it is always a JSON object
rather than free text that has to be parsed. When something still goes wrong,
the error says why: cut off for length, a refusal, or text without a story.
"""
import json


class ReplyError(RuntimeError):
    pass


TOOL = {'name': 'submit', 'description': 'Submit the requested JSON object.',
        'input_schema': {'type': 'object', 'additionalProperties': True}}


def ask(client, model, prompt, system=None, max_tokens=4000):
    """Return the reply as text '<json>{...}</json>' (callers parse it the same way as before)."""
    kwargs = {'model': model, 'max_tokens': max_tokens, 'messages': [{'role': 'user', 'content': prompt}],
              'tools': [TOOL], 'tool_choice': {'type': 'tool', 'name': 'submit'}}
    if system:
        kwargs['system'] = system
    response = client.messages.create(**kwargs)
    stop = getattr(response, 'stop_reason', None)
    blocks = list(getattr(response, 'content', []) or [])
    for block in blocks:
        if getattr(block, 'type', '') == 'tool_use' and isinstance(getattr(block, 'input', None), dict):
            if stop == 'max_tokens':
                raise ReplyError('the reply was cut off because it was too long')
            return '<json>' + json.dumps(block.input, ensure_ascii=False) + '</json>'
    text = ''.join(getattr(block, 'text', '') for block in blocks if getattr(block, 'type', '') == 'text')
    if stop == 'max_tokens':
        raise ReplyError('the reply was cut off because it was too long')
    if stop == 'refusal':
        raise ReplyError('Claude declined to write this one')
    if '{' not in text:
        snippet = ' '.join(text.split())[:160]
        raise ReplyError(f'the reply had no story in it ("{snippet}")' if snippet else 'the reply was empty')
    return text
