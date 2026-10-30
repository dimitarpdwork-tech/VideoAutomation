// Dashboard backend: reads the same files as the Python scripts and starts them as jobs.
// Rules about what may be uploaded live in Python; this file only mirrors them for display.
import fs from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {createHash, randomBytes} from 'node:crypto';

const root = path.resolve(process.cwd(), '..');
const SHARED = path.join(root, 'output', 'shared');
const KEY_FILE = () => path.join(root, 'credentials', 'anthropic_api_key.txt');
const PEXELS_FILE = () => path.join(root, 'credentials', 'pexels_api_key.txt');
const VOICES_DIR = path.join(root, 'voices');
const SAMPLES_DIR = path.join(SHARED, 'voice_samples');
const CLIP_FILE = /^[A-Za-z0-9_][A-Za-z0-9_ .-]{0,80}\.(wav|mp3|flac|m4a|ogg)$/i;
const SAMPLE_FILE = /^((kokoro|chatterbox)_[A-Za-z0-9_ .-]{1,80}|character_[a-z]+)\.wav$/;
const DESIGNS_DIR = path.join(SHARED, 'voice_designs');
const DESIGN_FILE = /^design_\d{8}_\d{6}_\d\.wav$/;
const CHANNEL_ID = /^[a-z0-9][a-z0-9_-]{0,39}$/;
const BATCH_ID = /^[a-zA-Z0-9_-]+$/;
const ITEM_FILE = /^(tiktok\/)?[A-Za-z0-9_.-]+\.(mp4|jpg|txt)$/;
const VOICE = /^[abefhijpz][fm]_[a-z]+$/;
const HEX = /^#[0-9A-Fa-f]{6}$/;
const WORDS = /[\p{L}\p{N}_]+(?:['’\-][\p{L}\p{N}_]+)*/gu;  // same as Python's \w-based count

const python = (env = '.venv') => process.platform === 'win32'
  ? path.join(root, env, 'Scripts', 'python.exe') : path.join(root, env, 'bin', 'python');

// ---------------------------------------------------------------------------
// Request checks

const LOCAL_HOSTS = ['localhost', '127.0.0.1', '[::1]'];
export function isLocalRequest(request) {
  try {
    const origin = new URL(request.headers.get('origin'));
    return origin.host === request.headers.get('host') && LOCAL_HOSTS.includes(origin.hostname);
  } catch { return false; }
}
// GETs carry no Origin; browsers mark cross-site requests with Sec-Fetch-Site.
export function isSameSiteGet(request) {
  const site = request.headers.get('sec-fetch-site');
  return !site || site === 'same-origin' || site === 'none';
}

// ---------------------------------------------------------------------------
// Files: same conventions as channel_config.py (backups, atomic writes, shared locks)

async function readJson(file, fallback) {
  try { return JSON.parse(await fs.readFile(file, 'utf8')); } catch (error) {
    if (error.code === 'ENOENT') return fallback;
    if (error instanceof SyntaxError) {
      try { return JSON.parse(await fs.readFile(file + '.bak', 'utf8')); } catch {}
      throw Error(`${path.basename(file)} is damaged and has no usable backup.`);
    }
    throw error;
  }
}

async function writeJson(file, value) {
  await fs.mkdir(path.dirname(file), {recursive: true});
  const temporary = `${file}.${process.pid}.${randomBytes(4).toString('hex')}.tmp`;
  await fs.writeFile(temporary, JSON.stringify(value, null, 2));
  try {
    JSON.parse(await fs.readFile(file, 'utf8'));
    await fs.copyFile(file, file + '.bak');
  } catch {}
  for (let attempt = 0; ; attempt++) {
    try { await fs.rename(temporary, file); return; } catch (error) {
      if (error.code !== 'EPERM' || attempt > 8) { await fs.rm(temporary, {force: true}); throw error; }
      await new Promise(resolve => setTimeout(resolve, 200 * (attempt + 1)));
    }
  }
}

function alive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try { process.kill(pid, 0); return true; } catch (error) { return error.code === 'EPERM'; }
}

// Same lock file as Python's update_json, so a Python and a dashboard edit of one file never clash.
async function withJsonLock(file, change, fallback) {
  const lockFile = path.join(SHARED, 'json-' + createHash('sha256').update(path.resolve(file)).digest('hex').slice(0, 16) + '.lock');
  await fs.mkdir(SHARED, {recursive: true});
  const deadline = Date.now() + 30000;
  let handle;
  while (!handle) {
    try { handle = await fs.open(lockFile, 'wx'); } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      const owner = parseInt((await fs.readFile(lockFile, 'utf8').catch(() => '')).split(' ')[0], 10);
      if (!alive(owner)) { await fs.rm(lockFile, {force: true}); continue; }
      if (Date.now() > deadline) throw Error('Another job is updating this data. Try again in a moment.');
      await new Promise(resolve => setTimeout(resolve, 200));
    }
  }
  try {
    await handle.writeFile(`${process.pid} ${Math.round(Date.now() / 1000)}`);
    await handle.close();
    const data = await readJson(file, structuredClone(fallback));
    const result = await change(data);
    await writeJson(file, result === undefined ? data : result);
    return result === undefined ? data : result;
  } finally { await fs.rm(lockFile, {force: true}); }
}

async function files(folder) {
  try { return await fs.readdir(folder, {withFileTypes: true}); } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error;
  }
}
const exists = file => fs.access(file).then(() => true, () => false);

// ---------------------------------------------------------------------------
// Settings: defaults and presets come from Python (initialize.py writes them)

let schemaCache = null;
async function schema() {
  if (!schemaCache) {
    schemaCache = await readJson(path.join(SHARED, 'settings_schema.json'), null);
    if (!schemaCache) throw Error('Run setup again: output/shared/settings_schema.json is missing.');
  }
  return schemaCache;
}

async function config(id = 'main') {
  if (!CHANNEL_ID.test(id)) throw Error('Invalid channel ID');
  const value = await readJson(path.join(root, 'channels', id, 'config.json'), null);
  if (!value) throw Error('Channel profile not found');
  const {defaults} = await schema();
  return {...structuredClone(defaults), ...value, schedule: {...defaults.schedule, ...(value.schedule || {})}};
}
const base = id => (id === 'main' ? root : path.join(root, 'channels', id));
const limits = c => (['funnel', 'long'].includes(c.video_format) ? [c.full_min_words, c.full_max_words] : [c.min_words, c.max_words]);
// Delivery cues such as [pause] are not spoken words (see delivery.py).
const countWords = text => ((text || '').replace(/\[\s*(?:pause|tense|whisper|urgent|calm|aside)\s*\]/gi, ' ').match(WORDS) || []).length;

