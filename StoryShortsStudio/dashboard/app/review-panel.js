'use client';
import {useState} from 'react';

const mediaUrl = (channel, batch, file) =>
  `/api/media?channel=${encodeURIComponent(channel)}&batch=${encodeURIComponent(batch)}&file=${encodeURIComponent(file)}`;
const minutes = seconds => (seconds ? `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, '0')}` : '');
const KIND = {full: 'Full video', teaser: 'Teaser Short', short: 'Short'};

async function post(body) {
  const response = await fetch('/api/channels', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw Error(result.error);
  return result;
}

function ReviewCard({channel, item, selected, onSelect, onDone, busy, setBusy, setMessage}) {
  const [title, setTitle] = useState(item.title);
  const [note, setNote] = useState('');
  const [part, setPart] = useState(0);
  const current = item.files[part] || item.files[0];
  async function act(body, done) {
    setBusy(true); setMessage('');
    try { await post({channel, batch: item.batch, ...body}); done?.(); await onDone(); } catch (error) { setMessage(error.message); } finally { setBusy(false); }
  }
  return <article className={'review-card' + (item.warnings.length ? ' warn' : '')}>
    <div className="review-media">
      <video key={current.file} controls preload="metadata" playsInline src={mediaUrl(channel, item.batch, current.file)}
             className={current.kind === 'full' ? 'landscape' : 'vertical'} aria-label={`Preview: ${item.title}`}/>
      {item.files.length > 1 && <div className="part-tabs" role="group" aria-label="Choose which video to preview">
        {item.files.map((f, i) => <button key={f.file} aria-pressed={i === part} className={i === part ? 'active' : ''} onClick={() => setPart(i)}>
          {KIND[f.kind]} {minutes(f.duration)}</button>)}
      </div>}
    </div>
    <div className="review-body">
      <label className="review-select"><input type="checkbox" checked={selected} onChange={e => onSelect(e.target.checked)}/> Select</label>
      <label className="review-title">YouTube title
        <span className="title-row"><input value={title} maxLength={100} onChange={e => setTitle(e.target.value)}/>
          {title.trim() !== item.title && <button disabled={busy} onClick={() => act({action: 'edit-title', name: item.name, title})}>Save title</button>}
        </span>
        {title.trim() !== item.title && <small>Changes the YouTube title only; the title card in the video keeps the original words.</small>}
      </label>
      {item.warnings.length > 0 && <ul className="review-warnings" aria-label="Sameness warnings">
        {item.warnings.map(w => <li key={w}>{w}</li>)}
      </ul>}
      <details><summary>Description</summary><pre>{item.description}</pre></details>
      {item.script && <details><summary>Script (opening)</summary><p className="script">{item.script}{item.script.length >= 1200 ? '…' : ''}</p></details>}
      <p className="review-meta">{item.batch} · voice {item.voice || 'default'}{item.generated ? ' · AI-written story' : ''}</p>
      <div className="review-actions">
        <button className="approve" disabled={busy} onClick={() => act({action: 'review', names: [item.name], decision: 'approved'})}>Approve</button>
        <input aria-label="Reason for rejecting (optional)" placeholder="Reason (optional)" value={note} maxLength={500} onChange={e => setNote(e.target.value)}/>
        <button className="reject" disabled={busy} onClick={() => act({action: 'review', names: [item.name], decision: 'rejected', note})}>Reject</button>
      </div>
    </div>
  </article>;
}

export default function ReviewPanel({channel, data, onRefresh}) {
  const items = data?.reviewItems ?? [];
  const [selected, setSelected] = useState({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const chosen = items.filter(item => selected[item.batch + '/' + item.name]);

  async function bulk(decision, list) {
    setBusy(true); setMessage('');
    try {
      const byBatch = {};
      for (const item of list) (byBatch[item.batch] ??= []).push(item.name);
      let total = 0;
      for (const [batch, names] of Object.entries(byBatch)) total += (await post({action: 'review', channel, batch, names, decision})).changed;
      setSelected({});
      setMessage(`${decision === 'approved' ? 'Approved' : 'Rejected'} ${total} video(s).`);
      await onRefresh();
    } catch (error) { setMessage(error.message); } finally { setBusy(false); }
  }

  if (!items.length) return null;
  return <section className="review-panel" aria-labelledby="review-heading">
    <div className="review-head">
      <div>
        <div className="eyebrow">REVIEW · NOTHING UPLOADS UNTIL YOU APPROVE IT</div>
        <h2 id="review-heading">{items.length} video{items.length === 1 ? '' : 's'} waiting for you</h2>
        <p>Watch at least the opening of each. Your review is the human judgment YouTube looks for on channels like these;
          reject anything that feels samey, rushed or off.</p>
      </div>
      <div className="bulk">
        <button disabled={busy || !chosen.length} onClick={() => bulk('approved', chosen)}>Approve selected ({chosen.length})</button>
        <button disabled={busy || !chosen.length} onClick={() => bulk('rejected', chosen)}>Reject selected</button>
        <button disabled={busy} onClick={() => setSelected(Object.fromEntries(items.map(i => [i.batch + '/' + i.name, true])))}>Select all</button>
      </div>
    </div>
    {message && <p role="status" className="channel-message">{message}</p>}
    <div className="review-list">
      {items.map(item => <ReviewCard key={item.batch + '/' + item.name} channel={channel} item={item} busy={busy} setBusy={setBusy}
        setMessage={setMessage} onDone={onRefresh} selected={!!selected[item.batch + '/' + item.name]}
        onSelect={value => setSelected({...selected, [item.batch + '/' + item.name]: value})}/>)}
    </div>
  </section>;
}
