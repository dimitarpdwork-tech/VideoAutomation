"""Talk to the Chatterbox narrator, which runs in its own environment (.venv-voice).

Production starts one worker per batch, so the voice model loads once rather
than once per video. The worker's progress messages go straight to this
program's error stream (the dashboard log); answers come back on stdout.
"""
import json
import os
import subprocess

from channel_config import ROOT, venv_python

ENV = '.venv-voice'


class VoiceError(RuntimeError):
    def __init__(self, message, needs_review=False):
        super().__init__(message)
        self.needs_review = needs_review


def installed():
    return venv_python(ENV).exists()


class VoiceWorker:
    def __init__(self, model='standard'):
        self.model, self.process = model, None

    def _start(self):
        if not installed():
            raise VoiceError('Chatterbox is not installed yet. Run setup_voice.cmd (Windows) or ./setup_voice.sh, '
                             'or switch this channel back to the Kokoro voice in Settings.')
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'TQDM_DISABLE': '1'}
        self.process = subprocess.Popen(
            [str(venv_python(ENV)), '-u', str(ROOT / 'chatterbox_narrator.py'), '--serve', '--model', self.model],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8', env=env)

    def narrate(self, **args):
        if self.process is None or self.process.poll() is not None:
            self._start()
        args = {key: str(value) if hasattr(value, 'resolve') else value for key, value in args.items()}
        try:
            self.process.stdin.write(json.dumps({'cmd': 'narrate', 'args': args}) + '\n')
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self.process = None
            raise VoiceError(f'The Chatterbox narrator stopped unexpectedly ({exc}).') from exc
        for line in self.process.stdout:
            if line.startswith('@@RESULT '):
                reply = json.loads(line[len('@@RESULT '):])
                if not reply.get('ok'):
                    raise VoiceError(reply.get('error') or 'Narration failed.', reply.get('needs_review', False))
                return reply['metadata']
            print(line, end='', flush=True)
        code = self.process.wait()
        self.process = None
        raise VoiceError(f'The Chatterbox narrator stopped unexpectedly (exit code {code}); see the messages above.')

    def close(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.write(json.dumps({'cmd': 'quit'}) + '\n')
                self.process.stdin.flush()
                self.process.wait(timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
        self.process = None
