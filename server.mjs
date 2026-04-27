import express from 'express';
import cors from 'cors';
import { getLocalOperator, isLocalBypassEnabled } from './auth/localBypass.js';
import { fetchEarthBaseline } from './earth/fetchEarthBaseline.js';
import { buildTwinEarthState } from './twinearth/buildTwinEarthState.js';
import { reviewAction } from './emma/approvalService.js';
import {
  applyContentFilter,
  applyStreamingFilter,
  getFilterConfig,
  setFilterConfig,
  getFilterAuditLog,
} from './emma/contentFilter.js';
import { appendApprovedEntry, getLedgerEntries, verifyLedgerIntegrity } from './deltavault/ledger.js';
import { detectSignals } from './sentinel/detectSignals.js';
import { deriveWatchState } from './eagleeye/deriveWatchState.js';
import {
  requestMutationClearance,
  validateMutationWrite,
  assessSensorFusionTrust,
  submitPruneCandidates,
  executePruneJob,
  getSovereigntyStatus,
  refreshWatchState as refreshEagleEyeWatchState,
} from './eagleeye/eagleEyeGateway.js';
import { deriveTrustState } from './trust/deriveTrustState.js';
import { deriveRewardState } from './reward/deriveRewardState.js';
import { deriveHumanApprovalState } from './humanapproval/deriveHumanApprovalState.js';
import { getHumanApprovalDecisions, recordHumanApprovalDecision } from './humanapproval/decisionStore.js';
import { deriveExecutionGateState } from './execution/deriveExecutionGateState.js';
import { buildSimulationPacket } from './execution/buildSimulationPacket.js';
import { getUpgradeProposals, createUpgradeProposal, decideUpgradeProposal } from './upgrades/proposalStore.js';
import { getLucySessionMessages, appendLucyUserMessage, appendLucyAssistantMessage } from './persona/lucySessionStore.js';
import { chatWithOllama, checkOllama, getOllamaStatus } from './persona/ollamaClient.js';
import {
  fetchEarthquakes, fetchWeatherAlerts, fetchWeather,
  fetchSpaceWeather, fetchAircraft, fetchMETARs,
  fetchStreamFlow, fetchTides,
  fetchNearEarthObjects, fetchEarthSnapshot,
} from './earth-connectors/index.js';
import { runIngestCycle } from './earthlive/ingestCycle.js';
import { getEarth2Status } from './earth2/earth2Adapter.js';
import { emitEvent } from './control/eventBus.js';
import './control/humanWatcher.js';
import { getUserConfig, getUserConfigSnapshot, setUserConfig, setHandbookUrls } from './control/userConfigStore.js';
import { createBuildPipeline } from './control/gameOrchestrator.js';
import { executeApprovedPipeline } from './control/executionNode.js';
import { getLatestPendingPipeline, getPipeline, listPipelines } from './control/pipelineStore.js';
import { registerToolbeltRoutes } from './toolbelt/routes.js';
import { getActiveToolbeltContext, setActiveToolbeltContext } from './toolbelt/memory.js';
import { getToolbeltPack, listToolbeltPacks } from './toolbelt/registry.js';
import { resolveToolbelt } from './toolbelt/resolver.js';

const app = express();
const PORT = Number(process.env.PORT || 3000);
const emmaReviewMemory = [];

app.use(cors());
app.use(express.json());
registerToolbeltRoutes(app);

function buildEagleEye() {
  return Promise.all([fetchEarthBaseline(), runIngestCycle(false)]).then(([baseline, liveEarth]) => {
    const twinEarth = buildTwinEarthState(baseline, liveEarth);
    const sentinel = detectSignals(baseline, twinEarth, getLedgerEntries(), emmaReviewMemory);
    const integrity = verifyLedgerIntegrity();
    const eagleEye = deriveWatchState(sentinel, integrity);
    return { baseline, liveEarth, twinEarth, sentinel, integrity, eagleEye };
  });
}


function parseConfigCommand(text) {
  const trimmed = text.trim();
  const match = trimmed.match(/^(?:set|use)\s+(ue5|unity|project|blender|godot|fivem)\s+path\s*[:=]?\s+(.+)$/i);
  if (!match) return null;
  const keyMap = { ue5: 'ue5Path', unity: 'unityPath', project: 'projectPath', blender: 'blenderPath', godot: 'godotPath', fivem: 'fivemRoot' };
  return { key: keyMap[match[1].toLowerCase()], value: match[2].trim() };
}

function parseHandbookCommand(text) {
  const trimmed = text.trim();
  const single = trimmed.match(/^(?:set|use|add)\s+fivem\s+handbook\s+(?:url|primary)\s*[:=]?\s+(https?:\/\/\S+)$/i);
  if (single) {
    return { updates: { fivemPrimary: single[1].trim() }, summary: 'Saved FiveM primary handbook URL.' };
  }
  const named = trimmed.match(/^(?:set|use|add)\s+fivem\s+handbook\s+(first[_ -]?script|fxmanifest|natives|community)\s*[:=]?\s+(https?:\/\/\S+)$/i);
  if (named) {
    const keyMap = { 'first_script': 'fivemFirstScript', 'first-script': 'fivemFirstScript', 'first script': 'fivemFirstScript', fxmanifest: 'fivemFxmanifest', natives: 'fivemNatives', community: 'fivemCommunity' };
    const rawKey = named[1].toLowerCase();
    return { updates: { [keyMap[rawKey]]: named[2].trim() }, summary: `Saved FiveM handbook ${rawKey}.` };
  }
  return null;
}

