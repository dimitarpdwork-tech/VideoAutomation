"""Chatterbox narration plumbing, delivery cues, the story pipeline, images and TikTok export.

Nothing here downloads a model or touches the network: the voice model, image
searches and the Claude API are replaced by small fakes.
"""
import io
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import channel_config as channels
import chatterbox_narrator as cb
import delivery
import image_picker
import make_video
import narrate
import produce_batch
import story_generator
import tiktok_export
import variety
import voice_worker
from voice_selection import select_clip


class DeliveryTests(unittest.TestCase):
    TEXT = 'The lights went out. [pause] Then the phone rang. [whisper] It was my own number. [tense] I answered.'

    def test_strip_leaves_clean_text(self):
        self.assertEqual(delivery.strip(self.TEXT),
                         'The lights went out. Then the phone rang. It was my own number. I answered.')

    def test_segments_carry_cues_to_their_sentence(self):
        rows = delivery.segments(delivery.to_marks(self.TEXT))
        self.assertEqual(rows, [(None, 'The lights went out.', False), (None, 'Then the phone rang.', True),
                                ('whisper', 'It was my own number.', False), ('tense', 'I answered.', False)])

    def test_cues_survive_script_cleanup_but_not_kokoro(self):
        story = {'title': 'Night call', 'text': self.TEXT}
        script, _, _ = narrate.build_script(story, True, True)
        self.assertEqual(delivery.count(script), 3)
        self.assertNotIn('pause', script)            # cues travel as private-use marks, not words
        self.assertEqual(delivery.remove_marks(script),
                         'Night call. The lights went out. Then the phone rang. It was my own number. I answered.')

    def test_pieces_group_sentences_and_respect_cues(self):
        script = delivery.to_marks('One. Two. Three. [tense] Four. ' + 'Five, ' * 80 + 'six.')
        rows = cb.pieces(script, limit=60)
        self.assertEqual(rows[0], (None, 'One. Two. Three.', False))
        self.assertEqual(rows[1][0], 'tense')
        self.assertTrue(all(len(text) <= 60 for _, text, _ in rows))
        joined = ' '.join(text for _, text, _ in rows)
        self.assertEqual(joined.split(), delivery.remove_marks(script).split())   # nothing lost or repeated

    def test_metadata_and_counts_ignore_cues(self):
        import metadata
        self.assertEqual(metadata.hook({'text': '[tense] It moved. [pause] Twice.'}), 'It moved. Twice.')
        self.assertEqual(produce_batch.word_count(delivery.strip('[pause] Two words')), 2)


class VoicePickTests(unittest.TestCase):
    def test_clip_follows_narrator_gender_only_when_set(self):
        story = {'title': 'x', 'text': 'My husband never locks the door.'}
        self.assertEqual(select_clip(story, 'deep.wav')[0], 'deep.wav')
        self.assertEqual(select_clip(story, 'deep.wav', female='soft.wav')[0], 'soft.wav')
        self.assertEqual(select_clip({'title': 'x', 'text': 'It rained.'}, '', 'm.wav', 'f.wav')[0], '')


class HookTests(unittest.TestCase):
    def test_slow_and_long_openings_are_flagged(self):
        self.assertIn('slow', variety.hook_problem('So this happened last year. It was odd.'))
        self.assertIn('too long', variety.hook_problem(' '.join(['word'] * 40) + '.'))
        self.assertIsNone(variety.hook_problem('[tense] The baby monitor whispered my name. I live alone.'))


