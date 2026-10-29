"""Offline tests for the funnel format, AI story generation and video extras."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import channel_config as channels
import make_video
import metadata
import produce_batch
import speech
import story_generator
import upload_next


class SpeechTests(unittest.TestCase):
    def test_reddit_shorthand_is_spoken_naturally(self):
        text = speech.expand_shorthand('AITA for telling my MIL (58F) no? My BF and I (25F) live w/ my SO. So I said no.')
        self.assertEqual(text, 'Am I the jerk for telling my mother-in-law, 58, no? My boyfriend and I, 25, '
                               'live with my partner. So I said no.')

    def test_meta_lines_and_spoilers_removed(self):
        text = speech.strip_meta('It began.\n\nEdit: thanks for all the upvotes!\nIt ended.\n\nTL;DR: she left.')
        self.assertNotIn('upvotes', text)
        self.assertNotIn('she left', text)
        self.assertIn('It ended.', text)

    def test_clean_language(self):
        self.assertEqual(speech.clean_language('That was a fucking mess and he was an asshole. Shit.'),
                         'That was a freaking mess and he was a jerk. Crap.')
        self.assertEqual(speech.clean_language('Classic assessment of a passing class.'),
                         'Classic assessment of a passing class.')


class TeaserTests(unittest.TestCase):
    config = channels.with_defaults({})
    story = {'title': 'The box in the attic',
             'text': ' '.join(f'Sentence number {i} keeps the tension rising a little more.' for i in range(60))}

    def test_teaser_stops_early_and_ends_with_call_to_action(self):
        teaser = produce_batch.teaser_text(self.story, self.config)
        self.assertTrue(teaser.endswith(self.config['teaser_cta']))
        spoken = produce_batch.word_count(teaser) + produce_batch.word_count(self.story['title'])
        self.assertLess(abs(spoken / produce_batch.WORDS_PER_SECOND - self.config['teaser_seconds']), 15)

    def test_teaser_uses_the_cliffhanger_chosen_by_the_writer(self):
        teaser = produce_batch.teaser_text({**self.story, 'teaser_sentences': 3}, self.config)
        self.assertEqual(teaser.count('Sentence number'), 3)

    def test_teaser_never_gives_away_most_of_a_short_story(self):
        short = {'title': 'T', 'text': 'One two three four five six. Seven eight nine ten eleven. Twelve thirteen fourteen.'}
        teaser = produce_batch.teaser_text(short, self.config)
        self.assertEqual(teaser.count('.') - self.config['teaser_cta'].count('.'), 1)


class MetadataKindTests(unittest.TestCase):
    def test_teaser_full_and_fiction(self):
        config = channels.with_defaults({})
        story = {'title': 'Invented', 'text': 'A hook. More.', 'fiction': True}
        teaser = metadata.build(story, config, 'teaser')
        self.assertIn('Full story: {full_url}', teaser['description'])
        self.assertNotIn('fiction', teaser['description'])
        full = metadata.build(story, config, 'full')
        self.assertIn(config['fiction_note'], full['description'])
        self.assertNotIn('#shorts', full['description'])
        self.assertIn('#storytime', full['description'])


class FunnelProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.patches = [patch.object(channels, 'ROOT', self.root), patch.object(channels, 'CHANNELS', self.root / 'channels'),
                        patch.object(channels, 'SHARED', self.root / 'shared'), patch.object(produce_batch, 'ROOT', self.root),
                        patch.object(produce_batch, 'SHARED', self.root / 'shared')]
        for p in self.patches:
            p.start()
        config = channels.create_channel('main', 'Main')
        config.update(video_format='funnel', full_min_words=100)
        channels.write_json(self.root / 'channels/main/config.json', config)
        (self.root / 'backgrounds').mkdir()
        (self.root / 'backgrounds/background_000.mp4').write_bytes(b'bg')
        self.stories = channels.paths('main')['stories']

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_full_video_teaser_and_thumbnail(self):
        text = ' '.join(f'This is sentence {i} of a long invented story.' for i in range(40))
        channels.write_json(self.stories / 'gen_1.json', {'id': 'gen_1', 'title': 'A long story', 'text': text,
                                                          'text_source': 'generated', 'fiction': True, 'teaser_sentences': 4})
        narrated, commands = [], []

        def narration():
            source = Path(sys.argv[1])
            folder = Path(sys.argv[sys.argv.index('--output') + 1])
            narrated.append((source.name, folder.name, '--clean-language' in sys.argv))
            folder.mkdir(parents=True, exist_ok=True)
            channels.write_json(folder / 'metadata.json', {'duration_seconds': 300 if folder.name == 'full' else 40})

        def command(args, **kwargs):
            commands.append(args)
            if '--filename' in args:
                (Path(args[args.index('--destination') + 1]) / args[args.index('--filename') + 1]).write_bytes(b'video')
            if '--out' in args:
                Path(args[args.index('--out') + 1]).write_bytes(b'jpg')
            return SimpleNamespace(returncode=0)

        with patch.object(produce_batch.narrate, 'main', narration), patch.object(produce_batch.subprocess, 'run', command), \
                patch.object(produce_batch, 'validate', lambda *a, **k: None), \
                patch.object(sys, 'argv', ['produce_batch.py', '--count', '1', '--batch', 'b1']):
            produce_batch.main()
        batch = channels.paths('main')['videos'] / 'b1'
        item = json.loads((batch / 'batch.json').read_text())[0]
        self.assertEqual((item['status'], item['video'], item['full_video'], item['thumbnail']),
                         ('complete', '01_gen_1_teaser.mp4', '01_gen_1_full.mp4', '01_gen_1_full.jpg'))
        self.assertTrue(item['generated'])
        self.assertEqual(item['review'], 'pending')
        self.assertIn('{full_url}', item['description'])
        self.assertEqual([n[1] for n in narrated], ['full', 'teaser'])
        self.assertTrue(all(n[2] for n in narrated))
        teaser_story = json.loads((channels.paths('main')['narrations'] / 'gen_1/b1/teaser_story.json').read_text())
        self.assertEqual(teaser_story['text'].count('This is sentence'), 4)
        renders = [c for c in commands if any(str(a).endswith('make_video.py') for a in c)]
        self.assertEqual([c[c.index('--format') + 1] for c in renders], ['landscape', 'vertical'])
        self.assertIn('--progress-bar', renders[1])
        self.assertNotIn('--progress-bar', renders[0])
        self.assertIn('--title-card', renders[0])
        self.assertIn('--grade', renders[0])

    def test_full_video_over_the_limit_needs_review(self):
        channels.write_json(self.stories / 'long.json', {'id': 'long', 'title': 'Long', 'text': 'word ' * 200, 'text_source': 'original'})

        def narration():
            folder = Path(sys.argv[sys.argv.index('--output') + 1])
            folder.mkdir(parents=True, exist_ok=True)
            channels.write_json(folder / 'metadata.json', {'duration_seconds': 16 * 60})

        with patch.object(produce_batch.narrate, 'main', narration), \
                patch.object(produce_batch.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), \
                patch.object(sys, 'argv', ['produce_batch.py', '--count', '1', '--batch', 'b1']):
            produce_batch.main()
        item = json.loads((channels.paths('main')['videos'] / 'b1/batch.json').read_text())[0]
        self.assertEqual(item['status'], 'skipped')
        self.assertIn('15 min', item['reason'])


class FunnelUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.shared = patch.object(channels, 'SHARED', self.root / 'shared')
        self.shared.start()
        self.addCleanup(self.shared.stop)
        self.folder = self.root / 'videos/b1'
        self.folder.mkdir(parents=True)
        for name in ('01_x_full.mp4', '01_x_teaser.mp4'):
            (self.folder / name).write_bytes(name.encode())
        self.item = {'name': '01_x', 'video': '01_x_teaser.mp4', 'full_video': '01_x_full.mp4', 'format': 'funnel', 'status': 'complete',
                     'title': 'X', 'description': 'Hook\n\nFull story: {full_url}', 'full_description': 'Full hook',
                     'thumbnail': '01_x_full.jpg', 'generated': True}
        channels.write_json(self.folder / 'batch.json', [self.item])

    def tearDown(self):
        self.temp.cleanup()

    def test_full_first_then_teaser_with_link(self):
        selected = upload_next.select_video(self.folder, {})
        self.assertEqual((selected[0].name, selected[5]), ('01_x_full.mp4', 'full'))
        full_digest = upload_next.fingerprint(self.folder / '01_x_full.mp4')
        self.assertIsNone(upload_next.select_video(self.folder, {full_digest: {'status': 'uploaded'}}, dry_run=True))
        with patch.object(upload_next, 'SHARED', self.root / 'shared'):
            upload_next.after_upload(self.folder, self.item, 'full', 'FULL123', None, 'main', None)
        row = json.loads((self.folder / 'batch.json').read_text())[0]
        self.assertEqual(row['full_video_id'], 'FULL123')
        selected = upload_next.select_video(self.folder, {full_digest: {'status': 'uploaded'}}, dry_run=True)
        self.assertEqual(selected[5], 'teaser')
        body = upload_next.video_body(selected[4], 'X', channels.with_defaults({}), kind='teaser')
        self.assertEqual(body['snippet']['description'], 'Hook\n\nFull story: https://youtu.be/FULL123')
        # AI-written text and a narrator voice over real images: not on YouTube's disclosure list.
        self.assertNotIn('containsSyntheticMedia', body['status'])
        realistic = upload_next.video_body({**self.item, 'synthetic_realistic': True}, 'X', channels.with_defaults({}), kind='full')
        self.assertTrue(realistic['status']['containsSyntheticMedia'])
        full_body = upload_next.video_body(self.item, 'X', channels.with_defaults({}), kind='full')
        self.assertEqual(full_body['snippet']['description'], 'Full hook')
        with patch.object(upload_next, 'SHARED', self.root / 'shared'):
            upload_next.after_upload(self.folder, row, 'teaser', 'SHORT9', None, 'main', None)
        todo = json.loads((self.root / 'shared/related_links.json').read_text())
        self.assertEqual((todo[0]['teaser_id'], todo[0]['full_id'], todo[0]['done']), ('SHORT9', 'FULL123', False))


class SafeFailureTests(unittest.TestCase):
    def test_rejected_before_start_clears_records(self):
        from googleapiclient.errors import HttpError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(channels, 'ROOT', root), patch.object(channels, 'CHANNELS', root / 'channels'), \
                    patch.object(channels, 'SHARED', root / 'shared'), patch.object(upload_next, 'SHARED', root / 'shared'):
                channels.create_channel('main', 'Main')
                folder = channels.paths('main')['videos'] / 'b1'
                folder.mkdir(parents=True)
                (folder / 'a.mp4').write_bytes(b'video')
                channels.write_json(folder / 'batch.json', [{'name': 'a', 'video': 'a.mp4', 'title': 'A', 'status': 'complete', 'review': 'approved'}])
                error = HttpError(SimpleNamespace(status=403, reason='Forbidden'),
                                  json.dumps({'error': {'errors': [{'reason': 'quotaExceeded'}]}}).encode())
                request = MagicMock()
                request.next_chunk.side_effect = error
                api = MagicMock()
                api.videos.return_value.insert.return_value = request
                request.resumable_uri = None
                with patch.object(upload_next, 'credentials_for', return_value=(None, 'CH')), \
                        patch('googleapiclient.discovery.build', return_value=api), \
                        patch('googleapiclient.http.MediaFileUpload'):
                    with self.assertRaisesRegex(RuntimeError, 'quota is used up.*safe to try again'):
                        upload_next.run('main')
                history = channels.read_json(channels.paths('main')['credentials'] / 'upload_history.json')
                self.assertEqual(history, {})
                self.assertIsNotNone(upload_next.select_video(folder, history))


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.patches = [patch.object(channels, 'ROOT', self.root), patch.object(channels, 'CHANNELS', self.root / 'channels'),
                        patch.object(story_generator, 'ROOT', self.root), patch.object(story_generator, 'CHANNELS', self.root / 'channels')]
        for p in self.patches:
            p.start()
        channels.create_channel('main', 'Main')
        self.source_text = ('My neighbour started digging a trench around his house in July. By August it was full of '
                            'water and he had bought a small rowing boat. ' * 4)
        channels.write_json(self.root / 'stories/abc.json', {'id': 'abc', 'title': 'My neighbour built a moat around his house',
                                                             'text': self.source_text, 'text_source': 'post_page', 'score': 9000})

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def reply(self, title, text, **extra):
        payload = json.dumps({'title': title, 'text': text, 'theme': 'neighbours', 'narrator': 'female', **extra})
        return SimpleNamespace(content=[SimpleNamespace(type='text', text=f'<json>{payload}</json>')])

    def test_copy_is_rejected_and_original_is_saved(self):
        original = ' '.join(f'The bakery on Linden Street had a new rule number {i} every single morning without fail.' for i in range(12))
        client = MagicMock()
        client.messages.create.side_effect = [self.reply('A moat for my neighbour', self.source_text),
                                              self.reply('The bakery that changed its rules daily', original)]
        logs = []
        created = story_generator.generate('main', 1, client=client, log=logs.append, mode='themes')
        self.assertEqual(len(created), 1)
        self.assertTrue(any('originality check' in line for line in logs))
        saved = json.loads(next((self.root / 'stories').glob('gen_*.json')).read_text())
        self.assertEqual((saved['text_source'], saved['fiction'], saved['narrator_gender']), ('generated', True, 'female'))
        self.assertNotIn('url', saved)
        first_prompt = client.messages.create.call_args_list[0].kwargs['messages'][0]['content']
        self.assertIn('My neighbour built a moat around his house - 9,000 upvotes', first_prompt)
        self.assertNotIn('rowing boat', first_prompt)  # source texts never reach the model
        second_prompt = client.messages.create.call_args_list[1].kwargs['messages'][0]['content']
        self.assertIn('rejected', second_prompt)

    def test_uses_own_channel_views(self):
        paths = channels.paths('main')
        channels.write_json(paths['credentials'] / 'upload_history.json', {'d1': {'title': 'Top video', 'video_id': 'v1', 'status': 'uploaded'},
                                                                         'd2': {'title': 'Flop', 'video_id': 'v2', 'status': 'uploaded'}})
        channels.write_json(paths['output'] / 'youtube_insights.json', {'videos': {'v1': {'viewCount': 50000}, 'v2': {'viewCount': 12}}})
        self.assertEqual(story_generator.own_channel_performance('main'), [('Top video', 50000), ('Flop', 12)])

    def test_funnel_length_and_teaser_field(self):
        config = channels.with_defaults({'video_format': 'funnel'})
        length, low, high = story_generator.length_target(config, 'auto')
        self.assertEqual(length, 'full')
        self.assertGreaterEqual(low, 900)
        parsed = story_generator.parse_reply('<json>' + json.dumps({'title': 'T', 'text': 'The door was open. ' * 25, 'teaser_sentences': 5}) + '</json>', 'full')
        self.assertEqual(parsed['teaser_sentences'], 5)
        with self.assertRaises(story_generator.GenerationError):
            story_generator.parse_reply('no json here', 'short')

    def test_no_key_is_a_clear_error(self):
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': ''}), patch.object(story_generator, 'KEY_FILE', self.root / 'none.txt'):
            with self.assertRaisesRegex(story_generator.GenerationError, 'No Claude API key'):
                story_generator.generate('main', 1)


class RenderExtrasTests(unittest.TestCase):
    def test_title_card_and_layouts(self):
        words = [{'word': w, 'start': i * .3, 'end': i * .3 + .25} for i, w in enumerate('Hello there. This is a test.'.split())]
        ass, count = make_video.build_captions(words, 'vertical', 'words', 'My {weird} title', 3)
        self.assertIn('PlayResX: 1080', ass)
        self.assertIn('Title,,0,0,0,,{\\fad(150,250)\\pos(540,330)}My weird title', ass)
        self.assertEqual(count, 6)
        ass, count = make_video.build_captions(words, 'landscape', 'words')
        self.assertIn('PlayResX: 1920', ass)
        self.assertNotIn('Dialogue: 1', ass)
        self.assertEqual(count, 2)  # landscape always uses phrases

    def test_filters(self):
        vertical = make_video.video_filter('vertical', (1080, 1920), 'c.ass', 40, True)
        self.assertIn("overlay=x='-w+w*min(t/40.000,1)'", vertical)  # slides in; drawbox would stay full width
        self.assertTrue(vertical.startswith('[0:v]fps=30,'))
        landscape = make_video.video_filter('landscape', (1080, 1920), 'c.ass', 40, False)
        self.assertIn('boxblur', landscape)
        self.assertNotIn('overlay=x=', landscape)
        self.assertNotIn('boxblur', make_video.video_filter('landscape', (1920, 1080), 'c.ass', 40, False))
        self.assertIn('sidechaincompress', make_video.audio_filter(0.1, True))
        self.assertNotIn('[2:a]', make_video.audio_filter(0.1, False))


if __name__ == '__main__':
    unittest.main()
