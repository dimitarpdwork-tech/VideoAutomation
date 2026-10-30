'use client';
import {useState, useEffect} from 'react';

const WORDS = /[\p{L}\p{N}_]+(?:['’\-][\p{L}\p{N}_]+)*/gu;
const wordsIn = text => (text.match(WORDS) || []).length;
const slug = name => name.toLowerCase().normalize('NFKD').replace(/[^\p{L}\p{N}]+/gu, '-').replace(/[^a-z0-9-]/g, '').replace(/^-+|-+$/g, '').slice(0, 40);
const VOICES = ['af_heart', 'af_bella', 'af_nicole', 'af_sarah', 'am_michael', 'am_adam', 'am_eric', 'am_fenrir', 'am_puck',
  'bf_emma', 'bf_isabella', 'bm_george', 'bm_fable', 'bm_lewis'];
const ZONES = ['America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Europe/London', 'Europe/Berlin', 'Europe/Sofia', 'Australia/Sydney'];
const PRESET_LABEL = {'horror': 'Horror fiction', 'sleep-history': 'History stories for sleep', 'drama': 'Revenge & drama stories'};
const FORMAT_LABEL = {shorts: 'Shorts only: one vertical Short per story',
  funnel: 'Full video + teaser Short: the Short stops at the cliffhanger and points to the full video',
  long: 'Long video only: one horizontal video per story (e.g. 2–3 hour sleep stories)'};
const splitList = (text, pattern) => text.split(pattern).map(t => t.trim()).filter(Boolean);
const sampleUrl = file => '/api/voice-sample?file=' + encodeURIComponent(file);
const tiktokUrl = (channel, batch, file) => `/api/media?channel=${encodeURIComponent(channel)}&batch=${encodeURIComponent(batch)}&file=${encodeURIComponent(file)}`;

function VoiceSamples({data, form, setForm, busy, action}) {
  const samples = data?.voiceSamples ?? [];
  const using = s => s.engine === 'chatterbox' ? form.voice_engine === 'chatterbox' && (form.voice_clip || '') === (s.clip || '')
    : form.voice_engine === 'kokoro' && form.voice === s.voice;
  return <fieldset className="voice-samples"><legend>Hear the narrators</legend>
    <p className="wide">Every narrator reads the same short horror passage. Pick by ear, then save settings.
      {!data?.voiceInstalled && ' Chatterbox (the human-sounding voice) is not installed yet: run setup_voice, then make the samples again.'}</p>
    <div className="wide sample-actions">
      <button type="button" disabled={busy || data?.voices?.running} onClick={() => action({action: 'voice-samples'})}>
        {data?.voices?.running ? 'Making samples…' : samples.length ? 'Make samples again' : 'Make voice samples'}</button>
      <small>Your own clips: put 10–30 seconds of clean speech you have the rights to (WAV or MP3) in the <code>voices</code> folder.</small>
    </div>
    {samples.length > 0 && <ul className="sample-list wide">{samples.map(s => <li key={s.file} className={using(s) ? 'chosen' : ''}>
      <div><strong>{s.label}</strong><small>{s.description}</small></div>
      <audio controls preload="none" src={sampleUrl(s.file)}/>
      <button type="button" disabled={using(s)} onClick={() => setForm(s.engine === 'chatterbox'
        ? {...form, voice_engine: 'chatterbox', voice_clip: s.clip || ''} : {...form, voice_engine: 'kokoro', voice: s.voice})}>
        {using(s) ? 'Selected' : 'Use this voice'}</button></li>)}</ul>}
    <Log title="Voice samples" job={data?.voices}/>
  </fieldset>;
}

function Log({title, job}) {
  if (!job?.log?.length && !job?.error) return null;
  const failed = !job.running && job.exitCode !== null && job.exitCode !== 0;
  return <div className={'job' + (failed ? ' failed' : '')}>
    {failed && <p role="alert" className="job-error"><strong>{title} stopped:</strong> {job.error}</p>}
    {job.log?.length > 0 && <details open={job.running || failed}><summary>{title}{job.running ? ' · running' : failed ? ' · full log' : ' · log'}</summary>
      <pre>{job.log.join('')}</pre></details>}
  </div>;
}

function Reason({children}) { return children ? <small className="reason">{children}</small> : null; }

export default function ChannelControls({data, channel, onChannel, onRefresh}) {
  const [adding, setAdding] = useState(false), [settingsOpen, setSettingsOpen] = useState(false), [storyOpen, setStoryOpen] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [name, setName] = useState(''), [preset, setPreset] = useState('horror'), [story, setStory] = useState({title: '', text: ''}), [apiKey, setApiKey] = useState('');
  const [count, setCount] = useState(1), [genCount, setGenCount] = useState(5), [autoCount, setAutoCount] = useState(5), [scheduleCount, setScheduleCount] = useState(7);
  const [form, setForm] = useState(null), [lists, setLists] = useState({hashtags: '', tags: '', ctas: '', images: '', tiktok: ''});
  const [pexelsKey, setPexelsKey] = useState('');
  const [message, setMessage] = useState(''), [busy, setBusy] = useState(false);
  const c = data?.channel;
  const configKey = JSON.stringify(c && {...c, connected: undefined, token: undefined});
  useEffect(() => {
    setForm(c ?? null);
    if (c) setLists({hashtags: c.hashtags.join(' '), tags: c.tags.join(', '), ctas: (c.teaser_ctas || []).join('\n'),
      images: (c.image_keywords || []).join(', '), tiktok: (c.tiktok_hashtags || []).join(' ')});
  }, [channel, configKey]);

  async function action(body) {
    setBusy(true); setMessage('');
    try {
      const response = await fetch('/api/channels', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({channel, ...body})});
      const result = await response.json();
      if (!response.ok) throw Error(result.error);
      if (body.action === 'create') { onChannel(result.id); setAdding(false); setName(''); }
      else if (body.action === 'settings') setMessage('Settings saved.');
      else if (body.action === 'add-story') {
        setStory({title: '', text: ''}); setStoryOpen(false);
        setMessage(result.fits ? `Story added (${result.words} words).`
          : `Story added (${result.words} words), but this channel only uses stories of ${result.low}–${result.high} words.`);
      } else if (body.action === 'api-key') { setApiKey(''); setMessage(result.removed ? 'API key removed.' : 'API key saved on this computer.'); }
      else if (body.action === 'pexels-key') { setPexelsKey(''); setMessage(result.removed ? 'Pexels key removed.' : 'Pexels key saved on this computer.'); }
      await onRefresh();
    } catch (error) { setMessage(error.message); } finally { setBusy(false); }
  }
  const set = (key, value) => setForm({...form, [key]: value});
  const num = (key, value) => set(key, value === '' ? '' : Number(value));
  function saveSettings(event) {
    event.preventDefault();
    action({action: 'settings', settings: {...form, hashtags: splitList(lists.hashtags, /[\s,]+/), tags: splitList(lists.tags, /,/),
      teaser_ctas: splitList(lists.ctas, /\n/), image_keywords: splitList(lists.images, /,/), tiktok_hashtags: splitList(lists.tiktok, /[\s,]+/)}});
  }

  const format = c?.video_format;
  const jobRunning = data?.production.running || data?.generation?.running || data?.scheduling?.running || data?.upload?.running;
  const unit = {funnel: 'full videos + teaser Shorts', long: 'long videos'}[format] || 'Shorts';
  const [low, high] = ['funnel', 'long'].includes(format) ? [c?.full_min_words, c?.full_max_words] : [c?.min_words, c?.max_words];
  const signIn = c?.token === 'expired' ? 'The Google sign-in expired; click "Reconnect channel".' : !c?.connected ? 'Connect the channel first.' : '';
  const noBackgrounds = data && !data.backgroundFiles.length && !data.imageMode ? 'Add a background video to the backgrounds folder first, or switch Settings > Background to one image per story.' : '';
  const noVoice = c?.voice_engine === 'chatterbox' && data && !data.voiceInstalled ? 'This channel uses the Chatterbox voice: run setup_voice first, or choose Kokoro in Settings.' : '';
  const toExport = (data?.tiktok ?? []).filter(t => !t.parts.length).length;
  const id = slug(name);

  return <section className="channel-controls">
    <div className="channel-toolbar">
      <label>CHANNEL<select value={channel} onChange={e => onChannel(e.target.value)}>
        {(data?.channels ?? [{id: 'main', name: 'Main channel'}]).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      <button onClick={() => setAdding(!adding)}>+ Add channel</button>
      <button aria-expanded={settingsOpen} onClick={() => setSettingsOpen(!settingsOpen)}>Settings</button>
      <button aria-expanded={storyOpen} onClick={() => setStoryOpen(!storyOpen)}>+ Write a story</button>
      <span className="channel-identity">{c?.youtube_channel_name || c?.youtube_channel_id || 'No YouTube channel connected'}</span>
      <button disabled={busy || data?.connection.running} onClick={() => action({action: 'connect'})}>
        {data?.connection.running ? 'Finish Google sign-in…' : c?.token === 'missing' || !c ? 'Connect channel' : 'Reconnect channel'}</button>
    </div>
    {data?.connection.running && <div className="channel-note">Google sign-in is waiting in your browser. If you closed its tab or saw an error, cancel and connect again.
      <button disabled={busy} onClick={() => action({action: 'cancel-connect'})}>Cancel sign-in</button></div>}
    {c?.token === 'expired' && <p role="alert" className="job-error">The Google sign-in for this channel expired (in Testing mode Google ends sign-ins after 7 days). Click "Reconnect channel".</p>}
    {adding && <form className="channel-form" onSubmit={e => { e.preventDefault(); action({action: 'create', id, name, preset}); }}>
      <label>Channel name<input required maxLength={80} value={name} onChange={e => setName(e.target.value)} placeholder="Midnight Archive"/>
        {name && <small>Folder: channels/{id || '…'}</small>}</label>
      <label>Channel type<select value={preset} onChange={e => setPreset(e.target.value)}>
        {(data?.presets ?? []).map(p => <option key={p} value={p}>{PRESET_LABEL[p] || p}</option>)}
        <option value="">Blank (set everything yourself)</option></select>
        <small>Sets its own voice, look, format and posting time, so channels do not look alike.</small></label>
      <button disabled={busy || !id}>Create channel</button></form>}
    {storyOpen && <form className="story-form" onSubmit={e => { e.preventDefault(); action({action: 'add-story', ...story}); }}>
      <label>Title<input required maxLength={100} value={story.title} onChange={e => setStory({...story, title: e.target.value})} placeholder="The night the power went out at my wedding"/></label>
      <label>Story<textarea required rows={9} value={story.text} onChange={e => setStory({...story, text: e.target.value})} placeholder="Write or paste your own story."/></label>
      <small>{wordsIn(story.text)} words · this channel uses stories of {low}–{high} words</small>
      <button disabled={busy}>Add to story library</button></form>}
    {c?.token === 'missing' && <p className="channel-note">Connect once and choose the correct YouTube channel. Every upload checks its identity before publishing.</p>}
    <Log title="Google sign-in" job={data?.connection}/>

    {settingsOpen && form && <form className="settings-form" onSubmit={saveSettings}>
      <fieldset><legend>Format</legend>
        <label className="wide">What to make from each story<select value={form.video_format} onChange={e => set('video_format', e.target.value)}>
          {(data?.formats ?? ['shorts', 'funnel', 'long']).map(f => <option key={f} value={f}>{FORMAT_LABEL[f]}</option>)}</select></label>
        {form.video_format === 'shorts' ? <>
          <label>Story length: min words<input type="number" value={form.min_words} onChange={e => num('min_words', e.target.value)}/></label>
          <label>Story length: max words<input type="number" value={form.max_words} onChange={e => num('max_words', e.target.value)}/></label>
        </> : <>
          <label>Story length: min words<input type="number" value={form.full_min_words} onChange={e => num('full_min_words', e.target.value)}/></label>
          <label>Story length: max words<input type="number" value={form.full_max_words} onChange={e => num('full_max_words', e.target.value)}/></label>
          <label>Longest video (minutes)<input type="number" value={form.max_full_minutes} onChange={e => num('max_full_minutes', e.target.value)}/><small>Over 15 needs a phone-verified YouTube account.</small></label>
        </>}
        {form.video_format === 'funnel' && <label>Teaser length (seconds)<input type="number" value={form.teaser_seconds} onChange={e => num('teaser_seconds', e.target.value)}/></label>}
        {form.video_format === 'long' && <label>Generated story length (words)<input type="number" min="2000" max="30000" step="500" value={form.long_target_words} onChange={e => num('long_target_words', e.target.value)}/><small>About 130 words per minute at sleep pace.</small></label>}
        <label className="wide">Stories collected from Reddit<select value={form.collected_stories} onChange={e => set('collected_stories', e.target.value)}>
          <option value="rewrite">Use only their concept: the generator writes a new, original story from each (recommended)</option>
          <option value="narrate">Narrate them as they are (only with the author's permission)</option></select></label>
        <label className="wide">Background<select value={form.background_mode} onChange={e => set('background_mode', e.target.value)}>
          <option value="image">One atmospheric photo per story, slowly panned (free-licence, found automatically)</option>
          <option value="clips">Background video clips from the backgrounds folder</option></select>
          {form.background_mode === 'image' && <small>{data?.hasPexelsKey ? 'Searches Pexels, then Openverse.' : 'Searches Openverse (public domain). A free Pexels key below gives far more choice.'}</small>}</label>
      </fieldset>
      <fieldset><legend>Protection</legend>
        <label className="schedule-check"><input type="checkbox" checked={form.require_review} onChange={e => set('require_review', e.target.checked)}/>Only upload videos I approved</label>
        <label>Uploads per day (max)<input type="number" min="1" max="10" value={form.max_uploads_per_day} onChange={e => num('max_uploads_per_day', e.target.value)}/><small>A full video and its teaser count as two.</small></label>
        {!form.require_review && <p className="job-error wide">Without review, unwatched videos can go out. Human review is the main thing that separates a channel from "mass-produced" content.</p>}
      </fieldset>
      <fieldset><legend>Publishing</legend>
        <label>Visibility<select value={form.privacy} onChange={e => set('privacy', e.target.value)}><option value="public">Public</option><option value="unlisted">Unlisted</option><option value="private">Private</option></select></label>
        <label>Time zone of your audience<input list="zones" value={form.schedule.timezone} onChange={e => set('schedule', {...form.schedule, timezone: e.target.value})}/></label>
        <label>Daily publish times<input value={form.schedule.times.join(', ')} onChange={e => set('schedule', {...form.schedule, times: splitList(e.target.value, /[,\s]+/)})} placeholder="17:30, 21:00"/></label>
        <label>Hashtags<input value={lists.hashtags} onChange={e => setLists({...lists, hashtags: e.target.value})} placeholder="#horrorstories #scarystories"/><small>Separate with spaces. Up to 15; #shorts is left off long videos.</small></label>
        <label>Tags<input value={lists.tags} onChange={e => setLists({...lists, tags: e.target.value})} placeholder="horror story, scary story"/><small>Separate with commas.</small></label>
        <label className="schedule-check"><input type="checkbox" checked={form.schedule.enabled} onChange={e => set('schedule', {...form.schedule, enabled: e.target.checked})}/>Local schedule (only while the scheduler window is open)</label>
      </fieldset>
      <fieldset><legend>Voice and look</legend>
        <label>Narration engine<select value={form.voice_engine} onChange={e => set('voice_engine', e.target.value)}>
          <option value="chatterbox">Chatterbox: human-sounding, acts out tense moments</option>
          <option value="kokoro">Kokoro: fast and light, flatter delivery</option></select>
          {form.voice_engine === 'chatterbox' && !data?.voiceInstalled && <small className="reason">Not installed yet: run setup_voice.</small>}</label>
        {form.voice_engine === 'chatterbox' ? <>
          <label>Narrator<select value={form.voice_clip || ''} onChange={e => set('voice_clip', e.target.value)}>
            <option value="">Chatterbox built-in voice</option>
            {(data?.voiceClips ?? []).map(f => <option key={f} value={f}>{f.replace(/\.[a-z0-9]+$/i, '').replace(/_/g, ' ')}</option>)}</select>
            <small>Cloned from a clip in the voices folder. Listen below.</small></label>
          <label>Expressiveness<input type="number" min="0.25" max="1.5" step="0.05" value={form.expressiveness} onChange={e => num('expressiveness', e.target.value)}/><small>0.35 calm · 0.5 natural · 0.7 dramatic</small></label>
        </> : <label>Narrator voice<input list="voices" value={form.voice} onChange={e => set('voice', e.target.value)}/><small>Switches to a matching male/female voice when the story makes the narrator clear.</small></label>}
        <label>Narration speed<input type="number" min="0.5" max="2" step="0.05" value={form.speed} onChange={e => num('speed', e.target.value)}/></label>
        <label>Colour grade<select value={form.color_grade} onChange={e => set('color_grade', e.target.value)}>{(data?.grades ?? ['none']).map(g => <option key={g}>{g}</option>)}</select></label>
        <label>Captions<select value={form.caption_style} onChange={e => set('caption_style', e.target.value)}><option value="words">Word by word</option><option value="phrases">Short phrases</option></select></label>
        <label>Caption font<input value={form.caption_font} onChange={e => set('caption_font', e.target.value)}/></label>
        <label>Caption colour<input type="color" value={form.caption_style === 'words' ? form.caption_color : form.phrase_color}
          onChange={e => set(form.caption_style === 'words' ? 'caption_color' : 'phrase_color', e.target.value.toUpperCase())}/></label>
      </fieldset>
      <VoiceSamples data={data} form={form} setForm={setForm} busy={busy} action={action}/>
      <button type="button" className="link" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>{advanced ? 'Hide advanced settings' : 'Show advanced settings'}</button>
      {advanced && <>
        <fieldset><legend>Descriptions and calls to action</legend>
          {form.video_format === 'funnel' && <label className="wide">Teaser call to action, one per line (one is picked at random each time)
            <textarea rows={3} value={lists.ctas} onChange={e => setLists({...lists, ctas: e.target.value})}/></label>}
          <label className="wide">{form.video_format === 'funnel' ? 'Teaser description' : 'Short description'}
            {form.video_format === 'funnel' ? <textarea rows={3} value={form.teaser_description_template} onChange={e => set('teaser_description_template', e.target.value)}/>
              : <textarea rows={3} value={form.description_template} onChange={e => set('description_template', e.target.value)}/>}</label>
          {form.video_format !== 'shorts' && <label className="wide">Full video description<textarea rows={3} value={form.full_description_template} onChange={e => set('full_description_template', e.target.value)}/></label>}
          <label className="wide">Fiction note<input value={form.fiction_note} onChange={e => set('fiction_note', e.target.value)}/>
            <small>Placeholders: {'{hook}'} opening lines · {'{credit}'} original post · {'{fiction_note}'} · {'{hashtags}'} · {'{title}'} · {'{category}'}</small></label>
          <label className="schedule-check"><input type="checkbox" checked={form.credit_source} onChange={e => set('credit_source', e.target.checked)}/>Credit the original author when a story has one</label>
          <label>YouTube category<select value={form.category_id} onChange={e => set('category_id', e.target.value)}><option value="24">Entertainment</option><option value="22">People &amp; Blogs</option><option value="23">Comedy</option><option value="27">Education</option><option value="1">Film &amp; Animation</option><option value="20">Gaming</option></select></label>
        </fieldset>
        <fieldset><legend>Fine-tuning</legend>
          {form.voice_engine === 'chatterbox' ? <>
            {[['voice_clip_male', 'Male narrator clip (optional)'], ['voice_clip_female', 'Female narrator clip (optional)']].map(([key, label]) =>
              <label key={key}>{label}<select value={form[key] || ''} onChange={e => set(key, e.target.value)}><option value="">Same as the channel narrator</option>
                {(data?.voiceClips ?? []).map(f => <option key={f} value={f}>{f}</option>)}</select></label>)}
            <label>Chatterbox model<select value={form.chatterbox_model} onChange={e => set('chatterbox_model', e.target.value)}>
              <option value="standard">Standard: best control of delivery</option><option value="turbo">Turbo: faster, ignores expressiveness</option></select></label>
          </> : <>
            <label>Male voice (optional)<input list="voices" value={form.voice_male || ''} onChange={e => set('voice_male', e.target.value)}/></label>
            <label>Female voice (optional)<input list="voices" value={form.voice_female || ''} onChange={e => set('voice_female', e.target.value)}/></label>
          </>}
          <label className="wide">Image search phrases (comma-separated; one is tried when a story has none of its own)
            <input value={lists.images} onChange={e => setLists({...lists, images: e.target.value})} placeholder="abandoned house night, dark forest fog"/></label>
          <label>TikTok part length (seconds)<input type="number" min="65" max="600" value={form.tiktok_part_seconds} onChange={e => num('tiktok_part_seconds', e.target.value)}/><small>Parts are cut at sentence ends and never under 61 s.</small></label>
          <label>TikTok hashtags<input value={lists.tiktok} onChange={e => setLists({...lists, tiktok: e.target.value})} placeholder="#horrortok #scarystories"/></label>
          <label>Pause after sentences (s)<input type="number" min="0" max="2" step="0.05" value={form.period_pause} onChange={e => num('period_pause', e.target.value)}/></label>
          <label>Title card (seconds, 0 = off)<input type="number" min="0" max="10" step="0.5" value={form.title_card ? form.title_card_seconds : 0}
            onChange={e => { const value = Number(e.target.value); setForm({...form, title_card: value > 0, title_card_seconds: value}); }}/></label>
          <label>Music volume<input type="number" min="0" max="1" step="0.02" value={form.music_volume} onChange={e => num('music_volume', e.target.value)}/>
            <small>{data?.musicFiles ? `${data.musicFiles} track(s) in music/` : 'Add tracks you may use to the music/ folder'}</small></label>
          <label className="schedule-check"><input type="checkbox" checked={form.progress_bar} onChange={e => set('progress_bar', e.target.checked)}/>Progress bar on Shorts</label>
          <label className="schedule-check"><input type="checkbox" checked={form.clean_language} onChange={e => set('clean_language', e.target.checked)}/>Advertiser-friendly language</label>
          <label>Background rotation<select multiple value={form.backgrounds} onChange={e => set('backgrounds', Array.from(e.target.selectedOptions, o => o.value))}>
            {(data?.backgroundFiles ?? []).map(f => <option key={f}>{f}</option>)}</select><small>None selected = use all.</small></label>
          <label>Claude model<input value={form.generator_model} onChange={e => set('generator_model', e.target.value)}/><small>claude-sonnet-5-5, or claude-haiku-5-5 (cheaper)</small></label>
          <label>Story theme<input value={form.story_category} onChange={e => set('story_category', e.target.value)}/></label>
        </fieldset>
      </>}
      <button disabled={busy}>Save settings</button>
      {message && <span role="status" className="channel-message inline">{message}</span>}
      <datalist id="voices">{VOICES.map(v => <option key={v} value={v}/>)}</datalist>
      <datalist id="zones">{ZONES.map(z => <option key={z} value={z}/>)}</datalist>
    </form>}
    {settingsOpen && <form className="key-form" onSubmit={e => { e.preventDefault(); action({action: 'api-key', key: apiKey, confirmRemove: !apiKey && confirm('Remove the saved Claude API key?')}); }}>
      <label>Claude API key {data?.hasApiKey ? <span className="ok">· saved</span> : <span>· not set</span>}
        <input type="password" autoComplete="off" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={data?.hasApiKey ? 'Enter a new key to replace it' : 'sk-ant-…'}/></label>
      <small>Used only for “Generate stories”. Stored on this computer in credentials/, never sent to the browser.</small>
      <button disabled={busy}>{apiKey ? 'Save key' : data?.hasApiKey ? 'Remove key' : 'Save key'}</button>
    </form>}
    {settingsOpen && <form className="key-form" onSubmit={e => { e.preventDefault(); action({action: 'pexels-key', key: pexelsKey, confirmRemove: !pexelsKey && confirm('Remove the saved Pexels API key?')}); }}>
      <label>Pexels API key (free, optional) {data?.hasPexelsKey ? <span className="ok">· saved</span> : <span>· not set</span>}
        <input type="password" autoComplete="off" value={pexelsKey} onChange={e => setPexelsKey(e.target.value)} placeholder={data?.hasPexelsKey ? 'Enter a new key to replace it' : 'From pexels.com/api'}/></label>
      <small>For background photos. Free at pexels.com/api; Pexels photos may be used in monetised videos without credit.</small>
      <button disabled={busy}>{pexelsKey ? 'Save key' : data?.hasPexelsKey ? 'Remove key' : 'Save key'}</button>
    </form>}

    <div className="production-row"><div><strong>Generate stories</strong>
      <p>{data?.conceptSources ? `Rewrites the concept of your ${data.conceptSources} most-upvoted collected stories as new, original stories first; then writes from your best themes.`
        : 'New fictional stories on the themes that perform best on your channel.'} Each opens with a hook and is checked against your library so it is original.
        {data?.generatedStories ? ` ${data.generatedStories} unused AI stories in the library.` : ''}</p>
      <Reason>{!data?.hasApiKey && 'Add a Claude API key in Settings to enable this.'}</Reason></div>
      <input aria-label="Number of stories to generate" type="number" min="1" max="50" value={genCount} onChange={e => setGenCount(Number(e.target.value))}/>
      <button disabled={busy || jobRunning || !data?.hasApiKey} onClick={() => action({action: 'generate', count: genCount})}>{data?.generation?.running ? 'Writing…' : 'Generate stories'}</button></div>
    <Log title="Story generation" job={data?.generation}/>

    <div className="production-row"><div><strong>Create videos</strong>
      <p>{data?.eligibleStories ?? 0} unused stories fit this channel ({low}–{high} words). Makes {unit}, which then wait for your review.
        {data?.reviewStories ? ` ${data.reviewStories} story(ies) set aside to edit.` : ''}</p>
      <Reason>{noBackgrounds || noVoice || (data && !data.eligibleStories ? (data.conceptSources ? 'Collected stories are used as concepts: click "Generate stories" to turn them into originals.' : 'No stories fit: add, generate or write one, or change the word limits.') : '')}</Reason></div>
      <input aria-label="Number of videos to create" type="number" min="1" max="100" value={count} onChange={e => setCount(Number(e.target.value))}/>
      <button disabled={busy || jobRunning || !data?.eligibleStories || !!noBackgrounds || !!noVoice} onClick={() => action({action: 'produce', count})}>{data?.production.running ? 'Working…' : 'Create videos'}</button></div>

    <div className="production-row autopilot"><div><strong>Autopilot</strong>
      <p>One click: {data?.hasApiKey ? 'generate stories and ' : ''}create {unit}. They land in Review; nothing uploads until you approve it.</p>
      <Reason>{noBackgrounds || noVoice}</Reason></div>
      <input aria-label="Number of stories for autopilot" type="number" min="1" max="30" value={autoCount} onChange={e => setAutoCount(Number(e.target.value))}/>
      <button className="primary" disabled={busy || jobRunning || !!noBackgrounds || !!noVoice} onClick={() => action({action: 'autopilot', count: autoCount})}>{data?.production.running ? 'Running…' : 'Run autopilot'}</button></div>
    <Log title="Production" job={data?.production}/>
    {data?.failed?.length > 0 && <details className="failed-list"><summary>{data.failed.length} story(ies) could not be made</summary>
      <ul>{data.failed.map(f => <li key={f.batch + f.name}><strong>{f.title || f.name}</strong>: {f.status === 'skipped' ? 'set aside to edit' : 'failed'}. {f.reason}</li>)}</ul></details>}

    <div className="production-row"><div><strong>Schedule on YouTube</strong>
      <p>Uploads approved videos now; YouTube publishes each at your next free time ({c?.schedule?.times?.join(', ')} {c?.schedule?.timezone}), at most {c?.max_uploads_per_day} a day. Your computer can be off afterwards.</p>
      <Reason>{signIn || (data && !data.stats.ready ? (data.stats.review ? `${data.stats.review} video(s) are waiting for your review.` : 'No approved videos yet.') : '')}</Reason></div>
      <input aria-label="Number of videos to schedule" type="number" min="1" max="50" value={scheduleCount} onChange={e => setScheduleCount(Number(e.target.value))}/>
      <button disabled={busy || jobRunning || !c?.connected || !data?.stats.ready} onClick={() => action({action: 'preschedule', count: scheduleCount})}>{data?.scheduling?.running ? 'Scheduling…' : 'Schedule uploads'}</button></div>
    <Log title="Scheduling" job={data?.scheduling}/>

    <div className="production-row"><div><strong>Export for TikTok</strong>
      <p>Turns approved videos into vertical parts of just over a minute (TikTok pays only for videos over one minute), with “Part 2 is on my profile” end cards and a caption file for each. You post them yourself.</p>
      <Reason>{data && !toExport ? 'Approved videos that have not been exported appear here.' : ''}</Reason></div>
      <span className="count-pill">{toExport} to export</span>
      <button disabled={busy || jobRunning || !toExport} onClick={() => action({action: 'tiktok'})}>{data?.production.running && data?.production.channel === channel ? 'Working…' : 'Export for TikTok'}</button></div>
    {(data?.tiktok ?? []).some(t => t.parts.length) && <details className="tiktok-list"><summary>TikTok files ({data.tiktok.filter(t => t.parts.length).length} stories)</summary>
      <ul>{data.tiktok.filter(t => t.parts.length).map(t => <li key={t.batch + t.name}><strong>{t.title}</strong>
        {t.parts.map((p, i) => <span key={p.file}> <a href={tiktokUrl(channel, t.batch, p.file)} download>Part {i + 1}</a>
          {' · '}<a href={tiktokUrl(channel, t.batch, p.file.replace(/\.mp4$/, '.txt'))} target="_blank" rel="noreferrer">caption</a></span>)}</li>)}</ul>
      <small>Files are also in each batch folder under tiktok/, with HOW_TO_POST.txt.</small></details>}
    {message && !settingsOpen && <p role="status" className="channel-message">{message}</p>}
  </section>;
}
