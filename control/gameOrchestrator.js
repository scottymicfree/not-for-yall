import path from 'node:path';
import { createPipeline } from './pipelineStore.js';
import { getUserConfig } from './userConfigStore.js';

function detectEngine(request) {
  const lower = request.toLowerCase();
  if (lower.includes('unity')) return 'UNITY';
  if (lower.includes('fivem')) return 'FIVEM';
  if (lower.includes('blender')) return 'BLENDER';
  if (lower.includes('godot')) return 'GODOT';
  return 'UE5';
}

function buildSteps(request, engine, config) {
  const projectName = request.toLowerCase().includes('st. louis') ? 'StLouisBuild' : 'LucyBuild';
  const projectRoot = config.projectPath || process.env.LUCY_PROJECT_PATH || '';
  const safeProjectRoot = projectRoot || '<set project path first>';
  if (engine === 'UE5') {
    return [
      {
        id: 1,
        action: 'CREATE_PROJECT',
        desc: 'Create or open UE5 project workspace.',
        command: config.ue5Path && projectRoot ? `"${config.ue5Path}" "${path.join(safeProjectRoot, `${projectName}.uproject`)}" -game -nosplash` : '',
      },
      {
        id: 2,
        action: 'INGEST_DATA',
        desc: 'Ingest local Earth/OSM/reference data into the project workspace.',
        command: projectRoot ? `cmd /c echo Ingesting local data into ${safeProjectRoot}` : '',
      },
      {
        id: 3,
        action: 'PROCEDURAL_GEN',
        desc: 'Run procedural generation / map build pass.',
        command: config.ue5Path && projectRoot ? `"${config.ue5Path}" "${path.join(safeProjectRoot, `${projectName}.uproject`)}" -run=pythonscript -script="${path.join(process.cwd(), 'backend', 'scripts', 'pcg_stub.py')}"` : '',
      },
    ];
  }
  if (engine === 'UNITY') {
    return [
      { id: 1, action: 'OPEN_PROJECT', desc: 'Open Unity project in batchmode.', command: config.unityPath && projectRoot ? `"${config.unityPath}" -batchmode -projectPath "${safeProjectRoot}" -quit` : '' },
      { id: 2, action: 'BUILD_PLAYER', desc: 'Run Unity build.', command: config.unityPath && projectRoot ? `"${config.unityPath}" -batchmode -projectPath "${safeProjectRoot}" -executeMethod BuildScript.PerformBuild -quit` : '' },
    ];
  }
  if (engine === 'FIVEM') {
    const root = config.fivemRoot || '<set fivem root first>';
    return [
      { id: 1, action: 'SCAFFOLD_RESOURCE', desc: 'Scaffold a standalone FiveM resource.', command: config.fivemRoot ? `cmd /c mkdir "${path.join(root, 'resources', 'lucy_generated_resource')}"` : '' },
      { id: 2, action: 'WRITE_MANIFEST', desc: 'Write fxmanifest scaffold.', command: config.fivemRoot ? `cmd /c echo fx_version 'cerulean' > "${path.join(root, 'resources', 'lucy_generated_resource', 'fxmanifest.lua')}"` : '' },
    ];
  }
  if (engine === 'BLENDER') {
    return [
      { id: 1, action: 'MODEL_ASSET', desc: 'Run Blender modeling script.', command: config.blenderPath && projectRoot ? `"${config.blenderPath}" --background --python "${path.join(process.cwd(), 'backend', 'scripts', 'blender_stub.py')}" -- "${safeProjectRoot}"` : '' },
    ];
  }
  return [
    { id: 1, action: 'PREPARE_PROJECT', desc: 'Prepare Godot project workspace.', command: config.godotPath && projectRoot ? `"${config.godotPath}" --headless --path "${safeProjectRoot}" --quit` : '' },
  ];
}

function findMissingConfig(engine, config) {
  const missing = [];
  if (!config.projectPath && engine !== 'FIVEM') missing.push('projectPath');
  if (engine === 'UE5' && !config.ue5Path) missing.push('ue5Path');
  if (engine === 'UNITY' && !config.unityPath) missing.push('unityPath');
  if (engine === 'FIVEM' && !config.fivemRoot) missing.push('fivemRoot');
  if (engine === 'BLENDER' && !config.blenderPath) missing.push('blenderPath');
  if (engine === 'GODOT' && !config.godotPath) missing.push('godotPath');
  return missing;
}

export function createBuildPipeline(request, proposedBy = 'local-operator') {
  const config = getUserConfig();
  const engine = detectEngine(request);
  const steps = buildSteps(request, engine, config);
  const missingConfig = findMissingConfig(engine, config);
  return createPipeline({
    request,
    engine,
    steps,
    proposedBy,
    estimatedSize: request.toLowerCase().includes('8k') ? 'large' : 'medium',
    missingConfig,
  });
}
