"""Channel configuration, identity checks, and shared duplicate records."""
import contextlib
import copy
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHANNELS = ROOT / 'channels'
SHARED = ROOT / 'output' / 'shared'
PRIVACY_OPTIONS = ('public', 'unlisted', 'private')
FORMATS = ('shorts', 'funnel', 'long')

# Every profile is read through these defaults, so profiles created by older
# versions pick up new settings without manual edits.
CHANNEL_DEFAULTS = {
    'youtube_channel_id': None, 'youtube_channel_name': None,
    'voice': 'af_heart', 'speed': 1.0, 'period_pause': 0.25,
    'caption_style': 'words', 'story_category': 'General stories',
    'backgrounds': [], 'min_words': 1, 'max_words': 400,
    'privacy': 'public', 'category_id': '24',
    'hashtags': ['#shorts', '#storytime'],
    'tags': ['story', 'storytime', 'shorts'],
    'description_template': '{hook}\n\n{credit}\n\n{fiction_note}\n\n{hashtags}',
    'credit_source': True,
    # 'shorts': one Short per story. 'funnel': a full horizontal video per story
    # plus a vertical teaser Short that stops at the cliffhanger. 'long': only the
    # full horizontal video (for example 2-3 hour sleep stories).
    'video_format': 'shorts',
    'full_min_words': 300, 'full_max_words': 2400, 'max_full_minutes': 15,
    'teaser_seconds': 45,
    'teaser_cta': 'Want to know how it ends? The full story is linked right above my name.',
    'teaser_description_template': '{hook}\n\n\u25b6 Full story: {full_url}\n\n{hashtags}',
    'full_description_template': '{hook}\n\n{credit}\n\n{fiction_note}\n\n{hashtags}',
    'fiction_note': 'This story is fiction. Names, characters and events are invented.',
    'clean_language': True, 'title_card': True, 'title_card_seconds': 3.0,
    'progress_bar': True, 'music_volume': 0.12,
    'generator_model': 'claude-sonnet-5-5',
    # Protection against mass-production enforcement: nothing uploads without your
    # approval, uploads per channel per day are capped, and each channel keeps its
    # own look and sound.
    'require_review': True, 'max_uploads_per_day': 3,
    'teaser_ctas': [],
    'voice_male': None, 'voice_female': None,
    'caption_font': 'Arial Black', 'caption_color': '#FFD400', 'phrase_color': '#FFFFFF',
    'color_grade': 'none',
    # Narration engine. 'kokoro' is fast and light; 'chatterbox' sounds human, acts
    # out delivery cues and clones a narrator from a short clip in voices/ ('' =
    # its built-in voice). Chatterbox needs setup_voice and ideally an NVIDIA card.
    'voice_engine': 'kokoro', 'voice_clip': '', 'voice_clip_male': None, 'voice_clip_female': None,
    'chatterbox_model': 'standard', 'expressiveness': 0.5,
    # The narrator persona: one character for voice, words and delivery (see persona.py).
    'persona': None,
    # Signature sound applied to the narration: natural, deep, uncanny, tape or room.
    'voice_character': 'natural',
    # Picture behind the narration: 'clips' (background videos) or 'image' (one
    # free-licence atmospheric photo per story, slowly panned).
    'background_mode': 'clips', 'image_keywords': [],
    # Stories collected from Reddit: 'rewrite' uses them only as concepts for new
    # original stories (default); 'narrate' reads them as they are (only with the
    # author's permission).
    'collected_stories': 'rewrite',
    # Long format: how many words the story generator writes (chaptered).
    'long_target_words': 12000,
    # TikTok export: full videos are cut into vertical parts of about this length.
    'tiktok_part_seconds': 75, 'tiktok_hashtags': [],
    'schedule': {'enabled': False, 'timezone': 'Europe/Berlin', 'times': ['10:00', '18:00']},
}


