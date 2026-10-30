'use client';
import {useEffect, useState, useRef} from 'react';
import ChannelControls from './channel-controls';
import ReviewPanel from './review-panel';

const time = seconds => { const rounded = Math.round(seconds || 0); return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, '0')}`; };
const mediaUrl = (channel, video) => `/api/media?channel=${encodeURIComponent(channel)}&batch=${encodeURIComponent(video.batch)}&file=${encodeURIComponent(video.file)}`;
const STATUS = {review: 'Waiting for review', rejected: 'Rejected', ready: 'Approved', waiting: 'After full video', uploaded: 'Uploaded',
  scheduled: 'Scheduled', used: 'Used', checking: 'Checking upload', resumable: 'Will resume'};
const VISIBILITY = {public: 'Public', unlisted: 'Unlisted', private: 'Private'};

function Icon({type, size = 20}) {
  const shapes = {play: <path d="m9 5 11 7-11 7Z"/>, upload: <><path d="M12 16V3m-5 5 5-5 5 5"/><path d="M4 15v5h16v-5"/></>,
    film: <><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 4v16M17 4v16M3 9h4m-4 6h4m10-6h4m-4 6h4"/></>,
    check: <path d="m5 12 4 4L20 5"/>, story: <><path d="M7 3h9l4 4v14H4V3Z"/><path d="M8 11h8m-8 4h6"/></>, arrow: <path d="M5 12h14m-5-5 5 5-5 5"/>,
    eye: <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></>};
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{shapes[type] || shapes.play}</svg>;
}

const JOBS = [['generation', 'Writing stories'], ['production', 'Making videos'], ['scheduling', 'Scheduling uploads'],
  ['upload', 'Uploading'], ['voices', 'Working on voice samples'], ['designs', 'Designing voices']];

// What is running right now, and its latest step, so nothing happens silently.
function WorkingBar({data}) {
  const running = JOBS.filter(([key]) => data?.[key]?.running);
  if (!running.length) return null;
  return <div className="working-bar" role="status">{running.map(([key, label]) => {
    const lines = (data[key].log || []).join('').split(/\r?\n/).map(l => l.trim()).filter(Boolean);
    const last = [...lines].reverse().find(l => !/^(Traceback|File |Warning|UserWarning|warnings\.warn)/.test(l)) || 'Starting…';
    return <div key={key}><span className="pulse"/><strong>{label}{data[key].channel ? ` · ${data.channels?.find(c => c.id === data[key].channel)?.name || data[key].channel}` : ''}</strong><span className="step">{last.slice(0, 160)}</span></div>;
  })}</div>;
}

function nextStep(data) {
  if (!data) return null;
  const c = data.channel;
  if (!data.backgroundFiles.length && !data.imageMode) return ['Add a background video', 'Put at least one MP4 you have the rights to use in the backgrounds folder, or switch Settings > Background to one photo per story.'];
  if (c.voice_engine === 'chatterbox' && !data.voiceInstalled) return ['Install the Chatterbox voice', 'Run setup_voice (it downloads about 3 GB once), or switch Settings > Narration engine to Kokoro.'];
  if (c.token === 'expired') return ['Reconnect YouTube', 'The Google sign-in for this channel expired. Click "Reconnect channel".'];
  if (data.reviewItems.length) return [`Review ${data.reviewItems.length} video${data.reviewItems.length === 1 ? '' : 's'}`, 'Watch them below and approve the ones that are good enough to publish.'];
  if (data.related.length) return [`Link ${data.related.length} teaser${data.related.length === 1 ? '' : 's'} in YouTube Studio`, 'Set each teaser Short\'s Related video so viewers can tap through to the full story.'];
  if (c.token === 'missing' && data.stats.ready) return ['Connect YouTube', 'Approved videos are waiting; connect the channel to schedule them.'];
  if (data.stats.ready) return [`Schedule ${data.stats.ready} approved video${data.stats.ready === 1 ? '' : 's'}`, 'Use "Schedule on YouTube" so they publish at your set times.'];
  if (!data.eligibleStories && data.conceptSources) return ['Generate stories', `${data.conceptSources} collected stories are waiting to be rewritten as originals. Click "Generate stories".`];
  if (!data.eligibleStories) return ['Add stories', 'Generate stories, write one, or collect some; none fit this channel right now.'];
  return ['Create the next batch', `${data.eligibleStories} stories are ready to become videos.`];
}

export default function Home() {
  const [channel, setChannelState] = useState('main');
  // Remember the chosen channel across restarts (per browser; harmless if storage is unavailable).
  useEffect(() => { try { const saved = localStorage.getItem('channel'); if (saved) setChannelState(saved); } catch {} }, []);
  const setChannel = id => { setChannelState(id); try { localStorage.setItem('channel', id); } catch {} };
  const channelRef = useRef(channel); channelRef.current = channel;
  const [data, setData] = useState(null), [error, setError] = useState(''), [sending, setSending] = useState(false), [filter, setFilter] = useState('all');
  const [preview, setPreview] = useState(null), [offline, setOffline] = useState(false);
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
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, offline ? 10000 : 2500);
    return () => clearInterval(id);
  }, [channel, offline]);
  async function post(url, body) {
    const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({channel, ...body})});
    const result = await response.json();
    if (!response.ok) throw Error(result.error);
    return result;
  }
  async function upload() { setSending(true); setError(''); try { await post('/api/upload', {}); await refresh(); } catch (e) { setError(e.message); } finally { setSending(false); } }
  async function markDone(teaserId) { try { await post('/api/channels', {action: 'related-done', teaserId}); await refresh(); } catch (e) { setError(e.message); } }
  async function insights() { setError(''); try { await post('/api/insights', {connect: !data?.insights.connected}); await refresh(); } catch (e) { setError(e.message); } }

  const stats = data?.stats ?? {}, busy = sending || data?.upload.running || data?.scheduling?.running;
  const rows = (data?.queue ?? []).filter(v => filter === 'all' || v.status === filter || (filter === 'uploaded' && v.status === 'scheduled'));
  const log = (data?.upload.log.join('') ?? '') + (data?.scheduling?.log?.join('') ?? '');
  const progress = [...log.matchAll(/Uploaded (\d+)%/g)].at(-1)?.[1] ?? '0';
  const c = data?.channel;
  const status = !c ? ['loading', 'Loading…'] : c.token === 'ok' ? ['ok', `Connected as ${c.youtube_channel_name || c.youtube_channel_id}`]
    : c.token === 'expired' ? ['bad', 'Sign-in expired'] : ['off', 'YouTube not connected'];
  const step = nextStep(data);
  const visibility = VISIBILITY[c?.privacy] ?? 'Public';
  const uploadReason = !data ? '' : c.token === 'expired' ? 'Reconnect the channel first.' : !c.connected ? 'Connect the channel first.'
    : !data.next ? (stats.review ? 'Approve videos in Review first.' : 'No approved videos waiting.') : '';

  return <div className="shell">
    <header><strong className="brand">Story Shorts Studio</strong><div className={'connection ' + status[0]}><i/>{status[1]}</div></header>
    <main>
      <WorkingBar data={data}/>
      {offline && <div role="alert" className="error">The dashboard server stopped. Start it again with start_dashboard (the window must stay open).</div>}
      {step && <section className="next-step" aria-label="Next step"><div className="eyebrow">NEXT STEP</div><h1>{step[0]}</h1><p>{step[1]}</p></section>}
      <ChannelControls data={data} channel={channel} onChannel={id => { setData(null); setChannel(id); }} onRefresh={refresh}/>
      <ReviewPanel channel={channel} data={data} onRefresh={refresh}/>
      {data?.related?.length > 0 && <section className="related-panel"><div className="eyebrow">ONE STEP IN YOUTUBE STUDIO</div>
        <h2>Link each teaser Short to its full video</h2>
        <p>YouTube does not let apps set a Short's “Related video”, and links in Shorts descriptions are not clickable, so do it once per Short:
          open it in Studio, choose <b>Related video</b>, pick the full video below, save.</p>
        <ul>{data.related.map(r => <li key={r.teaser_id}><span className="story-title">{r.title}</span>
          <a className="refresh" href={`https://studio.youtube.com/video/${r.teaser_id}/edit`} target="_blank" rel="noreferrer">Open Short in Studio ↗</a>
          <small>Pick: “{r.full_title}”</small><button className="refresh" onClick={() => markDone(r.teaser_id)}>Done</button></li>)}</ul></section>}
      <section className="stats" aria-label="Production statistics">{[
        ['Waiting for review', stats.review, 'Nothing uploads until approved', 'eye'], ['Approved', stats.ready, 'Ready to schedule', 'film'],
        ['Uploaded', stats.uploaded, 'Including scheduled', 'check'], ['Story library', stats.stories, 'Stories in this channel', 'story'],
      ].map(([label, value, note, icon]) => <article className="stat" key={label}><div className="stat-top">{label}<Icon type={icon}/></div><strong>{value ?? '—'}</strong><small>{note}</small></article>)}</section>
      <section className="insights-panel"><div className="insights-head"><div><div className="eyebrow">YOUTUBE INSIGHTS</div><h2>How your stories travel</h2>
        <p>{data?.insights.updatedAt ? 'Updated ' + new Date(data.insights.updatedAt).toLocaleString() + '. Refreshes every 5 minutes.' : 'Views appear here once the channel is connected and videos are uploaded.'}</p></div>
        {!c?.connected && <button className="refresh" disabled={data?.insights.running} onClick={insights}>{data?.insights.connected ? '↻ Refresh' : 'Connect read-only insights'}</button>}</div>
        <div className="insights-numbers">{[['Views', 'views'], ['Likes', 'likes'], ['Comments', 'comments']].map(([label, key]) =>
          <div key={key}><strong>{data?.insights.updatedAt ? data.insights.totals[key].toLocaleString() : '—'}</strong><span>{label}</span></div>)}</div>
        {data?.insights.error && <p className="insights-note" role="alert">{data.insights.error}</p>}
        {data?.topPerformers?.length > 0 && <div className="top-list"><div className="eyebrow">TOP PERFORMERS · THE STORY GENERATOR LEARNS FROM THESE</div>
          <ol>{data.topPerformers.map(v => <li key={v.videoId}><a href={'https://www.youtube.com/watch?v=' + v.videoId} target="_blank" rel="noreferrer">{v.title}</a><span>{v.views.toLocaleString()} views{v.watched != null ? ` · ${Math.round(v.watched)}% watched` : ''} · {v.kind}</span></li>)}</ol></div>}
        {c?.connected && data?.insights.retention === 'reconnect' && <p className="insights-note">To see how much of each video people watch, click “Reconnect channel” once; the new sign-in includes read-only YouTube Analytics.</p>}
      </section>
      {error && <div role="alert" className="error">{error}<button onClick={() => { setError(''); refresh(); }}>Dismiss</button></div>}
      <div className="workspace"><section className="library"><div className="section-head"><div><h2>Video queue <span>{stats.total ?? 0}</span></h2><p>Click a video to watch it.</p></div>
        <button className="refresh" onClick={refresh}>↻ Refresh</button></div>
        <div className="tabs" role="group" aria-label="Filter videos">{[['all', 'All'], ['review', 'Review'], ['ready', 'Approved'], ['waiting', 'Waiting'], ['uploaded', 'Uploaded'], ['rejected', 'Rejected']].map(([id, label]) =>
          <button key={id} aria-pressed={filter === id} className={filter === id ? 'active' : ''} onClick={() => setFilter(id)}>{label}</button>)}</div>
        <div className="table-wrap"><table><thead><tr><th>STORY</th><th>LENGTH</th><th>VIEWS</th><th>STATUS</th><th/></tr></thead><tbody>
          {rows.map(video => <tr key={video.batch + video.name} className="clickable" onClick={() => setPreview(video)}>
            <td><div className="story-cell"><span className="thumbnail"><Icon type="play" size={16}/></span><div>
              <div className="story-title" title={video.title}><span className={'kind ' + video.kind}>{({full: 'Full', teaser: 'Teaser', short: 'Short'})[video.kind]}</span>{video.generated && <span className="kind ai">AI story</span>}{video.title}</div>
              <small>{video.batch.replace('_', ' ')}</small></div></div></td>
            <td className="duration">{time(video.duration)}</td>
            <td className="duration">{video.insights?.viewCount?.toLocaleString() ?? '—'}{video.insights?.averageViewPercentage != null && <small className="watched" title="Average percentage watched"> · {Math.round(video.insights.averageViewPercentage)}%</small>}</td>
            <td><span className={'badge ' + video.status}><i/>{video.status === 'scheduled' ? 'Scheduled ' + new Date(video.publishAt).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : STATUS[video.status]}</span></td>
            <td>{video.videoId && <a className="external" onClick={e => e.stopPropagation()} href={'https://www.youtube.com/watch?v=' + video.videoId} target="_blank" rel="noreferrer" aria-label={'View on YouTube: ' + video.title}>↗</a>}</td></tr>)}
        </tbody></table>{rows.length === 0 && <div className="empty">{data ? 'No videos in this view.' : 'Loading your workspace…'}</div>}</div></section>
        <aside><section className="publish"><div className="publish-top"><span><Icon type="upload" size={17}/> NEXT UPLOAD</span><span className="public">{visibility}</span></div>
          <h3>{data?.next?.title ?? (data ? 'No approved videos waiting.' : 'Loading…')}</h3>
          <p className="publish-description">{data?.next ? (data.next.kind === 'full' ? 'The full video and its thumbnail. Its teaser Short goes next.' : data.next.kind === 'teaser' ? 'The teaser Short; it never goes live before its full video.' : 'One Short with its title, description and hashtags.')
            : 'For regular publishing, use "Schedule on YouTube" instead of uploading one by one.'}</p>
          <button className="upload-button" disabled={!!uploadReason || busy} onClick={upload}><Icon type="upload"/>{busy ? 'Uploading…' : `Upload now · ${visibility}`}<Icon type="arrow" size={18}/></button>
          {uploadReason && <small className="reason">{uploadReason}</small>}
          {c?.privacy !== 'private' && <small className="reason">Until Google audits your API project, YouTube keeps API uploads private.</small>}
          {busy && <div className="progress"><div style={{width: progress + '%'}}/></div>}
          <div className="publish-foot"><Icon type="check" size={14}/> Never uploads the same video twice; interrupted uploads resume.</div></section>
          <section className="activity"><div className="activity-title"><h2>Upload activity</h2><span className={busy ? 'live' : 'quiet'}>{busy ? '● LIVE' : '● IDLE'}</span></div>
            {data?.upload.error && <p role="alert" className="job-error">{data.upload.error}</p>}
            {log ? <pre>{log}</pre> : <div className="activity-empty"><p>Upload progress appears here.</p></div>}</section></aside></div>
      <footer><span><span className="footer-dot"/> Story Shorts Studio · runs on this computer</span></footer>
    </main>
    {preview && <div className="modal" role="dialog" aria-modal="true" aria-label={'Preview: ' + preview.title} onClick={() => setPreview(null)}>
      <div className="modal-body" onClick={e => e.stopPropagation()}>
        <button className="close" aria-label="Close preview" onClick={() => setPreview(null)}>×</button>
        <video controls autoPlay playsInline src={mediaUrl(channel, preview)} className={preview.kind === 'full' ? 'landscape' : 'vertical'}/>
        <h3>{preview.title}</h3><p>{STATUS[preview.status]} · {time(preview.duration)}</p></div></div>}
  </div>;
}
