# Validation

## 29 October 2026: reliability fixes and channel protections (Linux)

Passed:

- 77 offline tests (24 new), covering:
  - data recovery: a damaged state file falls back to its backup;
  - permissions: credentials are owner-only;
  - locks: a lock left by a dead process is cleared;
  - interrupted uploads: a connection drop mid-upload resumes on the next run;
  - failed and expired uploads: a failure before the session starts is safe to retry, and an expired session restarts;
  - unknown results: an uncertain upload is found on the channel instead of blocking the queue;
  - queue order: a leftover file no longer pins the queue, and a teaser finds its full video in the history;
  - approval and limits: unapproved videos never upload, and the daily cap holds;
  - crashed batches: a failing story is released and the batch continues, a stale reservation from a killed run is ignored, and resumed batches recognise uploaded files;
  - batch.json: production keeps fields the uploader and review wrote;
  - review and sameness: bulk and single review decisions work, and sameness warnings appear;
  - speech: a TL;DR line no longer erases a story, and capitalised words are not read as shorthand;
  - voices: the channel's accent is kept;
  - sign-in: an expired Google sign-in is reported, and reconnecting does not touch the broken token.
- Real renders with a test tone in place of Kokoro:
  - two Shorts in 52 s, about twice as fast as before;
  - a horror-preset full video with teaser and thumbnail;
  - the progress bar now grows (measured 50% at the halfway point);
  - a file named with a comma, an apostrophe and brackets renders.
- Live dashboard:
  - requests with another host name (DNS rebinding) and cross-site GETs are refused;
  - frame-blocking headers are present;
  - video preview streams with seeking, and path tricks are refused;
  - an upload is refused before approval;
  - approve, reject and title edits work, and the uploader picks only the approved video with its new title;
  - a preset channel can be created;
  - settings save, with plain-language validation errors.

Not validated here: real Kokoro narration, a GPU encoder (no graphics card on
the test machine), real Google sign-in, uploads, resumes against YouTube, the
dashboard UI in a browser.

## 28 October 2026: funnel format, AI stories and video extras (Linux)

Passed:

- 55 offline tests (17 new): Reddit shorthand and language cleanup, teaser
  cutting, full-video + teaser production, upload order and teaser links, AI
  disclosure, safe recovery from a quota rejection, the story generator with its
  originality guard (a copied story is rejected and rewritten; story texts never
  reach the model), and caption/filter building.
- Real production of a 757-word story: a 4-minute 1920x1080 full video with
  title card and ducked music, a thumbnail, and a 28-second teaser Short with
  progress bar that stops at the writer's chosen cliffhanger. Upload and
  scheduling dry runs put the full video first. The Kokoro voice was again
  replaced by a test tone.
- A real call to the Claude API with an invalid key returns a clear message.
- Live dashboard checks: queue video types and waiting teasers, API key saved
  locally with owner-only permissions and never sent to the browser, Studio
  checklist, settings validation, autopilot start and clean stop on error.

Not validated: story generation with a valid key, real Kokoro narration, the
dashboard in a browser, real uploads, thumbnails or scheduled publishing.

## 28 October 2026: cross-platform release (Linux, Python 3.12.13, Node 22)

Passed:

- 38 offline tests: the 25 original tests plus 13 new ones covering descriptions
  and hashtags, defaults for older profiles, review skipping, publish-time
  parsing, YouTube schedule slots (including a daylight-saving change) and
  background offsets.
- Real batch production of three stories on a generated 1080x1920 background:
  real script cleanup, voice selection, speed fitting (a 189 s narration was
  fitted to 179 s), FFmpeg rendering with word captions, random background
  start points and the full decode check. Only the Kokoro voice was replaced by
  a test tone, because the model host could not be reached from the test machine.
- Upload and YouTube-scheduling dry runs showing visibility and publish time.
- Dashboard production build; live API checks for adding a story, saving the new
  settings, rejecting bad templates, rejecting requests from other origins and
  refusing to schedule without a connected channel.

Not validated in this round: real Kokoro narration, the dashboard UI in a
browser, Google sign-in, real uploads or scheduled publishing, macOS, Windows.

## 27 October 2026: original Windows validation


Validated on 27 October 2026 using an isolated clone of the public repository on
an existing Windows laptop, with Python 3.12.15 and Node.js 22.14.0. This was not a
fresh Windows virtual machine. The application environments were newly created;
no existing account credentials, application environments, narration cache or
background collection were copied into the test workspace. Package download
caches could be reused by the installers.

## Passed

- Ran `setup.cmd` with an explicit Python 3.12 executable path. Both Python
  environments installed successfully; `pip check` reported no conflicts.
- Installed dashboard packages from the lockfile and completed the production build.
- Passed all 25 offline Python tests, including the release API-route regression test.
- Started the built dashboard in a browser and checked its video queue.
- Added an unconnected channel profile, switched profiles and saved settings.
- Downloaded the narration model and English language resources on first use.
- Generated a real 39.4-second video from a bundled story through the command line.
- Generated a second 44.55-second video using the dashboard's Create videos button.
- Used a temporary generated vertical background, rather than a bundled media asset.
- Decoded both completed videos fully with FFmpeg and inspected a rendered caption frame.
- Previewed an upload using `--dry-run`; no video was uploaded.
- Checked disabled startup uploading and the daily scheduler's one-shot dry run.
- Confirmed scheduling remained disabled and no OAuth credential files were created.
- Verified the upload button was disabled without a connected account and that
  Connect channel explained where to supply the missing OAuth client JSON.

## Fixes found during validation

The original release ignored every directory named `channels`, which also hid
`dashboard/app/api/channels/route.js` from Git. The ignore rule now applies only
to the root local-data directory, and the dashboard endpoint is distributed.

The setup script now accepts a Python executable path for installations that the
Windows launcher does not resolve through `py -3.12`.

## Not validated live

- A new user's Google OAuth sign-in, real YouTube upload or analytics retrieval.
- Publishing at an actual scheduled time or on a real Windows sign-in.
- Live Reddit collection.
- Other Windows machines, hardware configurations, antivirus products or future
  dependency releases.

This validation supports the local setup and video-production flow on the tested
machine. It does not guarantee that every external service or environment works.
