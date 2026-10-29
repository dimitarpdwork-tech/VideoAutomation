# Story Shorts Studio

A local app that turns stories into narrated videos with animated captions:
vertical Shorts, or full-length videos with teaser Shorts that send viewers to
them. It can write new stories for you, then publishes everything to YouTube
channels you connect. It runs
entirely on your computer (Windows, macOS or Linux). There is no hosted backend,
subscription or shared account.

**What it does, end to end**

1. **Stories in.** One click generates new fictional stories on the themes your
   audience responds to (Claude API). You can also write your own, drop JSON
   files into `stories/`, or collect top posts from a subreddit.
2. **Narration.** [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), a free
   open-source voice model, reads the story locally. A male or female voice is
   picked from narrator clues such as "I (24M)". Reddit shorthand (AITA, MIL,
   "(25F)") is read as real words, and strong profanity can be softened so
   videos stay advertiser-friendly.
3. **Rendering.** FFmpeg puts captions over one of your background clips,
   starting at a random point so reused backgrounds look different. Shorts get
   a hook title card and a progress bar; optional music ducks under the voice.
   Full videos are 1920×1080 and get an auto-made thumbnail.
4. **Metadata.** Each video gets a title, a description that opens with the
   story's first lines, a credit link to the original post, hashtags and tags.
5. **Publishing.** Upload now, or schedule a week of videos at once and let
   YouTube publish them at your chosen times while your computer is off.
   **Autopilot** does steps 1-5 with one click.

A dashboard at <http://127.0.0.1:3000> drives all of it; every step also has a
command-line equivalent.

## Requirements

- Python 3.12 (the voice model does not support newer versions yet).
- Node.js 20.9 or newer, with npm.
- A few GB of disk for dependencies and the voice model.
- Your own Google Cloud project with an OAuth "Desktop app" client (see below).
- At least one vertical (1080×1920) background MP4 you have the rights to use.

## Install

**Windows:** double-click `setup.cmd`. If the Python launcher cannot find 3.12,
pass its path: `setup.cmd "C:\Path\To\Python312\python.exe"`.

**macOS / Linux:**

```bash
./setup.sh                      # or: ./setup.sh /path/to/python3.12
```

Setup creates two Python environments (`.venv` for video/upload tools,
`.venv-tts` for narration), builds the dashboard and creates an unconnected
"Main channel" profile. It connects nothing and enables no automation. The voice
model downloads on first use.

Start the dashboard with `start_dashboard.cmd` (Windows) or
`./start_dashboard.sh`, keep the window open, and open <http://127.0.0.1:3000>.

## Connect a YouTube channel

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen. While it is in Testing, add the Google
   accounts you will sign in with as test users.
3. Create an OAuth client of type **Desktop app**, download the JSON and save it
   as `credentials/client_secret.json`.
4. In the dashboard, pick the profile and click **Connect channel**, then choose
   the right channel in the browser. Every upload re-checks that it is going to
   that same channel.
5. Use **+ Add channel** for more profiles; each is authorized separately and
   can use its own client JSON in `channels/<id>/credentials/`.

### Videos stay private? Read this