# Starting points for new channels. Each gives a channel its own voice, look and
# rhythm, so channels from the same pipeline do not read as one template.
PRESETS = {
    'horror': {
        'story_category': 'Horror fiction', 'video_format': 'funnel', 'voice': 'am_michael', 'speed': 0.95,
        'period_pause': 0.35, 'caption_style': 'phrases', 'caption_font': 'Georgia', 'phrase_color': '#E8E2D0',
        'caption_color': '#C8102E', 'color_grade': 'cold', 'music_volume': 0.10,
        'hashtags': ['#horrorstories', '#scarystories'], 'tags': ['horror story', 'scary story', 'creepy'],
        'voice_engine': 'chatterbox', 'expressiveness': 0.6, 'background_mode': 'image', 'voice_character': 'deep',
        'image_keywords': ['abandoned house night', 'dark forest fog', 'empty hallway dark', 'old staircase shadows',
                           'foggy road night', 'abandoned hospital corridor', 'dark window night house'],
        'tiktok_hashtags': ['#horrortok', '#scarystories', '#creepy'],
        'teaser_ctas': ['You do not want to miss how this ends. The full story is linked above my name.',
                        'It gets so much worse. Tap the link above my name for the rest.',
                        'The ending still keeps me up at night. Full story above my name.'],
        'schedule': {'timezone': 'America/New_York', 'times': ['21:00']},
    },
    'sleep-history': {
        'story_category': 'History for sleep', 'video_format': 'long', 'voice': 'bf_emma', 'speed': 0.85,
        'full_min_words': 3000, 'full_max_words': 25000, 'max_full_minutes': 240,
        'period_pause': 0.6, 'caption_style': 'phrases', 'caption_font': 'Palatino Linotype',
        'phrase_color': '#F3E9D2', 'color_grade': 'warm', 'music_volume': 0.08, 'title_card': False,
        'progress_bar': False, 'hashtags': ['#sleepstory', '#history'], 'tags': ['sleep story', 'history for sleep'],
        'voice_engine': 'chatterbox', 'expressiveness': 0.35, 'background_mode': 'image', 'long_target_words': 15000,
        'image_keywords': ['ancient ruins sunset', 'medieval castle mist', 'old library candles', 'roman forum ruins',
                           'stone village night', 'ancient egypt temple'],
        'schedule': {'timezone': 'America/New_York', 'times': ['22:00']},
    },
    'drama': {
        'story_category': 'Revenge and workplace drama', 'video_format': 'funnel', 'voice': 'af_heart',
        'speed': 1.1, 'period_pause': 0.15, 'caption_style': 'words', 'caption_font': 'Arial Black',
        'caption_color': '#FFD400', 'color_grade': 'none', 'music_volume': 0.12,
        'voice_engine': 'chatterbox', 'expressiveness': 0.55, 'tiktok_hashtags': ['#storytime', '#revenge', '#drama'],
        'hashtags': ['#storytime', '#revenge'], 'tags': ['revenge story', 'storytime', 'drama'],
        'teaser_ctas': ['Wait until you hear what they did next. Full story above my name.',
                        'This is only the beginning. The rest is linked above my name.',
                        'You will not believe how this ends. Tap above my name.'],
        'schedule': {'timezone': 'America/New_York', 'times': ['17:30']},
    },
}
GRADES = ('none', 'cold', 'warm', 'faded', 'noir')
VOICE_CHARACTERS = ('natural', 'deep', 'uncanny', 'tape', 'room')


def venv_python(env='.venv'):
    """Path to a project virtual environment's interpreter on any OS."""
    folder = ROOT / env
    return folder / 'Scripts' / 'python.exe' if os.name == 'nt' else folder / 'bin' / 'python'


def with_defaults(config):
    merged = copy.deepcopy(CHANNEL_DEFAULTS)
    for key, value in config.items():
        if key == 'schedule' and isinstance(value, dict):
            merged['schedule'].update(value)
        else:
            merged[key] = value
    return merged

class DataFileError(RuntimeError):
    """A state file is unreadable and has no usable backup."""


