import { listToolbeltPacks } from './registry.js';

const TERM_MAP = {
  fivem: ['fivem', 'lua', 'fxmanifest', 'natives', 'resource'],
  unity: ['unity', 'c#', 'buildpipeline'],
  ue5: ['ue5', 'unreal', 'blueprint', 'blueprints'],
  blender: ['blender', 'model', 'asset', 'mesh'],
  godot: ['godot', 'gdscript'],
  earth: ['earth', 'weather', 'seismic', 'volcano', 'solar', 'aircraft', 'gibs', 'imagery'],
  earth2: ['earth2', 'earth-2', 'earth2studio', 'forecast', 'twin earth'],
};

export function resolveToolbelt(request) {
  const lower = request.toLowerCase();
  const matches = [];
  for (const [id, terms] of Object.entries(TERM_MAP)) {
    if (terms.some((term) => lower.includes(term))) {
      matches.push(id);
    }
  }
  const packs = listToolbeltPacks();
  return packs.filter((pack) => matches.includes(pack.id));
}
