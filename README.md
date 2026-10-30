# Story Shorts Studio

A local app that turns stories into narrated videos with animated captions:
vertical Shorts, or full-length videos with teaser Shorts that send viewers to
them. It can write new stories for you, then publishes everything to YouTube
channels you connect. It runs
entirely on your computer (Windows, macOS or Linux). There is no hosted backend,
subscription or shared account.

**What it does, end to end**

1. **Stories in.** One click turns the most-upvoted stories you collected from
   Reddit into new, original stories that keep only the concept, or writes new
   ones on the themes your audience responds to (Claude API). Every story opens
   with a hook. You can also write your own or drop JSON files into `stories/`.
2. **Narration.** [Chatterbox](https://github.com/resemble-ai/chatterbox), a free
   open-source voice model that sounds human, reads the story on your computer
   in a narrator voice cloned from a short clip, and acts out tense moments
   (pauses, hushed lines). [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M)
   is the fast, lighter alternative. Reddit shorthand (AITA, MIL, "(25F)") is
   read as real words, and strong profanity can be softened so videos stay
   advertiser-friendly.
3. **Rendering.** FFmpeg puts captions over one atmospheric free-licence photo
   per story, slowly panned under a vignette (found automatically), or over
   your own background clips. Shorts get a hook title card and a progress bar;
   optional music ducks under the voice. Full videos are 1920×1080 and get an
   auto-made thumbnail.
4. **Metadata.** Each video gets a title, a description that opens with the
   story's first lines, a credit link to the original post, hashtags and tags.
5. **Publishing.** Upload now, or schedule a week of videos at once and let
   YouTube publish them at your chosen times while your computer is off.
   **Autopilot** does steps 1-4 with one click and stops at your review.
6. **TikTok.** Approved videos can be exported as vertical parts of just over a
   minute, with captions to paste, for posting by hand.

A dashboard at <http://127.0.0.1:3000> drives all of it; every step also has a
command-line equivalent.

## Requirements

- Python 3.12 (the voice model does not support newer versions yet).
- Node.js 20.9 or newer, with npm.
- About 10 GB of disk for dependencies and the voice models.
- For Chatterbox, ideally an NVIDIA graphics card (any RTX card works). Without
  one it runs on the processor, which is slow (several minutes per minute of
  audio). Kokoro runs fine without a graphics card.
- Your own Google Cloud project with an OAuth "Desktop app" client (see below).
- For the photo background nothing else; for the clip background, at least one
  vertical (1080×1920) MP4 you have the rights to use.

## Install

**Windows:** double-click `setup.cmd`. If the Python launcher cannot find 3.12,
pass its path: `setup.cmd "C:\Path\To\Python312\python.exe"`.

**macOS / Linux:**

```bash
./setup.sh                      # or: ./setup.sh /path/to/python3.12
```

Setup creates three Python environments (`.venv` for video/upload tools,
`.venv-tts` for Kokoro, `.venv-voice` for Chatterbox), builds the dashboard and
creates an unconnected "Main channel" profile. It connects nothing and enables
no automation.

The Chatterbox step (`setup_voice.py`) finds your NVIDIA card and installs the
matching GPU build of PyTorch (RTX 50-series cards included), then downloads the
voice model (about 3 GB). If it fails, setup still finishes and Kokoro works;
run `setup_voice.cmd` / `./setup_voice.sh` again later.

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
| Horror fiction | Full video + teaser Short | Chatterbox, dramatic; one dark photo per story; cold grade, serif phrase captions | 21:00 New York |
| History stories for sleep | Long video only (2–3 hours) | Chatterbox, calm; one historic photo per story; warm grade, no title card | 22:00 New York |
| Revenge & drama stories | Full video + teaser Short | Chatterbox, natural; background clips; word-by-word captions | 17:30 New York |

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

## Narration voices

Choose per channel in **Settings → Voice and look**.

- **Chatterbox** (default for new channels) sounds like a person reading, and
  follows the delivery cues the story generator writes into stories:
  `[pause]` before a reveal, `[tense]`, `[whisper]`, `[urgent]` and `[calm]`
  lines. The cues never show in captions or descriptions. **Expressiveness**
  sets how dramatic it is (0.35 calm, 0.5 natural, 0.7 dramatic).
- **Narrator clips.** Chatterbox clones a narrator from 10–30 seconds of clean
  speech in the `voices` folder; each channel can have its own. **Settings →
  Hear the narrators → Make voice samples** creates five starter clips made
  with Kokoro voices (which belong to nobody, so there are no rights issues)
  and reads the same short horror passage with each, so you can pick by ear.
  Only use your own voice, a voice you have written permission for, or a
  stock clip licensed for commercial use.
- **Quality checks.** Chatterbox speaks a sentence or two at a time. A piece
  that comes out far too short or long (a skipped or invented phrase) is
  spoken again; if it still looks wrong, the video gets a warning in Review
  naming the line to listen to. Captions are timed to the actual voice with a
  forced aligner.
- **Kokoro** is faster and needs no graphics card, but reads every line the
  same way.

Chatterbox adds an inaudible watermark (Resemble AI's "Perth") to its audio,
as its licence intends; you will not hear it.

## Background photos

With **Settings → Format → Background: one photo per story**, each story gets
one atmospheric photo, slowly panned under a vignette: the classic look of
narrated horror and sleep channels.

- The story generator suggests a search phrase per story (e.g. "abandoned
  farmhouse at night"); otherwise the channel's image search phrases are used.
- Sources: [Pexels](https://www.pexels.com/api/) with a free API key (Settings),
  then [Openverse](https://openverse.org), limited to public-domain (CC0/PDM)
  images. Both allow use in monetised videos. Pexels' API guidelines ask for a
  link back where possible, so videos with a Pexels photo get one line at the
  end of the description ("Background photo by … on Pexels: link").
- Every photo is used once across all channels. Where it came from is kept in
  `output/shared/images_used.json` and shown in Review.
- If no photo is found and the channel also has background clips, a clip is
  used and Review says so.

## Generate stories with AI

**Generate stories** writes new fictional stories with the Claude API.

- **From collected stories (concepts):** while the channel has unused stories
  collected from Reddit, it takes the most-upvoted one, keeps only its core
  idea, and writes a new story around it with a different narrator,
  characters, setting, events and ending. The result is checked against the
  source (no shared 8-word phrase, near-zero overlap, a different title) and
  rewritten if it is too close. Each collected story lends its concept once
  and is never narrated itself, unless you set **Stories collected from
  Reddit → Narrate them as they are** (only with the author's permission).
- **From themes:** otherwise it writes from your channel's best videos (views
  and average percentage watched) and collected titles ranked by upvotes,
  seeing **titles and numbers only**.
- **Hook first:** the first sentence must drop the listener into the story;
  slow openers ("So this happened…", greetings, long first sentences) are
  rejected and rewritten. Stories you add yourself get a "weak hook" warning
  in Review instead.
- **Long sleep stories** are written as an outline, then one chapter at a time,
  to the length set in **Settings → Format** (default 15,000 words for the
  sleep preset, about 2 hours).
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
| Narration engine, narrator, expressiveness | Chatterbox (narrator clip from `voices/`, expressiveness, optional male/female clips, standard or turbo model) or Kokoro (voice ID such as `am_michael`, optional male/female voices) |
| Speed, pause | Speaking speed, pause after sentences |
| Background | One photo per story (search phrases in advanced settings) or background clips |
| Stories collected from Reddit | Use only their concept (default) or narrate them as they are |
| TikTok part length, hashtags | Target length of TikTok parts (never under 61 s) and the hashtags in their captions |
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

## TikTok

**Export for TikTok** turns every approved video into vertical parts for
TikTok, which pays (Creator Rewards) only for videos longer than one minute:

- Full videos are re-cut from their narration at sentence ends into parts of
  about the channel's TikTok part length, never under 61 seconds. Each part
  starts with "Title · Part N" and ends with "Part N+1 is on my profile".
- Shorts are exported as they are.
- Files land in each batch folder under `tiktok/`: the videos, a caption file
  per part, and `HOW_TO_POST.txt`. The dashboard lists them with download links.

Posting stays manual: TikTok's posting API only allows private posts until
TikTok approves an app, and a new account is safest posted by hand. TikTok asks
creators to label realistic AI-generated audio, so switch on **AI-generated
content** under *More options* when posting; it shows a small tag and labelled
videos are not penalised. Creator Rewards also need 10,000 followers, 100,000
views in 30 days and an eligible country.

## Retention numbers

Channels connected with this version also grant read-only YouTube Analytics.
The dashboard then shows the average percentage watched next to views, and the
story generator favours themes people watch to the end. Channels connected
earlier keep working; click **Reconnect channel** once to add retention.

## Command line

```bash
# Windows: replace .venv/bin/python with .venv\Scripts\python.exe
.venv/bin/python story_generator.py --channel main --count 5
.venv/bin/python autopilot.py --channel main --count 5
.venv/bin/python review.py --channel main list
.venv/bin/python review.py --channel main approve --batch batch_20261029_120000
.venv-tts/bin/python produce_batch.py --channel main --count 12
.venv-tts/bin/python voice_samples.py
.venv-voice/bin/python chatterbox_narrator.py stories/1nspy0i.json --clip starter_deep_male.wav
.venv/bin/python tiktok_export.py --channel main
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
