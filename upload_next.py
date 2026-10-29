r"""Upload the next ready video for a channel, then rename it with _used.

Visibility comes from the channel's settings (public, unlisted or private).
With --publish-at the video is uploaded privately and YouTube itself makes it
public at that time, so this computer does not need to be on then.

In the funnel format the full video is always uploaded before its teaser
Short; the teaser's description then links to the full video, and the pair is
added to the YouTube Studio "related video" checklist (the API cannot set it).

Interrupted uploads resume where they stopped. An upload whose result is
unknown (for example after a power cut) is checked against the channel's
recent uploads automatically; it never blocks other videos.

Run: python upload_next.py --channel main
Preview without uploading: add --dry-run
"""
import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from channel_config import (paths, load_channel, credentials_for, lock, SHARED, read_json, write_json,
                            update_json, PRIVACY_OPTIONS)

ROOT = Path(__file__).resolve().parent
DEFAULT_DESCRIPTION = 'Narrated story with satisfying background visuals.'
CHUNK = 8 * 1024 * 1024
RETRIES = 5
# A record with no resumable session older than this, and no matching video on
# the channel, is treated as never uploaded.
UNCERTAIN_GRACE = timedelta(minutes=10)


def now_utc():
    return datetime.now(timezone.utc)


def stamp(moment=None):
    return (moment or now_utc()).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_publish_at(value):
    """Accept an ISO 8601 time; naive times are treated as UTC. Must be in the future."""
    moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    if moment <= now_utc():
        raise ValueError(f'Publish time {value} is not in the future.')
    return stamp(moment)


def needs_disclosure(item):
    """YouTube requires disclosure for realistic synthetic content: photoreal AI
    imagery, altered footage of real events or places, or real people made to say
    or do things. Production records which of these a video contains."""
    return bool(item.get('synthetic_realistic'))


def video_body(item, title, config, publish_at=None, kind='short'):
    """Request body for videos.insert: metadata from production plus channel settings."""
    privacy = config.get('privacy', 'public')
    if privacy not in PRIVACY_OPTIONS:
        raise RuntimeError(f'Unknown privacy setting: {privacy!r}')
    status = {'privacyStatus': privacy, 'selfDeclaredMadeForKids': False}
    if publish_at:
        status.update(privacyStatus='private', publishAt=publish_at)
    if needs_disclosure(item):
        status['containsSyntheticMedia'] = True
    description = item.get('full_description' if kind == 'full' else 'description') or DEFAULT_DESCRIPTION
    if kind == 'teaser':
        # Links in Shorts descriptions are not clickable; the Related video set in
        # Studio is the working link. Keep a plain pointer only when we have an ID.
        link = f"https://youtu.be/{item['full_video_id']}" if item.get('full_video_id') else ''
        description = description.replace('{full_url}', link)
    snippet = {'title': title, 'categoryId': str(config.get('category_id') or '24'),
               'description': description}
    if item.get('tags'):
        snippet['tags'] = list(item['tags'])
    return {'snippet': snippet, 'status': status}


def rejection_reason(exc):
    try:
        reason = json.loads(exc.content.decode('utf-8'))['error']['errors'][0]['reason']
    except Exception:
        reason = ''
    messages = {
        'quotaExceeded': "the project's daily YouTube API quota is used up (it resets at midnight Pacific time).",
        'uploadLimitExceeded': "the channel reached YouTube's daily upload limit.",
        'forbidden': 'the account is not allowed to upload (check the connected channel).',
        'invalidTitle': 'the title was rejected.', 'invalidDescription': 'the description was rejected.',
        'invalidTags': 'the tags were rejected.',
    }
    return messages.get(reason, f'HTTP {exc.resp.status} {reason}'.strip() + '.')


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def uploaded_record_for(history, folder, file_name):
    """The upload-history record of a file in this folder, by its original name."""
    target = str(folder / file_name)
    for record in history.values():
        if record.get('status') == 'uploaded' and record.get('file') == target:
            return record
    return None


def video_kind(item, path):
    if item.get('full_video') == path.name or item.get('format') == 'long':
        return 'full'
    return 'teaser' if item.get('format') == 'funnel' else 'short'


