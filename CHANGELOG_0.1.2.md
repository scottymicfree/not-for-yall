# Alpha Delta Vualt v0.1.2

## Structure-only refactor

This release applies the Lucy Build Directive without changing working behavior.

### Foundation rules followed
- Alpha Delta Vualt remains the only runtime foundation.
- No Google/Gemini/cloud reintroduction.
- No fake systems or new shell.
- No breaking launcher changes.

### Refactor completed
- Split workspace UI into dedicated modules:
  - `src/workspace/FileManagerPanel.tsx`
  - `src/workspace/FileViewerPane.tsx`
  - `src/workspace/WorkspaceShell.tsx`
- Split chat UI into:
  - `src/chat/DebugChatPanel.tsx`
- Split tools UI into:
  - `src/tools/AppStoreLinks.tsx`
  - `src/tools/InstalledToolsPanel.tsx`
- Split Earth UI entry into:
  - `src/earth/EarthShell.tsx`
- `src/App.tsx` now acts as orchestrator instead of carrying all UI markup.

### Compatibility
- Existing behavior preserved.
- Existing launcher preserved.
- Existing file manager, tool registry, and Earth flows preserved.
- Existing wrapper components kept for compatibility:
  - `src/components/WorkspaceSidebar.tsx`
  - `src/components/WorkspaceModule.tsx`

## Verification
- `npm install` passed
- `npm run lint` passed
- `npm run build` passed
