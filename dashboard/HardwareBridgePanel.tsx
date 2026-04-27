/**
 * HardwareBridgePanel.tsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Lucy OS Dashboard panel — Sovereign v2.1 Hardware Bridge
 *
 * Shows:
 *  • Bridge connection status + transport tier (PCIe / Ethernet / Serial / SIM)
 *  • Live board telemetry from http://localhost:8765/telemetry (SSE stream)
 *  • 137-node health grid (PRIME + C1-C8 + W001-W128)
 *  • GPU power/temp/util gauges (4× NVIDIA L40S)
 *  • FPGA / DVFS status
 *  • Governance controls: Halt Agent, Halt All, Throttle, Isolate, Reset GPU
 *  • Connection wizard: auto-probe or manual transport selection
 */

import React, {
  useCallback, useEffect, useReducer, useRef, useState
} from "react";

// ══════════════════════════════════════════════════════════════════════════════
// Types
// ══════════════════════════════════════════════════════════════════════════════

type Transport = "PCIe" | "Ethernet" | "Serial" | "SIM" | "NONE";
type HalMode   = "native" | "proto" | "sim" | "auto";
type BridgeStatus = "disconnected" | "connecting" | "connected" | "error";

interface NodeHealth {
  id: string;
  role: "prime" | "cluster" | "worker";
  gpu: number;
  health: "nominal" | "degraded" | "halted" | "isolated";
  util_pct: number;
}

interface GPUMetric {
  index: number;
  name: string;
  temp_c: number;
  power_w: number;
  util_pct: number;
  mem_used_mb: number;
  mem_total_mb: number;
}

interface Telemetry {
  timestamp: number;
  mode: string;
  lucidity_score: number;
  mesh_health: number;
  anomaly_score: number;
  active_nodes: number;
  gpu_util_avg: number;
  gpu_temp_max: number;
  gpu_power_total_w: number;
  fpga_queue_depth: number;
  memory_spine_gb: number;
  layer_states: Record<string, string>;
}

interface ProbeResult {
  probed: boolean;
  recommended_interface: Transport;
  hal_mode: HalMode;
  interfaces: Record<string, {
    available: boolean;
    latency_ms: number;
    latency_class: string;
    detail: string;
    error?: string;
  }>;
}

interface GovernanceLog {
  ts: number;
  action: string;
  target: string;
  result: "ok" | "error" | "pending";
}

// ══════════════════════════════════════════════════════════════════════════════
// Constants
// ══════════════════════════════════════════════════════════════════════════════

const BRIDGE_URL = "http://localhost:8765";
const TRANSPORT_COLORS: Record<Transport, string> = {
  PCIe:     "text-purple-400",
  Ethernet: "text-blue-400",
  Serial:   "text-yellow-400",
  SIM:      "text-gray-400",
  NONE:     "text-red-500",
};
const TRANSPORT_BG: Record<Transport, string> = {
  PCIe:     "bg-purple-500/20 border-purple-500/40",
  Ethernet: "bg-blue-500/20 border-blue-500/40",
  Serial:   "bg-yellow-500/20 border-yellow-500/40",
  SIM:      "bg-gray-500/20 border-gray-500/40",
  NONE:     "bg-red-500/20 border-red-500/40",
};

const NODE_HEALTH_COLOR = {
  nominal:  "bg-emerald-500",
  degraded: "bg-yellow-500",
  halted:   "bg-red-600",
  isolated: "bg-orange-500",
};

// ══════════════════════════════════════════════════════════════════════════════
// Hook: useBridge
// ══════════════════════════════════════════════════════════════════════════════

