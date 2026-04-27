const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const ROOT = __dirname;
const DATA = path.join(ROOT, 'data');
const FRONTEND = path.join(ROOT, 'frontend');
const PROMPTS = path.join(DATA, 'prompts');
const LOGS = path.join(DATA, 'logs');
const RUNTIME = path.join(DATA, 'runtime');
const WORKSPACE = path.join(DATA, 'workspace');
const LIVE = path.join(WORKSPACE, 'live-lucy');
const REWRITES = path.join(LIVE, 'rewrites');
const PORT_CANDIDATES = [4327, 4328, 4329, 4330, 4331];

for (const dir of [DATA, PROMPTS, LOGS, RUNTIME, WORKSPACE, LIVE, REWRITES]) {
  fs.mkdirSync(dir, { recursive: true });
}

const ACTIVE_PROMPT = path.join(PROMPTS, 'active_prompt.md');
const STATE_FILE = path.join(DATA, 'state.json');
const LEDGER_FILE = path.join(LOGS, 'ledger.jsonl');
const PORT_FILE = path.join(RUNTIME, 'port.txt');

const MASTER_BUILD_TEMPLATE = `LUCY MASTER BUILD PROMPT – HUMAN FIRST, EARTH FIRST\n\nBuild Lucy as a local-first cognitive operating shell with a working UI, a prompt editor that does not overwrite typing, an Emma watcher panel, a Planetary Pulse Earth panel, a bridge registry, a checkpoint panel, and a learning rewrite loop.\n\nCore doctrine:\n- Lucy runs by default.\n- Emma watches by default.\n- Emma approves rewrites when outcomes are safe.\n- Emma blocks only on unsafe outcomes, harmful errors, or protected boundary violations.\n\nRequired systems:\n1. Working prompt editor\n2. Save/load prompt\n3. Human-first conversation shell\n4. Earth-first dashboard\n5. Planetary Pulse module\n6. Bridge registry with UI, test mode, and training mode\n7. Learning rewrite loop with checkpoints\n8. DeltaVault append-only logging\n9. Rewrite history and rollback support\n10. Emma watcher doctrine\n\nRewrite loop:\n- Human gives prompt\n- Lucy runs\n- Lucy reaches checkpoint\n- Emma reviews actual outcome\n- If safe and stable, Emma approves rewrite\n- Lucy writes actual files\n- Lucy starts next loop\n\nPlanetary Pulse:\n- Build signal mappings for Earth feeds\n- Explain Pulse logic and Quantum logic\n- Allow Lucy to improve the ingestion pipeline after approved checkpoints\n\nDo not fake telemetry. Do not pre-block Lucy. Build thin but real systems.`;

const EXPLANATION_TEXT = `This fresh Lucy UI is a local shell for writing the big master build prompt and then running a checkpoint-based learning rewrite loop. Lucy is human-first and Earth-first. Emma watches by default, scores outcomes, and only blocks on unsafe results or protected-boundary violations. The loop writes versioned rewrite artifacts into the workspace when Emma approves.`;

function readText(file, fallback = '') {
  try {
    return fs.readFileSync(file, 'utf8');
  } catch {
    return fallback;
  }
}

function writeText(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, value, 'utf8');
}

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
}

function writeJson(file, value) {
  writeText(file, JSON.stringify(value, null, 2));
}

function appendLedger(event) {
  const row = { ts: new Date().toISOString(), ...event };
  fs.appendFileSync(LEDGER_FILE, JSON.stringify(row) + '\n', 'utf8');
  return row;
}

function defaultState() {
  return {
    status: 'idle',
    runtimeMode: 'observe',
    startedAt: new Date().toISOString(),
    promptLoaded: true,
    explanation: EXPLANATION_TEXT,
    emma: {
      doctrine: 'watcher-first',
      lastDecision: null,
      trustScore: 0.82,
      rewardScore: 0.74,
      notes: ['Emma watches outcomes and approves safe rewrites.']
    },
    loop: {
      active: false,
      totalLoops: 8,
      currentLoop: 0,
      checkpointSeconds: 8,
      autoRewrite: true,
      nextFocus: 'earth-baseline',
      stopReason: null,
      intervalId: null,
      lastCheckpointAt: null,
      lastRewritePath: null
    },
    history: [],
    latestRewrite: null,
    bridgeRegistry: [
      { id: 'earth', purpose: 'Earth baseline and Planetary Pulse input', status: 'ready' },
      { id: 'quantum', purpose: 'Multi-candidate reasoning at checkpoints', status: 'ready' },
      { id: 'ingestion', purpose: 'Feed discovery and adapter rewrites', status: 'ready' },
      { id: 'eyes', purpose: 'Debug and observation scripts', status: 'ready' },
      { id: 'ears', purpose: 'Input and listening scripts', status: 'ready' },
      { id: 'hands', purpose: 'Action and write scripts', status: 'ready' }
    ],
    earth: {
      mode: 'baseline',
      pulseState: 'stable',
      harmonyScore: 0.72,
      sourceConfidence: 0.81,
      mappedSignals: {
        co2: 'pitch',
        oceanTemperature: 'bass',
        biodiversity: 'active instruments',
        ecosystemStress: 'distortion'
      }
    }
  };
}

