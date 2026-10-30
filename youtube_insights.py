"""Fetch YouTube statistics; --connect opens read-only authorization.

Views, likes and comments come from the YouTube Data API. When the channel's
sign-in includes YouTube Analytics (every sign-in made with this version does),
average view duration and average percentage watched are added too: the
numbers that show whether a hook works. The story generator favours themes
people watch to the end.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from channel_config import ANALYTICS_SCOPE, paths, credentials_for, write_json

ROOT = Path(__file__).resolve().parent
SCOPES = ['https://www.googleapis.com/auth/youtube.readonly']

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--connect', action='store_true')
    parser.add_argument('--channel',default='main')
    args = parser.parse_args()
    channel_paths=paths(args.channel)
    token = channel_paths['credentials'] / 'insights_token.json'
    combined=channel_paths['credentials'] / 'channel_token.json'
    if combined.exists(): token=combined
    # Load with the scopes the sign-in actually granted (see channel_config.credentials_for).
    credentials = Credentials.from_authorized_user_file(str(token)) if token.exists() else None
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials or not credentials.valid:
        if not args.connect:
            raise RuntimeError('Connect insights to grant read-only YouTube access.')
        flow = InstalledAppFlow.from_client_secrets_file(str(ROOT / 'credentials/client_secret.json'), SCOPES)
        credentials = flow.run_local_server(port=0, access_type='offline', prompt='consent', timeout_seconds=300,
            authorization_prompt_message='Complete read-only authorization in your browser.',
            success_message='Insights connected. You can close this tab.')
    if not combined.exists(): write_json(token, json.loads(credentials.to_json()), private=True)
    history_file=channel_paths['credentials'] / 'upload_history.json'
    history = json.loads(history_file.read_text(encoding='utf-8')) if history_file.exists() else {}
    ids = sorted({row['video_id'] for row in history.values() if row.get('status')=='uploaded' and row.get('video_id')})
    videos = {}
    with build('youtube', 'v3', credentials=credentials) as youtube:
        for start in range(0, len(ids), 50):
            response = youtube.videos().list(part='statistics', id=','.join(ids[start:start+50])).execute()
            for video in response.get('items', []):
                stats = video.get('statistics', {})
                videos[video['id']] = {key: int(stats[key]) if key in stats else None
                    for key in ('viewCount','likeCount','commentCount')}
    retention = 'reconnect'
    if ANALYTICS_SCOPE in (credentials.scopes or []) and videos:
        try:
            add_retention(credentials, videos)
            retention = 'ok'
        except Exception as exc:  # Analytics lags a day or two and can refuse; statistics still count
            retention = 'unavailable'
            print(f'Retention numbers unavailable: {exc}', flush=True)
    output = channel_paths['output'] / 'youtube_insights.json'
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps({'updatedAt':datetime.now(timezone.utc).isoformat(), 'retention': retention,
                                     'videos':videos}, indent=2), encoding='utf-8')
    os.replace(temporary, output)
    print(f'Updated insights for {len(videos)} videos' + (' with retention.' if retention == 'ok' else '.'))


def add_retention(credentials, videos):
    """Average view duration (seconds) and percentage watched, lifetime, per video."""
    today = datetime.now(timezone.utc).date().isoformat()
    ids = sorted(videos)
    with build('youtubeAnalytics', 'v2', credentials=credentials) as analytics:
        for start in range(0, len(ids), 50):
            chunk = ids[start:start + 50]
            report = analytics.reports().query(
                ids='channel==MINE', startDate='2020-01-01', endDate=today,
                metrics='views,averageViewDuration,averageViewPercentage', dimensions='video',
                filters='video==' + ','.join(chunk), sort='-views', maxResults=len(chunk)).execute()
            columns = [header['name'] for header in report.get('columnHeaders', [])]
            for row in report.get('rows', []) or []:
                values = dict(zip(columns, row))
                video = videos.get(values.get('video'))
                if video is not None:
                    video['averageViewDuration'] = values.get('averageViewDuration')
                    video['averageViewPercentage'] = round(float(values.get('averageViewPercentage') or 0), 1)

if __name__ == '__main__':
    try: main()
    except Exception as exc: raise SystemExit(str(exc))
