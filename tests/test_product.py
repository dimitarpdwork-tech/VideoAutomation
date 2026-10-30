"""Offline tests for metadata, settings defaults, review skipping and YouTube scheduling."""
import json
import random
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import channel_config as channels
import make_video
import metadata
import preschedule
import produce_batch
import upload_next

STORY = {'id': 'abc', 'title': 'My neighbour built a moat. ', 'author': 'storyteller',
         'url': 'https://www.reddit.com/r/stories/comments/abc/moat/',
         'text': 'It started with a shovel. Then came the water. ' + 'Nobody said anything for weeks. ' * 30}


class MetadataTests(unittest.TestCase):
    def test_description_has_hook_credit_and_hashtags(self):
        meta = metadata.build(STORY, channels.with_defaults({}))
        self.assertEqual(meta['title'], 'My neighbour built a moat')
        self.assertTrue(meta['description'].startswith('It started with a shovel. Then came the water.'))
        self.assertIn('Original story by u/storyteller: https://www.reddit.com/r/stories/comments/abc/moat/', meta['description'])
        self.assertIn('#shorts #storytime', meta['description'])
        self.assertEqual(meta['tags'], ['story', 'storytime', 'shorts'])

    def test_original_story_has_no_credit_line(self):
        meta = metadata.build({'title': 'Mine', 'text': 'I wrote this. It is mine.'}, channels.with_defaults({}))
        self.assertNotIn('Original story', meta['description'])
        self.assertNotIn('\n\n\n', meta['description'])

    def test_credit_can_be_turned_off_and_bad_template_falls_back(self):
        config = channels.with_defaults({'credit_source': False, 'description_template': '{hook} {nope}'})
        meta = metadata.build(STORY, config)
        self.assertNotIn('Original story', meta['description'])
        self.assertIn('#shorts', meta['description'])

    def test_limits(self):
        long = {'title': 'word ' * 40, 'text': 'x' * 900}
        config = channels.with_defaults({'hashtags': [f'#tag{i}' for i in range(30)], 'tags': ['t' * 100] * 10})
        meta = metadata.build(long, config)
        self.assertLessEqual(len(meta['title']), 100)
        self.assertEqual(meta['description'].count('#tag'), 15)
        self.assertLessEqual(sum(len(t) + 1 for t in meta['tags']), 450)
        self.assertEqual(metadata.normalize_hashtags(['shorts', '#Shorts', '#a b']), ['#shorts', '#ab'])


class SettingsTests(unittest.TestCase):
    def test_old_profiles_receive_new_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(channels, 'CHANNELS', root):
                channels.write_json(root / 'old/config.json', {'id': 'old', 'name': 'Old', 'voice': 'am_adam',
                                                               'schedule': {'enabled': True, 'timezone': 'UTC'}})
                config = channels.load_channel('old')
        self.assertEqual(config['voice'], 'am_adam')
        self.assertEqual(config['privacy'], 'public')
        self.assertEqual(config['schedule']['times'], ['10:00', '18:00'])
        self.assertTrue(config['schedule']['enabled'])
        self.assertIsNot(channels.with_defaults({})['hashtags'], channels.CHANNEL_DEFAULTS['hashtags'])

    def test_venv_python_matches_platform(self):
        path = channels.venv_python('.venv')
        self.assertEqual(path.parent.name, 'Scripts' if channels.os.name == 'nt' else 'bin')


class UploadBodyTests(unittest.TestCase):
    def test_privacy_metadata_and_publish_time(self):
        item = {'description': 'Hook\n\n#shorts', 'tags': ['story']}
        body = upload_next.video_body(item, 'Title', channels.with_defaults({'privacy': 'unlisted'}))
        self.assertEqual(body['status']['privacyStatus'], 'unlisted')
        self.assertEqual(body['snippet']['description'], 'Hook\n\n#shorts')
        self.assertEqual(body['snippet']['tags'], ['story'])
        self.assertEqual(body['snippet']['categoryId'], '24')
        scheduled = upload_next.video_body({}, 'Title', channels.with_defaults({}), '2030-01-01T10:00:00Z')
        self.assertEqual(scheduled['status'], {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False,
                                               'publishAt': '2030-01-01T10:00:00Z'})
        self.assertEqual(scheduled['snippet']['description'], upload_next.DEFAULT_DESCRIPTION)
        with self.assertRaises(RuntimeError):
            upload_next.video_body({}, 'T', {'privacy': 'everyone'})

    def test_publish_at_parsing(self):
        self.assertEqual(upload_next.parse_publish_at('2030-06-01T12:00:00+02:00'), '2030-06-01T10:00:00Z')
        self.assertEqual(upload_next.parse_publish_at('2030-06-01T12:00:00'), '2030-06-01T12:00:00Z')
        with self.assertRaises(ValueError):
            upload_next.parse_publish_at('2020-01-01T00:00:00Z')


