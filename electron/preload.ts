import { contextBridge } from 'electron';

contextBridge.exposeInMainWorld('lucy', {
  platform: process.platform,
  version: 'phase-1-3',
});