def _parse(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def read_json(path, default=None):
    """Read a JSON state file; fall back to its .bak copy if it is corrupt."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return _parse(path)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        backup = path.with_name(path.name + '.bak')
        if backup.exists():
            try:
                data = _parse(backup)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            else:
                print(f'WARNING: {path.name} was damaged; using its backup copy.', file=sys.stderr, flush=True)
                return data
        raise DataFileError(f'{path} is damaged ({exc}) and has no usable backup. '
                            'Restore it from a copy, or delete it if you are sure it is not needed.') from exc


def _replace(source, target, attempts=10):
    # Antivirus, OneDrive or a reader holding the file can briefly block a rename on Windows.
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.2 * (attempt + 1))


def write_json(path, data, private=False):
    """Atomic, flushed write that keeps the previous version as <name>.bak.

    private=True makes the file readable by the owner only (tokens, keys).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if private:
            os.chmod(temporary, 0o600)
        if path.exists():
            backup = path.with_name(path.name + '.bak')
            try:
                _parse(path)  # never let a damaged file overwrite a good backup
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            else:
                shutil.copy2(path, backup)
                if private:
                    os.chmod(backup, 0o600)
        _replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    if os.name != 'nt':
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass


def update_json(path, change, default=None, private=False):
    """Read-modify-write under a short file lock, so concurrent writers merge instead of overwrite."""
    with lock('json-' + hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:16], wait=30):
        data = read_json(path, copy.deepcopy(default))
        result = change(data)
        write_json(path, data if result is None else result, private=private)
        return data if result is None else result


def load_channel(channel='main'):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,39}', channel):
        raise ValueError('Channel ID must use lowercase letters, numbers, hyphens or underscores.')
    config = read_json(CHANNELS / channel / 'config.json')
    if not config:
        raise ValueError(f'Unknown channel: {channel}')
    return with_defaults(config)

def paths(channel='main'):
    config = load_channel(channel)
    # Keep existing files in place for the original channel.
    base = ROOT if channel == 'main' else CHANNELS / channel
    return {name: base / name for name in ('credentials','stories','videos','narrations','output')}

def create_channel(channel, name, preset=None):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,39}', channel):
        raise ValueError('Use a short lowercase channel ID, e.g. wholesome-stories.')
    config_path = CHANNELS / channel / 'config.json'
    if config_path.exists():
        raise ValueError('That channel ID already exists.')
    if preset and preset not in PRESETS:
        raise ValueError(f'Unknown preset {preset!r}; choose one of: {", ".join(PRESETS)}.')
    base = copy.deepcopy(PRESETS.get(preset, {}))
    config = with_defaults({**base, 'id': channel, 'name': name.strip() or channel, 'preset': preset})
    write_json(config_path, config)
    for folder in paths(channel).values(): folder.mkdir(parents=True, exist_ok=True)
    return config

def story_fingerprint(text):
    normalized = ' '.join(unicodedata.normalize('NFKC',text).casefold().split())
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

def pid_alive(pid):
    """True if a process with this id is running (best effort, any OS)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_owner(target):
    """PID recorded in a lock file, or None if unreadable."""
    try:
        return int(Path(target).read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def clear_stale_lock(target):
    """Remove a lock whose process is gone. Returns True if one was removed."""
    target = Path(target)
    if target.exists() and not pid_alive(lock_owner(target)):
        target.unlink(missing_ok=True)
        return True
    return False


@contextlib.contextmanager
def file_lock(target, label, wait=0):
    """Exclusive lock file holding our PID; a lock left by a crashed process is cleared automatically."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + wait
    while True:
        try:
            handle = target.open('x')
            break
        except FileExistsError:
            if clear_stale_lock(target):
                continue
            if time.monotonic() >= deadline:
                raise RuntimeError(f'Another {label} job is running (process {lock_owner(target)}). '
                                   'Wait for it to finish.')
            time.sleep(0.2)
    try:
        with handle:
            handle.write(f'{os.getpid()} {time.time():.0f}')
            handle.flush()
        yield
    finally:
        if lock_owner(target) == os.getpid():
            target.unlink(missing_ok=True)