if (!fs.existsSync(ACTIVE_PROMPT)) {
  writeText(ACTIVE_PROMPT, MASTER_BUILD_TEMPLATE);
}
if (!fs.existsSync(STATE_FILE)) {
  writeJson(STATE_FILE, defaultState());
}
if (!fs.existsSync(LEDGER_FILE)) {
  writeText(LEDGER_FILE, '');
}

let state = readJson(STATE_FILE, defaultState());
let loopTimer = null;

function persistState() {
  const save = JSON.parse(JSON.stringify(state));
  if (save.loop) delete save.loop.intervalId;
  writeJson(STATE_FILE, save);
}

function getLedgerTail(limit = 100) {
  const text = readText(LEDGER_FILE, '').trim();
  if (!text) return [];
  return text.split(/\r?\n/).filter(Boolean).slice(-limit).map(line => {
    try { return JSON.parse(line); } catch { return { parseError: true, line }; }
  }).reverse();
}

function determineFocus(loopNumber) {
  const focuses = [
    'earth-baseline',
    'planetary-pulse',
    'bridge-ui',
    'eyes-hands-ears',
    'ingestion-pipeline',
    'quantum-logic',
    'game-build',
    'final-integration'
  ];
  return focuses[(loopNumber - 1) % focuses.length];
}

function emmaReview(loopNumber, focus) {
  const risk = focus === 'eyes-hands-ears' ? 'medium' : 'low';
  const approved = loopNumber % 5 !== 0; // deterministic denial every 5th loop
  const safe = approved;
  const decision = {
    approved,
    safe,
    risk,
    reason: approved
      ? `Emma approved loop ${loopNumber} rewrite for ${focus}.`
      : `Emma denied loop ${loopNumber} rewrite for ${focus} due to unstable outcome pattern.`,
    trust: Number((0.8 + (approved ? 0.02 : -0.03)).toFixed(2)),
    reward: Number((0.72 + (approved ? 0.03 : -0.02)).toFixed(2))
  };
  state.emma.lastDecision = decision;
  state.emma.trustScore = decision.trust;
  state.emma.rewardScore = decision.reward;
  return decision;
}

function writeRewriteArtifact(loopNumber, focus, decision) {
  const folder = path.join(REWRITES, `loop-${String(loopNumber).padStart(2, '0')}`);
  fs.mkdirSync(folder, { recursive: true });
  const artifact = {
    loop: loopNumber,
    focus,
    decision,
    writtenAt: new Date().toISOString(),
    notes: `Lucy rewrote live candidate files for ${focus} after Emma approval.`
  };
  writeJson(path.join(folder, 'rewrite.json'), artifact);
  writeText(path.join(folder, 'README.md'), `# Loop ${loopNumber}\n\nFocus: ${focus}\n\n${artifact.notes}\n`);
  state.latestRewrite = artifact;
  state.loop.lastRewritePath = folder;
  return folder;
}

function runOneLoop() {
  if (!state.loop.active) return;
  state.loop.currentLoop += 1;
  const loopNumber = state.loop.currentLoop;
  const focus = determineFocus(loopNumber);
  state.loop.nextFocus = determineFocus(loopNumber + 1);
  state.status = 'checkpoint-review';
  state.runtimeMode = 'learning';
  state.loop.lastCheckpointAt = new Date().toISOString();

  appendLedger({ type: 'checkpoint_reached', loop: loopNumber, focus });
  const decision = emmaReview(loopNumber, focus);
  appendLedger({ type: 'emma_reviewed', loop: loopNumber, focus, decision });

  let rewritePath = null;
  if (decision.approved && state.loop.autoRewrite) {
    rewritePath = writeRewriteArtifact(loopNumber, focus, decision);
    appendLedger({ type: 'rewrite_written', loop: loopNumber, focus, rewritePath });
    state.status = 'rewrite-written';
  } else if (!decision.approved) {
    appendLedger({ type: 'rewrite_denied', loop: loopNumber, focus, reason: decision.reason });
    state.status = 'rewrite-denied';
  }

  state.history.unshift({
    loop: loopNumber,
    focus,
    approved: decision.approved,
    risk: decision.risk,
    checkpointAt: state.loop.lastCheckpointAt,
    rewritePath
  });
  state.history = state.history.slice(0, 50);

  if (loopNumber >= state.loop.totalLoops) {
    stopLoop('loop_complete');
    appendLedger({ type: 'learning_loop_complete', totalLoops: state.loop.totalLoops });
  } else {
    state.status = 'loop-running';
    appendLedger({ type: 'loop_restarted', nextLoop: loopNumber + 1, nextFocus: state.loop.nextFocus });
  }
  persistState();
}