class PrescheduleTests(unittest.TestCase):
    def test_slots_follow_local_times_and_skip_taken(self):
        schedule = {'timezone': 'Europe/Sofia', 'times': ['18:00', '10:00']}
        now = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)  # 11:00 in Sofia
        slots = preschedule.upcoming_slots(schedule, set(), 3, now)
        self.assertEqual(slots, ['2026-10-28T16:00:00Z', '2026-10-29T08:00:00Z', '2026-10-29T16:00:00Z'])
        slots = preschedule.upcoming_slots(schedule, {'2026-10-28T16:00:00Z'}, 1, now)
        self.assertEqual(slots, ['2026-10-29T08:00:00Z'])

    def test_minimum_lead_and_daylight_saving(self):
        schedule = {'timezone': 'Europe/Berlin', 'times': ['10:00']}
        now = datetime(2026, 10, 24, 7, 45, tzinfo=timezone.utc)  # 09:45 local, inside the 30 min lead
        slots = preschedule.upcoming_slots(schedule, set(), 2, now)
        # Clocks go back on 25 October: 10:00 local is 08:00 UTC before, 09:00 UTC after.
        self.assertEqual(slots, ['2026-10-25T09:00:00Z', '2026-10-26T09:00:00Z'])


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.patches = [patch.object(channels, 'ROOT', self.root), patch.object(channels, 'CHANNELS', self.root / 'channels'),
                        patch.object(channels, 'SHARED', self.root / 'shared'), patch.object(produce_batch, 'ROOT', self.root),
                        patch.object(produce_batch, 'SHARED', self.root / 'shared')]
        for p in self.patches:
            p.start()
        channels.create_channel('main', 'Main')
        (self.root / 'backgrounds').mkdir()
        (self.root / 'backgrounds/background_000.mp4').write_bytes(b'bg')
        self.stories = channels.paths('main')['stories']

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def add(self, story_id, words, **extra):
        story = {'id': story_id, 'title': f'Story {story_id}', 'text': ' '.join(['word'] * words), **extra}
        channels.write_json(self.stories / f'{story_id}.json', story)

    def run_batch(self, count, narration):
        def command(args, **kwargs):
            if '--destination' in args:
                target = Path(args[args.index('--destination') + 1])
                (target / (args[args.index('--name') + 1] + '_yellow_words.mp4')).write_bytes(b'video')
            return SimpleNamespace(returncode=0)
        with patch.object(produce_batch.narrate, 'main', narration), patch.object(produce_batch.subprocess, 'run', command), \
                patch.object(produce_batch, 'validate', lambda *a, **k: None), \
                patch.object(sys, 'argv', ['produce_batch.py', '--count', str(count), '--batch', 'b1']):
            produce_batch.main()
        return json.loads((channels.paths('main')['videos'] / 'b1/batch.json').read_text())

    def test_collected_stories_are_concepts_unless_narration_is_allowed(self):
        self.add('bbb', 40, text_source='post_page', url='https://www.reddit.com/r/stories/comments/bbb/x/')
        config = channels.load_channel('main')
        path = self.stories / 'bbb.json'
        story = channels.read_json(path)
        self.assertIsNone(produce_batch.eligible_story(path, story, config))   # default: rewrite only
        self.assertEqual(produce_batch.eligible_story(path, story, {**config, 'collected_stories': 'narrate'}), 42)

    def test_problem_story_is_set_aside_and_batch_continues(self):
        config = channels.load_channel('main')
        channels.write_json(channels.CHANNELS / 'main/config.json', {**config, 'collected_stories': 'narrate'})
        self.add('aaa', 30, text_source='original')
        self.add('bbb', 40, text_source='post_page', url='https://www.reddit.com/r/stories/comments/bbb/x/')
        self.add('ccc', 50, text_source='feed_preview')  # truncated previews are never used

        def narration():
            source = Path(sys.argv[1])
            if source.stem == 'aaa':
                raise RuntimeError('Potential repeated sentences need review')
            folder = Path(sys.argv[sys.argv.index('--output') + 1])
            folder.mkdir(parents=True)
            channels.write_json(folder / 'metadata.json', {'duration_seconds': 40})

        plan = self.run_batch(2, narration)
        self.assertEqual([item['status'] for item in plan], ['skipped', 'complete'])
        self.assertIn('repeated sentences', plan[0]['reason'])
        self.assertIn('Original story: https://www.reddit.com/r/stories/comments/bbb/x/', plan[1]['description'])
        self.assertTrue((self.stories / 'aaa_review.json').exists())
        self.assertTrue((self.stories / 'bbb_used.json').exists())
        self.assertTrue((self.stories / 'ccc.json').exists())
        usage = channels.read_json(channels.SHARED / 'story_usage.json')
        self.assertEqual([row['story_id'] for row in usage.values()], ['bbb'])

    def test_story_too_long_for_shorts_is_set_aside(self):
        self.add('long', 60, text_source='original')

        def narration():
            folder = Path(sys.argv[sys.argv.index('--output') + 1])
            folder.mkdir(parents=True)
            channels.write_json(folder / 'metadata.json', {'duration_seconds': 240})

        plan = self.run_batch(1, narration)
        self.assertEqual(plan[0]['status'], 'skipped')
        self.assertIn('shorten the story', plan[0]['reason'])
        self.assertTrue((self.stories / 'long_review.json').exists())


class RenderTests(unittest.TestCase):
    def test_background_offset_stays_inside_clip(self):
        with patch.object(make_video, 'media_duration', return_value=600.0):
            offsets = [make_video.background_offset(Path('bg.mp4'), 60, random.Random(seed)) for seed in range(50)]
        self.assertTrue(all(0 <= o <= 540 for o in offsets))
        self.assertGreater(len(set(offsets)), 40)
        with patch.object(make_video, 'media_duration', return_value=30.0):
            self.assertEqual(make_video.background_offset(Path('bg.mp4'), 60), 0.0)


if __name__ == '__main__':
    unittest.main()