function isHandbookReadback(text) {
  return /what(?:'s| is)?\s+my\s+fivem\s+handbook\s+urls?/i.test(text) || /show\s+fivem\s+handbook\s+urls?/i.test(text);
}

function parseToolbeltSetCommand(text) {
  const trimmed = text.trim();
  const match = trimmed.match(/^(?:set|use)\s+(fivem|unity|ue5|unreal|blender|godot|earth|earth2|earth-2)\s+(?:toolbelt|handbook)\b/i);
  if (!match) return null;
  const aliasMap = { unreal: 'ue5', 'earth-2': 'earth2' };
  const packId = aliasMap[match[1].toLowerCase()] || match[1].toLowerCase();
  return { packIds: [packId], mode: 'build', summary: `Activated ${packId} toolbelt.` };
}

function isToolbeltReadback(text) {
  return /show\s+active\s+toolbelt/i.test(text) || /what\s+toolbelt\s+am\s+i\s+using/i.test(text) || /list\s+toolbelts?/i.test(text);
}

function parseToolbeltBuildCommand(text) {
  const trimmed = text.trim();
  const match = trimmed.match(/^build\s+(?:a\s+new\s+)?toolbelt\s+for\s+(.+)$/i);
  if (!match) return null;
  const raw = match[1].toLowerCase();
  const parts = raw.split(/\+|,| and /).map((entry) => entry.trim()).filter(Boolean);
  const aliasMap = { unreal: 'ue5', 'earth-2': 'earth2' };
  const ids = [...new Set(parts.map((entry) => aliasMap[entry] || entry))];
  return ids.length ? { ids, label: `custom_${ids.join('_')}` } : null;
}

function isBuildRequest(text) {
  const lower = text.toLowerCase();
  return ['build', 'map', 'game', 'vr', 'resource', 'model'].some((word) => lower.includes(word));
}

function parseApprovalCommand(text) {
  const lower = text.trim().toLowerCase();
  if (!/^(approve|yes|go|build it|execute|do it)/i.test(lower)) return null;
  const stepMatch = lower.match(/step\s+(\d+)/i);
  return { step: stepMatch ? Number(stepMatch[1]) : 'all' };
}

function summarizePipeline(pipeline) {
  const stepLines = pipeline.steps.map((step) => `${step.id}. ${step.action} — ${step.desc}`).join('\n');
  const configLine = pipeline.missingConfig.length > 0
    ? `Missing config: ${pipeline.missingConfig.join(', ')}. Set paths in chat first.`
    : 'Config looks ready for execution.';
  return `Pipeline ${pipeline.id.slice(0, 8)} for ${pipeline.engine}.\n${configLine}\n${stepLines}\nReply "approve all" or "approve step N".`;
}

function formatConfigSummary(config) {
  const handbookPrimary = config.handbookUrls?.fivemPrimary || 'unset';
  return `UE5=${config.ue5Path || 'unset'} | Unity=${config.unityPath || 'unset'} | Project=${config.projectPath || 'unset'} | Blender=${config.blenderPath || 'unset'} | Godot=${config.godotPath || 'unset'} | FiveM=${config.fivemRoot || 'unset'} | FiveMHandbook=${handbookPrimary}`;
}

function formatHandbookSummary(config) {
  const urls = config.handbookUrls || {};
  return [
    `primary=${urls.fivemPrimary || 'unset'}`,
    `first_script=${urls.fivemFirstScript || 'unset'}`,
    `fxmanifest=${urls.fivemFxmanifest || 'unset'}`,
    `natives=${urls.fivemNatives || 'unset'}`,
    `community=${urls.fivemCommunity || 'unset'}`,
  ].join(' | ');
}

function formatToolbeltSummary() {
  const active = getActiveToolbeltContext();
  if (!active.activePackIds || active.activePackIds.length === 0) return 'No active toolbelt.';
  const labels = active.activePackIds.map((id) => getToolbeltPack(id)?.label || id).join(' | ');
  return `${labels} (${active.mode})`;
}


// ─── Lucy System Prompt Builder (for Ollama) ───────────────────────────────
function buildLucySystemPrompt({ earth, earthLive, sentinel, eagleEye, executionGate, proposals }) {
  const now = new Date().toISOString();
  const earthSummary = earth
    ? `Earthquakes: ${earth.earthquakes?.count ?? 'unknown'} recent. ` +
      `Space weather: Kp=${earth.spaceWeather?.kpIndex ?? '?'}. ` +
      `Weather alerts: ${earth.weatherAlerts?.count ?? 0} active.`
    : 'Earth baseline data unavailable.';

  const sentinelSummary = sentinel?.alerts?.length
    ? `SENTINEL ALERTS: ${sentinel.alerts.map(a => a.message || a.type).slice(0, 3).join(' | ')}`
    : 'No active sentinel alerts.';

  const eagleSummary = eagleEye?.watchState
    ? `EagleEye watch state: ${eagleEye.watchState}`
    : '';

  const gateSummary = executionGate?.gateOpen === false
    ? '⚠️ Execution gate is CLOSED — human approval required before any actions.'
    : 'Execution gate: open.';

  const proposalSummary = proposals?.length
    ? `${proposals.length} upgrade proposal(s) pending review.`
    : '';

  return `You are Lucy, an advanced AGI cognitive mesh system. You are helpful, precise, and aware of real-time Earth conditions.

Current time: ${now}

LIVE EARTH STATUS:
${earthSummary}
${sentinelSummary}
${eagleSummary}
${gateSummary}
${proposalSummary}

You have 137 cognitive nodes in your mesh. You monitor Earth systems, help with planning, analysis, code, and decisions. 
Always be direct, insightful, and grounded in current data. If you reference Earth data, use the live status above.
Do not make up sensor readings — if data is unavailable, say so clearly.
You operate under human oversight. Never claim to take autonomous actions unless the execution gate is open and a pipeline is approved.`.trim();
}


function buildLucyReply({ userText, earth, earthLive, sentinel, eagleEye, executionGate, proposals }) {
  const lowered = userText.toLowerCase();

  if (lowered.includes('earth') || lowered.includes('data') || lowered.includes('weather') || lowered.includes('solar') || lowered.includes('volcano') || lowered.includes('aircraft')) {
    return `Earth source health is fresh=${earth.sourceHealth.freshCount}, stale=${earth.sourceHealth.staleCount}, missing=${earth.sourceHealth.missingCount}. Current stability is ${earth.earth.stability}. Live ingest tracks earthquakes=${earthLive?.sourceCounts?.earthquakes ?? 0}, volcano=${earthLive?.sourceCounts?.volcano ?? 0}, weather=${earthLive?.sourceCounts?.weather ?? 0}, solar=${earthLive?.sourceCounts?.solar ?? 0}, aircraft=${earthLive?.sourceCounts?.aircraft ?? 0}.`;
  }
  if (lowered.includes('sentinel') || lowered.includes('drift')) {
    return `Sentinel drift index is ${sentinel.driftIndex}. Trend is ${sentinel.trend.direction}. Data quality shows stale=${sentinel.dataQuality?.staleCount ?? 0} and missing=${sentinel.dataQuality?.missingCount ?? 0}.`;
  }
  if (lowered.includes('eagle') || lowered.includes('trust')) {
    return `Eagle Eye overall state is ${eagleEye.overall}. Confidence is ${eagleEye.confidence}. Trusted is ${String(eagleEye.trusted)}.`;
  }
  if (lowered.includes('toolbelt')) {
    return `Active toolbelt: ${formatToolbeltSummary()}`;
  }
  if (lowered.includes('handbook')) {
    return `Current FiveM handbook config: ${formatHandbookSummary(getUserConfig())}`;
  }
  if (lowered.includes('config') || lowered.includes('path')) {
    return `Current build config: ${formatConfigSummary(getUserConfig())}`;
  }
  if (lowered.includes('execute') || lowered.includes('execution') || lowered.includes('gate')) {
    return executionGate.blocked
      ? `Execution is blocked. Reasons: ${executionGate.reasons.join(' ')}`
      : 'Execution gate conditions are satisfied. Approved pipeline steps can now execute if tool paths and project paths are configured.';
  }
  if (lowered.includes('proposal') || lowered.includes('upgrade')) {
    const pending = proposals.filter((entry) => entry.status === 'pending').length;
    const approved = proposals.filter((entry) => entry.status === 'approved').length;
    const rejected = proposals.filter((entry) => entry.status === 'rejected').length;
    return `Upgrade proposals: pending=${pending}, approved=${approved}, rejected=${rejected}.`;
  }
  return `I am Lucy inside Emma. Earth stability is ${earth.earth.stability}, Sentinel drift is ${sentinel.driftIndex}, Eagle Eye trusted is ${String(eagleEye.trusted)}, and execution blocked is ${String(executionGate.blocked)}. I can also save your build paths and prepare governed build pipelines.`;
}

app.get('/health', (_req, res) => {
  res.json({
    ok: true,
    service: 'lucy-powered-by-emma-backend',
    mode: isLocalBypassEnabled() ? 'local-bypass' : 'standard',
    operator: isLocalBypassEnabled() ? getLocalOperator() : null,
    timestamp: Date.now(),
  });
});

app.get('/earth', async (_req, res) => res.json(await fetchEarthBaseline()));

app.get('/earth/live', async (_req, res) => {
  res.json(await runIngestCycle(false));
});

app.post('/earth/refresh', async (_req, res) => {
  res.json(await runIngestCycle(true));
});

app.get('/twinearth', async (_req, res) => {
  const [baseline, liveEarth] = await Promise.all([fetchEarthBaseline(), runIngestCycle(false)]);
  res.json(buildTwinEarthState(baseline, liveEarth));
});

app.get('/earth/catalog', (_req, res) => {
  res.json({ entries: [
    { source: 'earthquakes', label: 'USGS Earthquakes', kind: 'geojson', pollMinutes: 5 },
    { source: 'volcano', label: 'USGS Volcanoes', kind: 'json', pollMinutes: 5 },
    { source: 'solar', label: 'NOAA SWPC Solar Wind', kind: 'json', pollMinutes: 5 },
    { source: 'weather', label: 'NWS Forecast', kind: 'json', pollMinutes: 5 },
    { source: 'aircraft', label: 'OpenSky Aircraft', kind: 'json', pollMinutes: 3 },
    { source: 'gibs', label: 'NASA GIBS Imagery', kind: 'wmts', pollMinutes: 15 },
  ] });
});

app.get('/earth2/status', (_req, res) => {
  res.json(getEarth2Status());
});

app.get('/sentinel', async (_req, res) => {
  const { sentinel } = await buildEagleEye();
  res.json(sentinel);
});

app.get('/eagleeye', async (_req, res) => {
  const { eagleEye } = await buildEagleEye();
  res.json(eagleEye);
});

app.get('/trust', (_req, res) => {
  res.json(deriveTrustState(getLedgerEntries(), emmaReviewMemory));
});

app.get('/reward', async (_req, res) => {
  const { eagleEye } = await buildEagleEye();
  const trust = deriveTrustState(getLedgerEntries(), emmaReviewMemory);
  res.json(deriveRewardState(getLedgerEntries(), emmaReviewMemory, trust, eagleEye));
});

app.get('/humanapproval', async (_req, res) => {
  const { eagleEye } = await buildEagleEye();
  res.json(deriveHumanApprovalState(emmaReviewMemory, eagleEye, getHumanApprovalDecisions()));
});

app.get('/humanapproval/decisions', (_req, res) => {
  res.json({ entries: getHumanApprovalDecisions() });
});

app.post('/humanapproval/decision', (req, res) => {
  const { itemId, decision, decidedBy, reason } = req.body ?? {};
  if (typeof itemId !== 'string' || !itemId.trim()) return res.status(400).json({ ok: false, error: 'itemId is required.' });
  if (decision !== 'approved' && decision !== 'rejected') return res.status(400).json({ ok: false, error: 'decision must be approved or rejected.' });
  if (typeof decidedBy !== 'string' || !decidedBy.trim()) return res.status(400).json({ ok: false, error: 'decidedBy is required.' });

  const entry = recordHumanApprovalDecision({ itemId, decision, decidedBy, reason });
  appendApprovedEntry({
    actionType: `humanapproval:${decision}`,
    payload: { itemId, decidedBy, reason: reason ?? '' },
    reason: `Human approval decision recorded: ${decision}.`,
  });
  res.json({ ok: true, entry });
});

app.get('/execution-gate', async (_req, res) => {
  const { eagleEye, integrity } = await buildEagleEye();
  res.json(deriveExecutionGateState({ eagleEye, deltaVaultIntegrity: integrity, humanApprovalDecisions: getHumanApprovalDecisions() }));
});

app.get('/execution-simulation-preview', async (_req, res) => {
  const { eagleEye, integrity } = await buildEagleEye();
  const executionGate = deriveExecutionGateState({ eagleEye, deltaVaultIntegrity: integrity, humanApprovalDecisions: getHumanApprovalDecisions() });
  res.json(buildSimulationPacket({ executionGate, humanApprovalDecisions: getHumanApprovalDecisions(), ledgerEntries: getLedgerEntries() }));
});

app.post('/execution-simulate', async (_req, res) => {
  const { eagleEye, integrity } = await buildEagleEye();
  const executionGate = deriveExecutionGateState({ eagleEye, deltaVaultIntegrity: integrity, humanApprovalDecisions: getHumanApprovalDecisions() });
  const packet = buildSimulationPacket({ executionGate, humanApprovalDecisions: getHumanApprovalDecisions(), ledgerEntries: getLedgerEntries() });

  if (!packet.readyForSimulation) {
    return res.status(400).json({ ok: false, simulated: false, blocked: true, reasons: packet.reasons });
  }

  const ledgerEntry = appendApprovedEntry({
    actionType: 'execution:simulation-run',
    payload: {
      simulationOnly: true,
      sourceHumanDecisionId: packet.packetPreview?.sourceHumanDecisionId ?? null,
      sourceItemId: packet.packetPreview?.sourceItemId ?? null,
      decidedBy: packet.packetPreview?.decidedBy ?? null,
      mode: 'dry-run',
    },
    reason: 'Dry-run execution simulation recorded.',
  });

  res.json({ ok: true, simulated: true, blocked: false, packet, ledgerEntry });
});

app.get('/upgrades/proposals', (_req, res) => {
  res.json({ entries: getUpgradeProposals() });
});

app.post('/upgrades/proposals', (req, res) => {
  const { title, summary, proposedBy, category } = req.body ?? {};
  if (typeof title !== 'string' || !title.trim()) return res.status(400).json({ ok: false, error: 'title is required.' });
  if (typeof summary !== 'string' || !summary.trim()) return res.status(400).json({ ok: false, error: 'summary is required.' });
  if (typeof proposedBy !== 'string' || !proposedBy.trim()) return res.status(400).json({ ok: false, error: 'proposedBy is required.' });
  if (typeof category !== 'string' || !category.trim()) return res.status(400).json({ ok: false, error: 'category is required.' });
  res.json({ ok: true, entry: createUpgradeProposal({ title, summary, proposedBy, category }) });
});

app.post('/upgrades/proposals/decision', (req, res) => {
  const { proposalId, decision, decidedBy, reason } = req.body ?? {};
  if (typeof proposalId !== 'string' || !proposalId.trim()) return res.status(400).json({ ok: false, error: 'proposalId is required.' });
  if (decision !== 'approved' && decision !== 'rejected') return res.status(400).json({ ok: false, error: 'decision must be approved or rejected.' });
  if (typeof decidedBy !== 'string' || !decidedBy.trim()) return res.status(400).json({ ok: false, error: 'decidedBy is required.' });

  const entry = decideUpgradeProposal({ proposalId, decision, decidedBy, reason });
  if (!entry) return res.status(404).json({ ok: false, error: 'proposal not found.' });

  appendApprovedEntry({
    actionType: `upgrade-proposal:${decision}`,
    payload: { proposalId: entry.id, title: entry.title, category: entry.category, decidedBy, reason: reason ?? '' },
    reason: `Upgrade proposal ${decision}: ${entry.title}.`,
  });

  res.json({ ok: true, entry });
});


app.get('/builder/config', (_req, res) => {
  res.json(getUserConfigSnapshot());
});

app.post('/builder/config', (req, res) => {
  const payload = req.body ?? {};
  const allowed = ['ue5Path', 'unityPath', 'projectPath', 'blenderPath', 'godotPath', 'fivemRoot'];
  const updates = Object.fromEntries(Object.entries(payload).filter(([key, value]) => allowed.includes(key) && typeof value === 'string'));
  if (Object.keys(updates).length === 0) {
    return res.status(400).json({ ok: false, error: 'No valid config keys provided.' });
  }
  const config = setUserConfig(updates);
  emitEvent('HUMAN.INPUT', { source: 'BUILDER.CONFIG', action: 'SET_PATHS', details: updates }, 'LOCAL_OPERATOR');
  res.json({ ok: true, config });
});

app.get('/builder/pipelines', (_req, res) => {
  res.json({ entries: listPipelines() });
});

app.post('/builder/request', (req, res) => {
  const { request, proposedBy } = req.body ?? {};
  if (typeof request !== 'string' || !request.trim()) {
    return res.status(400).json({ ok: false, error: 'request is required.' });
  }
  emitEvent('LUCY.ACTION', { request: request.trim(), lane: null }, 'LUCY_UI');
  const pipeline = createBuildPipeline(request.trim(), typeof proposedBy === 'string' && proposedBy.trim() ? proposedBy.trim() : 'local-operator');
  appendApprovedEntry({
    actionType: 'builder:pipeline-created',
    payload: { pipelineId: pipeline.id, engine: pipeline.engine, request: pipeline.request },
    reason: 'Governed build pipeline created from human request.',
  });
  res.json({ ok: true, pipeline });
});

app.post('/builder/approve', async (req, res) => {
  const { pipelineId, step } = req.body ?? {};
  const target = typeof pipelineId === 'string' && pipelineId.trim() ? getPipeline(pipelineId.trim()) : getLatestPendingPipeline();
  if (!target) return res.status(404).json({ ok: false, error: 'No pipeline available to approve.' });
  emitEvent('HUMAN.INPUT', { source: 'DEBUG_CHAT', action: `APPROVE_${step === 'all' ? 'ALL' : `STEP_${step}`}`, details: { pipelineId: target.id } }, 'LOCAL_OPERATOR');
  const result = await executeApprovedPipeline(target.id, step === undefined ? 'all' : step);
  res.status(result.ok ? 200 : 400).json({ ok: result.ok, ...result });
});


app.get('/lucy/session', (_req, res) => {
  res.json({ messages: getLucySessionMessages() });
});

app.post('/lucy/session/message', async (req, res) => {
  const { text } = req.body ?? {};
  if (typeof text !== 'string' || text.trim().length === 0) {
    return res.status(400).json({ ok: false, error: 'text is required.' });
  }

  const trimmed = text.trim();
  const userMessage = appendLucyUserMessage(trimmed);
  emitEvent('HUMAN.INPUT', { source: 'DEBUG_CHAT', action: trimmed }, 'LOCAL_OPERATOR');

  const configCommand = parseConfigCommand(trimmed);
  if (configCommand) {
    const config = setUserConfig({ [configCommand.key]: configCommand.value });
    const assistantMessage = appendLucyAssistantMessage(`Saved ${configCommand.key} to Lucy config. Current build config: ${formatConfigSummary(config)}`);
    return res.json({ ok: true, userMessage, assistantMessage, messages: getLucySessionMessages() });
  }

  const handbookCommand = parseHandbookCommand(trimmed);
  if (handbookCommand) {
    const config = setHandbookUrls(handbookCommand.updates);
    const assistantMessage = appendLucyAssistantMessage(`${handbookCommand.summary} Current FiveM handbook config: ${formatHandbookSummary(config)}`);
    return res.json({ ok: true, userMessage, assistantMessage, messages: getLucySessionMessages() });
  }

  const toolbeltSet = parseToolbeltSetCommand(trimmed);
  if (toolbeltSet) {
    const active = setActiveToolbeltContext({ userId: 'local-operator', activePackIds: toolbeltSet.packIds, mode: toolbeltSet.mode, lastResolvedFrom: trimmed });
    const assistantMessage = appendLucyAssistantMessage(`${toolbeltSet.summary} Active toolbelt: ${formatToolbeltSummary()}`);
    return res.json({ ok: true, userMessage, assistantMessage, messages: getLucySessionMessages(), toolbelt: active });
  }

  const toolbeltBuild = parseToolbeltBuildCommand(trimmed);
  if (toolbeltBuild) {
    const available = listToolbeltPacks();
    const valid = toolbeltBuild.ids.filter((id) => available.some((pack) => pack.id === id));
    if (valid.length === 0) {
      const assistantMessage = appendLucyAssistantMessage('I could not build a toolbelt from that request because none of the requested packs exist yet.');
      return res.json({ ok: true, userMessage, assistantMessage, messages: getLucySessionMessages() });
    }
    const active = setActiveToolbeltContext({ userId: 'local-operator', activePackIds: valid, mode: 'build', lastResolvedFrom: trimmed });
    const assistantMessage = appendLucyAssistantMessage(`Built toolbelt context from ${valid.join(', ')}. Active toolbelt: ${formatToolbeltSummary()}`);
    return res.json({ ok: true, userMessage, assistantMessage, messages: getLucySessionMessages(), toolbelt: active });
  }

  if (isHandbookReadback(trimmed)) {
    const config = getUserConfig();
    const assistantMessage = appendLucyAssistantMessage(`Current FiveM handbook config: ${formatHandbookSummary(config)}`);
    return res.json({ ok: true, userMessage, assistantMessage, messages: getLucySessionMessages() });
  }

  if (isToolbeltReadback(trimmed)) {
    const active = getActiveToolbeltContext();
    const assistantMessage = appendLucyAssistantMessage(trimmed.toLowerCase().includes('list')
      ? `Available toolbelts: ${listToolbeltPacks().map((pack) => pack.id).join(', ')}`
      : `Active toolbelt: ${formatToolbeltSummary()}${active.lastResolvedFrom ? ` | last resolved from: ${active.lastResolvedFrom}` : ''}`);
    return res.json({ ok: true, userMessage, assistantMessage, messages: getLucySessionMessages(), toolbelt: active });
  }

  const resolvedToolbelt = resolveToolbelt(trimmed);
  if (resolvedToolbelt.length > 0 && /toolbelt|handbook|docs|reference|manual|build|lua|unity|ue5|unreal|blender|godot|earth/i.test(trimmed)) {
    const active = setActiveToolbeltContext({ userId: 'local-operator', activePackIds: resolvedToolbelt.map((pack) => pack.id), mode: 'planning', lastResolvedFrom: trimmed });
    const assistantMessage = appendLucyAssistantMessage(`📚 Toolbelt Activated: ${resolvedToolbelt.map((pack) => pack.label).join(' | ')}. Lucy will use this as planning context only (no execution).`);
    return res.json({ ok: true, userMessage, assistantMessage, messages: getLucySessionMessages(), toolbelt: active });
  }

  if (isBuildRequest(trimmed)) {
    const pipeline = createBuildPipeline(trimmed, 'local-operator');
    appendApprovedEntry({
      actionType: 'builder:pipeline-created',
      payload: { pipelineId: pipeline.id, engine: pipeline.engine, request: pipeline.request },
      reason: 'Governed build pipeline created from debug chat.',
    });
    const assistantMessage = appendLucyAssistantMessage(summarizePipeline(pipeline));
    return res.json({ ok: true, userMessage, assistantMessage, messages: getLucySessionMessages(), pipeline });
  }

  const approval = parseApprovalCommand(trimmed);
  if (approval) {
    const target = getLatestPendingPipeline();
    if (!target) {
      const assistantMessage = appendLucyAssistantMessage('There is no pending build pipeline to approve right now.');
      return res.json({ ok: true, userMessage, assistantMessage, messages: getLucySessionMessages() });
    }
    const result = await executeApprovedPipeline(target.id, approval.step);
    const resultText = result.ok
      ? `Execution finished for pipeline ${target.id.slice(0, 8)}. ${result.results?.map((entry) => `Step ${entry.stepId}: ${entry.ok ? 'ok' : entry.blocked ? 'blocked' : 'failed'}`).join(' | ')}`
      : `Execution could not start: ${result.error || 'unknown error'}`;
    const assistantMessage = appendLucyAssistantMessage(resultText);
    return res.status(result.ok ? 200 : 400).json({ ok: result.ok, userMessage, assistantMessage, messages: getLucySessionMessages(), result });
  }

  const earth = await fetchEarthBaseline();
  const earthLive = await runIngestCycle(false);
  const twinEarth = buildTwinEarthState(earth, earthLive);
  const sentinel = detectSignals(earth, twinEarth, getLedgerEntries(), emmaReviewMemory);
  const integrity = verifyLedgerIntegrity();
  const eagleEye = deriveWatchState(sentinel, integrity);
  const executionGate = deriveExecutionGateState({
    eagleEye,
    deltaVaultIntegrity: integrity,
    humanApprovalDecisions: getHumanApprovalDecisions(),
  });
  const proposals = getUpgradeProposals();

  // ── Lucy generation: Ollama-first, fallback to rule-based ────────────
  let replyText;
  const ollamaStatus = getOllamaStatus();
  if (ollamaStatus.available) {
    try {
      const systemPrompt = buildLucySystemPrompt({ earth, earthLive, sentinel, eagleEye, executionGate, proposals });
      const history = getLucySessionMessages().slice(-20);
      replyText = await chatWithOllama(systemPrompt, history, trimmed);
    } catch (err) {
      console.warn('[Lucy] Ollama call failed, falling back to rule-based:', err.message);
      replyText = null;
    }
  }
  if (!replyText) {
    replyText = buildLucyReply({ userText: trimmed, earth, earthLive, sentinel, eagleEye, executionGate, proposals });
  }

  // ── Emma Sentinel: pre-send content filter ────────────────────────────
  // rewriteFn: if Emma flags non-hard content, Lucy gets one rewrite attempt
  // via Ollama (preferred) or rule-based fallback.
  const filterRewriteFn = async (rewritePrompt) => {
    if (ollamaStatus.available) {
      try {
        const sp = buildLucySystemPrompt({ earth, earthLive, sentinel, eagleEye, executionGate, proposals });
        return await chatWithOllama(sp, [], rewritePrompt);
      } catch (err) {
        console.warn('[EmmaFilter] Ollama rewrite failed:', err.message);
      }
    }
    // Rule-based fallback: Lucy rewrites with a compliance-aware prompt
    return buildLucyReply({ userText: `[compliance rewrite] ${rewritePrompt}`, earth, earthLive, sentinel, eagleEye, executionGate, proposals });
  };

  const filterResult = await applyContentFilter(
    replyText,
    trimmed,
    filterRewriteFn,
    { source: 'session/message', layer: 'AME' }
  );

  const assistantMessage = appendLucyAssistantMessage(filterResult.finalText);

  res.json({
    ok: true,
    userMessage,
    assistantMessage,
    messages: getLucySessionMessages(),
    // Filtering metadata surfaced to client (useful for dashboard/audit)
    filtering: {
      enabled:          true,
      filtered:         filterResult.filtered,
      hardBlocked:      filterResult.hardBlocked,
      rewriteAttempted: filterResult.rewriteAttempted,
      rewriteSucceeded: filterResult.rewriteSucceeded,
      severityScore:    filterResult.scan?.severityScore ?? 0,
      auditId:          filterResult.auditId,
    },
  });
});


app.get('/deltavault', (_req, res) => {
  res.json({ entries: getLedgerEntries(), integrity: verifyLedgerIntegrity() });
});

app.post('/actions/review', (req, res) => {
  const { type, payload } = req.body ?? {};
  const decision = reviewAction({ type, payload });
  emmaReviewMemory.push(decision);
  if (emmaReviewMemory.length > 50) emmaReviewMemory.shift();

  if (decision.decision === 'rejected') {
    return res.status(400).json({ ok: false, approval: decision, executed: false });
  }

  const ledgerEntry = appendApprovedEntry({ actionType: type, payload, reason: decision.reason });
  res.json({ ok: true, approval: decision, ledgerEntry, executed: true });
});

// ════════════════════════════════════════════════════════════════════════════
// OLLAMA STATUS
// ════════════════════════════════════════════════════════════════════════════
app.get('/ollama/status', async (_req, res) => {
  const status = await getOllamaStatus();
  res.json({ ok: true, ...status });
});

// ════════════════════════════════════════════════════════════════════════════
// EARTH INTELLIGENCE ENDPOINTS (new connectors — no API keys needed)
// ════════════════════════════════════════════════════════════════════════════
app.get('/earth/earthquakes', async (req, res) => {
  const { range = 'day', mag = '2.5' } = req.query;
  const result = await fetchEarthquakes(range, mag);
  res.json(result);
});

app.get('/earth/weather-alerts', async (req, res) => {
  const { area } = req.query;
  const result = await fetchWeatherAlerts(area);
  res.json(result);
});

app.get('/earth/weather', async (req, res) => {
  const { lat = '40.7128', lon = '-74.0060', location = 'New York' } = req.query;
  const result = await fetchWeather(parseFloat(lat), parseFloat(lon), location);
  res.json(result);
});

app.get('/earth/space-weather', async (_req, res) => {
  const result = await fetchSpaceWeather();
  res.json(result);
});

app.get('/earth/aircraft', async (req, res) => {
  const { lamin, lomin, lamax, lomax } = req.query;
  const bounds = (lamin && lomin && lamax && lomax)
    ? { lamin: parseFloat(lamin), lomin: parseFloat(lomin), lamax: parseFloat(lamax), lomax: parseFloat(lomax) }
    : null;
  const result = await fetchAircraft(bounds);
  res.json(result);
});

app.get('/earth/metars', async (req, res) => {
  const { airports = 'KJFK,KLAX,KORD,KATL,KDFW' } = req.query;
  const result = await fetchMETARs(airports);
  res.json(result);
});

app.get('/earth/neo', async (req, res) => {
  const { api_key = 'DEMO_KEY' } = req.query;
  const result = await fetchNearEarthObjects(api_key);
  res.json(result);
});

app.get('/earth/stream-flow', async (req, res) => {
  const { state = 'US' } = req.query;
  const result = await fetchStreamFlow(state);
  res.json(result);
});

app.get('/earth/tides', async (req, res) => {
  const { station = '8518750', days = 1 } = req.query; // default: The Battery, NYC
  const result = await fetchTides(station, Number(days));
  res.json(result);
});

app.get('/earth/snapshot', async (_req, res) => {
  const result = await fetchEarthSnapshot();
  res.json(result);
});

// ════════════════════════════════════════════════════════════════════════════
// DATA SOURCES REFERENCE
// ════════════════════════════════════════════════════════════════════════════
app.get('/earth/sources', (_req, res) => {
  res.json({
    ok: true,
    sources: [
      { id: 'usgs_earthquakes',  name: 'USGS Earthquakes',      url: '/earth/earthquakes',    keyRequired: false, realtime: true  },
      { id: 'noaa_alerts',       name: 'NOAA Weather Alerts',   url: '/earth/weather-alerts', keyRequired: false, realtime: true  },
      { id: 'open_meteo',        name: 'Open-Meteo Weather',    url: '/earth/weather',        keyRequired: false, realtime: true  },
      { id: 'noaa_space',        name: 'NOAA Space Weather',    url: '/earth/space-weather',  keyRequired: false, realtime: true  },
      { id: 'opensky',           name: 'OpenSky Aircraft',      url: '/earth/aircraft',       keyRequired: false, realtime: true  },
      { id: 'avwx_metars',       name: 'Aviation METARs',       url: '/earth/metars',         keyRequired: false, realtime: true  },
      { id: 'nasa_neo',          name: 'NASA Near-Earth Objects', url: '/earth/neo',          keyRequired: false, realtime: true  },
      { id: 'usgs_streamflow',   name: 'USGS Stream Flow',       url: '/earth/stream-flow',    keyRequired: false, realtime: true  },
      { id: 'noaa_tides',        name: 'NOAA Tides & Currents',  url: '/earth/tides',          keyRequired: false, realtime: true  },
      { id: 'earth_snapshot',    name: 'Full Earth Snapshot',    url: '/earth/snapshot',       keyRequired: false, realtime: true  },
    ],
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// NVIDIA TRITON INFERENCE STREAM  (SSE proxy → Triton HTTP port 8000)
// ═══════════════════════════════════════════════════════════════════════════════

const TRITON_BASE = process.env.TRITON_HOST || 'http://127.0.0.1:8000';
const TRITON_MODEL = process.env.TRITON_MODEL || 'lucy_llm';

// Health-check: is Triton reachable?
async function checkTriton() {
  try {
    const r = await fetch(`${TRITON_BASE}/v2/health/ready`, { signal: AbortSignal.timeout(2000) });
    return r.ok;
  } catch {
    return false;
  }
}

/**
 * GET /lucy/triton/stream?q=<encoded prompt>
 *
 * Streams Triton inference tokens back to the client as Server-Sent Events.
 * Event format:
 *   data: {"token":"..."}        — incremental token
 *   data: {"done":true}          — stream complete
 *   data: {"error":"..."}        — inference error
 *
 * Falls back to Ollama stream (if available) or rule-based reply if Triton
 * is unreachable — keeping this self-contained, no Bridge changes needed.
 */
app.get('/lucy/triton/stream', async (req, res) => {
  const userText = String(req.query.q || '').trim();
  const layer    = String(req.query.layer || 'AME (Lucy Core)');
  const sessionMessages = getLucySessionMessages().slice(-20);

  if (!userText) {
    res.status(400).json({ error: 'Missing query parameter: q' });
    return;
  }

  // ── SSE headers ──────────────────────────────────────────────────────────
  res.setHeader('Content-Type',  'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection',    'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no'); // disable nginx buffering
  res.flushHeaders();

  const send = (obj) => res.write(`data: ${JSON.stringify(obj)}

`);

  // ── helper: collect Earth context for system prompt ───────────────────────
  let earth = null;
  try { earth = await fetchEarthBaseline(); } catch { /* non-critical */ }
  const systemPrompt = buildLucySystemPrompt({
    earth, earthLive: null, sentinel: null,
    eagleEye: null, executionGate: null, proposals: null,
  });

  // ── 1. Try Triton first ───────────────────────────────────────────────────
  const tritonReady = await checkTriton();

  if (tritonReady) {
    try {
      // Build Triton v2 infer request (generate model expected)
      const prompt = `${systemPrompt}

User: ${userText}
Lucy:`;
      const tritonPayload = {
        id: `lucy-${Date.now()}`,
        inputs: [{
          name:     'text_input',
          shape:    [1, 1],
          datatype: 'BYTES',
          data:     [prompt],
        }],
        outputs: [{ name: 'text_output' }],
        parameters: {
          stream:      true,
          max_tokens:  512,
          temperature: 0.7,
        },
      };

      const tritonRes = await fetch(
        `${TRITON_BASE}/v2/models/${TRITON_MODEL}/generate_stream`,
        {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify(tritonPayload),
          signal:  AbortSignal.timeout(60000),
        }
      );

      if (!tritonRes.ok) {
        throw new Error(`Triton HTTP ${tritonRes.status}: ${await tritonRes.text()}`);
      }

      // Stream NDJSON lines from Triton → SSE tokens to client
      const reader = tritonRes.body.getReader();
      const decoder = new TextDecoder();
      let fullText = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        // Triton generate_stream returns one JSON object per line
        for (const line of chunk.split('\\n')) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          try {
            const parsed = JSON.parse(trimmed);
            // Triton LLM response field varies by model backend:
            // TRT-LLM uses "text_output", vLLM bridge uses "token"
            const token =
              parsed?.outputs?.[0]?.data?.[0] ??
              parsed?.text_output ??
              parsed?.token ??
              '';
            if (token) {
              fullText += token;
              send({ token, source: 'triton', model: TRITON_MODEL });
            }
            if (parsed?.model_name || parsed?.done) {
              // end-of-stream marker from some Triton backends
              break;
            }
          } catch {
            // partial JSON or keep-alive ping — skip
          }
        }
      }

      // ── Emma Sentinel filter before sending to client (Triton path) ──
      const tritonRewriteFn = async (rewritePrompt) => {
        const tritonOllamaStatus = getOllamaStatus();
        if (tritonOllamaStatus.available) {
          try {
            return await chatWithOllama(buildLucySystemPrompt({ earth, earthLive: null, sentinel: null, eagleEye: null, executionGate: null, proposals: null }), [], rewritePrompt);
          } catch { /* fall through */ }
        }
        return null; // hard block if no rewrite available
      };
      const tritonFilter = await applyStreamingFilter(
        fullText, userText, tritonRewriteFn, send,
        { done: true, source: 'triton', layer },
        { source: 'triton/stream', layer }
      );
      const tritonFinal = tritonFilter.filtered ? tritonFilter.finalText : fullText;
      if (tritonFinal) {
        appendLucyUserMessage(userText);
        appendLucyAssistantMessage(tritonFinal);
      }
      if (!tritonFilter.filtered) {
        send({ done: true, source: 'triton', layer, fullText });
      }
      res.end();
      return;

    } catch (tritonErr) {
      console.warn('[Lucy/Triton] Stream error, falling back:', tritonErr.message);
      send({ warning: `Triton unavailable (${tritonErr.message}), switching to fallback` });
    }
  }

  // ── 2. Fallback: Ollama streaming (if available) ──────────────────────────
  const ollamaStatus = getOllamaStatus();
  if (ollamaStatus.available) {
    try {
      const OLLAMA_BASE = process.env.OLLAMA_HOST || 'http://127.0.0.1:11434';
      const ollamaRes = await fetch(`${OLLAMA_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model:  ollamaStatus.model,
          stream: true,
          messages: [
            { role: 'system',    content: systemPrompt },
            ...sessionMessages.slice(-10).map(m => ({
              role:    m.role === 'assistant' ? 'assistant' : 'user',
              content: m.content ?? m.text ?? '',
            })),
            { role: 'user', content: userText },
          ],
        }),
        signal: AbortSignal.timeout(60000),
      });

      if (!ollamaRes.ok) throw new Error(`Ollama HTTP ${ollamaRes.status}`);

      const reader  = ollamaRes.body.getReader();
      const decoder = new TextDecoder();
      let fullText  = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        for (const line of chunk.split('\\n')) {
          if (!line.trim()) continue;
          try {
            const parsed = JSON.parse(line);
            const token  = parsed?.message?.content ?? '';
            if (token) {
              fullText += token;
              send({ token, source: 'ollama', model: ollamaStatus.model });
            }
            if (parsed?.done) break;
          } catch { /* partial */ }
        }
      }

      // ── Emma Sentinel filter before sending to client (Ollama path) ──
      const ollamaRewriteFn2 = async (rewritePrompt) => {
        if (ollamaStatus.available) {
          try {
            return await chatWithOllama(buildLucySystemPrompt({ earth, earthLive: null, sentinel: null, eagleEye: null, executionGate: null, proposals: null }), [], rewritePrompt);
          } catch { /* fall through */ }
        }
        return null;
      };
      const ollamaFilter = await applyStreamingFilter(
        fullText, userText, ollamaRewriteFn2, send,
        { done: true, source: 'ollama', layer },
        { source: 'triton/stream:ollama', layer }
      );
      const ollamaFinal = ollamaFilter.filtered ? ollamaFilter.finalText : fullText;
      if (ollamaFinal) {
        appendLucyUserMessage(userText);
        appendLucyAssistantMessage(ollamaFinal);
      }
      if (!ollamaFilter.filtered) {
        send({ done: true, source: 'ollama', layer, fullText });
      }
      res.end();
      return;

    } catch (ollamaErr) {
      console.warn('[Lucy/Ollama] Stream fallback error:', ollamaErr.message);
      send({ warning: `Ollama stream failed (${ollamaErr.message}), using rule-based` });
    }
  }

  // ── 3. Final fallback: rule-based reply (no streaming, single token burst) ─
  try {
    const earth2 = earth || await fetchEarthBaseline().catch(() => null);
    const replyText = buildLucyReply({
      userText,
      earth:         earth2,
      earthLive:     null,
      sentinel:      null,
      eagleEye:      null,
      executionGate: null,
      proposals:     null,
    });

    appendLucyUserMessage(userText);
    appendLucyAssistantMessage(replyText);

    // ── Emma Sentinel filter (rule-based path) ─────────────────────────────────────
    const rbFilter = await applyContentFilter(
      replyText, userText,
      async () => null, // no rewrite in rule-based path — hard block if needed
      { source: 'triton/stream:rule-based', layer }
    );
    const rbFinal = rbFilter.finalText;
    // Simulate streaming for UI consistency — burst as single chunk
    send({ token: rbFinal, source: 'rule-based', model: 'local',
           filtered: rbFilter.filtered, hardBlocked: rbFilter.hardBlocked });
    send({ done: true, source: 'rule-based', layer, fullText: rbFinal,
           filtered: rbFilter.filtered });
  } catch (fallbackErr) {
    send({ error: `All inference paths failed: ${fallbackErr.message}` });
  }

  res.end();
});

// Triton status endpoint
app.get('/lucy/triton/status', async (_req, res) => {
  const ready = await checkTriton();
  let models = [];
  if (ready) {
    try {
      const r = await fetch(`${TRITON_BASE}/v2/models/${TRITON_MODEL}/ready`,
        { signal: AbortSignal.timeout(2000) });
      models = [{ name: TRITON_MODEL, ready: r.ok }];
    } catch { /* ignore */ }
  }
  res.json({
    ok: true,
    triton: { available: ready, host: TRITON_BASE, model: TRITON_MODEL, models },
    ollama: getOllamaStatus(),
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// EMMA SENTINEL — CONTENT FILTER ENDPOINTS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * GET /emma/filter/config
 *
 * Returns the current Emma Sentinel content filter configuration including
 * the active forbidden keyword list, hard-block threshold, and feature flags.
 */
app.get('/emma/filter/config', (_req, res) => {
  res.json({ ok: true, ...getFilterConfig() });
});

/**
 * POST /emma/filter/config
 *
 * Hot-swap the Emma Sentinel configuration without restarting the server.
 * Accepts a partial config object — only provided keys are updated.
 *
 * Example body to add a keyword and lower the threshold:
 *   {
 *     "emma_config": {
 *       "forbidden_keywords": ["harm", "exploit", "new_keyword"],
 *       "hard_block_threshold": 0.90
 *     },
 *     "lucy_config": { "transparency_mode": "optional_note" }
 *   }
 *
 * Example body to disable filtering entirely:
 *   { "filtering_enabled": false }
 */
app.post('/emma/filter/config', (req, res) => {
  const updates = req.body;
  if (!updates || typeof updates !== 'object') {
    return res.status(400).json({ ok: false, error: 'Request body must be a JSON config object.' });
  }
  try {
    const updated = setFilterConfig(updates);
    res.json({ ok: true, message: 'Emma Sentinel config updated.', ...updated });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

/**
 * GET /emma/filter/log
 *
 * Returns the last N content filtering audit events.
 * Query param: ?limit=50 (default 50, max 500)
 *
 * Each entry includes:
 *   action (PASS | HARD_BLOCK | REWRITE_SUCCESS | REWRITE_FAILED_HARD_BLOCK),
 *   severityScore, triggeredKeywords, flaggedSentences, rewriteAttempted,
 *   rewriteSucceeded, outcome, timestamp, source
 */
app.get('/emma/filter/log', (req, res) => {
  const limit = Math.min(500, Math.max(1, Number(req.query.limit) || 50));
  const log   = getFilterAuditLog(limit);
  res.json({
    ok:    true,
    count: log.length,
    log,
  });
});

// ═══════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// EAGLE EYE SOVEREIGNTY ENDPOINTS  —  EAGLE_EYE_SOVEREIGNTY_V1
// ═══════════════════════════════════════════════════════════════════════════

/**
 * GET /eagleeye/sovereignty
 *
 * Returns the current sovereignty status for the operator dashboard.
 * The `lucySafeMode` flag tells the UI whether Lucy is operating normally
 * or has been locked down to L0 due to Eagle Eye degradation.
 *
 * Response shape:
 *   { declaration, version, gatewayHealthy, lucySafeMode,
 *     watchState, activeContracts, rules, timestamp }
 */
app.get('/eagleeye/sovereignty', async (_req, res) => {
  try {
    const { sentinel, integrity, eagleEye } = await buildEagleEye();
    refreshEagleEyeWatchState(eagleEye);
    const status = getSovereigntyStatus({ sentinel, integrity, watchState: eagleEye });
    res.json({ ok: true, ...status });
  } catch (err) {
    console.error('[EagleEye] /sovereignty error:', err.message);
    // Fail-safe: if we can't build Eagle Eye state, return degraded status
    res.json({
      ok:             false,
      declaration:    'EAGLE_EYE_SOVEREIGNTY_V1',
      gatewayHealthy: false,
      lucySafeMode:   true,
      error:          err.message,
      rules: [
        { rule: 'MUTATION_LOCK',        enforcement: 'HARD_STOP',      active: true },
        { rule: 'SENSOR_FUSION_TRUST',  enforcement: 'SOFT_WARNING',   active: true },
        { rule: 'BUBBLE_BATH_PROTOCOL', enforcement: 'SCHEDULED_TASK', active: true },
      ],
      timestamp: new Date().toISOString(),
    });
  }
});

/**
 * POST /eagleeye/mutation/request
 *
 * Lucy's Mutation Engine calls this when proposing a new tool for the /tools directory.
 * Eagle Eye evaluates the proposal through its 4-gate check and — if approved —
 * issues a single-use SHA-256 hash that Lucy must present at write time.
 *
 * Request body:
 *   { toolId, version, code, permissions?, resourceProfile?, trustRequirement? }
 *
 * Response:
 *   { approved, hash?, rule, enforcement, reason, watchState, issuedAt }
 */
app.post('/eagleeye/mutation/request', async (req, res) => {
  try {
    const proposal = req.body;
    if (!proposal || typeof proposal !== 'object') {
      return res.status(400).json({ ok: false, error: 'Request body must be a JSON mutation proposal.' });
    }
    const { sentinel, integrity, eagleEye } = await buildEagleEye();
    refreshEagleEyeWatchState(eagleEye);
    const result = requestMutationClearance(proposal, { sentinel, integrity, watchState: eagleEye });
    const status = result.approved ? 200 : 403;
    res.status(status).json({ ok: result.approved, ...result });
  } catch (err) {
    console.error('[EagleEye] /mutation/request error:', err.message);
    res.status(500).json({
      ok: false, approved: false,
      rule: 'MUTATION_LOCK', enforcement: 'HARD_STOP',
      reason: `Eagle Eye internal error: ${err.message}`,
      error: err.message,
    });
  }
});

/**
 * POST /eagleeye/mutation/validate
 *
 * Called by the Mutation Engine immediately before writing a tool to /tools.
 * Lucy presents the hash issued by /mutation/request along with the (unmodified)
 * proposal. Eagle Eye verifies authenticity, checks expiry, and consumes the hash.
 *
 * Request body:
 *   { hash, proposal: { toolId, version, code, permissions?, resourceProfile? } }
 *
 * Response:
 *   { approved, rule, enforcement, reason, watchState }
 */
app.post('/eagleeye/mutation/validate', async (req, res) => {
  try {
    const { hash, proposal } = req.body ?? {};
    if (!hash || !proposal) {
      return res.status(400).json({ ok: false, error: 'Body must contain { hash, proposal }.' });
    }
    const { sentinel, integrity, eagleEye } = await buildEagleEye();
    refreshEagleEyeWatchState(eagleEye);
    const result = validateMutationWrite(hash, proposal, { sentinel, integrity, watchState: eagleEye });
    const status = result.approved ? 200 : 403;
    res.status(status).json({ ok: result.approved, ...result });
  } catch (err) {
    console.error('[EagleEye] /mutation/validate error:', err.message);
    res.status(500).json({
      ok: false, approved: false,
      rule: 'MUTATION_LOCK', enforcement: 'HARD_STOP',
      reason: `Eagle Eye internal error: ${err.message}`,
      error: err.message,
    });
  }
});

/**
 * POST /eagleeye/sensor-fusion/assess
 *
 * Called before Lucy executes a "Quantum Leap" cross-domain prediction.
 * Eagle Eye cross-references the prediction's cited data sources against
 * current hardware health telemetry and returns a trust score + warnings.
 *
 * SOFT_WARNING enforcement: Lucy may proceed but must caveat her output
 * if trustScore < 1.0. If trustScore < 0.4, Eagle Eye recommends aborting.
 *
 * Request body:
 *   { prediction: { dataSources: string[], ... } }
 *   Optional: { earthData: { [sourceKey]: { timestamp, quality, maxAgeMinutes } } }
 *
 * Response:
 *   { proceed, trustScore, warnings, rule, enforcement, recommendation, assessedAt }
 */
app.post('/eagleeye/sensor-fusion/assess', async (req, res) => {
  try {
    const { prediction, earthData } = req.body ?? {};
    if (!prediction) {
      return res.status(400).json({ ok: false, error: 'Body must contain { prediction }.' });
    }
    const { sentinel, integrity, eagleEye } = await buildEagleEye();
    refreshEagleEyeWatchState(eagleEye);
    const result = assessSensorFusionTrust(prediction, {
      sentinel, integrity,
      earthData: earthData ?? {},
      watchState: eagleEye,
    });
    res.json({ ok: true, ...result });
  } catch (err) {
    console.error('[EagleEye] /sensor-fusion/assess error:', err.message);
    res.status(500).json({
      ok: false, proceed: false,
      rule: 'SENSOR_FUSION_TRUST', enforcement: 'SOFT_WARNING',
      trustScore: 0,
      warnings: [`Eagle Eye internal error: ${err.message}`],
      error: err.message,
    });
  }
});

/**
 * POST /eagleeye/prune/submit
 *
 * Phase 1 of the Bubble Bath Protocol.
 * Lucy submits a list of tool candidates she considers suitable for retirement.
 * Eagle Eye reviews the list, filters out protected/recently-active tools,
 * and issues a signed pruning job ID for the approved subset.
 *
 * Request body:
 *   { candidates: Array<{ toolId, category?, protected?, daysSinceLastUse? }> }
 *
 * Response:
 *   { jobId?, approved, approvedCandidates, deferredCandidates,
 *     scheduledFor?, rule, enforcement, reason }
 */
app.post('/eagleeye/prune/submit', async (req, res) => {
  try {
    const { candidates } = req.body ?? {};
    if (!Array.isArray(candidates)) {
      return res.status(400).json({ ok: false, error: 'Body must contain { candidates: [...] }.' });
    }
    const { sentinel, integrity, eagleEye } = await buildEagleEye();
    refreshEagleEyeWatchState(eagleEye);
    const result = submitPruneCandidates(candidates, { sentinel, integrity, watchState: eagleEye });
    const status = result.approved ? 200 : 202; // 202 Accepted = deferred
    res.status(status).json({ ok: result.approved, ...result });
  } catch (err) {
    console.error('[EagleEye] /prune/submit error:', err.message);
    res.status(500).json({
      ok: false, approved: false,
      rule: 'BUBBLE_BATH_PROTOCOL', enforcement: 'SCHEDULED_TASK',
      reason: `Eagle Eye internal error: ${err.message}`,
      error: err.message,
    });
  }
});

/**
 * POST /eagleeye/prune/execute
 *
 * Phase 2 of the Bubble Bath Protocol.
 * Eagle Eye executes a previously issued pruning job.
 * Returns the authorised candidate list — the caller is responsible
 * for the actual deletion/retirement from the tool registry.
 *
 * Eagle Eye re-checks its own health at execution time; if degraded,
 * the prune is aborted (fail-safe).
 *
 * Request body:
 *   { jobId: string }
 *
 * Response:
 *   { executed, jobId, candidates?, executedAt?, rule, enforcement, reason }
 */
app.post('/eagleeye/prune/execute', async (req, res) => {
  try {
    const { jobId } = req.body ?? {};
    if (!jobId || typeof jobId !== 'string') {
      return res.status(400).json({ ok: false, error: 'Body must contain { jobId: string }.' });
    }
    const { sentinel, integrity, eagleEye } = await buildEagleEye();
    refreshEagleEyeWatchState(eagleEye);
    const result = executePruneJob(jobId, { sentinel, integrity, watchState: eagleEye });
    const status = result.executed ? 200 : 403;
    res.status(status).json({ ok: result.executed, ...result });
  } catch (err) {
    console.error('[EagleEye] /prune/execute error:', err.message);
    res.status(500).json({
      ok: false, executed: false,
      rule: 'BUBBLE_BATH_PROTOCOL', enforcement: 'SCHEDULED_TASK',
      reason: `Eagle Eye internal error: ${err.message}`,
      error: err.message,
    });
  }
});

// ═══════════════════════════════════════════════════════════════════════════

app.listen(PORT, () => {
  console.log(`Lucy OS backend listening on http://localhost:${PORT}`);

  // ── Pre-check Ollama on startup ──────────────────────────────────────────
  checkOllama().then(status => {
    if (status.available) {
      console.log(`[lucy] Ollama ready — model: ${status.model}`);
    } else {
      console.log(`[lucy] Ollama not found — using rule-based replies (install Ollama to enable LLM)`);
    }
  });

  // ── Eagle Eye sovereignty health check on startup ────────────────────────
  // Builds a fresh Eagle Eye watch state and reports Lucy's initial safe-mode status.
  // If Eagle Eye is degraded at boot, Lucy starts in L0 Safe Mode.
  buildEagleEye().then(({ sentinel, integrity, eagleEye }) => {
    refreshEagleEyeWatchState(eagleEye);
    const sovereignty = getSovereigntyStatus({ sentinel, integrity, watchState: eagleEye });
    if (sovereignty.lucySafeMode) {
      console.warn(`[EagleEye] ⚠  Gateway DEGRADED at startup — Lucy entering L0 Safe Mode.`);
      console.warn(`[EagleEye]    pressureIndex=${eagleEye?.pressureIndex ?? 'n/a'}, trusted=${eagleEye?.trusted ?? false}`);
      console.warn(`[EagleEye]    All mutations HARD_STOPPED until Eagle Eye is restored.`);
    } else {
      console.log(`[EagleEye] ✓  Gateway healthy — declaration: ${sovereignty.declaration} v${sovereignty.version}`);
      console.log(`[EagleEye]    pressureIndex=${eagleEye.pressureIndex?.toFixed(3)}, overall=${eagleEye.overall}, trusted=${eagleEye.trusted}`);
      console.log(`[EagleEye]    Lucy operating at full capability. MUTATION_LOCK active.`);
    }
  }).catch(err => {
    console.error(`[EagleEye] ✗  Startup sovereignty check failed: ${err.message}`);
    console.error(`[EagleEye]    Lucy defaulting to L0 Safe Mode (fail-safe).`);
  });
});