def select_video(folder, history, dry_run=False, require_approval=False, blocked=None):
    """Next uploadable video in one batch folder, or None.

    Returns (path, used_path, digest, title, item, kind, resume_record).
    Files whose earlier upload needs attention are listed in `blocked` and skipped.
    """
    manifest_path = folder / 'batch.json'
    if not manifest_path.exists():
        return None
    items = read_json(manifest_path, [])
    for path in sorted(folder.glob('*.mp4')):
        if path.stem.endswith('_used'):
            continue
        digest = fingerprint(path)
        previous = history.get(digest)
        used = path.with_stem(path.stem + '_used')
        resume = None
        if previous:
            if previous.get('status') == 'uploaded':
                if not dry_run and not used.exists():
                    path.rename(used)
                print(f'Skipping already uploaded video: {path.name}', flush=True)
                continue
            if previous.get('resumable_uri'):
                resume = previous
            else:
                if blocked is not None:
                    blocked.append((path, digest, previous))
                continue
        item = next((row for row in items if path.name in (row.get('video'), row.get('full_video'))), None)
        if not item or item.get('status') != 'complete':
            continue
        if require_approval and item.get('review') != 'approved':
            continue
        kind = video_kind(item, path)
        if kind == 'teaser' and not item.get('full_video_id'):
            # The full video goes up first; find its ID in the history if batch.json lost it.
            full = uploaded_record_for(history, folder, item.get('full_video', ''))
            if not full:
                continue
            item = {**item, 'full_video_id': full['video_id'], 'full_publish_at': full.get('publish_at')}
        title = item['title'].strip()
        if not title or len(title) > 100 or any(char in title for char in '<>'):
            raise RuntimeError(f'Story title is invalid for YouTube (maximum 100 characters): {title!r}')
        return path, used, digest, title, item, kind, resume
    return None


def find_next(channel, history, dry_run=False, folder=None, require_approval=False, blocked=None):
    """Search the channel's batches (oldest first) for the next uploadable video."""
    videos = paths(channel)['videos']
    folders = [folder] if folder else sorted(p.parent for p in videos.glob('*/batch.json'))
    for candidate in folders:
        selection = select_video(candidate, history, dry_run, require_approval, blocked)
        if selection:
            return candidate, selection
    return None, None


def find_on_channel(youtube, title, since):
    """Video ID of a recent upload with this exact title, or None."""
    channels = youtube.channels().list(part='contentDetails', mine=True).execute().get('items', [])
    if not channels:
        return None
    uploads = channels[0]['contentDetails']['relatedPlaylists']['uploads']
    response = youtube.playlistItems().list(part='snippet', playlistId=uploads, maxResults=50).execute()
    for entry in response.get('items', []):
        snippet = entry.get('snippet', {})
        published = snippet.get('publishedAt', '')
        if snippet.get('title') == title and (not since or published >= since[:19]):
            return snippet.get('resourceId', {}).get('videoId')
    return None


def resolve_uncertain(youtube, channel, blocked, ledger, history):
    """Settle uploads whose outcome is unknown, so they never block the queue."""
    for path, digest, record in blocked:
        started = record.get('started')
        if started and now_utc() - datetime.fromisoformat(started.replace('Z', '+00:00')) < UNCERTAIN_GRACE:
            print(f'{path.name}: an upload started {started} may still be running; leaving it for now.', flush=True)
            continue
        found = find_on_channel(youtube, record.get('title', ''), started)
        if found:
            record.update(status='uploaded', video_id=found, resolved='found on channel')
            print(f'{path.name}: found on the channel as {found}; marked uploaded.', flush=True)
        else:
            history.pop(digest, None)
            print(f'{path.name}: not on the channel; it will be uploaded again.', flush=True)
        write_json(ledger, history)


def uploads_on_day(history, day, zone):
    """How many videos are published (or scheduled to publish) on this local day."""
    count = 0
    for record in history.values():
        when = record.get('publish_at') or record.get('finished') or record.get('started')
        if record.get('status') != 'uploaded' or not when:
            continue
        moment = datetime.fromisoformat(when.replace('Z', '+00:00')).astimezone(zone)
        count += moment.date() == day
    return count


def save_batch_fields(folder, item, fields):
    """Merge upload results into batch.json without overwriting production's changes."""
    def change(rows):
        for row in rows:
            if row.get('name') == item.get('name'):
                row.update(fields)
    update_json(folder / 'batch.json', change, [])


def after_upload(folder, item, kind, video_id, publish_at, channel, credentials):
    """Thumbnail for full videos; pairing records for the Short-to-full funnel."""
    if kind == 'full':
        save_batch_fields(folder, item, {'full_video_id': video_id, 'full_publish_at': publish_at})
        thumb = folder / (item.get('thumbnail') or '')
        if item.get('thumbnail') and thumb.is_file():
            try:
                from googleapiclient.discovery import build
                from googleapiclient.http import MediaFileUpload
                with build('youtube', 'v3', credentials=credentials) as api:
                    api.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumb), mimetype='image/jpeg')).execute()
                print('Custom thumbnail set.', flush=True)
            except Exception as exc:  # the video itself is fine
                print(f'Thumbnail not set ({exc}). Custom thumbnails need a phone-verified channel; '
                      'you can upload it in YouTube Studio.', flush=True)
    elif kind == 'teaser' and item.get('full_video_id'):
        record = {'channel': channel, 'teaser_id': video_id, 'full_id': item['full_video_id'],
                  'title': item.get('title'), 'done': False, 'added': stamp()}
        update_json(SHARED / 'related_links.json', lambda rows: rows.append(record), [])
        print(f"Next step: in YouTube Studio, open the Short (https://studio.youtube.com/video/{video_id}/edit) "
              f"and set Related video to the full story ({item['full_video_id']}). The dashboard lists these.",
              flush=True)


