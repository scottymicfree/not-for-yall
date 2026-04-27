const promptInput = document.getElementById('promptInput');
const promptStatus = document.getElementById('promptStatus');
const promptChars = document.getElementById('promptChars');
let promptDirty = false;

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

async function getJson(url) {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function post(url, body = {}) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function setPromptStatus(text) {
  promptStatus.textContent = text;
}

promptInput.addEventListener('input', () => {
  promptDirty = true;
  setPromptStatus('Unsaved changes');
  promptChars.textContent = String(promptInput.value.length);
});

async function refresh() {
  const data = await getJson('/api/state');
  const { state, activePrompt, ledger, explanation } = data;

  document.getElementById('statusBadge').textContent = `Status: ${state.status}`;
  document.getElementById('modeBadge').textContent = `Mode: ${state.runtimeMode}`;

  if (!promptDirty && document.activeElement !== promptInput) {
    promptInput.value = activePrompt || '';
    promptChars.textContent = String(promptInput.value.length);
    setPromptStatus('Saved');
  }

  document.getElementById('loopBox').textContent = pretty(state.loop);
  document.getElementById('emmaBox').textContent = pretty(state.emma);
  document.getElementById('earthBox').textContent = pretty(state.earth);
  document.getElementById('bridgeBox').textContent = pretty(state.bridgeRegistry);
  document.getElementById('historyBox').textContent = pretty(state.history);
  document.getElementById('ledgerBox').textContent = pretty(ledger);
  document.getElementById('explainBox').textContent = explanation;
}

async function savePrompt() {
  await post('/api/prompt/save', { prompt: promptInput.value });
  promptDirty = false;
  setPromptStatus('Saved');
  await refresh();
}

async function loadTemplate() {
  const data = await post('/api/load-template');
  promptInput.value = data.template || '';
  promptDirty = true;
  setPromptStatus('Unsaved changes');
  promptChars.textContent = String(promptInput.value.length);
}

async function startLoop() {
  const totalLoops = Number(document.getElementById('totalLoops').value || 8);
  const checkpointSeconds = Number(document.getElementById('checkpointSeconds').value || 8);
  const autoRewrite = document.getElementById('autoRewrite').checked;
  await post('/api/loop/start', { totalLoops, checkpointSeconds, autoRewrite });
  await refresh();
}

async function stopLoop() {
  await post('/api/loop/stop');
  await refresh();
}

async function checkpoint() {
  await post('/api/checkpoint');
  await refresh();
}

document.getElementById('savePromptBtn').addEventListener('click', savePrompt);
document.getElementById('loadTemplateBtn').addEventListener('click', loadTemplate);
document.getElementById('startLoopBtn').addEventListener('click', startLoop);
document.getElementById('stopLoopBtn').addEventListener('click', stopLoop);
document.getElementById('checkpointBtn').addEventListener('click', checkpoint);

refresh().catch(console.error);
setInterval(() => {
  refresh().catch(console.error);
}, 1500);
