'use client';
// Simple mode: voice, story, video. Everything else lives in /advanced.
import {useEffect, useRef, useState} from 'react';
import {WorkingBar, lastLine} from './working';

const sampleUrl = file => '/api/voice-sample?file=' + encodeURIComponent(file);
const mediaUrl = (channel, batch, file) => `/api/media?channel=${encodeURIComponent(channel)}&batch=${encodeURIComponent(batch)}&file=${encodeURIComponent(file)}`;
const pretty = clip => clip ? clip.replace(/\.[a-z0-9]+$/i, '').replace(/^designed_/, '').replace(/_/g, ' ') : '';
const minutes = seconds => `${Math.floor((seconds || 0) / 60)}:${String(Math.round(seconds || 0) % 60).padStart(2, '0')}`;

const ROLES = {
  narrator: {title: 'Story narrator', note: 'Tells the story. Dark and calm works best for horror.',
    description: 'A deep, slow male voice in his fifties, slightly hoarse, speaking quietly and close to the microphone, calm and matter-of-fact, like a man telling the one story he never tells anyone.'},
  host: {title: 'Intro host', note: 'Welcomes listeners after the hook and signs off at the end. A cheerful voice makes a nice contrast.',
    description: 'A warm, upbeat male radio host in his forties, bright and friendly with a smile you can hear, clear American accent, medium pitch, relaxed and welcoming, like a late-night DJ who is genuinely glad you tuned in. Crisp diction, clean close-microphone sound.'},
};

function Step({number, title, done, children}) {
  return <section className={'simple-step' + (done ? ' done' : '')}>
    <div className="step-number">{done ? '✓' : number}</div>
    <div className="step-body"><h2>{title}</h2>{children}</div>
  </section>;
}

function VoiceSlot({role, data, busy, act, designing, setDesigning}) {
  const c = data.channel;
  const clip = role === 'narrator' ? (c.voice_engine === 'chatterbox' ? c.voice_clip : '') : c.host_voice_clip;
  const sample = (data.voiceSamples || []).find(s => s.engine === 'chatterbox' && (s.clip || '') === (clip || ''));
  const others = (data.voiceClips || []).filter(f => role === 'narrator' ? f !== c.host_voice_clip : f !== c.voice_clip);
  return <div className="voice-slot">
    <div className="slot-head"><div><strong>{ROLES[role].title}</strong><small>{ROLES[role].note}</small></div></div>
    <div className="slot-current">
      {clip ? <span className="slot-name">{pretty(clip)}</span> : <span className="slot-empty">{role === 'host' ? 'No intro host: the video is only the story' : 'Not chosen yet'}</span>}
      {clip && (sample ? <audio controls preload="none" src={sampleUrl(sample.file)}/> : <small>{data.voices?.running ? 'Preparing its sample…' : 'No sample to play yet.'}</small>)}
    </div>
    <div className="slot-actions">
      <button type="button" className="big" disabled={busy} onClick={() => setDesigning(designing === role ? null : role)}>
        {designing === role ? 'Close' : '✨ Create a new voice'}</button>
      <select aria-label={'Saved voices for ' + ROLES[role].title} value="" disabled={busy}
        onChange={e => e.target.value && act({action: 'set-voice', role, clip: e.target.value === '-' ? '' : e.target.value}, 'Saved.')}>
        <option value="">Use a saved voice…</option>
        {role === 'host' && clip && <option value="-">No intro host</option>}
        {others.map(f => <option key={f} value={f}>{pretty(f)}</option>)}
      </select>
    </div>
  </div>;
}

function Designer({role, data, busy, act}) {
  const [description, setDescription] = useState(ROLES[role].description);
  useEffect(() => setDescription(ROLES[role].description), [role]);
  const running = data.designs?.running;
  const takes = (data.voiceDesigns || []).slice(0, 3);
  if (!data.designerInstalled) return <p className="simple-note">The voice creator is not installed. Run <code>setup_voice_designer.cmd</code> once in the StoryShortsStudio folder.</p>;
  return <div className="designer-simple">
    <h3>New voice for: {ROLES[role].title}</h3>
    <label>Describe the voice (you can keep this as it is)
      <textarea rows={3} maxLength={500} value={description} onChange={e => setDescription(e.target.value)}/></label>
    <button type="button" className="primary big" disabled={busy || running || description.trim().length < 10}
      onClick={() => act({action: 'design-voice', description, count: 3}, 'Creating 3 voices. About a minute each.')}>
      {running ? 'Creating voices…' : 'Create 3 voices'}</button>
    {running && <p className="simple-note">{lastLine(data.designs)}</p>}
    {!running && takes.length > 0 && <><p className="simple-note">Listen, then pick one:</p>
      <ul className="takes">{takes.map((d, i) => <li key={d.file}>
        <strong>Voice {i + 1}</strong>
        <audio controls preload="none" src={sampleUrl(d.file)}/>
        <button type="button" className="primary" disabled={busy}
          onClick={() => act({action: 'keep-design', file: d.file, role,
            name: `${role === 'host' ? 'Host' : 'Narrator'} ${d.file.slice(7, 15)} ${d.file.slice(16, 20)} ${i + 1}`},
          `Saved as the ${ROLES[role].title.toLowerCase()}.`)}>Use this voice</button>
      </li>)}</ul></>}
    {data.designs?.error && !running && <p className="simple-error">{data.designs.error}</p>}
  </div>;
}