// Close to Python's casefold() + split(): enough for display; production re-checks.
function fingerprint(text) {
  const normal = text.normalize('NFKC').toLowerCase().replace(/ß/g, 'ss').replace(/ς/g, 'σ')
    .split(/[\s\u0085\u001c-\u001f]+/u).filter(Boolean).join(' ');
  return createHash('sha256').update(normal).digest('hex');
}

// ---------------------------------------------------------------------------
// Jobs

const jobs = globalThis.__channelJobs ??= {};
const connectionProcesses = globalThis.__connectionProcesses ??= new Map();
const blank = () => ({running: false, log: [], channel: null, error: null, exitCode: null});
const production = globalThis.__productionJob ??= blank();
const scheduling = globalThis.__schedulingJob ??= blank();
const generation = globalThis.__generationJob ??= blank();
const voiceJob = globalThis.__voiceJob ??= blank();
const designJob = globalThis.__designJob ??= blank();
const job = id => jobs[id] ??= {upload: blank(), insights: {...blank(), lastAttempt: 0}, connection: blank()};

// The one line worth showing when a job fails: the last message, not the traceback.
function summary(log) {
  const lines = log.join('').split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  const message = [...lines].reverse().find(line => !/^(Traceback|File "|\^|~|During handling|The above exception)/.test(line));
  return (message || 'The job stopped.').replace(/^[A-Za-z]+Error: /, '').slice(0, 400);
}

function start(script, args, state, tts = false) {
  // tts: true runs in .venv-tts (Kokoro); a string names another environment.
  if (state.running) throw Error('This job is already running.');
  Object.assign(state, {running: true, error: null, log: [], exitCode: null, lastAttempt: Date.now()});
  const child = spawn(python(typeof tts === 'string' ? tts : tts ? '.venv-tts' : '.venv'), ['-u', path.join(root, script), ...args],
    {cwd: root, windowsHide: true, env: {...process.env, PYTHONIOENCODING: 'utf-8'}});
  const append = chunk => { state.log.push(chunk.toString()); if (state.log.length > 400) state.log.shift(); };
  child.stdout.on('data', append);
  child.stderr.on('data', append);
  child.on('error', error => Object.assign(state, {error: error.message, running: false, exitCode: 1}));
  child.on('close', code => {
    Object.assign(state, {running: false, exitCode: code});
    if (code !== 0) state.error = summary(state.log);
    const logs = path.join(SHARED, 'logs');
    fs.mkdir(logs, {recursive: true}).then(() => fs.appendFile(path.join(logs, script.replace('.py', '.log')),
      `\n=== ${new Date().toISOString()} ${args.join(' ')} (exit ${code}) ===\n${state.log.join('')}`)).catch(() => {});
  });
  return child;
}
const view = state => ({...state, log: [...state.log]});

// ---------------------------------------------------------------------------
// Snapshot: everything the dashboard shows

function tokenStatus(credentials) {
  return Promise.all([exists(path.join(credentials, 'channel_token.json')), exists(path.join(credentials, 'reconnect_needed.json'))])
    .then(([token, expired]) => (!token ? 'missing' : expired ? 'expired' : 'ok'));
}

function fileStatus(receipt, present) {
  if (receipt?.status === 'uploaded') return 'uploaded';
  if (receipt?.resumable_uri) return 'resumable';
  if (receipt) return 'checking';
  return present ? 'ready' : 'used';
}

async function scriptExcerpt(directory, item, batch, kind) {
  const stem = item.story.replace(/\.json$/, '');
  const folder = path.join(directory, 'narrations', stem, batch, ...(item.format === 'shorts' ? [] : [kind === 'teaser' ? 'teaser' : 'full']));
  const text = await fs.readFile(path.join(folder, 'script.txt'), 'utf8').catch(() => '');
  return text.slice(0, 1200);
}

async function imageCredit(relative) {
  const record = await readJson(path.join(root, relative.replace(/\.jpg$/i, '.json')), null).catch(() => null);
  return record ? {source: record.source, page: record.page, author: record.author, license: record.license} : {source: 'image'};
}

export async function snapshot(id = 'main') {
  const selected = await config(id), directory = base(id), state = job(id), credentials = path.join(directory, 'credentials');
  const token = await tokenStatus(credentials);
  const connected = token === 'ok';
  const insightsConnected = token !== 'missing' || await exists(path.join(credentials, 'insights_token.json'));
  const cache = await readJson(path.join(directory, 'output/youtube_insights.json'), {updatedAt: null, videos: {}});
  if (connected && Date.now() - state.insights.lastAttempt > 300000 && !state.insights.running) {
    start('youtube_insights.py', ['--channel', id], state.insights);
  }
  const history = await readJson(path.join(credentials, 'upload_history.json'), {});
  const records = Object.values(history);
  const queue = [], reviewItems = [], failed = [], tiktok = [];
  for (const folder of (await files(path.join(directory, 'videos'))).filter(f => f.isDirectory()).sort((a, b) => a.name.localeCompare(b.name))) {
    const videoDir = path.join(directory, 'videos', folder.name);
    const batch = await readJson(path.join(videoDir, 'batch.json'), []);
    const names = new Set((await files(videoDir)).filter(f => f.isFile()).map(f => f.name));
    for (const item of batch) {
      if (item.status === 'failed' || item.status === 'skipped') { failed.push({batch: folder.name, name: item.name, title: item.title, status: item.status, reason: item.reason}); continue; }
      if (item.status !== 'complete' || !item.video) continue;
      const review = item.review || 'pending';
      if (item.tiktok?.length) tiktok.push({batch: folder.name, name: item.name, title: item.title, parts: item.tiktok});
      else if (review === 'approved') tiktok.push({batch: folder.name, name: item.name, title: item.title, parts: []});
      const parts = item.format === 'funnel' && item.full_video
        ? [[item.full_video, 'full', item.full_duration_seconds], [item.video, 'teaser', item.duration_seconds]]
        : [[item.video, item.format === 'long' ? 'full' : 'short', item.duration_seconds]];
      const fullReceipt = item.full_video ? records.find(r => r.file === path.join(videoDir, item.full_video) && r.status === 'uploaded') : null;
      for (const [file, kind, duration] of parts) {
        const usedName = file.replace(/\.mp4$/i, '_used.mp4');
        if (!names.has(file) && !names.has(usedName)) continue;
        const receipt = records.find(r => r.file === path.join(videoDir, file));
        let status = fileStatus(receipt, names.has(file));
        if (status === 'ready' && review !== 'approved') status = review === 'rejected' ? 'rejected' : 'review';
        if (status === 'ready' && kind === 'teaser' && !fullReceipt && !item.full_video_id) status = 'waiting';
        if (status === 'uploaded' && receipt?.publish_at && receipt.publish_at > new Date().toISOString()) status = 'scheduled';
        queue.push({name: file, file: names.has(file) ? file : usedName, kind, item: item.name, title: item.title, duration,
          background: item.background, batch: folder.name, status, review, generated: !!item.generated,
          videoId: receipt?.video_id, privacy: receipt?.privacy, publishAt: receipt?.publish_at ?? null,
          insights: cache.videos?.[receipt?.video_id] ?? null});
      }
      if (review === 'pending' && parts.every(([file]) => names.has(file))) {
        reviewItems.push({batch: folder.name, name: item.name, title: item.title, format: item.format,
          description: item.format === 'long' ? item.full_description : item.description, fullDescription: item.full_description,
          files: parts.map(([file, kind, duration]) => ({file, kind, duration})),
          thumbnail: item.thumbnail && names.has(item.thumbnail) ? item.thumbnail : null,
          warnings: [...(item.variety_warnings || []), ...(item.narration_warnings || []).map(w => 'Voice: ' + w)],
          voice: item.voice, generated: !!item.generated, image: item.image ? await imageCredit(item.image) : null,
          script: await scriptExcerpt(directory, item, folder.name, parts[0][1])});
      }
    }
  }

  let stories = 0, eligible = 0, generatedStories = 0, setAside = 0, conceptSources = 0, latestStory = null;
  const [low, high] = limits(selected);
  const usage = await readJson(path.join(SHARED, 'story_usage.json'), {}), seen = new Set();
  const done = Object.fromEntries(Object.entries(usage).filter(([, row]) => row.status === 'complete'));
  const doneIds = new Set(Object.values(done).map(row => row.story_id));
  for (const file of (await files(path.join(directory, 'stories'))).filter(f => f.isFile() && f.name.endsWith('.json'))) {
    const story = await readJson(path.join(directory, 'stories', file.name), {}).catch(() => ({}));
    if (!story || typeof story.text !== 'string' || !story.text.trim()) continue;
    stories++;
    if (file.name.endsWith('_review.json')) setAside++;
    const unused = !/_(used|review)\.json$/.test(file.name);
    if (story.text_source === 'generated' && unused) generatedStories++;
    const hash = fingerprint(story.text), title = (story.title || '').trim(), count = countWords(`${story.title} ${story.text}`);
    const storyId = story.id || file.name.replace(/\.json$/, '');
    const concept = story.text_source === 'post_page' && (selected.collected_stories || 'rewrite') !== 'narrate';
    if (concept && unused && !story.concept_used_by) conceptSources++;
    const fits = unused && story.text_source !== 'feed_preview' && !concept && !done[hash] && !doneIds.has(storyId) && !seen.has(hash)
        && title && title.length <= 100 && !/[<>]/.test(title) && count >= low && count <= high;
    if (fits) { eligible++; seen.add(hash); }
    if (['generated', 'original'].includes(story.text_source)) {
      const modified = (await fs.stat(path.join(directory, 'stories', file.name))).mtimeMs;
      const usedName = file.name.endsWith('_used.json') ? file.name : null;
      if (!latestStory || modified > latestStory.modified) latestStory = {file: file.name, title, words: count, modified,
        text: story.text.replace(/\[[a-z]+\]\s*/g, '').slice(0, 1500), ready: !!fits, used: !!usedName || !!done[hash] || doneIds.has(storyId),
        tooLong: count > high, tooShort: count < low};
    }
  }
  const backgroundFiles = (await files(path.join(root, 'backgrounds'))).filter(f => f.isFile() && /\.mp4$/i.test(f.name)).map(f => f.name);
  const profiles = [];
  for (const folder of (await files(path.join(root, 'channels'))).filter(f => f.isDirectory())) {
    const c = await readJson(path.join(root, 'channels', folder.name, 'config.json'), null).catch(() => null);
    if (c) profiles.push({id: c.id, name: c.name, youtube_channel_id: c.youtube_channel_id, preset: c.preset ?? null});
  }
  const titles = Object.fromEntries(queue.filter(v => v.videoId).map(v => [v.videoId, v.title]));
  const related = (await readJson(path.join(SHARED, 'related_links.json'), [])).filter(r => r.channel === id && !r.done)
    .map(r => ({...r, full_title: titles[r.full_id] || r.title}));
  const hasApiKey = !!process.env.ANTHROPIC_API_KEY || await exists(KEY_FILE());
  const hasPexelsKey = !!process.env.PEXELS_API_KEY || await exists(PEXELS_FILE());
  const voiceClips = (await files(VOICES_DIR)).filter(f => f.isFile() && CLIP_FILE.test(f.name)).map(f => f.name).sort();
  const voiceSamples = (await readJson(path.join(SAMPLES_DIR, 'index.json'), [])).filter(s => SAMPLE_FILE.test(s.file || ''));
  const voiceInstalled = await exists(python('.venv-voice'));
  const designerInstalled = await exists(python('.venv-design'));
  const voiceDesigns = (await readJson(path.join(DESIGNS_DIR, 'index.json'), [])).filter(d => DESIGN_FILE.test(d.file || '')).slice(-9).reverse();
  const characterPreview = await readJson(path.join(SAMPLES_DIR, 'characters.json'), null);
  const voiceDescriptions = {};
  for (const clip of voiceClips) {
    const sidecar = await readJson(path.join(VOICES_DIR, clip.replace(/\.[a-z0-9]+$/i, '.json')), null).catch(() => null);
    if (sidecar?.description) voiceDescriptions[clip] = sidecar.description;
  }
  const musicFiles = (await files(path.join(root, 'music'))).filter(f => f.isFile() && /\.(mp3|m4a|aac|wav|ogg|flac)$/i.test(f.name)).length;
  const topPerformers = queue.filter(v => v.insights?.viewCount).sort((a, b) => b.insights.viewCount - a.insights.viewCount).slice(0, 5)
    .map(v => ({title: v.title, kind: v.kind, views: v.insights.viewCount, videoId: v.videoId, watched: v.insights.averageViewPercentage ?? null}));
  const {presets, grades, formats} = await schema();
  return {
    channel: {...selected, connected, token}, channels: profiles, presets: Object.keys(presets), grades, formats,
    backgroundFiles, eligibleStories: eligible, latestStory, generatedStories, reviewStories: setAside, conceptSources,
    hasPexelsKey, voiceClips, voiceSamples, voiceInstalled, voices: view(voiceJob), tiktok: tiktok.slice(-30),
    designerInstalled, voiceDesigns, designs: view(designJob), characterPreview, voiceDescriptions, voiceCharacters: (await schema()).voice_characters ?? ['natural'],
    imageMode: selected.background_mode === 'image',
    related, hasApiKey, musicFiles, topPerformers, reviewItems, failed: failed.slice(-20),
    stats: {stories, backgrounds: backgroundFiles.length, total: queue.length,
      review: queue.filter(v => v.status === 'review').length,
      ready: queue.filter(v => v.status === 'ready' || v.status === 'waiting').length,
      uploaded: queue.filter(v => v.status === 'uploaded' || v.status === 'scheduled').length},
    queue, next: queue.find(v => v.status === 'ready' || v.status === 'resumable') ?? null,
    insights: {...state.insights, connected: insightsConnected, updatedAt: cache.updatedAt, retention: cache.retention ?? null,
      totals: queue.reduce((t, v) => ({views: t.views + (v.insights?.viewCount ?? 0), likes: t.likes + (v.insights?.likeCount ?? 0),
        comments: t.comments + (v.insights?.commentCount ?? 0)}), {views: 0, likes: 0, comments: 0})},
    upload: view(state.upload), connection: state.connection, production: view(production),
    scheduling: view(scheduling), generation: view(generation), updatedAt: new Date().toISOString(),
  };
}

// ---------------------------------------------------------------------------
// Media: stream a finished video or thumbnail for preview (supports seeking)

export async function media(id, batch, file, range) {
  await config(id);
  if (!BATCH_ID.test(batch || '') || !ITEM_FILE.test(file || '')) throw Error('Invalid file');
  const folder = path.join(base(id), 'videos', batch), full = path.join(folder, file);
  if (path.dirname(full) !== (file.startsWith('tiktok/') ? path.join(folder, 'tiktok') : folder)) throw Error('Invalid file');
  return streamFile(full, file.endsWith('.jpg') ? 'image/jpeg' : file.endsWith('.txt') ? 'text/plain; charset=utf-8' : 'video/mp4', range);
}

// A voice sample from output/shared/voice_samples (Settings > Voice).
export async function voiceSample(file, range) {
  if (DESIGN_FILE.test(file || '')) return streamFile(path.join(DESIGNS_DIR, file), 'audio/wav', range);
  if (!SAMPLE_FILE.test(file || '')) throw Error('Invalid file');
  return streamFile(path.join(SAMPLES_DIR, file), 'audio/wav', range);
}

async function streamFile(full, type, range) {
  const {size} = await fs.stat(full);
  const match = /^bytes=(\d*)-(\d*)$/.exec(range || '');
  if (!match || (!match[1] && !match[2])) {
    return {status: 200, headers: {'Content-Type': type, 'Content-Length': String(size), 'Accept-Ranges': 'bytes'},
      stream: createReadStream(full)};
  }
  let startByte = match[1] ? Number(match[1]) : Math.max(0, size - Number(match[2]));
  let endByte = match[1] && match[2] ? Math.min(Number(match[2]), size - 1) : size - 1;
  if (startByte >= size || startByte > endByte) return {status: 416, headers: {'Content-Range': `bytes */${size}`}, stream: null};
  return {status: 206, headers: {'Content-Type': type, 'Content-Length': String(endByte - startByte + 1),
    'Content-Range': `bytes ${startByte}-${endByte}/${size}`, 'Accept-Ranges': 'bytes'},
    stream: createReadStream(full, {start: startByte, end: endByte})};
}

// ---------------------------------------------------------------------------
// Actions

export async function connectChannel(id) {
  await config(id);
  const child = start('manage_channel.py', ['connect', id], job(id).connection);
  connectionProcesses.set(id, child);
  child.once('close', () => { if (connectionProcesses.get(id) === child) connectionProcesses.delete(id); });
  return {started: true};
}

export async function cancelConnection(id) {
  await config(id);
  const child = connectionProcesses.get(id), state = job(id).connection;
  if (child && child.exitCode === null) {
    await new Promise((resolve, reject) => {
      child.once('close', resolve);
      if (!child.kill()) reject(Error('Could not stop the sign-in process. Please restart the dashboard.'));
    });
  }
  connectionProcesses.delete(id);
  Object.assign(state, {running: false, error: null, exitCode: null, log: ['Sign-in cancelled. You can connect again.']});
  return {cancelled: true};
}

export async function syncInsights(connect = false, id = 'main') {
  await config(id);
  if (connect) return connectChannel(id);
  if (!job(id).insights.running) start('youtube_insights.py', ['--channel', id], job(id).insights);
  return {started: true};
}

const anyJobRunning = id => production.running || generation.running || scheduling.running || voiceJob.running || designJob.running || job(id).upload.running;

export async function uploadNext(id = 'main') {
  const data = await snapshot(id);
  if (data.channel.token === 'expired') throw Error('The Google sign-in expired. Click "Reconnect channel" first.');
  if (!data.channel.connected) throw Error('Connect this channel before uploading.');
  if (!data.next) throw Error(data.stats.review ? 'Approve videos in Review first; only approved videos upload.' : 'No videos are ready to upload.');
  if (anyJobRunning(id)) throw Error('Another job is running. Wait for it to finish.');
  start('upload_next.py', ['--channel', id], job(id).upload);
  return {started: true};
}

export async function produce(id, count, story, remake = false) {
  const data = await snapshot(id);
  if (story !== undefined && story !== null) {
    if (typeof story !== 'string' || !/^[A-Za-z0-9_.-]{1,120}\.json$/.test(story) || /_review\.json$/.test(story)
        || (!remake && /_used\.json$/.test(story))) throw Error('Choose an unused story.');
    if (!(await exists(path.join(base(id), 'stories', story)))) throw Error('That story was not found.');
    if (data.channel.voice_engine === 'chatterbox' && !data.voiceInstalled) throw Error('The Chatterbox voice is not installed. Run setup_voice first.');
    if (voiceJob.running || designJob.running) throw Error('A voice is still being made. Wait for it to finish.');
    if (production.running || generation.running) throw Error('Something is already running. Wait for it to finish.');
    production.channel = id;
    start('produce_batch.py', ['--channel', id, '--count', '1', remake ? '--remake' : '--story', story], production, true);
    return {started: true};
  }
  if (!Number.isInteger(count) || count < 1 || count > 100) throw Error('Choose between 1 and 100 videos.');
  if (!data.backgroundFiles.length && !data.imageMode) throw Error('Add at least one background video to the backgrounds folder first, or set the channel to use one image per story.');
  if (data.channel.voice_engine === 'chatterbox' && !data.voiceInstalled) throw Error('This channel uses the Chatterbox voice, which is not installed. Run setup_voice, or choose Kokoro in Settings.');
  if (voiceJob.running) throw Error('Voice samples are being made. Wait for them to finish.');
  if (count > data.eligibleStories) throw Error(`Only ${data.eligibleStories} unused stories fit this channel's word limits.`);
  if (production.running) throw Error('Production or autopilot is already running. Jobs run one batch at a time.');
  production.channel = id;
  start('produce_batch.py', ['--channel', id, '--count', String(count)], production, true);
  return {started: true};
}

export async function createProfile(id, name, preset) {
  if (!CHANNEL_ID.test(id || '')) throw Error('The channel ID could not be made from that name; use letters or numbers.');
  if (typeof name !== 'string' || !name.trim() || name.length > 80) throw Error('Enter a channel name under 80 characters.');
  const {presets} = await schema();
  if (preset && !presets[preset]) throw Error('Unknown channel type.');
  if (name.trim().startsWith('-')) throw Error('The name cannot start with a dash.');
  const args = [path.join(root, 'manage_channel.py'), 'create', id, `--name=${name.trim()}`, ...(preset ? [`--preset=${preset}`] : [])];
  await new Promise((resolve, reject) => {
    let log = '';
    const child = spawn(python(), args, {cwd: root, windowsHide: true});
    child.stderr.on('data', chunk => (log += chunk.toString()));
    child.stdout.on('data', chunk => (log += chunk.toString()));
    child.on('error', reject);
    child.on('close', code => (code === 0 ? resolve() : reject(Error(summary([log])))));
  });
  return {id};
}

const TEMPLATE_KEYS = ['hook', 'credit', 'hashtags', 'title', 'category', 'fiction_note'];
function checkTemplate(value, label, extra = []) {
  if (typeof value !== 'string' || value.length > 2000 || /[<>]/.test(value)) throw Error(`${label}: under 2000 characters, without < or >.`);
  const allowed = [...TEMPLATE_KEYS, ...extra];
  const bad = [...value.matchAll(/\{([^}]*)\}/g)].map(m => m[1]).find(key => !allowed.includes(key));
  if (bad !== undefined) throw Error(`${label}: unknown placeholder {${bad}}. Use ${allowed.map(k => `{${k}}`).join(' ')}.`);
}

export async function saveSettings(id, values) {
  const {grades, formats, privacy} = await schema();
  const v = values || {};
  const fail = message => { throw Error(message); };
  if (!VOICE.test(v.voice || '')) fail('Voice: enter a Kokoro voice ID, e.g. af_heart or am_michael.');
  for (const key of ['voice_male', 'voice_female']) if (v[key] && !VOICE.test(v[key])) fail('Male/female voice: a Kokoro voice ID, or leave empty.');
  if (!['words', 'phrases'].includes(v.caption_style)) fail('Captions: choose a style.');
  if (!Number.isFinite(v.speed) || v.speed < 0.5 || v.speed > 2) fail('Narration speed must be between 0.5 and 2.');
  if (!Number.isFinite(v.period_pause) || v.period_pause < 0 || v.period_pause > 2) fail('Pause after sentences must be 0–2 seconds.');
  if (!Number.isInteger(v.min_words) || !Number.isInteger(v.max_words) || v.min_words < 1 || v.max_words < v.min_words || v.max_words > 5000) fail('Short word limits: whole numbers, minimum below maximum, at most 5000.');
  if (!Array.isArray(v.backgrounds) || v.backgrounds.some(n => typeof n !== 'string' || !/^[^\\/]+\.mp4$/i.test(n))) fail('Backgrounds: choose files from the backgrounds folder.');
  const s = v.schedule;
  if (!s || typeof s.enabled !== 'boolean' || !Array.isArray(s.times) || !s.times.length || s.times.length > 24 || s.times.some(t => !/^([01]\d|2[0-3]):[0-5]\d$/.test(t))) fail('Publish times: like 10:00, 18:30 (24-hour, two digits).');
  try { new Intl.DateTimeFormat('en', {timeZone: s.timezone}); } catch { fail('Time zone: use a name like America/New_York or Europe/Sofia.'); }
  if (!privacy.includes(v.privacy)) fail('Visibility must be public, unlisted or private.');
  if (!/^\d{1,2}$/.test(String(v.category_id))) fail('Choose a YouTube category.');
  if (!Array.isArray(v.hashtags) || v.hashtags.length > 15 || v.hashtags.some(t => !/^#?[\p{L}\p{N}_]{1,50}$/u.test(t))) fail('Hashtags: up to 15, letters and numbers only, e.g. #shorts #storytime.');
  if (!Array.isArray(v.tags) || v.tags.join(',').length > 450 || v.tags.some(t => typeof t !== 'string' || /[<>]/.test(t))) fail('Tags: under 450 characters in total, without < or >.');
  checkTemplate(v.description_template, 'Short description');
  checkTemplate(v.teaser_description_template, 'Teaser description', ['full_url']);
  checkTemplate(v.full_description_template, 'Full video description');
  if (!formats.includes(v.video_format)) fail('Choose a format.');
  const ints = [['full_min_words', 50, 30000, 'Full video minimum words'], ['full_max_words', 100, 30000, 'Full video maximum words'],
    ['max_full_minutes', 3, 240, 'Full video maximum minutes'], ['teaser_seconds', 15, 170, 'Teaser length'],
    ['max_uploads_per_day', 1, 10, 'Uploads per day']];
  for (const [key, lo, hi, label] of ints) if (!Number.isInteger(v[key]) || v[key] < lo || v[key] > hi) fail(`${label} must be a whole number from ${lo} to ${hi}.`);
  if (v.full_max_words < v.full_min_words) fail('Full video word limits: the minimum is above the maximum.');
  for (const [key, label] of [['teaser_cta', 'Call to action'], ['fiction_note', 'Fiction note']]) {
    if (typeof v[key] !== 'string' || v[key].length > 300 || /[<>{}]/.test(v[key])) fail(`${label}: under 300 characters, without < > { }.`);
  }
  if (!Array.isArray(v.teaser_ctas) || v.teaser_ctas.length > 10 || v.teaser_ctas.some(t => typeof t !== 'string' || t.length > 200 || /[<>{}]/.test(t))) fail('Call-to-action variants: up to 10 lines, each under 200 characters.');
  if (!Number.isFinite(v.title_card_seconds) || v.title_card_seconds < 0 || v.title_card_seconds > 10) fail('Title card time must be 0–10 seconds.');
  if (!Number.isFinite(v.music_volume) || v.music_volume < 0 || v.music_volume > 1) fail('Music volume must be between 0 and 1.');
  if (typeof v.generator_model !== 'string' || !/^[a-z0-9.\-]{3,60}$/.test(v.generator_model)) fail('Claude model: a model name like claude-sonnet-5-5.');
  if (typeof v.caption_font !== 'string' || !/^[A-Za-z0-9 \-]{2,40}$/.test(v.caption_font)) fail('Caption font: a font name like Arial Black.');
  for (const [key, label] of [['caption_color', 'Word caption colour'], ['phrase_color', 'Phrase caption colour']]) if (!HEX.test(v[key] || '')) fail(`${label}: a colour like #FFD400.`);
  if (!grades.includes(v.color_grade)) fail('Choose a colour grade.');
  if (!['kokoro', 'chatterbox'].includes(v.voice_engine)) fail('Choose a narration engine.');
  for (const key of ['voice_clip', 'voice_clip_male', 'voice_clip_female', 'host_voice_clip']) if (v[key] && !CLIP_FILE.test(v[key])) fail('Narrator clip: choose a file from the voices folder.');
  if (!['standard', 'turbo'].includes(v.chatterbox_model)) fail('Choose a Chatterbox model.');
  const characters = (await schema()).voice_characters ?? ['natural'];
  const p = v.persona;
  if (p !== null && p !== undefined) {
    if (typeof p !== 'object' || Array.isArray(p)) fail('Persona: invalid.');
    for (const key of ['name', 'identity', 'speech', 'intro', 'outro', 'voice_description']) {
      if (p[key] !== undefined && (typeof p[key] !== 'string' || p[key].length > 600 || /[<>]/.test(p[key]))) fail('Persona: each field under 600 characters, without < or >.');
    }
    if (p.asides !== undefined && !['none', 'rare', 'some'].includes(p.asides)) fail('Persona: asides must be none, rare or some.');
    if (p.gender !== undefined && !['male', 'female', 'any'].includes(p.gender)) fail('Persona: choose male, female or any.');
    if (p.age !== undefined && !/^[0-9\- ]{0,12}$/.test(p.age)) fail('Persona: age like 50-75.');
    if (p.voice_clip && !CLIP_FILE.test(p.voice_clip)) fail('Persona: invalid narrator clip.');
  }
  if (!characters.includes(v.voice_character ?? 'natural')) fail('Choose a voice character.');
  if (!Number.isFinite(v.expressiveness) || v.expressiveness < 0.25 || v.expressiveness > 1.5) fail('Expressiveness must be between 0.25 and 1.5.');
  if (!['clips', 'image'].includes(v.background_mode)) fail('Choose a background type.');
  if (!Array.isArray(v.image_keywords) || v.image_keywords.length > 20 || v.image_keywords.some(k => typeof k !== 'string' || k.length > 60 || /[<>{}]/.test(k))) fail('Image keywords: up to 20 phrases, each under 60 characters.');
  if (!['rewrite', 'narrate'].includes(v.collected_stories)) fail('Choose how collected stories are used.');
  if (!Number.isInteger(v.long_target_words) || v.long_target_words < 2000 || v.long_target_words > 30000) fail('Long story length must be a whole number from 2000 to 30000 words.');
  if (!Number.isInteger(v.tiktok_part_seconds) || v.tiktok_part_seconds < 65 || v.tiktok_part_seconds > 600) fail('TikTok part length must be 65 to 600 seconds.');
  if (!Array.isArray(v.tiktok_hashtags) || v.tiktok_hashtags.length > 10 || v.tiktok_hashtags.some(t => !/^#?[\p{L}\p{N}_]{1,50}$/u.test(t))) fail('TikTok hashtags: up to 10, letters and numbers only.');
  const clean = {
    ...v, hashtags: v.hashtags.map(t => (t.startsWith('#') ? t : '#' + t)), category_id: String(v.category_id),
    teaser_ctas: v.teaser_ctas.map(t => t.trim()).filter(Boolean), voice_male: v.voice_male || null, voice_female: v.voice_female || null,
    story_category: String(v.story_category || 'General stories').slice(0, 100),
    voice_clip: v.voice_clip || '', host_voice_clip: v.host_voice_clip || '', voice_clip_male: v.voice_clip_male || null, voice_clip_female: v.voice_clip_female || null,
    image_keywords: v.image_keywords.map(k => k.trim()).filter(Boolean),
    tiktok_hashtags: v.tiktok_hashtags.map(t => (t.startsWith('#') ? t : '#' + t)),
    voice_character: v.voice_character ?? 'natural',
    persona: p && (p.identity || '').trim() ? Object.fromEntries(['name', 'identity', 'speech', 'intro', 'outro', 'asides', 'gender', 'age',
      'voice_clip', 'voice_description'].filter(k => p[k] !== undefined && p[k] !== null).map(k => [k, typeof p[k] === 'string' ? p[k].trim() : p[k]])) : null,
  };
  for (const key of ['credit_source', 'clean_language', 'title_card', 'progress_bar', 'require_review']) clean[key] = v[key] !== false;
  const keys = ['voice', 'voice_male', 'voice_female', 'speed', 'period_pause', 'caption_style', 'min_words', 'max_words', 'backgrounds',
    'schedule', 'privacy', 'category_id', 'hashtags', 'tags', 'description_template', 'credit_source', 'video_format', 'full_min_words',
    'full_max_words', 'max_full_minutes', 'teaser_seconds', 'teaser_cta', 'teaser_ctas', 'teaser_description_template',
    'full_description_template', 'fiction_note', 'clean_language', 'title_card', 'title_card_seconds', 'progress_bar', 'music_volume',
    'generator_model', 'story_category', 'require_review', 'max_uploads_per_day', 'caption_font', 'caption_color', 'phrase_color', 'color_grade',
    'voice_engine', 'voice_clip', 'voice_clip_male', 'voice_clip_female', 'chatterbox_model', 'expressiveness', 'background_mode',
    'image_keywords', 'collected_stories', 'long_target_words', 'tiktok_part_seconds', 'tiktok_hashtags', 'voice_character', 'persona', 'host_voice_clip'];
  await config(id);
  // Merge into the file as it is now: a sign-in finishing meanwhile keeps its channel binding.
  await withJsonLock(path.join(root, 'channels', id, 'config.json'), current => {
    for (const key of keys) current[key] = clean[key];
  }, {});
  return {saved: true};
}

export async function addStory(id, title, text) {
  const c = await config(id);
  title = typeof title === 'string' ? title.trim().replace(/\s+/g, ' ') : '';
  text = typeof text === 'string' ? text.trim() : '';
  if (!title || title.length > 100 || /[<>]/.test(title)) throw Error('Give the story a title under 100 characters, without < or >.');
  const words = countWords(text);
  if (words < 20) throw Error('The story needs at least 20 words.');
  if (text.length > 200000) throw Error('The story is too long (200,000 characters maximum).');
  const storyId = 'own_' + Date.now().toString(36) + randomBytes(3).toString('hex');
  const story = {id: storyId, title, text, text_source: 'original', collected_at: new Date().toISOString()};
  await writeJson(path.join(base(id), 'stories', storyId + '.json'), story);
  const [low, high] = limits(c), total = countWords(`${title} ${text}`);
  return {id: storyId, words, fits: total >= low && total <= high, low, high};
}

export async function review(id, batch, names, decision, note) {
  await config(id);
  if (!BATCH_ID.test(batch || '')) throw Error('Invalid batch.');
  if (!['approved', 'rejected', 'pending'].includes(decision)) throw Error('Invalid decision.');
  if (!Array.isArray(names) || !names.length || names.some(n => typeof n !== 'string')) throw Error('Choose at least one video.');
  if (note !== undefined && note !== null && (typeof note !== 'string' || note.length > 500)) throw Error('Note: under 500 characters.');
  const file = path.join(base(id), 'videos', batch, 'batch.json');
  let changed = 0;
  await withJsonLock(file, rows => {
    for (const row of rows) {
      if (row.status !== 'complete' || !names.includes(row.name)) continue;
      row.review = decision;
      row.reviewed_at = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
      if (note) row.review_note = note;
      changed++;
    }
  }, []);
  if (!changed) throw Error('Those videos were not found or are not finished.');
  return {changed};
}

export async function editTitle(id, batch, name, title) {
  await config(id);
  if (!BATCH_ID.test(batch || '')) throw Error('Invalid batch.');
  title = typeof title === 'string' ? title.trim().replace(/\s+/g, ' ') : '';
  if (!title || title.length > 100 || /[<>]/.test(title)) throw Error('Title: 1–100 characters, without < or >.');
  let found = false;
  await withJsonLock(path.join(base(id), 'videos', batch, 'batch.json'), rows => {
    for (const row of rows) if (row.name === name && row.status === 'complete') { row.title = title; found = true; }
  }, []);
  if (!found) throw Error('Video not found.');
  return {saved: true};
}

export async function preschedule(id, count) {
  const data = await snapshot(id);
  if (data.channel.token === 'expired') throw Error('The Google sign-in expired. Click "Reconnect channel" first.');
  if (!data.channel.connected) throw Error('Connect this channel before scheduling uploads.');
  if (!Number.isInteger(count) || count < 1 || count > 50) throw Error('Choose between 1 and 50 videos.');
  if (!data.stats.ready) throw Error(data.stats.review ? 'Approve videos in Review first; only approved videos are scheduled.' : 'No videos are ready. Create videos first.');
  if (anyJobRunning(id)) throw Error('Another job is running. Wait for it to finish.');
  scheduling.channel = id;
  start('preschedule.py', ['--channel', id, '--count', String(count)], scheduling);
  return {started: true};
}

export async function generateStories(id, count) {
  await config(id);
  if (!Number.isInteger(count) || count < 1 || count > 50) throw Error('Choose between 1 and 50 stories.');
  if (!(process.env.ANTHROPIC_API_KEY || await exists(KEY_FILE()))) throw Error('Add your Claude API key in Settings first.');
  if (generation.running || production.running) throw Error('Stories are already being generated.');
  generation.channel = id;
  start('story_generator.py', ['--channel', id, '--count', String(count)], generation);
  return {started: true};
}

export async function autopilot(id, count) {
  await config(id);
  if (!Number.isInteger(count) || count < 1 || count > 30) throw Error('Choose between 1 and 30 stories.');
  const c = await config(id);
  if (c.background_mode !== 'image' && !(await files(path.join(root, 'backgrounds'))).some(f => f.isFile() && /\.mp4$/i.test(f.name))) throw Error('Add at least one background video first, or set the channel to use one image per story.');
  if (c.voice_engine === 'chatterbox' && !(await exists(python('.venv-voice')))) throw Error('This channel uses the Chatterbox voice, which is not installed. Run setup_voice, or choose Kokoro in Settings.');
  if (voiceJob.running) throw Error('Voice samples are being made. Wait for them to finish.');
  if (production.running || generation.running || scheduling.running) throw Error('Another job is running. Wait for it to finish.');
  production.channel = id;
  start('autopilot.py', ['--channel', id, '--count', String(count)], production);
  return {started: true};
}

export async function saveApiKey(key, confirmRemove) {
  if (typeof key !== 'string') throw Error('Enter an API key.');
  key = key.trim();
  if (key === '') {
    if (!confirmRemove) throw Error('Leave the field empty and confirm to remove the saved key.');
    await fs.rm(KEY_FILE(), {force: true});
    return {saved: true, removed: true};
  }
  if (!/^[A-Za-z0-9_\-]{20,300}$/.test(key)) throw Error('That does not look like an API key.');
  await fs.mkdir(path.dirname(KEY_FILE()), {recursive: true});
  await fs.writeFile(KEY_FILE(), key, {mode: 0o600});
  await fs.chmod(KEY_FILE(), 0o600).catch(() => {});
  return {saved: true};
}

export async function makeVoiceSamples(id) {
  await config(id);
  if (!(await exists(python('.venv-tts')))) throw Error('Run setup first: the Kokoro voice is not installed.');
  if (anyJobRunning(id)) throw Error('Another job is running. Wait for it to finish.');
  start('voice_samples.py', [], voiceJob, true);
  return {started: true};
}

export async function exportTikTok(id) {
  const data = await snapshot(id);
  if (!data.tiktok.some(t => !t.parts.length)) throw Error('Approve videos in Review first; each approved video is exported once.');
  if (anyJobRunning(id)) throw Error('Another job is running. Wait for it to finish.');
  production.channel = id;
  start('tiktok_export.py', ['--channel', id], production);
  return {started: true};
}

export async function savePexelsKey(key, confirmRemove) {
  if (typeof key !== 'string') throw Error('Enter an API key.');
  key = key.trim();
  if (key === '') {
    if (!confirmRemove) throw Error('Leave the field empty and confirm to remove the saved key.');
    await fs.rm(PEXELS_FILE(), {force: true});
    return {saved: true, removed: true};
  }
  if (!/^[A-Za-z0-9]{20,100}$/.test(key)) throw Error('That does not look like a Pexels API key.');
  await fs.mkdir(path.dirname(PEXELS_FILE()), {recursive: true});
  await fs.writeFile(PEXELS_FILE(), key, {mode: 0o600});
  await fs.chmod(PEXELS_FILE(), 0o600).catch(() => {});
  return {saved: true};
}

// Voice designer: invent a narrator from a description (Qwen3-TTS VoiceDesign, .venv-design).
export async function designVoice(id, description, count) {
  await config(id);
  description = typeof description === 'string' ? description.replace(/\s+/g, ' ').trim() : '';
  if (description.length < 10 || description.length > 500) throw Error('Describe the voice in 10–500 characters.');
  if (!Number.isInteger(count) || count < 1 || count > 5) throw Error('Choose 1 to 5 takes.');
  if (!(await exists(python('.venv-design')))) throw Error('The voice designer is not installed yet: run setup_voice_designer.');
  if (anyJobRunning(id)) throw Error('Another job is running. Wait for it to finish.');
  start('voice_designer.py', ['--description', description, '--count', String(count)], designJob, '.venv-design');
  return {started: true};
}

// Keep a designed take as a narrator clip, then make its Chatterbox sample.
export async function keepDesign(id, file, name, role) {
  await config(id);
  if (!DESIGN_FILE.test(file || '')) throw Error('Choose a voice take.');
  const slug = (typeof name === 'string' ? name : '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40);
  if (!slug) throw Error('Give the voice a name, e.g. "Old Caretaker".');
  const designs = await readJson(path.join(DESIGNS_DIR, 'index.json'), []);
  const take = designs.find(d => d.file === file);
  if (!take) throw Error('That take was not found.');
  if (anyJobRunning(id)) throw Error('Another job is running. Wait for it to finish.');
  await fs.mkdir(VOICES_DIR, {recursive: true});
  const stem = 'designed_' + slug;
  if (await exists(path.join(VOICES_DIR, stem + '.wav'))) throw Error('A narrator with that name already exists; choose another name.');
  await fs.copyFile(path.join(DESIGNS_DIR, file), path.join(VOICES_DIR, stem + '.wav'));
  await writeJson(path.join(VOICES_DIR, stem + '.json'), {description: take.description, seed: take.seed, from: file});
  if (role) await setVoice(id, role, stem + '.wav');
  const sampling = await exists(python('.venv-voice'));
  if (sampling) start('voice_samples.py', ['--only', stem], voiceJob, true);
  return {clip: stem + '.wav', sampling};
}

// The simple page's two voice slots: the story narrator and the intro host ('' = no host).
export async function setVoice(id, role, clip) {
  await config(id);
  if (!['narrator', 'host'].includes(role)) throw Error('Choose narrator or host.');
  clip = clip || '';
  if (clip && !CLIP_FILE.test(clip)) throw Error('Choose a voice from the list.');
  if (clip && !(await exists(path.join(VOICES_DIR, clip)))) throw Error('That voice file is missing from the voices folder.');
  if (role === 'narrator' && !clip) throw Error('The story needs a narrator voice.');
  await withJsonLock(path.join(root, 'channels', id, 'config.json'), current => {
    if (role === 'narrator') { current.voice_engine = 'chatterbox'; current.voice_clip = clip; }
    else current.host_voice_clip = clip;
    if (current.voice_clip && current.host_voice_clip === current.voice_clip) current.host_voice_clip = '';
  }, {});
  return {saved: true};
}

// Draft the narrator persona from a designed voice's description (Claude API).
export async function draftPersona(id, clip, description) {
  await config(id);
  if (!(process.env.ANTHROPIC_API_KEY || await exists(KEY_FILE()))) throw Error('Add your Claude API key in Settings first.');
  if (anyJobRunning(id)) throw Error('Another job is running. Wait for it to finish.');
  let args;
  if (clip) {
    if (!CLIP_FILE.test(clip)) throw Error('Invalid narrator clip.');
    args = ['--channel', id, '--clip', clip];
  } else {
    description = typeof description === 'string' ? description.replace(/\s+/g, ' ').trim() : '';
    if (description.length < 10 || description.length > 500) throw Error('Describe the narrator in 10–500 characters.');
    args = ['--channel', id, '--description', description];
  }
  generation.channel = id;
  start('persona.py', args, generation);
  return {started: true};
}

// Hear the current narrator through every voice character (takes seconds).
export async function characterPreviews(id, sample) {
  await config(id);
  if (!SAMPLE_FILE.test(sample || '') || sample.startsWith('character_')) throw Error('Choose a narrator sample first.');
  if (voiceJob.running) throw Error('Voice samples are being made. Wait for them to finish.');
  start('voice_character_samples.py', [sample], voiceJob);
  return {started: true};
}

// Open a project folder in Explorer / Finder. Only these fixed folders can be opened.
export async function openFolder(id, which) {
  await config(id);
  const folders = {voices: VOICES_DIR, samples: SAMPLES_DIR, videos: path.join(base(id), 'videos'), stories: path.join(base(id), 'stories'), channel: path.join(root, 'channels', id)};
  const folder = folders[which];
  if (!folder) throw Error('Unknown folder.');
  await fs.mkdir(folder, {recursive: true});
  const [command, args] = process.platform === 'win32' ? ['explorer.exe', [folder]]
    : process.platform === 'darwin' ? ['open', [folder]] : ['xdg-open', [folder]];
  const child = spawn(command, args, {detached: true, stdio: 'ignore', windowsHide: false});
  child.on('error', () => {});
  child.unref();
  return {opened: true};
}

export async function markRelatedDone(id, teaserId) {
  await config(id);
  let found = false;
  await withJsonLock(path.join(SHARED, 'related_links.json'), rows => {
    for (const row of rows) if (row.channel === id && row.teaser_id === teaserId) { row.done = true; found = true; }
  }, []);
  if (!found) throw Error('Item not found.');
  return {saved: true};
}
