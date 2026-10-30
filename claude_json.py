"""Ask Claude for a JSON object reliably.

Uses Claude's structured outputs (output_config.format with a JSON schema), so
the reply always matches the schema. If the API refuses the schema for the
chosen model, it asks once more without it and reads the JSON from the text.
When something goes wrong, the error says why: cut off for length, declined,
or text without a story.
"""
import json


class ReplyError(RuntimeError):
    pass


_SCHEMALESS_MODELS = set()   # models that refused structured outputs in this run


def strict(properties, required=None):
    """A JSON schema object as structured outputs require: no extra properties."""
    return {'type': 'object', 'properties': properties, 'required': list(required or properties),
            'additionalProperties': False}


def _request(client, model, prompt, system, max_tokens, schema):
    kwargs = {'model': model, 'max_tokens': max_tokens, 'messages': [{'role': 'user', 'content': prompt}]}
    if system:
        kwargs['system'] = system
    if schema is not None:
        # extra_body works with every version of the Python SDK.
        kwargs['extra_body'] = {'output_config': {'format': {'type': 'json_schema', 'schema': schema}}}
    return send(client, kwargs)


def send(client, kwargs):
    """Stream real API calls (the SDK requires it for large max_tokens); plain create() for test doubles."""
    try:
        import anthropic
        real = isinstance(client, anthropic.Anthropic)
    except ImportError:
        real = False
    if real:
        with client.messages.stream(**kwargs) as stream:
            return stream.get_final_message()
    return client.messages.create(**kwargs)


def cut_off(response):
    used = getattr(getattr(response, 'usage', None), 'output_tokens', None)
    return ReplyError('the reply was cut off because it was too long' + (f' ({used:,} tokens)' if used else ''))


def ask(client, model, prompt, system=None, max_tokens=4000, schema=None):
    """Return the reply text, which holds one JSON object."""
    use_schema = schema if model not in _SCHEMALESS_MODELS else None
    try:
        response = _request(client, model, prompt, system, max_tokens, use_schema)
    except Exception as exc:  # the API refused the schema: ask without it
        message = str(exc)
        if use_schema is None or getattr(exc, 'status_code', None) != 400 or not any(
                word in message for word in ('output_config', 'json_schema', 'schema', 'format')):
            raise
        _SCHEMALESS_MODELS.add(model)
        response = _request(client, model, prompt, system, max_tokens, None)
    stop = getattr(response, 'stop_reason', None)
    blocks = list(getattr(response, 'content', []) or [])
    text = ''.join(getattr(block, 'text', '') for block in blocks if getattr(block, 'type', '') == 'text')
    if stop == 'max_tokens':
        raise cut_off(response)
    if stop == 'refusal':
        raise ReplyError('Claude declined to write this one')
    if '{' not in text:
        snippet = ' '.join(text.split())[:160]
        raise ReplyError(f'the reply had no story in it ("{snippet}")' if snippet else 'the reply was empty')
    if text.lstrip().startswith('{'):
        return '<json>' + text.strip() + '</json>'
    return text
