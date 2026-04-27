import express from 'express';
import cors from 'cors';
import { getLocalOperator, isLocalBypassEnabled } from './auth/localBypass.js';
import { fetchEarthBaseline } from './earth/fetchEarthBaseline.js';
import { buildTwinEarthState } from './twinearth/buildTwinEarthState.js';
import { reviewAction } from './emma/approvalService.js';
import { appendApprovedEntry, getLedgerEntries, verifyLedgerIntegrity } from './deltavault/ledger.js';
import { detectSignals } from './sentinel/detectSignals.js';
import { deriveWatchState } from './eagleeye/deriveWatchState.js';
import { deriveTrustState } from './trust/deriveTrustState.js';
import { deriveRewardState } from './reward/deriveRewardState.js';
import { deriveHumanApprovalState } from './humanapproval/deriveHumanApprovalState.js';
import { getHumanApprovalDecisions, recordHumanApprovalDecision } from './humanapproval/decisionStore.js';
import { deriveExecutionGateState } from './execution/deriveExecutionGateState.js';
import { buildSimulationPacket } from './execution/buildSimulationPacket.js';
import { getUpgradeProposals, createUpgradeProposal, decideUpgradeProposal } from './upgrades/proposalStore.js';
import { getLucySessionMessages, appendLucyUserMessage, appendLucyAssistantMessage } from './persona/lucySessionStore.js';
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

  const assistantMessage = appendLucyAssistantMessage(
    buildLucyReply({ userText: trimmed, earth, earthLive, sentinel, eagleEye, executionGate, proposals })
  );

  res.json({ ok: true, userMessage, assistantMessage, messages: getLucySessionMessages() });
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

app.listen(PORT, () => {
  console.log(`Emma backend listening on http://localhost:${PORT}`);
});
