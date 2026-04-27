import { contextBridge } from 'electron';

contextBridge.exposeInMainWorld('emmaArchitecture', {
  platform: process.platform,
  version: 'phase-4',
  persona: 'Lucy',
});
