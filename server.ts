import express from "express";
import { createServer as createViteServer } from "vite";
import path from "path";
import { CognitiveEngine } from "./src/server/CognitiveEngine";

async function startServer() {
  const app = express();
  const PORT = 3000;

  app.use(express.json());

  // Initialize the Cognitive Engine
  const engine = new CognitiveEngine();
  engine.start();

  // API Routes
  app.get("/api/health", (req, res) => {
    res.json({ status: "ok" });
  });

  // SSE Endpoint for real-time cognitive state
  app.get("/api/state/stream", (req, res) => {
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.flushHeaders();

    const sendState = () => {
      const state = engine.getState();
      res.write(`data: ${JSON.stringify(state)}\n\n`);
    };

    // Send initial state
    sendState();

    // Subscribe to engine ticks
    const interval = setInterval(sendState, 200); // 5Hz update rate to frontend

    req.on("close", () => {
      clearInterval(interval);
    });
  });

  // Endpoint to submit new intents (prompts)
  app.post("/api/intent", (req, res) => {
    const { goal, origin = "user" } = req.body;
    if (!goal) {
      return res.status(400).json({ error: "Goal is required" });
    }
    
    const intent = engine.addIntent(goal, origin);
    res.json({ success: true, intent });
  });

  // Vite middleware for development
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`[Lucy Chassis] Server running on http://localhost:${PORT}`);
  });
}

startServer();