def lock(name, wait=0):
    return file_lock(SHARED / (name + '.lock'), name, wait)


ANALYTICS_SCOPE = 'https://www.googleapis.com/auth/yt-analytics.readonly'


class SignInExpired(RuntimeError):
    """The saved Google sign-in no longer works; the channel must be reconnected."""


def token_status(channel):
    """'missing', 'expired' (known to need reconnecting) or 'ok' (present, not known bad)."""
    credentials = paths(channel)['credentials']
    if not (credentials / 'channel_token.json').exists():
        return 'missing'
    return 'expired' if (credentials / 'reconnect_needed.json').exists() else 'ok'


def credentials_for(channel, connect=False):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    channel_paths = paths(channel)
    token = channel_paths['credentials'] / 'channel_token.json'
    marker = channel_paths['credentials'] / 'reconnect_needed.json'
    # New sign-ins also grant read-only YouTube Analytics (watch time and retention).
    # Saved sign-ins keep the permissions they were given: they are loaded with their
    # own scopes, because asking Google to refresh a token for more than it granted fails.
    scopes = ['https://www.googleapis.com/auth/youtube.upload', 'https://www.googleapis.com/auth/youtube.readonly',
              ANALYTICS_SCOPE]
    if connect:
        # A fresh sign-in never depends on the old token, which may be the broken part.
        token.parent.mkdir(parents=True, exist_ok=True)
        client = channel_paths['credentials'] / 'client_secret.json'
        if not client.exists():
            client = ROOT / 'credentials/client_secret.json'
        if not client.exists():
            raise RuntimeError('Add your own Desktop OAuth client JSON at credentials/client_secret.json first. See README.md.')
        flow = InstalledAppFlow.from_client_secrets_file(str(client), scopes)
        creds = flow.run_local_server(port=0, access_type='offline', prompt='consent select_account', timeout_seconds=300,
                                      authorization_prompt_message='Choose the Google / YouTube channel for this profile in your browser.',
                                      success_message='Channel authorization received. Return to the dashboard.')
    else:
        creds = Credentials.from_authorized_user_file(str(token)) if token.exists() else None
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                write_json(marker, {'since': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'detail': str(exc)[:300]})
                raise SignInExpired('The Google sign-in for this channel has expired or was revoked. '
                                    'Click "Reconnect channel" in the dashboard. (In Testing mode Google ends sign-ins after 7 days.)') from exc
    if not creds or not creds.valid:
        raise RuntimeError('Connect this channel in the dashboard before uploading.')
    from googleapiclient.discovery import build
    with build('youtube', 'v3', credentials=creds) as api:
        channels = api.channels().list(part='snippet', mine=True).execute().get('items', [])
    if len(channels) != 1:
        raise RuntimeError('Could not identify exactly one authorized YouTube channel.')
    actual = channels[0]
    expected = load_channel(channel).get('youtube_channel_id')
    if expected and actual['id'] != expected:
        raise RuntimeError(f"Wrong YouTube channel: expected {expected}, got {actual['id']}. Nothing uploaded.")
    if not expected and not connect:
        raise RuntimeError('Connect this profile to bind its YouTube channel first.')
    if connect:
        # Do not bind the same destination to multiple profiles by accident.
        for config_file in CHANNELS.glob('*/config.json'):
            other = read_json(config_file, {})
            if other.get('id') != channel and other.get('youtube_channel_id') == actual['id']:
                raise RuntimeError(f"This YouTube channel is already assigned to {other['name']}.")
        # Merge into the file as it is now, so settings saved during sign-in are kept.
        update_json(CHANNELS / channel / 'config.json',
                    lambda cfg: cfg.update(youtube_channel_id=actual['id'], youtube_channel_name=actual['snippet']['title']), {})
    write_json(token, json.loads(creds.to_json()), private=True)
    marker.unlink(missing_ok=True)
    if os.name != 'nt':
        try:
            os.chmod(token.parent, 0o700)
        except OSError:
            pass
    return creds, actual['id']
