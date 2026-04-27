import { exec } from 'node:child_process';
import { appendApprovedEntry } from '../deltavault/ledger.js';
import { appendPipelineEvent, approveStep, getPipeline, updateStep, setPipelineStatus } from './pipelineStore.js';

function runCommand(command) {
  return new Promise((resolve) => {
    exec(command, { windowsHide: true }, (error, stdout, stderr) => {
      resolve({
        ok: !error,
        output: (stdout || stderr || '').trim(),
        error: error ? error.message : '',
      });
    });
  });
}

export async function executeApprovedPipeline(pipelineId, requestedStep = 'all') {
  let pipeline = getPipeline(pipelineId);
  if (!pipeline) return { ok: false, error: 'pipeline not found' };
  if (pipeline.missingConfig.length > 0) {
    setPipelineStatus(pipelineId, 'awaiting-config');
    appendPipelineEvent(pipelineId, 'PIPELINE_BLOCKED', `Missing config: ${pipeline.missingConfig.join(', ')}`);
    return { ok: false, error: `Missing config: ${pipeline.missingConfig.join(', ')}` };
  }

  const targetSteps = requestedStep === 'all'
    ? pipeline.steps.filter((step) => ['pending', 'approved'].includes(step.status))
    : pipeline.steps.filter((step) => step.id === requestedStep);

  if (targetSteps.length === 0) {
    return { ok: false, error: 'No matching pipeline steps available.' };
  }

  setPipelineStatus(pipelineId, 'running');
  const results = [];

  for (const step of targetSteps) {
    approveStep(pipelineId, step.id);
    updateStep(pipelineId, step.id, { status: 'running', startedAt: new Date().toISOString() });
    appendPipelineEvent(pipelineId, 'STEP_STARTED', `${step.action} started.`);

    if (!step.command) {
      updateStep(pipelineId, step.id, {
        status: 'blocked',
        finishedAt: new Date().toISOString(),
        error: 'Missing executable path or project path.',
      });
      appendPipelineEvent(pipelineId, 'STEP_BLOCKED', `${step.action} blocked: missing executable path or project path.`);
      results.push({ stepId: step.id, ok: false, blocked: true, output: '', error: 'Missing executable path or project path.' });
      continue;
    }

    const result = await runCommand(step.command);
    updateStep(pipelineId, step.id, {
      status: result.ok ? 'completed' : 'failed',
      finishedAt: new Date().toISOString(),
      output: result.output,
      error: result.error,
    });
    appendPipelineEvent(pipelineId, result.ok ? 'STEP_COMPLETED' : 'STEP_FAILED', `${step.action} ${result.ok ? 'completed' : 'failed'}.`);
    appendApprovedEntry({
      actionType: `pipeline:${step.action.toLowerCase()}`,
      payload: { pipelineId, stepId: step.id, command: step.command, ok: result.ok },
      reason: result.ok ? `${step.action} executed.` : `${step.action} failed during execution.`,
    });
    results.push({ stepId: step.id, ...result });
    if (!result.ok && requestedStep === 'all') break;
  }

  pipeline = getPipeline(pipelineId);
  const terminalState = pipeline?.steps.some((step) => step.status === 'failed') ? 'failed'
    : pipeline?.steps.every((step) => ['completed', 'blocked'].includes(step.status)) ? 'completed'
    : 'approved';
  setPipelineStatus(pipelineId, terminalState || 'approved');
  return { ok: !results.some((entry) => entry.ok === false && !entry.blocked), results, pipeline: getPipeline(pipelineId) };
}