function useBridge(bridgeUrl: string) {
  const [status,    setStatus]    = useState<BridgeStatus>("disconnected");
  const [transport, setTransport] = useState<Transport>("NONE");
  const [halMode,   setHalMode]   = useState<HalMode>("sim");
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const [nodes,     setNodes]     = useState<NodeHealth[]>([]);
  const [gpus,      setGpus]      = useState<GPUMetric[]>([]);
  const [probe,     setProbe]     = useState<ProbeResult | null>(null);
  const [govLog,    setGovLog]    = useState<GovernanceLog[]>([]);

  const sseRef = useRef<EventSource | null>(null);

  // ── Fetch helpers ──────────────────────────────────────────────────────────
  const apiFetch = useCallback(async (path: string, opts?: RequestInit) => {
    const resp = await fetch(`${bridgeUrl}${path}`, {
      ...opts,
      headers: { "Content-Type": "application/json", ...(opts?.headers ?? {}) },
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }, [bridgeUrl]);

  // ── Connect ────────────────────────────────────────────────────────────────
  const connect = useCallback(async () => {
    setStatus("connecting");
    try {
      // 1. Health check
      const health = await apiFetch("/health");
      if (!health.ok) throw new Error("Bridge health check failed");

      // 2. Probe
      const p: ProbeResult = await apiFetch("/probe");
      setProbe(p);
      setTransport((p.recommended_interface as Transport) || "SIM");
      setHalMode(p.hal_mode || "sim");

      // 3. Initial status
      const st = await apiFetch("/status");
      if (st.gpus) setGpus(st.gpus);

      // 4. Nodes
      const nd = await apiFetch("/nodes");
      if (nd.nodes) setNodes(nd.nodes);

      // 5. Start SSE telemetry stream
      if (sseRef.current) sseRef.current.close();
      const sse = new EventSource(`${bridgeUrl}/events`);
      sse.onmessage = (e) => {
        try {
          const t: Telemetry = JSON.parse(e.data);
          setTelemetry(t);
        } catch {}
      };
      sse.onerror = () => setStatus("error");
      sseRef.current = sse;

      setStatus("connected");
    } catch (err) {
      console.warn("Bridge connect failed:", err);
      setStatus("error");
    }
  }, [apiFetch, bridgeUrl]);

  const disconnect = useCallback(() => {
    sseRef.current?.close();
    sseRef.current = null;
    setStatus("disconnected");
    setTelemetry(null);
  }, []);

  // ── Governance actions ─────────────────────────────────────────────────────
  const govAction = useCallback(async (
    label: string,
    path: string,
    body: Record<string, unknown>
  ) => {
    const entry: GovernanceLog = {
      ts: Date.now(), action: label, target: String(body.node_id ?? body.gpu_index ?? "all"),
      result: "pending"
    };
    setGovLog(prev => [entry, ...prev.slice(0, 49)]);

    try {
      await apiFetch(path, { method: "POST", body: JSON.stringify(body) });
      setGovLog(prev => prev.map(e => e === entry ? { ...e, result: "ok" } : e));
      // Refresh nodes after governance
      const nd = await apiFetch("/nodes");
      if (nd.nodes) setNodes(nd.nodes);
    } catch (err) {
      setGovLog(prev => prev.map(e => e === entry ? { ...e, result: "error" } : e));
    }
  }, [apiFetch]);

  const haltAgent   = (nodeId: string) =>
    govAction(`Halt ${nodeId}`,        "/halt_agent",    { node_id: nodeId });
  const haltAll     = () =>
    govAction("Halt ALL",              "/halt_all",      { reason: "dashboard" });
  const throttle    = (nodeId: string, score: number) =>
    govAction(`Throttle ${nodeId}`,    "/throttle_agent",{ node_id: nodeId, anomaly_score: score });
  const isolate     = (nodeId: string) =>
    govAction(`Isolate ${nodeId}`,     "/isolate_agent", { node_id: nodeId, duration_s: 60 });
  const resetGpu    = (idx: number) =>
    govAction(`Reset GPU${idx}`,       "/reset_gpu",     { gpu_index: idx });

  return {
    status, transport, halMode, telemetry, nodes, gpus, probe, govLog,
    connect, disconnect, haltAgent, haltAll, throttle, isolate, resetGpu,
  };
}

// ══════════════════════════════════════════════════════════════════════════════
// Sub-components
// ══════════════════════════════════════════════════════════════════════════════

/* ── StatusBadge ── */
function StatusBadge({ status }: { status: BridgeStatus }) {
  const cfg = {
    disconnected: { dot: "bg-gray-500", text: "text-gray-400",   label: "Disconnected" },
    connecting:   { dot: "bg-yellow-400 animate-pulse", text: "text-yellow-300", label: "Connecting…" },
    connected:    { dot: "bg-emerald-400", text: "text-emerald-300", label: "Connected" },
    error:        { dot: "bg-red-500 animate-pulse", text: "text-red-400", label: "Error" },
  }[status];
  return (
    <span className={`flex items-center gap-1.5 text-sm font-medium ${cfg.text}`}>
      <span className={`w-2 h-2 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  );
}

/* ── TransportBadge ── */
function TransportBadge({ transport }: { transport: Transport }) {
  const tierLabels: Record<Transport, string> = {
    PCIe:     "Tier 1 · PCIe DMA",
    Ethernet: "Tier 2 · Ethernet BMC",
    Serial:   "Tier 3 · UART Serial",
    SIM:      "Tier 4 · Simulation",
    NONE:     "No transport",
  };
  return (
    <span className={`px-2 py-0.5 rounded border text-xs font-mono ${TRANSPORT_BG[transport]} ${TRANSPORT_COLORS[transport]}`}>
      {tierLabels[transport]}
    </span>
  );
}

/* ── MetricCard ── */
function MetricCard({
  label, value, unit, color = "text-white", sub,
}: {
  label: string; value: string | number; unit?: string;
  color?: string; sub?: string;
}) {
  return (
    <div className="bg-gray-900/60 border border-gray-700/50 rounded-lg p-3 flex flex-col gap-1">
      <div className="text-xs text-gray-500 uppercase tracking-wide">{label}</div>
      <div className={`text-xl font-bold font-mono ${color}`}>
        {value}<span className="text-sm font-normal text-gray-400 ml-1">{unit}</span>
      </div>
      {sub && <div className="text-xs text-gray-500">{sub}</div>}
    </div>
  );
}

/* ── GaugeBar ── */
function GaugeBar({
  value, max = 100, color = "bg-blue-500", label, showPct = true,
}: {
  value: number; max?: number; color?: string; label: string; showPct?: boolean;
}) {
  const pct = Math.min(100, (value / max) * 100);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-xs text-gray-400">
        <span>{label}</span>
        <span>{showPct ? `${pct.toFixed(0)}%` : value.toFixed(1)}</span>
      </div>
      <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all duration-500`}
             style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/* ── GPUCard ── */
function GPUCard({ gpu }: { gpu: GPUMetric }) {
  const tempColor = gpu.temp_c > 80 ? "text-red-400" : gpu.temp_c > 70 ? "text-yellow-400" : "text-emerald-400";
  const memPct    = (gpu.mem_used_mb / gpu.mem_total_mb) * 100;

  return (
    <div className="bg-gray-900/60 border border-gray-700/50 rounded-lg p-3 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold text-gray-300">GPU {gpu.index}</span>
        <span className={`text-xs font-mono ${tempColor}`}>{gpu.temp_c}°C</span>
      </div>
      <GaugeBar value={gpu.util_pct} label="Util" color="bg-violet-500" />
      <GaugeBar value={memPct}       label="VRAM" color="bg-blue-500" />
      <div className="text-xs text-gray-500 text-right font-mono">{gpu.power_w.toFixed(0)} W</div>
    </div>
  );
}

/* ── NodeGrid ── */
function NodeGrid({
  nodes, onHalt, onIsolate,
}: {
  nodes: NodeHealth[];
  onHalt: (id: string) => void;
  onIsolate: (id: string) => void;
}) {
  const prime    = nodes.filter(n => n.role === "prime");
  const clusters = nodes.filter(n => n.role === "cluster");
  const workers  = nodes.filter(n => n.role === "worker");

  return (
    <div className="flex flex-col gap-3">
      {/* PRIME */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-500 w-14 shrink-0">PRIME</span>
        {prime.map(n => (
          <button key={n.id}
            title={`${n.id} — ${n.health} (${n.util_pct.toFixed(0)}%)\nClick: halt`}
            onClick={() => onHalt(n.id)}
            className={`w-6 h-6 rounded text-xs font-bold text-white
              ${NODE_HEALTH_COLOR[n.health]} hover:opacity-80 transition-opacity`}>
            P
          </button>
        ))}
      </div>

      {/* Clusters C1-C8 */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-gray-500 w-14 shrink-0">CLUSTER</span>
        {clusters.map(n => (
          <button key={n.id}
            title={`${n.id} — ${n.health} (${n.util_pct.toFixed(0)}%)\nClick: halt`}
            onClick={() => onHalt(n.id)}
            className={`w-6 h-6 rounded text-xs font-bold text-white
              ${NODE_HEALTH_COLOR[n.health]} hover:opacity-80 transition-opacity`}>
            {n.id.replace("C", "")}
          </button>
        ))}
      </div>

      {/* Workers W001-W128 — tiny dots */}
      <div className="flex flex-col gap-1">
        <span className="text-xs text-gray-500">WORKERS ({workers.length})</span>
        <div className="flex flex-wrap gap-0.5">
          {workers.map(n => (
            <button key={n.id}
              title={`${n.id} — ${n.health} (${n.util_pct.toFixed(0)}%)\nClick: isolate`}
              onClick={() => onIsolate(n.id)}
              className={`w-2.5 h-2.5 rounded-sm ${NODE_HEALTH_COLOR[n.health]}
                hover:opacity-80 transition-opacity`} />
          ))}
        </div>
        <div className="flex gap-3 text-xs text-gray-600 mt-1">
          {(["nominal","degraded","halted","isolated"] as const).map(h => (
            <span key={h} className="flex items-center gap-1">
              <span className={`w-2 h-2 rounded-sm ${NODE_HEALTH_COLOR[h]}`} />
              {h}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── GovernancePanel ── */
function GovernancePanel({
  onHaltAll, onResetGpu, onThrottle, onHaltAgent,
}: {
  onHaltAll:   () => void;
  onResetGpu:  (idx: number) => void;
  onThrottle:  (node: string, score: number) => void;
  onHaltAgent: (node: string) => void;
}) {
  const [targetNode,  setTargetNode]  = useState("W001");
  const [anomScore,   setAnomScore]   = useState(0.75);
  const [confirmHalt, setConfirmHalt] = useState(false);

  return (
    <div className="flex flex-col gap-4">
      {/* Emergency Halt All */}
      <div className="bg-red-950/40 border border-red-700/40 rounded-lg p-3">
        <div className="text-xs text-red-400 mb-2 font-semibold uppercase tracking-wide">
          ⚠ Emergency Governance
        </div>
        {!confirmHalt ? (
          <button
            onClick={() => setConfirmHalt(true)}
            className="w-full py-2 bg-red-700/80 hover:bg-red-600 text-white rounded font-bold text-sm transition-colors">
            HALT ALL 137 NODES
          </button>
        ) : (
          <div className="flex gap-2">
            <button
              onClick={() => { onHaltAll(); setConfirmHalt(false); }}
              className="flex-1 py-2 bg-red-600 hover:bg-red-500 text-white rounded font-bold text-sm transition-colors">
              CONFIRM HALT ALL
            </button>
            <button
              onClick={() => setConfirmHalt(false)}
              className="flex-1 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded text-sm transition-colors">
              Cancel
            </button>
          </div>
        )}
      </div>

      {/* GPU Reset */}
      <div className="bg-gray-900/60 border border-gray-700/50 rounded-lg p-3">
        <div className="text-xs text-gray-400 mb-2 font-semibold uppercase tracking-wide">
          GPU Reset
        </div>
        <div className="flex gap-2">
          {[0, 1, 2, 3].map(i => (
            <button key={i}
              onClick={() => onResetGpu(i)}
              className="flex-1 py-1.5 bg-orange-800/60 hover:bg-orange-700 text-orange-200 rounded text-xs font-mono transition-colors">
              GPU {i}
            </button>
          ))}
        </div>
      </div>

      {/* Throttle / Halt agent */}
      <div className="bg-gray-900/60 border border-gray-700/50 rounded-lg p-3">
        <div className="text-xs text-gray-400 mb-2 font-semibold uppercase tracking-wide">
          Node Control
        </div>
        <div className="flex flex-col gap-2">
          <div className="flex gap-2 items-center">
            <label className="text-xs text-gray-500 w-12 shrink-0">Node</label>
            <input
              value={targetNode}
              onChange={e => setTargetNode(e.target.value)}
              className="flex-1 bg-gray-800 border border-gray-600 rounded px-2 py-1 text-xs font-mono text-gray-200 focus:outline-none focus:border-blue-500"
              placeholder="W001, C3, PRIME"
            />
          </div>
          <div className="flex gap-2 items-center">
            <label className="text-xs text-gray-500 w-12 shrink-0">Anomaly</label>
            <input
              type="range" min={0} max={1} step={0.01}
              value={anomScore}
              onChange={e => setAnomScore(Number(e.target.value))}
              className="flex-1 accent-yellow-400"
            />
            <span className="text-xs font-mono text-yellow-400 w-10 text-right">
              {anomScore.toFixed(2)}
            </span>
          </div>
          <div className="text-xs text-gray-600 text-right">
            → clock: {anomScore < 0.30 ? 2520 : anomScore < 0.60 ? 1890 : anomScore < 0.80 ? 1260 : anomScore < 0.95 ? 630 : 735} MHz
          </div>
          <div className="flex gap-2 mt-1">
            <button
              onClick={() => onThrottle(targetNode, anomScore)}
              className="flex-1 py-1.5 bg-yellow-800/60 hover:bg-yellow-700 text-yellow-200 rounded text-xs transition-colors">
              Throttle
            </button>
            <button
              onClick={() => onHaltAgent(targetNode)}
              className="flex-1 py-1.5 bg-red-900/60 hover:bg-red-800 text-red-200 rounded text-xs transition-colors">
              Halt Node
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── ConnectionWizard ── */
function ConnectionWizard({ onConnect }: { onConnect: () => void }) {
  const [bridgeUrlInput, setBridgeUrlInput] = useState(BRIDGE_URL);
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState<"ok" | "fail" | null>(null);

  const checkBridge = async () => {
    setChecking(true);
    setCheckResult(null);
    try {
      const r = await fetch(`${bridgeUrlInput}/health`, { signal: AbortSignal.timeout(3000) });
      setCheckResult(r.ok ? "ok" : "fail");
    } catch {
      setCheckResult("fail");
    }
    setChecking(false);
  };

  return (
    <div className="flex flex-col items-center justify-center h-full gap-6 py-10">
      <div className="text-center">
        <div className="text-4xl mb-3">🔌</div>
        <div className="text-lg font-bold text-white">Connect to Sovereign v2.1</div>
        <div className="text-sm text-gray-400 mt-1">
          Start Lucy Bridge Service then connect here
        </div>
      </div>

      <div className="bg-gray-900/80 border border-gray-700/50 rounded-xl p-5 w-full max-w-md flex flex-col gap-4">
        <div>
          <label className="text-xs text-gray-400 block mb-1">Bridge Service URL</label>
          <input
            value={bridgeUrlInput}
            onChange={e => setBridgeUrlInput(e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-gray-200 focus:outline-none focus:border-blue-500"
          />
        </div>

        <div className="bg-gray-800/60 rounded-lg p-3 text-xs text-gray-400 font-mono">
          <div className="text-gray-500 mb-1">Start bridge service:</div>
          <div className="text-green-400">python lucy_bridge_service.py --mode auto</div>
        </div>

        <div className="flex gap-2">
          <button
            onClick={checkBridge}
            disabled={checking}
            className="flex-1 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded text-sm transition-colors disabled:opacity-50">
            {checking ? "Checking…" : "Test Connection"}
          </button>
          <button
            onClick={onConnect}
            className="flex-1 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm font-semibold transition-colors">
            Connect
          </button>
        </div>

        {checkResult === "ok" && (
          <div className="text-xs text-emerald-400 text-center">
            ✓ Bridge service is reachable
          </div>
        )}
        {checkResult === "fail" && (
          <div className="text-xs text-red-400 text-center">
            ✗ Could not reach bridge service — is it running?
          </div>
        )}
      </div>

      <div className="text-xs text-gray-600 text-center max-w-sm">
        Transport priority: PCIe (native DMA) → Ethernet (BMC Redfish) → USB → Serial → SIM
      </div>
    </div>
  );
}

/* ── GovernanceLog ── */
function GovernanceLogPanel({ log: govLog }: { log: GovernanceLog[] }) {
  return (
    <div className="flex flex-col gap-1 max-h-40 overflow-y-auto">
      {govLog.length === 0 && (
        <div className="text-xs text-gray-600 text-center py-4">No governance actions yet</div>
      )}
      {govLog.map((entry, i) => (
        <div key={i} className="flex items-center gap-2 text-xs font-mono py-0.5">
          <span className={
            entry.result === "ok" ? "text-emerald-400" :
            entry.result === "error" ? "text-red-400" : "text-yellow-400"
          }>
            {entry.result === "ok" ? "✓" : entry.result === "error" ? "✗" : "⟳"}
          </span>
          <span className="text-gray-500">{new Date(entry.ts).toLocaleTimeString()}</span>
          <span className="text-gray-300">{entry.action}</span>
          <span className="text-gray-500">→ {entry.target}</span>
        </div>
      ))}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Main component
// ══════════════════════════════════════════════════════════════════════════════

type Tab = "telemetry" | "nodes" | "gpus" | "governance" | "probe";

export default function HardwareBridgePanel() {
  const bridge = useBridge(BRIDGE_URL);
  const [tab, setTab] = useState<Tab>("telemetry");

  const tabs: { id: Tab; label: string }[] = [
    { id: "telemetry",  label: "Telemetry"  },
    { id: "nodes",      label: "Nodes"      },
    { id: "gpus",       label: "GPUs"       },
    { id: "governance", label: "Governance" },
    { id: "probe",      label: "Probe"      },
  ];

  // ── Synthetic telemetry when not connected ────────────────────────────────
  const tele: Telemetry = bridge.telemetry ?? {
    timestamp: Date.now() / 1000,
    mode: "disconnected",
    lucidity_score: 0,
    mesh_health: 0,
    anomaly_score: 0,
    active_nodes: 0,
    gpu_util_avg: 0,
    gpu_temp_max: 0,
    gpu_power_total_w: 0,
    fpga_queue_depth: 0,
    memory_spine_gb: 0,
    layer_states: {},
  };

  return (
    <div className="flex flex-col h-full bg-gray-950 text-gray-100 rounded-xl overflow-hidden">

      {/* ── Header ── */}
      <div className="flex items-center justify-between px-4 py-3 bg-gray-900/80 border-b border-gray-800">
        <div className="flex items-center gap-3">
          <span className="text-lg">🧠</span>
          <div>
            <div className="text-sm font-bold text-white">Sovereign v2.1 Bridge</div>
            <div className="text-xs text-gray-500">137-node Hyperswarm Neural Mesh</div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <TransportBadge transport={bridge.transport} />
          <StatusBadge status={bridge.status} />
          {bridge.status === "connected" ? (
            <button
              onClick={bridge.disconnect}
              className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs text-gray-300 transition-colors">
              Disconnect
            </button>
          ) : (
            <button
              onClick={bridge.connect}
              disabled={bridge.status === "connecting"}
              className="px-3 py-1 bg-blue-600 hover:bg-blue-500 rounded text-xs text-white font-semibold transition-colors disabled:opacity-50">
              {bridge.status === "connecting" ? "Connecting…" : "Connect"}
            </button>
          )}
        </div>
      </div>

      {/* ── Show wizard if not connected and no telemetry ── */}
      {bridge.status === "disconnected" ? (
        <ConnectionWizard onConnect={bridge.connect} />
      ) : (
        <>
          {/* ── Tab bar ── */}
          <div className="flex border-b border-gray-800 px-4 gap-1 pt-2">
            {tabs.map(t => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`px-3 py-1.5 text-xs font-medium rounded-t transition-colors
                  ${tab === t.id
                    ? "bg-gray-800 text-white border-b-2 border-blue-500"
                    : "text-gray-500 hover:text-gray-300"}`}>
                {t.label}
              </button>
            ))}
          </div>

          {/* ── Tab content ── */}
          <div className="flex-1 overflow-y-auto p-4">

            {/* TELEMETRY */}
            {tab === "telemetry" && (
              <div className="flex flex-col gap-4">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <MetricCard
                    label="Lucidity"
                    value={(tele.lucidity_score * 100).toFixed(1)}
                    unit="%"
                    color={tele.lucidity_score > 0.8 ? "text-emerald-400" : "text-yellow-400"}
                  />
                  <MetricCard
                    label="Mesh Health"
                    value={tele.mesh_health.toFixed(1)}
                    unit="%"
                    color="text-blue-400"
                  />
                  <MetricCard
                    label="Anomaly Score"
                    value={tele.anomaly_score.toFixed(3)}
                    color={tele.anomaly_score > 0.6 ? "text-red-400" : "text-gray-300"}
                    sub={`→ ${
                      tele.anomaly_score < 0.30 ? "2520" :
                      tele.anomaly_score < 0.60 ? "1890" :
                      tele.anomaly_score < 0.80 ? "1260" :
                      tele.anomaly_score < 0.95 ? "630" : "735"
                    } MHz`}
                  />
                  <MetricCard
                    label="Active Nodes"
                    value={tele.active_nodes}
                    unit="/ 137"
                    color="text-purple-400"
                  />
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  <MetricCard label="GPU Util Avg"    value={tele.gpu_util_avg.toFixed(1)}      unit="%" />
                  <MetricCard label="GPU Temp Max"    value={tele.gpu_temp_max.toFixed(1)}      unit="°C"
                    color={tele.gpu_temp_max > 80 ? "text-red-400" : "text-gray-200"} />
                  <MetricCard label="GPU Power Total" value={tele.gpu_power_total_w.toFixed(0)} unit="W" />
                  <MetricCard label="FPGA Queue"      value={tele.fpga_queue_depth}             unit="cmds" />
                  <MetricCard label="Memory Spine"    value={tele.memory_spine_gb.toFixed(2)}  unit="GB" />
                  <MetricCard label="HAL Mode"        value={tele.mode}                        color="text-gray-400" />
                </div>

                {/* Layer states */}
                {Object.keys(tele.layer_states).length > 0 && (
                  <div className="bg-gray-900/60 border border-gray-700/50 rounded-lg p-3">
                    <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">
                      Layer States
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                      {Object.entries(tele.layer_states).map(([layer, state]) => (
                        <div key={layer} className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${
                            state === "active" ? "bg-emerald-400" : "bg-yellow-400"
                          }`} />
                          <span className="text-xs text-gray-400 capitalize">
                            {layer.replace(/_/g, " ")}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* NODES */}
            {tab === "nodes" && (
              <div className="flex flex-col gap-4">
                <div className="text-xs text-gray-500">
                  Click PRIME/cluster node to halt · Click worker dot to isolate
                </div>
                {bridge.nodes.length > 0 ? (
                  <NodeGrid
                    nodes={bridge.nodes}
                    onHalt={bridge.haltAgent}
                    onIsolate={bridge.isolate}
                  />
                ) : (
                  <div className="text-xs text-gray-600 text-center py-8">
                    Loading node topology…
                  </div>
                )}
              </div>
            )}

            {/* GPUs */}
            {tab === "gpus" && (
              <div className="flex flex-col gap-4">
                <div className="grid grid-cols-2 gap-3">
                  {bridge.gpus.length > 0 ? (
                    bridge.gpus.map(g => <GPUCard key={g.index} gpu={g} />)
                  ) : (
                    [0, 1, 2, 3].map(i => (
                      <div key={i} className="bg-gray-900/60 border border-gray-700/50 rounded-lg p-3">
                        <div className="text-xs text-gray-600">GPU {i} — no data</div>
                      </div>
                    ))
                  )}
                </div>
                <div className="bg-gray-900/60 border border-gray-700/50 rounded-lg p-3 text-xs text-gray-500">
                  <div className="grid grid-cols-2 gap-1 font-mono">
                    <div>Bus IDs:</div><div></div>
                    <div>GPU 0:</div><div className="text-gray-400">0000:01:00.0</div>
                    <div>GPU 1:</div><div className="text-gray-400">0000:41:00.0</div>
                    <div>GPU 2:</div><div className="text-gray-400">0000:81:00.0</div>
                    <div>GPU 3:</div><div className="text-gray-400">0000:C1:00.0</div>
                  </div>
                </div>
              </div>
            )}

            {/* GOVERNANCE */}
            {tab === "governance" && (
              <div className="flex flex-col gap-4">
                <GovernancePanel
                  onHaltAll={bridge.haltAll}
                  onResetGpu={bridge.resetGpu}
                  onThrottle={bridge.throttle}
                  onHaltAgent={bridge.haltAgent}
                />
                <div className="bg-gray-900/60 border border-gray-700/50 rounded-lg p-3">
                  <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">
                    Governance Log
                  </div>
                  <GovernanceLogPanel log={bridge.govLog} />
                </div>
              </div>
            )}

            {/* PROBE */}
            {tab === "probe" && (
              <div className="flex flex-col gap-3">
                {bridge.probe ? (
                  <>
                    <div className="flex items-center gap-3 mb-1">
                      <span className="text-sm text-gray-400">Recommended:</span>
                      <TransportBadge transport={bridge.probe.recommended_interface as Transport} />
                      <span className="text-xs font-mono text-gray-500">
                        mode={bridge.probe.hal_mode}
                      </span>
                    </div>
                    {Object.entries(bridge.probe.interfaces).map(([name, info]) => (
                      <div key={name}
                        className="bg-gray-900/60 border border-gray-700/50 rounded-lg p-3 flex items-start justify-between gap-3">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className={`w-2 h-2 rounded-full ${
                              info.available ? "bg-emerald-400" : "bg-gray-600"
                            }`} />
                            <span className="text-sm font-medium text-gray-300">{name}</span>
                            <span className="text-xs text-gray-600">{info.latency_class}</span>
                          </div>
                          {info.detail && (
                            <div className="text-xs text-gray-500 mt-1 ml-4">{info.detail}</div>
                          )}
                          {info.error && (
                            <div className="text-xs text-red-500 mt-1 ml-4">{info.error}</div>
                          )}
                        </div>
                        <div className="text-xs font-mono text-gray-400 shrink-0">
                          {info.available ? `${info.latency_ms.toFixed(1)} ms` : "—"}
                        </div>
                      </div>
                    ))}
                  </>
                ) : (
                  <div className="text-xs text-gray-600 text-center py-8">
                    Connect to view probe results
                  </div>
                )}
              </div>
            )}

          </div>

          {/* ── Footer: last update ── */}
          <div className="px-4 py-2 bg-gray-900/60 border-t border-gray-800 flex items-center justify-between text-xs text-gray-600">
            <span>
              Bridge: <span className="font-mono text-gray-500">{BRIDGE_URL}</span>
            </span>
            <span>
              {bridge.telemetry
                ? `Updated ${new Date(tele.timestamp * 1000).toLocaleTimeString()}`
                : "No data"}
            </span>
          </div>
        </>
      )}
    </div>
  );
}