Google locks every video uploaded through an **unaudited** API project to
private, whatever visibility you request. The uploader warns you when this
happens. To publish publicly through the API you must pass Google's
YouTube API Services compliance audit for your project (search "YouTube API
Services audit and quota extension form"). Until then, you can upload as private and switch videos to
public by hand in YouTube Studio. See the
[upload API reference](https://developers.google.com/youtube/v3/docs/videos/insert).

## Channels and presets

Run several channels, each clearly different. **+ Add channel** offers three
channel types that set a distinct voice, look, format and posting time:

| Type | Format | Voice and look | Posts (audience time) |
|---|---|---|---|
| Horror fiction | Full video + teaser Short | Slow male narrator, cold grade, serif phrase captions | 21:00 New York |
| History stories for sleep | Long video only (2–3 hours) | Soft British female narrator, warm grade, no title card | 22:00 New York |
| Revenge & drama stories | Full video + teaser Short | Brisk narrator, word-by-word captions | 17:30 New York |

Every setting can be changed afterwards. Schedule times are in your audience's
time zone, not yours.

## Staying monetised: built-in protections

YouTube judges channels as a whole for mass-produced, repetitive content and
has terminated channels that run on templates. The app is built to keep a
human in charge and channels distinct:

- **Nothing uploads without your approval.** New videos land in **Review**,
  where you watch them, fix titles, and approve or reject, one at a time or in
  bulk. Autopilot stops there too.
- **Daily cap per channel** (Settings → Protection; default 3, a full video and
  its teaser count as two).
- **Sameness warnings:** a video whose title or opening is too close to the
  channel's recent ones, or follows the same title pattern, is flagged in Review.
- **Distinct channels:** presets give each channel its own voice, captions,
  colour grade, calls to action and posting time; calls to action rotate.
- **Disclosure as the rules require:** YouTube asks creators to label
  *realistic* altered or synthetic content (photoreal AI scenes, altered real
  events, real people). Stories narrated over real footage or photos are not on
  that list; a video that does contain such material is labelled automatically.

None of this guarantees monetisation; what YouTube rewards is content viewers
find worth watching. See "Making money with it" below.

## Formats

Choose per channel in **Settings → Format**.

- **Shorts only.** One vertical Short (up to 3 minutes) per story.
- **Long video only.** One horizontal video per story, up to 4 hours (videos
  over 15 minutes need a phone-verified YouTube account). Made for the sleep
  channel.
- **Full video + teaser Short.** Each story becomes:
  - a **full video** (horizontal, up to 15 minutes by default) with a thumbnail;
  - a **teaser Short** (about 45 s) that tells the opening, stops at the
    cliffhanger, and ends with a spoken call to action, e.g. "Want to know how
    it ends? The full story is linked right above my name."

  The full video is always uploaded first, and a teaser never goes live before
  its full video. Full videos also earn
  long-form watch hours, which count toward monetization; Shorts views do not.

  **One manual step:** links in Shorts descriptions are not clickable, and
  YouTube's API cannot set a Short's **Related video** (the tappable link above
  the channel name). After each teaser uploads, the
  dashboard lists it with an "Open Short in Studio" button: choose
  *Related video*, pick the full video, save, then click *Done*.

  AI-written stories mark the best cliffhanger themselves; for other stories the
  teaser stops at a sentence break near the teaser length.

## Generate stories with AI

**Generate stories** writes new fictional stories with the Claude API.

- **What it learns from:** your channel's own videos ranked by views, and
  collected Reddit stories ranked by upvotes. It sees **titles and numbers
  only**, never the story texts, and is told to write a completely new story
  (new characters, events and details) on the themes that work.
- **Originality guard:** every result is compared with every story in your
  library. Anything that shares too much wording, or has a near-identical
  title, is rejected and rewritten. This stops copying; it does not stop
  stories from feeling alike, which is what the sameness warnings in Review
  are for.
- **Labelling:** generated stories are marked as fiction, and the fiction note
  can be added to descriptions with `{fiction_note}`.
- **Setup:** create an API key at [console.anthropic.com](https://console.anthropic.com),
  then paste it in **Settings → Claude API key**. It is stored only on your
  computer (`credentials/anthropic_api_key.txt`), or you can set
  `ANTHROPIC_API_KEY` instead. API usage is billed by Anthropic; the cheaper
  `claude-haiku-5-5` model can be chosen in Settings.

## Autopilot

**Run autopilot** generates stories (when an API key is saved) and produces the
videos. They wait in **Review**; once you approve them, **Schedule on YouTube**
publishes them over the following days. To run production weekly with Windows
Task Scheduler or cron:

```bash
.venv/bin/python autopilot.py --channel main --count 7
```

Review in bulk whenever you have time: `python review.py --channel main list`
and `python review.py --channel main approve --batch <batch>` do the same from
the command line.

## Create videos

1. Put backgrounds in `backgrounds/` named `background_000.mp4`,
   `background_001.mp4`, … Longer clips give more variety, since each video
   starts at a random point. Use footage you recorded or licensed; clips ripped
   from other creators get Content ID claims. Vertical clips also work for full
   videos: they are shown centred over a blurred copy of themselves.
2. Optional: put music you are allowed to use (MP3, M4A, WAV, OGG, FLAC) in
   `music/`. A random track plays under each video and lowers automatically
   while the narrator speaks.
3. Add or generate stories.
4. Pick a channel, review **Settings**, choose a count and click
   **Create videos**. One batch runs at a time.

Finished videos appear in **Review**. A story that needs editing (a passage
pasted twice, too long for a Short, a full video over the minute limit) is
renamed `<id>_review.json`; a story that failed for another reason stays in the
library. Either way the batch carries on, and the dashboard lists what happened.

Rendering uses your graphics card when it has a hardware encoder (NVIDIA, Intel,
AMD or Apple) and falls back to the CPU otherwise; the narrator voice also uses
an NVIDIA card when one is present.

### Adding stories

- **Write your own:** click **+ Write a story** in the dashboard. Original
  writing is what YouTube's monetization review looks for (see below).
- **Files:** any JSON with `title` and `text` in the profile's stories folder
  (`stories/` for the main profile, `channels/<id>/stories/` for others).
  Optional `url` and `author` fields produce a credit line.
- **Collect from Reddit:**

  ```bash
  .venv/bin/python -m pip install -r requirements-scraper.txt   # Windows: .venv\Scripts\python.exe
  .venv/bin/python scraper.py --subreddit stories --time all --scrolls 5
  ```

  Chrome opens; complete any checks, then press Enter in the terminal.
  Reddit posts belong to their authors. Ask permission or keep the credit
  line on, and respect Reddit's terms.

The same story is never used twice, even across profiles.

## Settings

| Setting | What it controls |
|---|---|
| Format | Shorts only, full video + teaser Short, or long video only; word limits and teaser length |
| Protection | Approval before upload (on by default), uploads per day |
| Calls to action | Several teaser endings, one picked at random each time |
| Colour grade, caption font and colour | Each channel's look: none, cold, warm, faded or noir |
| Visibility | Public, unlisted or private uploads |
| YouTube category | Defaults to Entertainment |
| Hashtags | Up to 15, shown above the title (e.g. `#shorts #storytime`) |
| Tags | Search tags sent with the upload |
| Description templates | One for Shorts / teasers, one for full videos. Placeholders: `{hook}` first lines, `{credit}` link to the original, `{fiction_note}`, `{hashtags}`, `{title}`, `{category}`, `{full_url}` (teasers) |
| Credit original author | Adds "Original story by u/…: link" when the story has a source |
| Voice, speed, pause | Kokoro voice (e.g. `af_heart`, `am_michael`, `bf_emma`); optional male/female voices; speaking speed, pause after sentences |
| Captions | Yellow word-by-word or white phrases (full videos always use phrases) |
| Hook title card | Seconds the title is shown at the start (0 = off) |
| Progress bar, music volume | Shorts progress bar; volume of tracks from `music/` |
| Advertiser-friendly language | Softens strong profanity in narration and captions |
| Claude model, story category | Which model writes stories, and the theme it should lean toward |
| Word limits | Which stories qualify for this channel |
| Time zone, daily times | Used by both scheduling options below |

## Publishing

Only approved videos are uploaded or scheduled.

- **Upload now:** publishes one approved video with the channel's visibility. In
  the funnel format this alternates: full video, then its teaser.
- **Schedule on YouTube (recommended):** uploads up to 50 approved videos now as
  private, each with a publish time from your daily times. YouTube publishes
  them; your computer can be off. Already-used slots are skipped, so running it
  again fills the next free days. Command line:
  `python preschedule.py --channel main --count 7` (add `--dry-run` to preview).
- **Local schedule:** enable it in Settings and keep `start_scheduler.cmd` /
  `./start_scheduler.sh` running. It uploads at each time while the computer is
  awake and online. A time reached up to 15 minutes late still runs; times
  missed while the computer was off are not replayed.

YouTube's API has a daily quota per Google Cloud project, which limits how many
uploads you can do per day. Spread large batches over several days.

Uploads are recorded by file fingerprint, so a video is never uploaded twice.

- **Refused before starting** (daily quota, upload limit, permissions): nothing
  is recorded; retry later.
- **Interrupted midway** (network drop, computer closed): the next run resumes
  from where it stopped.
- **Unknown result** (for example a power cut at the last moment): the next run
  looks for the video on your channel and either records it or uploads again.
  It never blocks other videos.
- **Sign-in expired:** the dashboard says so and asks you to reconnect.

Custom thumbnails for full videos are uploaded automatically when your channel
allows it (YouTube requires a phone-verified account); otherwise the `.jpg`
next to the video is ready to upload in Studio.

## Command line

```bash
# Windows: replace .venv/bin/python with .venv\Scripts\python.exe
.venv/bin/python story_generator.py --channel main --count 5
.venv/bin/python autopilot.py --channel main --count 5
.venv/bin/python review.py --channel main list
.venv/bin/python review.py --channel main approve --batch batch_20261029_120000
.venv-tts/bin/python produce_batch.py --channel main --count 12
.venv/bin/python upload_next.py --channel main --dry-run
.venv/bin/python upload_next.py --channel main
.venv/bin/python upload_next.py --channel main --publish-at 2026-11-02T18:00:00+02:00
.venv/bin/python preschedule.py --channel main --count 7
```

## Making money with it: read before you invest time

- **Monetization needs originality.** YouTube's Partner Program does not pay for
  "inauthentic", mass-produced or repetitive content, and channels that only
  read other people's posts over gameplay are a common rejection. Original
  stories (written or generated), your own footage and a consistent voice give
  you a real chance. Automation helps you produce; it does not replace review
  of what goes out. Watch a few videos from each batch before scheduling.
- **Eligibility:** 1,000 subscribers plus either 10 million Shorts views in 90
  days or 4,000 long-form watch hours in 12 months.
- **Shorts revenue per view is low.** The full video + teaser format exists for
  this reason: Shorts bring people in, and long videos earn more per view.
- **Never buy or bot views.** It violates YouTube's terms and gets channels
  terminated.

## Privacy and troubleshooting

Credentials, tokens, settings, logs, models, generated media and your stories
stay on your computer and are excluded from Git. The dashboard only accepts
requests from your own machine.

- **No videos available:** create a batch first; uploading never generates.
- **No eligible stories:** check word limits (Shorts and full videos have
  separate limits), titles (max 100 characters), and that stories are not
  marked `_used` or `_review`.
- **Story generation fails:** the message says why: an invalid API key, an
  unknown model name, or a rate limit.
- **Teaser shows "After full video":** the full video has to be uploaded first;
  scheduling and Upload now handle this order automatically.
- **A job "is running" but nothing is:** locks left by a crashed program are
  cleared automatically the next time a job starts.
- **A data file was damaged** (for example by a power cut): the app falls back
  to the `.bak` copy kept next to it and tells you.
- **Logs:** every dashboard job is saved in `output/shared/logs/`.
- **Narration fails on Linux:** install `espeak-ng` (e.g. `sudo apt install espeak-ng`).
- **Sign-in stopped working:** reconnect the profile; Google may require periodic
  re-authorization while the consent screen is in Testing.
- **Uncertain upload or stale lock:** check YouTube Studio and make sure no
  worker is running before editing upload records or deleting a `.lock` file.

## Development

```bash
.venv/bin/python -m unittest discover -s tests
cd dashboard && npm run build
```
