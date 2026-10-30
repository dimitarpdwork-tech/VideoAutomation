// Rebuild the dashboard when its code is newer than the last build (for example after `git pull`).
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const newest = target => {
  const stat = fs.statSync(target, {throwIfNoEntry: false});
  if (!stat) return 0;
  if (!stat.isDirectory()) return stat.mtimeMs;
  return Math.max(0, ...fs.readdirSync(target).map(name => newest(path.join(target, name))));
};
const built = fs.statSync(path.join(here, '.next', 'BUILD_ID'), {throwIfNoEntry: false})?.mtimeMs ?? 0;
const source = Math.max(...['app', 'lib', 'proxy.js', 'next.config.mjs', 'package.json'].map(p => newest(path.join(here, p))));
if (source > built) {
  console.log('Dashboard code changed since the last build; rebuilding (about a minute)...');
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const result = spawnSync(npm, ['run', 'build'], {cwd: here, stdio: 'inherit', shell: process.platform === 'win32'});
  if (result.status !== 0) process.exit(result.status ?? 1);
}
