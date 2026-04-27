import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const STORE_PATH = path.join(process.cwd(), 'data', 'control', 'pipelines.json');

function ensureDir() {
  fs.mkdirSync(path.dirname(STORE_PATH), { recursive: true });
}

function loadStore() {
  ensureDir();
  if (!fs.existsSync(STORE_PATH)) {
    fs.writeFileSync(STORE_PATH, JSON.stringify({ pipelines: [] }, null, 2));
    return { pipelines: [] };
  }
  try {
    const parsed = JSON.parse(fs.readFileSync(STORE_PATH, 'utf8'));
    return { pipelines: Array.isArray(parsed.pipelines) ? parsed.pipelines : [] };
  } catch {
    return { pipelines: [] };
  }
}

function saveStore(store) {
  ensureDir();
  fs.writeFileSync(STORE_PATH, JSON.stringify(store, null, 2));
}

let cache = loadStore();

function nowIso() { return new Date().toISOString(); }

export function listPipelines() {
  return cache.pipelines.map((entry) => structuredClone(entry)).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export function createPipeline(input) {
  const pipeline = {
    id: crypto.randomUUID(),
    request: input.request,
    engine: input.engine,
    status: 'pending',
    createdAt: nowIso(),
    updatedAt: nowIso(),
    proposedBy: input.proposedBy || 'local-operator',
    estimatedSize: input.estimatedSize || 'unknown',
    missingConfig: input.missingConfig || [],
    steps: (input.steps || []).map((step) => ({
      ...step,
      status: step.status || 'pending',
      output: step.output || '',
      error: step.error || '',
      approvedAt: step.approvedAt || null,
      startedAt: step.startedAt || null,
      finishedAt: step.finishedAt || null,
    })),
    eventLog: [{ at: nowIso(), type: 'PIPELINE_CREATED', message: `Pipeline created for ${input.engine}.` }],
  };
  cache.pipelines.unshift(pipeline);
  saveStore(cache);
  return structuredClone(pipeline);
}

export function getPipeline(pipelineId) {
  const found = cache.pipelines.find((entry) => entry.id === pipelineId);
  return found ? structuredClone(found) : null;
}

export function getLatestPendingPipeline() {
  const found = cache.pipelines.find((entry) => ['pending', 'awaiting-config', 'approved', 'running'].includes(entry.status));
  return found ? structuredClone(found) : null;
}

export function updatePipeline(pipelineId, updater) {
  const index = cache.pipelines.findIndex((entry) => entry.id === pipelineId);
  if (index === -1) return null;
  const current = cache.pipelines[index];
  const updated = updater(structuredClone(current));
  updated.updatedAt = nowIso();
  cache.pipelines[index] = updated;
  saveStore(cache);
  return structuredClone(updated);
}

export function appendPipelineEvent(pipelineId, type, message) {
  return updatePipeline(pipelineId, (pipeline) => {
    pipeline.eventLog.push({ at: nowIso(), type, message });
    return pipeline;
  });
}

export function setPipelineStatus(pipelineId, status) {
  return updatePipeline(pipelineId, (pipeline) => {
    pipeline.status = status;
    return pipeline;
  });
}

export function approveStep(pipelineId, stepId) {
  return updatePipeline(pipelineId, (pipeline) => {
    pipeline.steps = pipeline.steps.map((step) => step.id === stepId ? { ...step, status: 'approved', approvedAt: nowIso() } : step);
    if (pipeline.status === 'pending' || pipeline.status === 'awaiting-config') pipeline.status = 'approved';
    return pipeline;
  });
}

export function updateStep(pipelineId, stepId, changes) {
  return updatePipeline(pipelineId, (pipeline) => {
    pipeline.steps = pipeline.steps.map((step) => step.id === stepId ? { ...step, ...changes } : step);
    return pipeline;
  });
}
