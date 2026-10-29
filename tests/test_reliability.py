"""Offline tests for Phase 1 (reliability) and Phase 2 (protection) behaviour."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import channel_config as channels
import produce_batch
import review
import speech
import upload_next
import variety
from voice_selection import select_voice


class Workspace(unittest.TestCase):
    """A throwaway project root with one channel."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.patches = [patch.object(channels, 'ROOT', self.root), patch.object(channels, 'CHANNELS', self.root / 'channels'),
                        patch.object(channels, 'SHARED', self.root / 'shared'), patch.object(upload_next, 'SHARED', self.root / 'shared'),
                        patch.object(produce_batch, 'ROOT', self.root), patch.object(produce_batch, 'SHARED', self.root / 'shared')]
        for p in self.patches:
            p.start()
        channels.create_channel('main', 'Main')
        self.videos = channels.paths('main')['videos']
        self.ledger = channels.paths('main')['credentials'] / 'upload_history.json'

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def batch(self, name, items, files):
        folder = self.videos / name
        folder.mkdir(parents=True)
        for file in files:
            (folder / file).write_bytes(file.encode())
        channels.write_json(folder / 'batch.json', items)
        return folder


class StateFileTests(Workspace):
    def test_damaged_file_falls_back_to_backup(self):
        path = self.root / 'shared' / 'state.json'
        channels.write_json(path, {'v': 1})
        channels.write_json(path, {'v': 2})
        self.assertEqual(json.loads((path.parent / 'state.json.bak').read_text()), {'v': 1})
        path.write_text('{"v": 3')  # a power cut mid-write
        self.assertEqual(channels.read_json(path), {'v': 1})
        (path.parent / 'state.json.bak').write_text('broken')
        with self.assertRaises(channels.DataFileError):
            channels.read_json(path)

    @unittest.skipIf(os.name == 'nt', 'POSIX permissions')
    def test_tokens_are_owner_only(self):
        path = self.root / 'credentials' / 'token.json'
        channels.write_json(path, {'secret': 1}, private=True)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_update_json_merges(self):
        path = self.root / 'shared' / 'list.json'
        channels.update_json(path, lambda rows: rows.append(1), [])
        channels.update_json(path, lambda rows: rows.append(2), [])
        self.assertEqual(channels.read_json(path), [1, 2])

    def test_stale_lock_is_cleared(self):
        lock_file = self.root / 'shared' / 'production.lock'
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.write_text('999999999 0')  # a process that no longer exists
        with channels.lock('production'):
            self.assertEqual(channels.lock_owner(lock_file), os.getpid())
        self.assertFalse(lock_file.exists())
        lock_file.write_text(f'{os.getpid()} 0')  # a live process: respected
        with self.assertRaisesRegex(RuntimeError, 'running'):
            with channels.lock('production'):
                pass


class UploadSelectionTests(Workspace):
    def test_leftover_file_does_not_pin_the_queue(self):
        self.batch('batch_1', [{'name': '01_a', 'video': '01_a.mp4', 'status': 'pending', 'title': 'A'}], ['01_a.mp4'])
        self.batch('batch_2', [{'name': '01_b', 'video': '01_b.mp4', 'status': 'complete', 'title': 'B',
                                'review': 'approved'}], ['01_b.mp4'])
        folder, selection = upload_next.find_next('main', {}, dry_run=True, require_approval=True)
        self.assertEqual((folder.name, selection[0].name), ('batch_2', '01_b.mp4'))

    def test_unapproved_videos_are_never_uploaded(self):
        self.batch('b', [{'name': '01_a', 'video': '01_a.mp4', 'status': 'complete', 'title': 'A', 'review': 'pending'}],
                   ['01_a.mp4'])
        self.assertEqual(upload_next.find_next('main', {}, True, require_approval=True), (None, None))
        self.assertIsNotNone(upload_next.find_next('main', {}, True, require_approval=False)[1])

    def test_teaser_finds_its_full_video_in_history(self):
        folder = self.batch('b', [{'name': '01_x', 'video': '01_x_teaser.mp4', 'full_video': '01_x_full.mp4',
                                   'format': 'funnel', 'status': 'complete', 'title': 'X', 'review': 'approved'}],
                            ['01_x_teaser.mp4'])
        history = {'d': {'status': 'uploaded', 'file': str(folder / '01_x_full.mp4'), 'video_id': 'FULL9',
                         'publish_at': '2030-01-01T10:00:00Z'}}
        selection = upload_next.select_video(folder, history, dry_run=True, require_approval=True)
        self.assertEqual((selection[5], selection[4]['full_video_id'], selection[4]['full_publish_at']),
                         ('teaser', 'FULL9', '2030-01-01T10:00:00Z'))


