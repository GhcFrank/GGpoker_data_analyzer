// Optional real-browser regression: node tests/check_when_i_call_browser.mjs
// Uses Node 22+, Python and a local Chrome; no npm packages or external requests.
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const testDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.dirname(testDir);
const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'wic-browser-'));
const processes = [];
let socket;

function start(command, args, pattern, env = {}) {
  const child = spawn(command, args, { cwd: repo, env: { ...process.env, ...env } });
  processes.push(child);
  return new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(Error(`Startup timed out: ${command}\n${output}`)), 20000);
    function inspect(data) {
      output += data;
      const match = output.match(pattern);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    }
    child.stdout.on('data', inspect);
    child.stderr.on('data', inspect);
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('exit', code => { clearTimeout(timer); reject(Error(`${command} exited ${code}\n${output}`)); });
  });
}

try {
  const appUrl = await start(process.env.PYTHON_BIN || 'python3', ['-u', '-c', `
from http.server import ThreadingHTTPServer
import os
import app
import poker.service
from poker.models import HandDataset
from poker.service import AnalysisService
from tests.test_when_i_call import make_hand, call_line, action
from tests.test_when_i_raise import preflop_line

hands = [make_hand(call_line() + call_line('turn') + call_line('river'), hand_id='triple', cards={'Villain': ('As', 'Kh')}),
         make_hand(hand_id='unknown'), make_hand(hand_id='suited', cards={'Villain': ('As', 'Ks')}),
         make_hand(hand_id='nine', max_players=9, hero='BB', opponent='BTN'),
         make_hand([action('Hero', 'bet'), action('Villain', 'raise'), action('Hero', 'call')], hand_id='raise-call')]
# WIR-only aggression fixtures leave the existing WIC sample counts unchanged.
for hand_id, raisers, cards in (
    ('wir-srp', ['Hero'], {'Villain': ('Ah', 'Ad')}),
    ('wir-3bet', ['Villain', 'Hero'], {'Villain': ('As', 'Kh')}),
    ('wir-3bet-unknown', ['Villain', 'Hero'], {}),
    ('wir-6bet', ['Hero', 'Villain', 'Hero', 'Villain', 'Hero'], {'Villain': ('Qc', 'Qd')}),
):
    hands.append(make_hand(preflop_line(raisers) + [
        action('Hero', 'bet', 'flop', 33), action('Villain', 'call', 'flop', 33),
        action('Hero', 'bet', 'turn', 75), action('Villain', 'fold', 'turn'),
    ], hand_id=hand_id, cards=cards))
class ReviewService(AnalysisService):
    def reload(self):
        self._dataset = HandDataset(hands)
        return self._dataset
svc = ReviewService(os.environ['WIC_TEST_DATA_DIR'])
svc.reload()
poker.service._service = svc
server = ThreadingHTTPServer(('127.0.0.1', 0), app.LocalHandler)
print(f'WIC_URL=http://127.0.0.1:{server.server_port}', flush=True)
server.serve_forever()
`], /WIC_URL=(http:\/\/127\.0\.0\.1:\d+)/, {
    PYTHONPATH: [repo, path.join(repo, 'poker_analyzer')].join(path.delimiter),
    WIC_TEST_DATA_DIR: tempDir,
  });
  const browserUrl = await start(process.env.CHROME_BIN || 'google-chrome', [
    '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-background-networking', `--user-data-dir=${path.join(tempDir, 'chrome')}`,
    '--remote-debugging-port=0', 'about:blank',
  ], /DevTools listening on (ws:\/\/[^\s]+)/);
  const targets = await (await fetch(`http://127.0.0.1:${new URL(browserUrl).port}/json`)).json();
  socket = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let sequence = 0;
  const pending = new Map();
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data);
    if (!message.id) return;
    const { resolve, reject, timer } = pending.get(message.id);
    pending.delete(message.id);
    clearTimeout(timer);
    message.error ? reject(Error(JSON.stringify(message.error))) : resolve(message.result);
  };
  function send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++sequence;
      const timer = setTimeout(() => reject(Error(`Browser command timed out: ${method}`)), 30000);
      pending.set(id, { resolve, reject, timer });
      socket.send(JSON.stringify({ id, method, params }));
    });
  }
  await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  for (const scenario of ['when_i_call_browser_scenarios.js', 'when_i_raise_browser_scenarios.js']) {
    // A fresh document keeps each panel's regression scenarios independent.
    await send('Page.navigate', { url: 'about:blank' });
    await send('Page.navigate', { url: appUrl });
    for (let attempt = 0; attempt < 100; attempt++) {
      const ready = await send('Runtime.evaluate', { expression: '!!document.querySelector("#wicStreetGroup input")', returnByValue: true });
      if (ready.result.value) break;
      await new Promise(resolve => setTimeout(resolve, 30));
    }
    const expression = await fs.readFile(path.join(testDir, scenario), 'utf8');
    const outcome = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (outcome.exceptionDetails || !outcome.result?.value?.ok) throw Error(JSON.stringify(outcome, null, 2));
    console.log(`PASS: ${scenario}: ${outcome.result.value.passed.length} browser checks`);
    console.log(outcome.result.value.passed.join('\n'));
  }
} finally {
  if (socket) socket.close();
  await Promise.all(processes.map(async child => {
    if (child.exitCode !== null || child.signalCode !== null) return;
    const exited = once(child, 'exit');
    child.kill();
    await exited;
  }));
  await fs.rm(tempDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
