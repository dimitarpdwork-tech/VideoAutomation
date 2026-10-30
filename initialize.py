"""Create local folders and an unconnected profile without overwriting data.

Also writes output/shared/settings_schema.json: the channel defaults, presets and
allowed values, which the dashboard reads so it never disagrees with Python.
"""
from channel_config import (ROOT, CHANNELS, SHARED, CHANNEL_DEFAULTS, PRESETS, GRADES, FORMATS,
                            PRIVACY_OPTIONS, create_channel, write_json)


def write_schema():
    write_json(SHARED / 'settings_schema.json', {
        'defaults': CHANNEL_DEFAULTS, 'presets': PRESETS, 'grades': list(GRADES),
        'formats': list(FORMATS), 'privacy': list(PRIVACY_OPTIONS)})


def initialize():
    for name in ('credentials', 'backgrounds', 'music', 'stories', 'videos', 'narrations', 'output', 'voices'):
        (ROOT / name).mkdir(exist_ok=True)
    write_schema()
    if not (CHANNELS / 'main' / 'config.json').exists():
        create_channel('main', 'Main channel')
    print('Local workspace ready. No accounts connected or automation enabled.')


if __name__ == '__main__':
    initialize()
