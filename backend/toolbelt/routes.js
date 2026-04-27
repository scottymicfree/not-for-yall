import { listToolbeltPacks, getToolbeltPack, upsertToolbeltPack } from './registry.js';
import { getActiveToolbeltContext, setActiveToolbeltContext } from './memory.js';
import { resolveToolbelt } from './resolver.js';

export function registerToolbeltRoutes(app) {
  app.get('/toolbelt/list', (_req, res) => {
    res.json({ entries: listToolbeltPacks(), active: getActiveToolbeltContext() });
  });

  app.get('/toolbelt/active', (_req, res) => {
    const active = getActiveToolbeltContext();
    res.json({ active, entries: active.activePackIds.map((id) => getToolbeltPack(id)).filter(Boolean) });
  });

  app.post('/toolbelt/set', (req, res) => {
    const { packIds, mode, userId } = req.body ?? {};
    if (!Array.isArray(packIds) || packIds.length === 0) {
      return res.status(400).json({ ok: false, error: 'packIds must be a non-empty array.' });
    }
    const validIds = packIds.filter((id) => !!getToolbeltPack(id));
    if (validIds.length === 0) {
      return res.status(404).json({ ok: false, error: 'No valid toolbelt packs found.' });
    }
    const active = setActiveToolbeltContext({ userId: typeof userId === 'string' ? userId : 'local-operator', activePackIds: validIds, mode: typeof mode === 'string' ? mode : 'planning' });
    res.json({ ok: true, active, entries: validIds.map((id) => getToolbeltPack(id)).filter(Boolean) });
  });

  app.post('/toolbelt/resolve', (req, res) => {
    const { request, mode, userId } = req.body ?? {};
    if (typeof request !== 'string' || !request.trim()) {
      return res.status(400).json({ ok: false, error: 'request is required.' });
    }
    const matches = resolveToolbelt(request.trim());
    if (matches.length > 0) {
      const active = setActiveToolbeltContext({ userId: typeof userId === 'string' ? userId : 'local-operator', activePackIds: matches.map((pack) => pack.id), mode: typeof mode === 'string' ? mode : 'planning', lastResolvedFrom: request.trim() });
      return res.json({ ok: true, request: request.trim(), matches, active });
    }
    return res.json({ ok: true, request: request.trim(), matches: [], active: getActiveToolbeltContext() });
  });

  app.post('/toolbelt/build', (req, res) => {
    const { label, packIds, tags, userId } = req.body ?? {};
    const basePacks = Array.isArray(packIds) ? packIds.map((id) => getToolbeltPack(id)).filter(Boolean) : [];
    if (basePacks.length === 0) {
      return res.status(400).json({ ok: false, error: 'At least one valid packId is required.' });
    }
    const created = upsertToolbeltPack({
      id: typeof label === 'string' && label.trim() ? label.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '_') : undefined,
      label: typeof label === 'string' && label.trim() ? label.trim() : `Custom Toolbelt ${new Date().toISOString()}`,
      type: 'build_docs',
      primary: basePacks[0].primary,
      refs: [...new Set(basePacks.flatMap((pack) => [pack.primary, ...pack.refs]))],
      tags: [...new Set([...(Array.isArray(tags) ? tags : []), ...basePacks.flatMap((pack) => pack.tags)])],
      sourceMode: 'lucy_generated',
      planningOnly: true,
      active: true,
      version: 'generated',
    });
    const active = setActiveToolbeltContext({ userId: typeof userId === 'string' ? userId : 'local-operator', activePackIds: [created.id], mode: 'build', lastResolvedFrom: 'toolbelt-build' });
    res.json({ ok: true, entry: created, active });
  });
}