export default function Simple() {
  const [channel, setChannelState] = useState('main');
  useEffect(() => { try { const saved = localStorage.getItem('channel'); if (saved) setChannelState(saved); } catch {} }, []);
  const setChannel = id => { setChannelState(id); try { localStorage.setItem('channel', id); } catch {} };
  const channelRef = useRef(channel); channelRef.current = channel;
  const [data, setData] = useState(null), [message, setMessage] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [designing, setDesigning] = useState(null), [fullStory, setFullStory] = useState(false), [offline, setOffline] = useState(false);

  async function refresh() {
    try {
      const response = await fetch('/api/dashboard?channel=' + encodeURIComponent(channel), {cache: 'no-store'});
      const result = await response.json();
      if (!response.ok) throw Error(result.error);
      setOffline(false);
      if (channelRef.current === channel) setData(result);
    } catch (e) {
      if (e instanceof TypeError) setOffline(true);
      else if (/profile not found/i.test(e.message) && channel !== 'main') setChannel('main');
      else setError(e.message);
    }
  }
  useEffect(() => { refresh(); const id = setInterval(refresh, 2500); return () => clearInterval(id); }, [channel]);
  useEffect(() => { if (!message) return; const t = setTimeout(() => setMessage(''), 7000); return () => clearTimeout(t); }, [message]);

  async function act(body, done, url = '/api/channels') {
    setBusy(true); setError(''); setMessage('');
    try {
      const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({channel, ...body})});
      const result = await response.json();
      if (!response.ok) throw Error(result.error);
      if (body.action === 'keep-design') setDesigning(null);
      if (done) setMessage(done);
      await refresh();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  if (!data) return <div className="simple-shell"><header><strong className="brand">Story Shorts Studio</strong></header>
    <main className="simple-main"><p className="simple-note">{offline ? 'The dashboard server is not running. Start it again with start_dashboard.' : 'Loading…'}</p></main></div>;

  const c = data.channel, story = data.latestStory;
  const narratorSet = c.voice_engine === 'chatterbox' && !!c.voice_clip;
  const writing = data.generation?.running, making = data.production?.running;
  // The newest finished video of this channel.
  const newestBatch = (data.queue || []).reduce((m, v) => (v.batch > m ? v.batch : m), '');
  const videos = (data.queue || []).filter(v => v.batch === newestBatch);
  const main = videos.find(v => v.kind === 'full') || videos[0];
  const teaser = videos.find(v => v.kind === 'teaser');
  const failed = (data.failed || []).filter(f => f.batch >= newestBatch).at(-1);
  const productionError = !making && data.production?.exitCode ? data.production.error : '';
  const reviewItem = main && (data.reviewItems || []).find(r => r.batch === main.batch && r.name === main.item);
  const approved = main && ['ready', 'waiting', 'uploaded', 'scheduled'].includes(main.status);

  return <div className="simple-shell">
    <header><strong className="brand">Story Shorts Studio</strong>
      <div className="simple-head-right">
        {(data.channels || []).length > 1 && <select aria-label="Channel" value={channel} onChange={e => { setData(null); setChannel(e.target.value); }}>
          {data.channels.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}
        <a className="mode-link" href="/advanced">Advanced settings →</a></div></header>
    <main className="simple-main">
      <WorkingBar data={data}/>
      {message && <div className="simple-toast" role="status">{message}</div>}
      {error && <div className="simple-error" role="alert">{error} <button onClick={() => setError('')}>OK</button></div>}

      <Step number={1} title="Voices" done={narratorSet}>
        {!data.voiceInstalled && <p className="simple-error">The narrator voice is not installed. Run <code>setup_voice.cmd</code> once in the StoryShortsStudio folder.</p>}
        <div className="voice-slots">
          <VoiceSlot role="narrator" data={data} busy={busy} act={act} designing={designing} setDesigning={setDesigning}/>
          <VoiceSlot role="host" data={data} busy={busy} act={act} designing={designing} setDesigning={setDesigning}/>
        </div>
        {designing && <Designer role={designing} data={data} busy={busy} act={act}/>}
      </Step>

      <Step number={2} title="Story" done={!!story && !story.used}>
        <div className="step-actions">
          <button type="button" className="primary big" disabled={busy || writing || making || !data.hasApiKey}
            onClick={() => act({action: 'generate', count: 1}, 'Writing a new story. About 1–2 minutes.')}>
            {writing ? 'Writing…' : '✍️ Write a new story'}</button>
          {!data.hasApiKey && <small>Add your Claude API key in Advanced settings first.</small>}
        </div>
        {writing && <p className="simple-note">{lastLine(data.generation)}</p>}
        {!writing && data.generation?.exitCode ? <p className="simple-error">{data.generation.error}</p> : null}
        {story && <article className="story-preview">
          <h3>{story.title}</h3>
          <small>{story.words} words · {story.used ? 'already made into a video' : story.ready ? 'ready for a video' : story.tooLong ? 'too long for this channel' : 'too short for this channel'}</small>
          <p>{fullStory ? story.text : story.text.slice(0, 450) + (story.text.length > 450 ? '…' : '')}</p>
          {story.text.length > 450 && <button type="button" className="link" onClick={() => setFullStory(!fullStory)}>{fullStory ? 'Show less' : 'Read more'}</button>}
        </article>}
        {!story && !writing && <p className="simple-note">No story yet. Click “Write a new story”.</p>}
      </Step>

      <Step number={3} title="Video" done={approved}>
        <div className="step-actions">
          <button type="button" className="primary big" disabled={busy || making || writing || !story?.ready || !narratorSet}
            onClick={() => act({action: 'produce', count: 1, story: story.file}, 'Making the video. This takes about 10–15 minutes.')}>
            {making ? 'Making the video…' : '🎬 Make the video'}</button>
          {story?.used && <button type="button" className="big" disabled={busy || making || writing || !narratorSet}
            onClick={() => act({action: 'produce', count: 1, story: story.file, remake: true}, 'Remaking the video with the current voice, pacing and music. About 10–15 minutes.')}>
            🔁 Remake this video</button>}
          {!making && story?.used && <small>Remake uses the same story with the latest voice, pacing and music. The old video is set aside so it is never uploaded.</small>}
          {!narratorSet && <small>Choose a story narrator in step 1 first.</small>}
        </div>
        {making && <p className="simple-note">{lastLine(data.production)}</p>}
        {!making && (productionError || failed) && <p className="simple-error">{failed?.reason || productionError}</p>}
        {main && !making && <div className="video-result">
          <video controls playsInline preload="metadata" src={mediaUrl(channel, main.batch, main.file)} className={main.kind === 'full' ? 'landscape' : 'vertical'}/>
          <div className="video-side">
            <h3>{main.title}</h3>
            <small>{minutes(main.duration)}{teaser ? ' · plus a teaser Short' : ''}</small>
            {teaser && <details><summary>Watch the teaser Short</summary>
              <video controls playsInline preload="none" src={mediaUrl(channel, teaser.batch, teaser.file)} className="vertical small"/></details>}
            {reviewItem?.warnings?.length > 0 && <ul className="warnings">{reviewItem.warnings.map(w => <li key={w}>{w}</li>)}</ul>}
            {main.status === 'review' && <div className="step-actions">
              <button type="button" className="primary big" disabled={busy}
                onClick={() => act({action: 'review', batch: main.batch, names: [main.item], decision: 'approved'}, 'Approved.')}>👍 Approve</button>
              <button type="button" className="big" disabled={busy}
                onClick={() => act({action: 'review', batch: main.batch, names: [main.item], decision: 'rejected'}, 'Rejected. Write a new story and make another.')}>👎 Reject</button>
            </div>}
            {approved && <p className="simple-ok">{main.status === 'uploaded' || main.status === 'scheduled' ? 'Uploaded to YouTube.' : 'Approved. Upload it from Advanced settings → Upload now or Schedule on YouTube.'}</p>}
            {main.status === 'rejected' && <p className="simple-note">Rejected. Write a new story and make another.</p>}
          </div>
        </div>}
      </Step>
      <p className="simple-foot">Everything else (channel settings, music volume, persona wording, schedules, uploads) is in <a href="/advanced">Advanced settings</a>.</p>
    </main>
  </div>;
}