class WorkerProtocolTests(unittest.TestCase):
    """The production side of the Chatterbox worker, against a stand-in process."""
    FAKE = textwrap.dedent('''
        import json, sys
        for line in sys.stdin:
            request = json.loads(line)
            if request['cmd'] == 'quit':
                break
            args = request['args']
            print('loading...', file=sys.stderr, flush=True)
            if args['clip'] == 'crash.wav':
                sys.exit(3)
            if args['clip'] == 'review.wav':
                print('@@RESULT ' + json.dumps({'ok': False, 'error': 'Potential repeated sentences need review', 'needs_review': True}), flush=True)
                continue
            print('progress line', flush=True)
            print('@@RESULT ' + json.dumps({'ok': True, 'metadata': {'duration_seconds': 12.5, 'clip': args['clip']}}), flush=True)
    ''')

    def worker(self, folder):
        script = Path(folder) / 'fake_worker.py'
        script.write_text(self.FAKE)
        worker = voice_worker.VoiceWorker()
        worker._start = lambda: setattr(worker, 'process', subprocess.Popen(
            [sys.executable, '-u', str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8'))
        return worker

    def test_success_review_and_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = self.worker(folder)
            self.assertEqual(worker.narrate(clip='a.wav', story_path=Path('x.json'))['clip'], 'a.wav')
            first = worker.process
            self.assertEqual(worker.narrate(clip='b.wav')['duration_seconds'], 12.5)
            self.assertIs(worker.process, first)          # the model stays loaded between stories
            with self.assertRaises(voice_worker.VoiceError) as caught:
                worker.narrate(clip='review.wav')
            self.assertTrue(caught.exception.needs_review)
            with self.assertRaisesRegex(voice_worker.VoiceError, 'stopped unexpectedly'):
                worker.narrate(clip='crash.wav')
            self.assertEqual(worker.narrate(clip='c.wav')['clip'], 'c.wav')   # restarts after a crash
            worker.close()

    def test_missing_install_is_explained(self):
        with patch.object(voice_worker, 'venv_python', return_value=Path('/nonexistent/python')):
            with self.assertRaisesRegex(voice_worker.VoiceError, 'setup_voice'):
                voice_worker.VoiceWorker().narrate(clip='')


class GeneratorPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.patches = [patch.object(channels, 'ROOT', self.root), patch.object(channels, 'CHANNELS', self.root / 'channels'),
                        patch.object(story_generator, 'ROOT', self.root), patch.object(story_generator, 'CHANNELS', self.root / 'channels')]
        for p in self.patches:
            p.start()
        channels.create_channel('night', 'Night', 'horror')
        self.stories = channels.paths('night')['stories']
        self.source = ('I work nights at a parking garage downtown. Level four has been closed for a year because of '
                       'cracks in the concrete. Last Tuesday the camera on level four showed a car with its lights on. ') * 3
        channels.write_json(self.stories / 'r1.json', {'id': 'r1', 'title': 'The closed level of the garage', 'text': self.source,
                                                       'text_source': 'post_page', 'score': 12000, 'url': 'https://reddit.com/r/x'})
        channels.write_json(self.stories / 'r2.json', {'id': 'r2', 'title': 'Low score story', 'text': 'Short source text here. ' * 20,
                                                       'text_source': 'post_page', 'score': 10})

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    @staticmethod
    def reply(**data):
        return SimpleNamespace(content=[SimpleNamespace(type='text', text='<json>' + json.dumps(data) + '</json>')])

    def test_concept_mode_rewrites_the_top_story_once(self):
        retelling = {'title': 'Level four', 'text': self.source, 'narrator': 'male'}
        original = {'title': 'The lighthouse log that kept writing itself',
                    'text': ('[tense] The logbook had a new entry, and I was the only keeper on the island. '
                             + ' '.join(f'Night {i}, the lamp turned toward the cliffs instead of the sea.' for i in range(12))),
                    'narrator': 'female', 'image_query': 'lighthouse storm night', 'concept': 'a place that should be empty shows activity'}
        client = MagicMock()
        client.messages.create.side_effect = [self.reply(**retelling), self.reply(**original)]
        logs = []
        created = story_generator.generate('night', 1, client=client, log=logs.append)
        self.assertEqual(len(created), 1)
        prompt = client.messages.create.call_args_list[0].kwargs['messages'][0]['content']
        self.assertIn('ONLY for its core concept', prompt)
        self.assertIn('Level four has been closed', prompt)          # the source text is the concept input
        self.assertIn('horror', client.messages.create.call_args_list[0].kwargs['system'].lower())
        self.assertTrue(any('rejected by originality check' in line for line in logs))   # the retelling was rejected
        story = created[0]
        self.assertEqual((story['concept_source'], story['mode'], story['image_query']), ('r1', 'concept', 'lighthouse storm night'))
        self.assertNotIn('url', story)
        self.assertEqual(channels.read_json(self.stories / 'r1.json')['concept_used_by'], [story['id']])
        self.assertEqual(story_generator.concept_sources('night')[0][1]['id'], 'r2')   # r1 is not offered again

    def test_overused_cues_are_dropped_and_slow_hooks_rejected(self):
        heavy = ' '.join('[tense] It moved.' for _ in range(40))
        self.assertEqual(delivery.count(story_generator.tidy_cues(heavy)), 0)
        with self.assertRaisesRegex(story_generator.GenerationError, 'slow'):
            story_generator.parse_reply('<json>' + json.dumps({'title': 'T', 'text': 'So this happened. ' * 30}) + '</json>', 'short')

    def test_long_stories_are_written_chapter_by_chapter(self):
        config = channels.load_channel('night')
        channels.write_json(channels.CHANNELS / 'night/config.json', {**config, 'video_format': 'long', 'long_target_words': 3000,
                                                                       'full_min_words': 2000, 'full_max_words': 25000})
        outline = {'title': 'A winter in a mountain monastery', 'premise': 'Calm.', 'narrator': 'male', 'image_query': 'snowy monastery',
                   'chapters': [{'heading': f'Part {i}', 'summary': 'Quiet days.'} for i in range(1, 3)]}
        chapter = lambda n: SimpleNamespace(content=[SimpleNamespace(type='text', text='<text>' + (
            f'The bells rang softly for chapter {n}. ' + ' '.join(f'Snow fell on stone path number {n}{i} by the gate.' for i in range(140))) + '</text>')])
        client = MagicMock()
        client.messages.create.side_effect = [self.reply(**outline), chapter(1), chapter(2)]
        created = story_generator.generate('night', 1, client=client, log=lambda m: None)
        self.assertEqual(client.messages.create.call_count, 3)
        self.assertEqual(created[0]['mode'], 'long')
        self.assertGreater(len(created[0]['text'].split()), 2000)
        self.assertIn('previous chapter ended', client.messages.create.call_args_list[2].kwargs['messages'][0]['content'])


def jpeg(width=2000, height=1200):
    from PIL import Image
    data = io.BytesIO()
    Image.new('RGB', (width, height), (40, 40, 60)).save(data, 'JPEG')
    return data.getvalue()


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        shared = Path(self.temp.name)
        self.patches = [patch.object(image_picker, 'IMAGES', shared / 'images'), patch.object(image_picker, 'USED', shared / 'used.json'),
                        patch.object(image_picker, '_get', lambda url, headers=None, limit=0: (jpeg(), 'image/jpeg'))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_each_image_is_used_once_and_recorded(self):
        results = [{'id': f'pexels:{i}', 'url': f'https://x/{i}.jpg', 'page': f'https://pexels.com/{i}', 'author': 'A',
                    'license': 'Pexels License', 'width': 4000, 'height': 2600} for i in (1, 2)]
        searched = []
        searchers = [('Pexels', lambda q: searched.append(q) or results)]
        config = {'image_keywords': ['dark forest'], 'story_category': 'Horror fiction'}
        first = image_picker.pick({'image_query': 'old barn night'}, config, 'night', 'story_a', searchers=searchers, log=lambda m: None)
        second = image_picker.pick({}, config, 'night', 'story_b', searchers=searchers, log=lambda m: None)
        self.assertEqual(searched[0], 'old barn night')
        self.assertEqual(json.loads(first.with_suffix('.json').read_text())['id'], 'pexels:1')
        self.assertEqual(json.loads(second.with_suffix('.json').read_text())['id'], 'pexels:2')
        self.assertEqual(image_picker.pick({}, config, 'night', 'story_a', searchers=[]), first)   # reused for the same story

    def test_clear_error_when_nothing_is_found(self):
        def offline(query):
            raise OSError('no network')
        with self.assertRaisesRegex(image_picker.NoImage, 'Pexels API key'):
            image_picker.pick({}, {}, 'night', 's', searchers=[('Openverse', offline)], log=lambda m: None)


class RenderTests(unittest.TestCase):
    def test_image_mode_renders_a_real_video(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'n').mkdir()
            import math, struct
            with wave.open(str(folder / 'n/narration.wav'), 'wb') as audio:
                audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000)
                audio.writeframes(b''.join(struct.pack('<h', int(8000 * math.sin(i / 12))) for i in range(48000)))
            (folder / 'n/timings.json').write_text(json.dumps([{'word': 'Hello.', 'start': 0.1, 'end': 0.6}]))
            (folder / 'n/metadata.json').write_text(json.dumps({'duration_seconds': 2.0}))
            (folder / 'photo.jpg').write_bytes(jpeg(2400, 1600))
            argv = ['make_video.py', '--narration', str(folder / 'n'), '--image', str(folder / 'photo.jpg'),
                    '--destination', str(folder / 'out'), '--filename', 'x.mp4', '--format', 'vertical', '--progress-bar',
                    '--title-card', 'Part 1', '--end-text', 'Part 2 is on my profile', '--end-seconds', '1', '--encoder', 'libx264']
            with patch.object(sys, 'argv', argv):
                make_video.main()
            produce_batch.validate(folder / 'out/x.mp4', 2.0)
            self.assertIn('1080x1920', make_video.probe(folder / 'out/x.mp4'))
            self.assertFalse(list((folder / 'out').glob('_*')))   # the prepared image and vignette are cleaned up

    def test_end_card_is_in_captions(self):
        words = [{'word': 'Hi.', 'start': 0, 'end': 0.5}]
        ass, _ = make_video.build_captions(words, 'vertical', 'phrases', end_text='Part 2 is on my profile', duration=70)
        self.assertIn('0:01:06.00,0:01:11.00,Title', ass)


class TikTokTests(unittest.TestCase):
    def test_parts_are_cut_at_sentence_ends_and_never_too_short(self):
        words = []
        for second in range(0, 300, 5):
            words += [{'word': 'Something', 'start': second, 'end': second + 2}, {'word': 'happened.', 'start': second + 2, 'end': second + 4.5}]
        parts = tiktok_export.split(words, 300.0, 75)
        self.assertEqual(parts[0][0], 0.0)
        self.assertEqual(parts[-1][1], 300.0)
        self.assertTrue(all(end - start >= tiktok_export.MIN_PART for start, end in parts))
        self.assertTrue(all(abs(cut % 5 - 4.75) < 0.01 for _, cut in parts[:-1]))   # between sentences
        self.assertEqual(tiktok_export.split(words[:20], 50.0, 75), [(0.0, 50.0)])

    def test_export_cuts_narration_and_records_parts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            with patch.object(channels, 'ROOT', root), patch.object(channels, 'CHANNELS', root / 'channels'):
                channels.create_channel('night', 'Night', 'horror')
                cp = channels.paths('night')
                narration = cp['narrations'] / 'gen_1' / 'b1' / 'full'
                narration.mkdir(parents=True)
                with wave.open(str(narration / 'narration.wav'), 'wb') as audio:
                    audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000)
                    audio.writeframes(b'\x00\x00' * 24000 * 200)
                words = [{'word': 'Then.' if i % 4 == 3 else 'and', 'start': i * 0.5, 'end': i * 0.5 + 0.4} for i in range(400)]
                channels.write_json(narration / 'timings.json', words)
                channels.write_json(narration / 'metadata.json', {'duration_seconds': 200.0})
                (cp['videos'] / 'b1').mkdir(parents=True)
                item = {'name': '01_gen_1', 'story': 'gen_1.json', 'used_story': 'gen_1_used.json', 'title': 'The garage',
                        'format': 'funnel', 'status': 'complete', 'review': 'approved', 'image': 'output/shared/images/x.jpg'}
                channels.write_json(cp['stories'] / 'gen_1_used.json', {'title': 'The garage', 'text': 'It moved. Then it stopped.'})
                rendered = []

                def render(part_dir, item, config, dest, filename, title, end_text):
                    rendered.append((filename, title, end_text, json.loads((part_dir / 'metadata.json').read_text())['duration_seconds']))
                    (dest / filename).write_bytes(b'mp4')
                with patch.object(tiktok_export, 'render_part', render), patch.object(tiktok_export.produce_batch, 'validate', lambda *a: None):
                    parts = tiktok_export.export_item(item, 'b1', channels.load_channel('night'), cp, log=lambda m: None)
                self.assertEqual(len(parts), 3)               # 200 s at a 75 s target
                self.assertEqual(rendered[0][1:3], ('The garage · Part 1', 'Part 2 is on my profile'))
                self.assertIsNone(rendered[-1][2])
                self.assertAlmostEqual(sum(r[3] for r in rendered), 200.0, places=1)
                caption = (cp['videos'] / 'b1/tiktok/01_gen_1_part1.txt').read_text()
                self.assertIn('The garage (Part 1/3)', caption)
                self.assertIn('#horrortok', caption)
                part_words = json.loads((narration.parent / 'tiktok/part2/timings.json').read_text())
                self.assertGreaterEqual(part_words[0]['start'], 0)


class ProductionWithChatterboxTests(unittest.TestCase):
    def test_batch_uses_worker_image_and_keeps_warnings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            patches = [patch.object(channels, 'ROOT', root), patch.object(channels, 'CHANNELS', root / 'channels'),
                       patch.object(channels, 'SHARED', root / 'output/shared'), patch.object(produce_batch, 'SHARED', root / 'output/shared'),
                       patch.object(produce_batch, 'ROOT', root)]
            for p in patches:
                p.start()
            try:
                channels.create_channel('night', 'Night', 'horror')
                (root / 'backgrounds').mkdir()
                cp = channels.paths('night')
                channels.write_json(cp['stories'] / 'gen_1.json', {'id': 'gen_1', 'title': 'The garage', 'text_source': 'generated',
                                                                   'text': '[tense] It moved. ' + 'The car sat there. ' * 300,
                                                                   'image_query': 'garage night'})
                calls = []

                def narrate_with_worker(**args):
                    calls.append(args)
                    out = Path(args['output'])
                    out.mkdir(parents=True, exist_ok=True)
                    seconds = 40 if out.name == 'teaser' else 300
                    channels.write_json(out / 'metadata.json', {'duration_seconds': seconds, 'quality_warnings': ['Check the line "x"']})
                    return channels.read_json(out / 'metadata.json')
                image = root / 'output/shared/images/night/gen_1.jpg'
                image.parent.mkdir(parents=True)
                image.write_bytes(jpeg())
                commands = []

                def run(command, **kwargs):
                    commands.append(command)
                    if '--destination' in command:
                        dest = Path(command[command.index('--destination') + 1])
                        name = command[command.index('--filename') + 1] if '--filename' in command else command[command.index('--name') + 1] + '.mp4'
                        (dest / name).write_bytes(b'video')
                    return SimpleNamespace(returncode=0)
                with patch.object(voice_worker, 'installed', return_value=True), \
                        patch.object(voice_worker.VoiceWorker, 'narrate', side_effect=narrate_with_worker), \
                        patch.object(produce_batch.image_picker, 'pick', return_value=image), \
                        patch.object(produce_batch.subprocess, 'run', run), patch.object(produce_batch, 'validate', lambda *a, **k: None), \
                        patch.object(sys, 'argv', ['produce_batch.py', '--channel', 'night', '--count', '1', '--batch', 'b1']):
                    produce_batch.main()
                plan = channels.read_json(cp['videos'] / 'b1/batch.json')
                self.assertEqual(plan[0]['status'], 'complete', plan[0].get('reason'))
                self.assertEqual(plan[0]['voice'], 'chatterbox:built-in')
                self.assertEqual(plan[0]['image'], 'output/shared/images/night/gen_1.jpg')
                self.assertEqual(plan[0]['narration_warnings'], ['Check the line "x"'] * 2)   # full + teaser
                self.assertEqual({c['expressiveness'] for c in calls}, {0.6})
                render = next(c for c in commands if 'make_video.py' in str(c[1]))
                self.assertIn('--image', render)
                thumb = next(c for c in commands if 'thumbnail.py' in str(c[1]))
                self.assertIn('--image', thumb)
            finally:
                for p in reversed(patches):
                    p.stop()


class RetentionTests(unittest.TestCase):
    def test_retention_is_added_per_video(self):
        import youtube_insights
        report = {'columnHeaders': [{'name': n} for n in ('video', 'views', 'averageViewDuration', 'averageViewPercentage')],
                  'rows': [['v1', 100, 41, 63.27]]}
        api = MagicMock()
        api.reports.return_value.query.return_value.execute.return_value = report
        build = MagicMock()
        build.return_value.__enter__.return_value = api
        videos = {'v1': {'viewCount': 100}, 'v2': {'viewCount': 3}}
        with patch.object(youtube_insights, 'build', build):
            youtube_insights.add_retention(object(), videos)
        self.assertEqual(videos['v1']['averageViewPercentage'], 63.3)
        self.assertEqual(videos['v1']['averageViewDuration'], 41)
        self.assertNotIn('averageViewPercentage', videos['v2'])
        self.assertEqual(api.reports.return_value.query.call_args.kwargs['filters'], 'video==v1,v2')


if __name__ == '__main__':
    unittest.main()


class VoiceSampleTests(unittest.TestCase):
    def test_samples_run_end_to_end_with_a_stand_in_voice(self):
        import voice_samples

        def fake_narrate():
            out = Path(sys.argv[sys.argv.index('--output') + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / 'narration.wav').write_bytes(b'RIFF')
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            with patch.object(voice_samples.cb, 'VOICES', folder / 'voices'), \
                    patch.object(voice_samples.cb, 'SAMPLES', folder / 'samples'), \
                    patch('narrate.main', fake_narrate), patch.object(voice_samples.voice_worker, 'installed', return_value=False):
                voice_samples.main()
            self.assertEqual(len(list((folder / 'voices').glob('starter_*.wav'))), 5)
            index = json.loads((folder / 'samples/index.json').read_text())
            self.assertEqual(len(index), 5)