def http_error(status, reason=''):
    from googleapiclient.errors import HttpError
    return HttpError(SimpleNamespace(status=status, reason='x'), json.dumps({'error': {'errors': [{'reason': reason}]}}).encode())


class UploadRecoveryTests(Workspace):
    def setUp(self):
        super().setUp()
        self.folder = self.batch('b', [{'name': '01_a', 'video': '01_a.mp4', 'status': 'complete', 'title': 'A',
                                        'review': 'approved'}], ['01_a.mp4'])
        self.digest = upload_next.fingerprint(self.folder / '01_a.mp4')

    def api(self, request):
        api = MagicMock()
        api.videos.return_value.insert.return_value = request
        return api

    def upload(self, api):
        with patch.object(upload_next, 'credentials_for', return_value=(None, 'CH')), \
                patch('googleapiclient.discovery.build', return_value=api), patch('googleapiclient.http.MediaFileUpload'):
            return upload_next.run('main')

    def test_network_drop_resumes_instead_of_blocking(self):
        first = MagicMock(resumable_uri=None, resumable_progress=0)

        def chunk(num_retries):
            first.resumable_uri, first.resumable_progress = 'https://upload/session1', 8_000_000
            raise ConnectionResetError('connection reset')
        first.next_chunk.side_effect = chunk
        with self.assertRaisesRegex(RuntimeError, 'Run again to resume'):
            self.upload(self.api(first))
        record = channels.read_json(self.ledger)[self.digest]
        self.assertEqual((record['status'], record['resumable_uri'], record['bytes']), ('uploading', 'https://upload/session1', 8_000_000))

        second = MagicMock(resumable_uri=None, resumable_progress=0)
        second.next_chunk.return_value = (None, {'id': 'VID1', 'status': {'privacyStatus': 'public'}})
        self.assertEqual(self.upload(self.api(second)), 'VID1')
        self.assertEqual(second.resumable_uri, 'https://upload/session1')
        self.assertTrue(second._in_error_state)  # asks YouTube how much it already has
        record = channels.read_json(self.ledger)[self.digest]
        self.assertEqual((record['status'], record['video_id']), ('uploaded', 'VID1'))
        self.assertNotIn('resumable_uri', record)
        self.assertTrue((self.folder / '01_a_used.mp4').exists())

    def test_failure_before_session_is_safe_to_retry(self):
        request = MagicMock(resumable_uri=None)
        request.next_chunk.side_effect = TimeoutError('timed out')
        with self.assertRaisesRegex(RuntimeError, 'safe to try again'):
            self.upload(self.api(request))
        self.assertEqual(channels.read_json(self.ledger), {})

    def test_expired_session_restarts(self):
        channels.write_json(self.ledger, {self.digest: {'status': 'uploading', 'file': 'x', 'title': 'A',
                                                        'resumable_uri': 'https://upload/old', 'bytes': 5}})
        request = MagicMock(resumable_uri=None)
        request.next_chunk.side_effect = http_error(404)
        with self.assertRaisesRegex(RuntimeError, 'session expired'):
            self.upload(self.api(request))
        self.assertEqual(channels.read_json(self.ledger), {})

    def test_uncertain_upload_is_checked_against_the_channel(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        channels.write_json(self.ledger, {self.digest: {'status': 'uploading', 'file': 'x', 'title': 'A', 'started': old}})
        api = MagicMock()
        api.channels.return_value.list.return_value.execute.return_value = {
            'items': [{'contentDetails': {'relatedPlaylists': {'uploads': 'UU1'}}}]}
        api.playlistItems.return_value.list.return_value.execute.return_value = {
            'items': [{'snippet': {'title': 'A', 'publishedAt': old, 'resourceId': {'videoId': 'FOUND1'}}}]}
        self.assertIsNone(self.upload(api))  # found: nothing left to upload
        record = channels.read_json(self.ledger)[self.digest]
        self.assertEqual((record['status'], record['video_id']), ('uploaded', 'FOUND1'))
        self.assertTrue((self.folder / '01_a_used.mp4').exists())

    def test_daily_cap(self):
        today = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        cfg = channels.load_channel('main')
        cfg.update(max_uploads_per_day=1, schedule={**cfg['schedule'], 'timezone': 'UTC'})
        channels.write_json(channels.CHANNELS / 'main/config.json', cfg)
        channels.write_json(self.ledger, {'other': {'status': 'uploaded', 'finished': today}})
        with self.assertRaises(upload_next.DailyCapReached):
            self.upload(MagicMock())


class ProductionRecoveryTests(Workspace):
    def setUp(self):
        super().setUp()
        (self.root / 'backgrounds').mkdir()
        (self.root / 'backgrounds/background_000.mp4').write_bytes(b'bg')
        stories = channels.paths('main')['stories']
        for key in ('aaa', 'bbb'):
            channels.write_json(stories / f'{key}.json', {'id': key, 'title': f"Story {key}, part 2 (it's [bad])",
                                                          'text': f'{key} ' + 'word ' * 40, 'text_source': 'original'})
        channels.write_json(stories / 'list.json', [1, 2, 3])  # not a story

    def run_batch(self, render):
        def narration():
            folder = Path(sys.argv[sys.argv.index('--output') + 1])
            folder.mkdir(parents=True, exist_ok=True)
            channels.write_json(folder / 'metadata.json', {'duration_seconds': 30})
        with patch.object(produce_batch.narrate, 'main', narration), patch.object(produce_batch.subprocess, 'run', render), \
                patch.object(produce_batch, 'validate', lambda *a, **k: None), \
                patch.object(sys, 'argv', ['produce_batch.py', '--count', '2']):
            produce_batch.main()
        return channels.read_json(channels.SHARED / 'story_usage.json', {})

    def test_crashing_story_is_released_and_batch_continues(self):
        import subprocess

        def render(args, **kwargs):
            name = args[args.index('--name') + 1]
            self.assertRegex(name, r'^[0-9]{2}_[A-Za-z0-9_-]+$')  # safe for FFmpeg filters
            if 'aaa' in name:
                raise subprocess.CalledProcessError(1, 'ffmpeg')
            (Path(args[args.index('--destination') + 1]) / (name + '_yellow_words.mp4')).write_bytes(b'v')
            return SimpleNamespace(returncode=0)
        usage = self.run_batch(render)
        self.assertEqual([row['story_id'] for row in usage.values()], ['bbb'])
        self.assertTrue((channels.paths('main')['stories'] / 'aaa.json').exists())  # still available
        plan = channels.read_json(next(self.videos.glob('*/batch.json')))
        self.assertEqual(sorted(i['status'] for i in plan), ['complete', 'failed'])

    def test_stale_reservation_from_a_killed_run_is_ignored(self):
        from channel_config import story_fingerprint
        text = channels.read_json(channels.paths('main')['stories'] / 'aaa.json')['text']
        channels.write_json(channels.SHARED / 'story_usage.json',
                            {story_fingerprint(text): {'channel': 'main', 'batch': 'old', 'status': 'reserved', 'story_id': 'aaa'}})

        def render(args, **kwargs):
            (Path(args[args.index('--destination') + 1]) / (args[args.index('--name') + 1] + '_yellow_words.mp4')).write_bytes(b'v')
            return SimpleNamespace(returncode=0)
        usage = self.run_batch(render)
        self.assertEqual(sorted(row['story_id'] for row in usage.values()), ['aaa', 'bbb'])

    def test_plan_save_keeps_uploader_fields(self):
        path = self.root / 'plan.json'
        channels.write_json(path, [{'name': '01_a', 'status': 'complete', 'full_video_id': 'F1', 'review': 'approved'}])
        produce_batch.write_plan(path, [{'name': '01_a', 'status': 'complete', 'review': 'pending'}])
        saved = channels.read_json(path)[0]
        self.assertEqual((saved['full_video_id'], saved['review']), ('F1', 'approved'))

    def test_resume_recognises_uploaded_files(self):
        folder = self.root / 'b'
        folder.mkdir()
        (folder / '01_x_full_used.mp4').write_bytes(b'v')
        (folder / '01_x_teaser.mp4').write_bytes(b'v')
        item = {'format': 'funnel', 'video': '01_x_teaser.mp4', 'full_video': '01_x_full.mp4'}
        self.assertTrue(produce_batch.finished_files_exist(folder, item))


class ReviewTests(Workspace):
    def test_bulk_and_single_decisions(self):
        self.batch('b1', [{'name': f'0{i}_s', 'status': 'complete', 'review': 'pending', 'title': f'T{i}'} for i in (1, 2, 3)]
                   + [{'name': '04_s', 'status': 'failed'}], [])
        self.assertEqual(review.decide('main', 'b1', ['02_s'], 'rejected', 'weak ending'), ['02_s'])
        self.assertEqual(review.decide('main', 'b1', [], 'approved'), ['01_s', '03_s'])
        rows = {r['name']: r for r in channels.read_json(self.videos / 'b1/batch.json')}
        self.assertEqual((rows['02_s']['review'], rows['02_s']['review_note']), ('rejected', 'weak ending'))
        self.assertNotIn('review', rows['04_s'])
        self.assertEqual(review.pending('main'), [])


class VarietyTests(unittest.TestCase):
    def test_warnings(self):
        recent = [{'title': f'My boss fired me for reason {i}', 'opening': f'It was a Monday number {i}.'} for i in range(6)]
        warnings = variety.check('My boss fired me for reason 9', 'It was a Monday number 3.', recent)
        self.assertEqual(len(warnings), 3)
        self.assertEqual(variety.check('The lighthouse keeper', 'Fog rolled in.', recent), [])


class SpeechAndVoiceTests(unittest.TestCase):
    def test_tldr_keeps_story_and_caps_are_not_shorthand(self):
        self.assertEqual(speech.strip_meta('TL;DR my sister sold my car.\nSo it began.\nShe smiled.').strip(),
                         'So it began.\nShe smiled.')
        self.assertEqual(speech.for_narration('I was SO angry. IT WAS TIL MIDNIGHT. My SO and her DD left. TIL that cats purr.'),
                         'I was SO angry. IT WAS TIL MIDNIGHT. My partner and her daughter left. Today I learned that cats purr.')
        self.assertEqual(speech.for_narration('TIL my cat can open doors.'), 'Today I learned my cat can open doors.')

    def test_name_dick_is_kept(self):
        self.assertEqual(speech.clean_language('Uncle Dick Johnson waved. He was a dick.'),
                         'Uncle Dick Johnson waved. He was a jerk.')

    def test_voice_follows_channel_accent(self):
        self.assertEqual(select_voice({'text': 'My gf helped.'}, 'bf_emma')[0], 'bm_george')
        self.assertEqual(select_voice({'text': 'I (30M) ran.'}, 'am_adam')[0], 'am_adam')
        self.assertEqual(select_voice({'text': 'My wife cried.'}, 'af_heart', male='am_eric')[0], 'am_eric')

    def test_spoken_title_keeps_question(self):
        import narrate
        script, _, _ = narrate.prepare_script({'title': 'Did she really?', 'text': 'Yes she did.'})
        self.assertTrue(script.startswith('Did she really? Yes'))

    def test_safe_name(self):
        self.assertEqual(produce_batch.safe_name("AITA, don't [x]"), 'AITA_don_t_x')


class SignInTests(Workspace):
    def test_expired_token_is_reported_and_reconnect_skips_refresh(self):
        from google.auth.exceptions import RefreshError
        creds = channels.paths('main')['credentials']
        (creds / 'channel_token.json').write_text('{}')
        expired = SimpleNamespace(expired=True, refresh_token='r', valid=False)
        expired.refresh = MagicMock(side_effect=RefreshError('invalid_grant'))
        with patch('google.oauth2.credentials.Credentials.from_authorized_user_file', return_value=expired):
            with self.assertRaises(channels.SignInExpired):
                channels.credentials_for('main')
        self.assertEqual(channels.token_status('main'), 'expired')
        fresh = SimpleNamespace(valid=True, to_json=lambda: '{"t": 1}')
        flow = MagicMock()
        flow.run_local_server.return_value = fresh
        api = MagicMock()
        api.__enter__.return_value = api
        api.channels.return_value.list.return_value.execute.return_value = {'items': [{'id': 'UC1', 'snippet': {'title': 'Mine'}}]}
        (self.root / 'credentials').mkdir(exist_ok=True)
        (self.root / 'credentials/client_secret.json').write_text('{}')
        with patch('google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file', return_value=flow), \
                patch('google.oauth2.credentials.Credentials.from_authorized_user_file') as old_token, \
                patch('googleapiclient.discovery.build', return_value=api):
            channels.credentials_for('main', connect=True)
        old_token.assert_not_called()  # the broken token is never touched when reconnecting
        self.assertEqual(channels.token_status('main'), 'ok')
        self.assertEqual(channels.load_channel('main')['youtube_channel_id'], 'UC1')


if __name__ == '__main__':
    unittest.main()