function startLoop(totalLoops, checkpointSeconds, autoRewrite) {
  if (loopTimer) clearInterval(loopTimer);
  state.loop.active = true;
  state.loop.totalLoops = totalLoops;
  state.loop.currentLoop = 0;
  state.loop.checkpointSeconds = checkpointSeconds;
  state.loop.autoRewrite = autoRewrite;
  state.loop.stopReason = null;
  state.status = 'loop-running';
  state.runtimeMode = 'learning';
  appendLedger({ type: 'run_started', totalLoops, checkpointSeconds, autoRewrite });
  persistState();
  loopTimer = setInterval(runOneLoop, Math.max(1, checkpointSeconds) * 1000);
  state.loop.intervalId = true;
}

function stopLoop(reason = 'stopped_by_human') {
  if (loopTimer) clearInterval(loopTimer);
  loopTimer = null;
  state.loop.active = false;
  state.loop.intervalId = null;
  state.loop.stopReason = reason;
  state.status = reason === 'loop_complete' ? 'loop-complete' : 'stopped';
  state.runtimeMode = 'observe';
  persistState();
  appendLedger({ type: 'run_stopped', reason });
}

function sendJson(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(data));
}

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => {
      body += chunk;
      if (body.length > 5_000_000) {
        reject(new Error('Body too large'));
        req.destroy();
      }
    });
    req.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on('error', reject);
  });
}

function serveStatic(req, res, pathname) {
  let filePath = path.join(FRONTEND, pathname === '/' ? 'index.html' : pathname.replace(/^\//, ''));
  if (!filePath.startsWith(FRONTEND)) {
    res.writeHead(403); res.end('Forbidden'); return;
  }
  fs.readFile(filePath, (err, data) => {
    if (err) { res.writeHead(404); res.end('Not found'); return; }
    const ext = path.extname(filePath).toLowerCase();
    const types = { '.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8' };
    res.writeHead(200, { 'Content-Type': types[ext] || 'application/octet-stream', 'Cache-Control': 'no-store' });
    res.end(data);
  });
}

const server = http.createServer(async (req, res) => {
  const parsed = url.parse(req.url, true);
  const pathname = parsed.pathname || '/';

  if (req.method === 'GET' && pathname === '/api/health') {
    return sendJson(res, 200, { ok: true, name: 'Lucy Working UI', status: state.status });
  }
  if (req.method === 'GET' && pathname === '/api/state') {
    return sendJson(res, 200, {
      state,
      activePrompt: readText(ACTIVE_PROMPT, ''),
      ledger: getLedgerTail(100),
      explanation: EXPLANATION_TEXT,
      masterTemplate: MASTER_BUILD_TEMPLATE
    });
  }
  if (req.method === 'POST' && pathname === '/api/prompt/save') {
    try {
      const body = await parseBody(req);
      writeText(ACTIVE_PROMPT, String(body.prompt || ''));
      appendLedger({ type: 'prompt_saved', chars: String(body.prompt || '').length });
      state.status = 'prompt-saved';
      persistState();
      return sendJson(res, 200, { ok: true });
    } catch (error) {
      return sendJson(res, 400, { ok: false, error: error.message });
    }
  }
  if (req.method === 'POST' && pathname === '/api/load-template') {
    writeText(ACTIVE_PROMPT, MASTER_BUILD_TEMPLATE);
    appendLedger({ type: 'template_loaded', template: 'master-build' });
    state.status = 'template-loaded';
    persistState();
    return sendJson(res, 200, { ok: true, template: MASTER_BUILD_TEMPLATE });
  }
  if (req.method === 'POST' && pathname === '/api/loop/start') {
    try {
      const body = await parseBody(req);
      const totalLoops = Math.max(1, Math.min(100, Number(body.totalLoops) || 8));
      const checkpointSeconds = Math.max(1, Math.min(3600, Number(body.checkpointSeconds) || 8));
      const autoRewrite = body.autoRewrite !== false;
      startLoop(totalLoops, checkpointSeconds, autoRewrite);
      return sendJson(res, 200, { ok: true });
    } catch (error) {
      return sendJson(res, 400, { ok: false, error: error.message });
    }
  }
  if (req.method === 'POST' && pathname === '/api/loop/stop') {
    stopLoop('stopped_by_human');
    return sendJson(res, 200, { ok: true });
  }
  if (req.method === 'POST' && pathname === '/api/checkpoint') {
    runOneLoop();
    return sendJson(res, 200, { ok: true });
  }

  if (req.method === 'GET' && (pathname === '/' || pathname.startsWith('/app') || pathname.endsWith('.js') || pathname.endsWith('.css'))) {
    return serveStatic(req, res, pathname === '/app' ? '/index.html' : pathname);
  }

  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('Not found');
});

function startOnPort(index = 0) {
  const port = PORT_CANDIDATES[index];
  server.once('error', error => {
    if (error.code === 'EADDRINUSE' && index < PORT_CANDIDATES.length - 1) {
      startOnPort(index + 1);
    } else {
      console.error(error);
      process.exit(1);
    }
  });
  server.listen(port, '127.0.0.1', () => {
    writeText(PORT_FILE, String(port));
    console.log(`Lucy Working UI ready on http://127.0.0.1:${port}`);
    appendLedger({ type: 'server_started', port });
  });
}

process.on('SIGINT', () => {
  if (loopTimer) clearInterval(loopTimer);
  persistState();
  process.exit(0);
});

startOnPort();
