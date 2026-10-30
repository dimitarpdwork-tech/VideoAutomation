"""Hear a narrator with each voice character (natural, deep, uncanny, tape, room).

Takes one narrator sample and writes output/shared/voice_samples/character_<name>.wav
for every character, so the dashboard can play them side by side. Takes seconds.

Run: python voice_character_samples.py chatterbox_starter_deep_male.wav
"""
import argparse
import re
import subprocess
import sys

import imageio_ffmpeg

import make_video
from channel_config import SHARED, write_json

SAMPLES = SHARED / 'voice_samples'


def render(source, character, target):
    graph = (make_video.voice_character(character, '[0:a]', '[voice]')
             + f';[voice]{make_video.CLEAN},loudnorm=I=-16:TP=-1.5:LRA=11,{make_video.CLEAN}[a]')
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source),
                    '-filter_complex', graph, '-map', '[a]', '-ar', '48000', '-c:a', 'pcm_s16le', str(target)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('sample', help='A file name in output/shared/voice_samples')
    args = parser.parse_args()
    if not re.fullmatch(r'(kokoro|chatterbox)_[A-Za-z0-9_ .-]{1,80}\.wav', args.sample):
        parser.error('choose a narrator sample file')
    source = SAMPLES / args.sample
    if not source.is_file():
        sys.exit(f'{args.sample} was not found; make the voice samples first.')
    for character in make_video.VOICE_CHARACTERS:
        render(source, character, SAMPLES / f'character_{character}.wav')
        print(f'Made the "{character}" preview.', flush=True)
    write_json(SAMPLES / 'characters.json', {'source': args.sample, 'characters': list(make_video.VOICE_CHARACTERS)})


if __name__ == '__main__':
    main()
