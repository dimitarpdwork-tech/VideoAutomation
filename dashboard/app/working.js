'use client';

export const JOBS = [['generation', 'Writing the story'], ['production', 'Making the video'], ['scheduling', 'Scheduling uploads'],
  ['upload', 'Uploading'], ['voices', 'Preparing the voice'], ['designs', 'Creating voices']];

export function lastLine(job) {
  const lines = (job?.log || []).join('').split(/\r?\n/).map(l => l.trim()).filter(Boolean);
  return [...lines].reverse().find(l => !/^(Traceback|File |Warning|UserWarning|warnings\.warn|\s*\^)/.test(l)) || 'Starting…';
}

// What is running right now, and its latest step, so nothing happens silently.
export function WorkingBar({data}) {
  const running = JOBS.filter(([key]) => data?.[key]?.running);
  if (!running.length) return null;
  return <div className="working-bar" role="status">{running.map(([key, label]) =>
    <div key={key}><span className="pulse"/><strong>{label}{data[key].channel ? ` · ${data.channels?.find(c => c.id === data[key].channel)?.name || data[key].channel}` : ''}</strong>
      <span className="step">{lastLine(data[key]).slice(0, 160)}</span></div>)}</div>;
}
