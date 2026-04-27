/**
 * preload.js — Electron context bridge
 * Exposes safe APIs to the React renderer process.
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('lucyElectron', {
  // Bridge service control
  getBridgeStatus: () => ipcRenderer.invoke('bridge:status'),
  restartBridge:   () => ipcRenderer.invoke('bridge:restart'),
  getVersion:      () => ipcRenderer.invoke('app:version'),

  // Platform info
  platform: process.platform,
  isElectron: true,
});