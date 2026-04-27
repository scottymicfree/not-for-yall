import { contextBridge as o } from "electron";
o.exposeInMainWorld("lucy", {
  platform: process.platform,
  version: "phase-1-3"
});
