import { app as o, BrowserWindow as d } from "electron";
import n from "node:path";
import { fileURLToPath as a } from "node:url";
const s = a(import.meta.url), i = n.dirname(s);
let e = null;
function l() {
  e = new d({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    title: "Lucy",
    backgroundColor: "#050714",
    webPreferences: {
      preload: n.join(i, "preload.mjs"),
      contextIsolation: !0,
      nodeIntegration: !1,
      sandbox: !0
    }
  });
  const t = process.env.VITE_DEV_SERVER_URL;
  if (t)
    e.loadURL(t), e.webContents.openDevTools({ mode: "detach" });
  else {
    const r = n.join(i, "../dist/index.html");
    e.loadFile(r);
  }
  e.on("closed", () => {
    e = null;
  });
}
o.whenReady().then(() => {
  l(), o.on("activate", () => {
    d.getAllWindows().length === 0 && l();
  });
});
o.on("window-all-closed", () => {
  process.platform !== "darwin" && o.quit();
});