def send(request, on_progress):
    """Drive a resumable upload to completion, reporting the session URI as soon as it exists."""
    result = None
    while result is None:
        progress, result = request.next_chunk(num_retries=RETRIES)
        on_progress(request, progress)
    return result


def run(channel='main', dry_run=False, publish_at=None, folder=None):
    config = load_channel(channel)
    require_approval = bool(config.get('require_review', True))
    ledger = paths(channel)['credentials'] / 'upload_history.json'
    history = read_json(ledger, {})
    blocked = []
    folder, selected = find_next(channel, history, dry_run, folder, require_approval, blocked)
    youtube = credentials = channel_id = None
    if blocked and not dry_run:
        from googleapiclient.discovery import build
        credentials, channel_id = credentials_for(channel)
        youtube = build('youtube', 'v3', credentials=credentials)
        resolve_uncertain(youtube, channel, blocked, ledger, history)
        blocked = []
        folder, selected = find_next(channel, history, dry_run, None, require_approval, blocked)
    for path, _, record in blocked:
        print(f'Needs attention: {path.name} (upload started {record.get("started", "earlier")}); '
              'it will be checked against the channel on the next real run.', flush=True)
    if selected is None:
        waiting = ' (videos waiting for your approval are not uploaded)' if require_approval else ''
        print(f'No videos ready to upload{waiting}.', flush=True)
        return None
    path, used, digest, title, item, kind, resume = selected
    shared = read_json(SHARED / 'video_uploads.json', {})
    if digest in shared and shared[digest].get('channel') != channel:
        raise RuntimeError('This exact video was uploaded or claimed by another channel. Nothing uploaded.')
    usage = read_json(SHARED / 'story_usage.json', {})
    if item.get('story_hash') in usage and usage[item['story_hash']]['channel'] != channel:
        raise RuntimeError('This story is assigned to another channel. Nothing uploaded.')
    print(f"Channel: {config['name']} ({config.get('youtube_channel_id') or 'not connected'})", flush=True)
    if resume:
        publish_at = resume.get('publish_at')
    cap = int(config.get('max_uploads_per_day') or 0)
    if cap and not resume:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(config['schedule']['timezone'])
        target = publish_at or (item.get('full_publish_at') if kind == 'teaser' else None)
        day = (datetime.fromisoformat(target.replace('Z', '+00:00')) if target else now_utc()).astimezone(zone).date()
        # A teaser shares its full video's day; count the pair as one story.
        if kind != 'teaser' and uploads_on_day(history, day, zone) >= cap:
            raise DailyCapReached(f"{config['name']} already has {cap} upload(s) on {day}; "
                                  'the daily cap in Settings keeps the channel from looking mass-produced.')
    full_at = item.get('full_publish_at')
    if kind == 'teaser' and full_at and full_at > stamp() and (publish_at is None or publish_at < full_at):
        publish_at = full_at  # never let the teaser go live before the video it points to
        print(f'Teaser scheduled for {full_at}, when its full video goes public.', flush=True)
    body = video_body(item, title, config, publish_at, kind)
    visibility = (f'PRIVATE until {publish_at}, then public (scheduled by YouTube)' if publish_at
                  else body['status']['privacyStatus'].upper())
    label = {'full': 'Full video', 'teaser': 'Teaser Short', 'short': 'Short'}[kind]
    print(f'{label}: {path.name}\nTitle: {title}\nVisibility: {visibility}', flush=True)
    if body['status'].get('containsSyntheticMedia'):
        print('Disclosed to YouTube as containing realistic altered or synthetic content.', flush=True)
    if resume:
        print(f"Resuming an interrupted upload ({resume.get('bytes', 0) / 1e6:.0f} MB already sent).", flush=True)
    if dry_run:
        print(f'Dry run only. After a successful upload: {used.name}', flush=True)
        return 'dry-run'

    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    if youtube is None:
        credentials, channel_id = credentials_for(channel)
        youtube = build('youtube', 'v3', credentials=credentials)
    media = MediaFileUpload(str(path), mimetype='video/mp4', chunksize=CHUNK, resumable=True)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media, notifySubscribers=False)
    record = resume or {'status': 'uploading', 'file': str(path), 'title': title, 'kind': kind,
                        'started': stamp(), 'publish_at': publish_at}
    if resume:
        request.resumable_uri = resume['resumable_uri']
        request._in_error_state = True  # makes the client ask YouTube how much it already has
    history[digest] = record
    write_json(ledger, history)
    shared[digest] = {**record, 'channel': channel, 'youtube_channel_id': channel_id}
    write_json(SHARED / 'video_uploads.json', shared)

    def on_progress(req, progress):
        if req.resumable_uri and (record.get('resumable_uri') != req.resumable_uri
                                  or record.get('bytes') != req.resumable_progress):
            record.update(resumable_uri=req.resumable_uri, bytes=req.resumable_progress)
            write_json(ledger, history)
        if progress:
            print(f'Uploaded {progress.progress():.0%}', flush=True)

    def forget(message):
        history.pop(digest, None)
        shared.pop(digest, None)
        write_json(ledger, history)
        write_json(SHARED / 'video_uploads.json', shared)
        return RuntimeError(message)

    def remember_session():
        # Save the resume link even when the connection dropped mid-chunk.
        if request.resumable_uri:
            record.update(resumable_uri=request.resumable_uri, bytes=request.resumable_progress or record.get('bytes', 0))
            write_json(ledger, history)

    try:
        result = send(request, on_progress)
    except HttpError as exc:
        status = exc.resp.status
        if resume and status in (404, 410):
            raise forget('The interrupted upload session expired, so nothing was uploaded. '
                         'Run again to upload it from the start.') from exc
        if not request.resumable_uri and status in (400, 401, 403, 404):
            # Rejected before a session existed (quota, permissions, bad metadata): no video exists.
            raise forget(f'YouTube rejected the upload before it started: {rejection_reason(exc)} '
                         'Nothing was uploaded; it is safe to try again later.') from exc
        remember_session()
        raise _interrupted(record, exc) from exc
    except Exception as exc:
        if not request.resumable_uri:
            # The session was never created, so YouTube cannot have the video.
            raise forget(f'The upload could not start ({exc}). Nothing was uploaded; it is safe to try again.') from exc
        remember_session()
        raise _interrupted(record, exc) from exc
    except BaseException:
        remember_session()  # Ctrl+C or the dashboard stopping: keep what we know, then stop
        raise
    finally:
        media.stream().close()  # Windows prevents renaming while the stream is open
        youtube.close()

    video_id = result['id']
    record.update(status='uploaded', video_id=video_id, youtube_channel_id=channel_id,
                  privacy=result.get('status', {}).get('privacyStatus'), renamed_file=str(used), finished=stamp())
    record.pop('resumable_uri', None)
    write_json(ledger, history)
    shared[digest] = {**record, 'channel': channel}
    write_json(SHARED / 'video_uploads.json', shared)
    print(f'Uploaded: https://www.youtube.com/watch?v={video_id}', flush=True)
    after_upload(folder, item, kind, video_id, publish_at, channel, credentials)
    if record['privacy'] == 'private' and not publish_at and config.get('privacy') != 'private':
        print('WARNING: YouTube set this video to PRIVATE. Uploads from Google Cloud projects that have '
              'not passed the YouTube API audit are locked to private. See README > "Videos stay private".',
              flush=True)
    try:
        path.rename(used)
    except OSError as exc:
        raise RuntimeError('Upload SUCCEEDED, but the local file could not be renamed. '
                           'Upload history will prevent re-uploading this video. '
                           f'Close any app using the file, then run again. Details: {exc}') from exc
    print(f'Renamed: {used.name}', flush=True)
    return video_id


class DailyCapReached(RuntimeError):
    """The channel has reached its uploads-per-day limit."""


def _interrupted(record, exc):
    sent = record.get('bytes') or 0
    return RuntimeError(f'Upload interrupted after {sent / 1e6:.0f} MB ({exc}). '
                        'Run again to resume from where it stopped; nothing will be uploaded twice.')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--folder', type=Path, help='Only look in this batch folder')
    parser.add_argument('--channel', default='main')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--publish-at', help='ISO time to publish, e.g. 2026-11-02T18:00:00+02:00')
    args = parser.parse_args()
    if args.publish_at:
        try:
            args.publish_at = parse_publish_at(args.publish_at)
        except ValueError as exc:
            parser.error(str(exc))
    channel_paths = paths(args.channel)
    folder = None
    if args.folder is not None:
        folder = args.folder.resolve()
        if folder.parent != channel_paths['videos'].resolve():
            parser.error('Video folder must belong to the selected channel.')
        if not folder.is_dir():
            parser.error('Video folder does not exist')
    with lock('upload', wait=0 if args.dry_run else 120):
        run(args.channel, args.dry_run, args.publish_at, folder)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(f'Upload stopped: {exc}')
