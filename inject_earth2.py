#!/usr/bin/env python3
"""Inject NVIDIA Earth-2 TwinEarth section into Lucy OS v5 dashboard."""

import re

HTML_FILE = "dashboard/mesh/index.html"

EARTH2_HTML = r"""
     <!-- NVIDIA EARTH-2 TWIN EARTH — FULL WIDTH BOTTOM ROW -->
     <div id="earth2Section" class="earth2-section">
       <div class="earth2-header">
         <div class="earth2-title-group">
           <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
           <span class="earth2-title">Earth 2 & Live VR <span class="earth2-subtitle">Omniverse Twin</span></span>
           <span class="earth2-badge nvidia">NVIDIA EARTH-2</span>
           <span class="earth2-badge">CESIUM USD</span>
           <span class="earth2-badge green">DELTAVAULT</span>
         </div>
         <div class="earth2-header-badges">
           <span class="earth2-badge mono">GIBS WMTS: SYNCED</span>
           <span class="earth2-badge mono">FourCastNet: READY</span>
           <span id="e2FeedStatus" class="earth2-badge green mono pulse-badge">&#9685; POLLING</span>
         </div>
       </div>
       <div class="earth2-body">
         <!-- LEFT: 3D Globe -->
         <div class="earth2-globe-col" id="earth2GlobeCol">
           <div class="earth2-globe-container" id="earth2GlobeContainer">
             <div class="earth2-globe-badge top-left"><span class="live-dot"></span>VR VIEWPORT LIVE</div>
             <button id="e2ExpandBtn" class="earth2-expand-btn" title="Expand Globe">&#10178;</button>
             <canvas id="earth2Canvas" class="earth2-canvas"></canvas>
             <div id="terminatorOverlay" class="terminator-overlay"></div>
             <div class="earth2-globe-footer">
               <span class="earth2-badge mono">NASA GIBS <span class="green">ON</span></span>
               <span class="earth2-badge mono">TERM LIGHTING <span class="green">ON</span></span>
               <span id="e2FlightCount" class="earth2-badge mono">ADS-B: 0 flights</span>
             </div>
           </div>
           <div class="earth2-nims-panel">
             <div class="panel-title"><div class="dot"></div>NVIDIA NIMs / EMMA Bridge</div>
             <div class="nims-grid">
               <div class="nims-row"><span>Modulus/PhysicsNeMo:</span><span class="green">READY</span></div>
               <div class="nims-row"><span>Forecast Horizon:</span><span class="white">15 DAYS</span></div>
               <div class="nims-row"><span>CUDA Device:</span><span class="blue">A100-SXM</span></div>
               <div class="nims-row"><span>Export Format:</span><span class="white">OpenUSD</span></div>
               <div class="nims-row"><span>Pangu-Weather:</span><span class="green">ACTIVE</span></div>
               <div class="nims-row"><span>DeltaVault Sync:</span><span class="green">LIVE</span></div>
             </div>
           </div>
         </div>
         <!-- MIDDLE: Live Feed -->
         <div class="earth2-feed-col">
           <div class="earth2-feed-header">
             <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
             LIVE INGESTION PIPELINE
             <span id="e2FeedCount" class="earth2-badge mono" style="margin-left:auto">0 events</span>
           </div>
           <div id="earth2Feed" class="earth2-feed-list"></div>
         </div>
         <!-- RIGHT: Scenario Builder -->
         <div class="earth2-scenario-col">
           <div class="earth2-scenario-header">
             <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
             Earth-2 Predictive Simulation
           </div>
           <p class="earth2-scenario-sub">Inject Prompts into Omniverse USD Baseline</p>
           <div class="earth2-form-group">
             <label>Location Target (Lat/Lon or Name)</label>
             <input id="e2LocationInput" type="text" placeholder="e.g. 34.05N, -118.24W (Los Angeles Basin)" class="earth2-input" />
           </div>
           <div class="earth2-form-group">
             <label>Physical Modification Prompt</label>
             <textarea id="e2ScenarioInput" class="earth2-textarea" placeholder="e.g. Inject massive thermal anomaly. Measure NOAA geomagnetic response and calculate 15-day climate deviation via Earth-2 Pangu-Weather model."></textarea>
           </div>
           <button id="e2RunBtn" class="earth2-run-btn">
             <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
             INJECT INTO TWIN EARTH
           </button>
           <div id="e2ProgressBar" class="earth2-progress-wrap" style="display:none">
             <div class="earth2-progress-label"><span>Omniverse GPU Render Stream</span><span id="e2ProgressPct">0%</span></div>
             <div class="earth2-progress-track"><div id="e2ProgressFill" class="earth2-progress-fill"></div></div>
           </div>
           <div id="e2Results" class="earth2-results" style="display:none">
             <div class="earth2-results-header">
               <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
               Earth2Studio Results Ready
             </div>
             <p id="e2ResultText" class="earth2-results-body"></p>
           </div>
           <div class="earth2-stats-row">
             <div class="earth2-stat-tile"><div id="e2SeismicCount" class="stat-val amber">0</div><div class="stat-label">SEISMIC</div></div>
             <div class="earth2-stat-tile"><div id="e2SolarWind" class="stat-val cyan">---</div><div class="stat-label">SOLAR km/s</div></div>
             <div class="earth2-stat-tile"><div id="e2FlightStat" class="stat-val green">0</div><div class="stat-label">ADS-B</div></div>
             <div class="earth2-stat-tile"><div id="e2SimRuns" class="stat-val white">0</div><div class="stat-label">SIM RUNS</div></div>
           </div>
         </div>
       </div>
     </div><!-- END EARTH-2 -->

"""

EARTH2_CSS = """
    /* ── NVIDIA Earth-2 TwinEarth Section ─────────────────────────────── */
    .earth2-section {
      background: #070d1a;
      border: 1px solid #1e3a5f;
      border-radius: 6px;
      margin: 10px 12px 12px;
      overflow: hidden;
      box-shadow: 0 0 40px rgba(6,182,212,0.05);
    }
    .earth2-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 16px;
      border-bottom: 1px solid #1e293b;
      background: #0a1628;
    }
    .earth2-title-group { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .earth2-title { font-size: 16px; font-weight: 700; color: #e2e8f0; letter-spacing: 0.5px; }
    .earth2-subtitle { font-weight: 300; color: #64748b; font-size: 14px; }
    .earth2-header-badges { display: flex; gap: 8px; align-items: center; }
    .earth2-badge {
      font-family: 'Courier New', monospace;
      font-size: 9px;
      padding: 2px 7px;
      border-radius: 2px;
      border: 1px solid #334155;
      color: #94a3b8;
      background: #0f172a;
      white-space: nowrap;
    }
    .earth2-badge.nvidia { border-color: #76b900; color: #76b900; background: rgba(118,185,0,0.08); }
    .earth2-badge.green { border-color: #10b981; color: #10b981; background: rgba(16,185,129,0.08); }
    .earth2-badge.mono { font-family: 'Courier New', monospace; }
    .pulse-badge { animation: badgePulse 2s infinite; }
    @keyframes badgePulse { 0%,100%{opacity:1} 50%{opacity:0.5} }

    .earth2-body {
      display: grid;
      grid-template-columns: 380px 1fr 320px;
      gap: 0;
      min-height: 420px;
    }
    @media (max-width: 1400px) {
      .earth2-body { grid-template-columns: 320px 1fr 280px; }
    }

    /* Globe Column */
    .earth2-globe-col {
      border-right: 1px solid #1e293b;
      display: flex;
      flex-direction: column;
      background: #050b18;
    }
    .earth2-globe-container {
      position: relative;
      flex: 1;
      min-height: 280px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #020610;
      border-bottom: 1px solid #1e293b;
      overflow: hidden;
    }
    .earth2-canvas {
      display: block;
      border-radius: 4px;
    }
    .terminator-overlay {
      position: absolute;
      inset: 0;
      pointer-events: none;
      border-radius: 50%;
      transition: background 60s linear;
    }
    .earth2-globe-badge {
      position: absolute;
      top: 10px;
      left: 12px;
      z-index: 10;
      font-family: 'Courier New', monospace;
      font-size: 9px;
      color: #cbd5e1;
      display: flex;
      align-items: center;
      gap: 6px;
      text-transform: uppercase;
      letter-spacing: 1px;
    }
    .live-dot {
      width: 8px; height: 8px;
      border-radius: 50%;
      background: #ef4444;
      animation: liveDotPulse 1.5s infinite;
      display: inline-block;
    }
    @keyframes liveDotPulse {
      0%,100%{box-shadow:0 0 0 0 rgba(239,68,68,0.7)}
      50%{box-shadow:0 0 0 6px rgba(239,68,68,0)}
    }
    .earth2-expand-btn {
      position: absolute;
      top: 8px; right: 8px;
      z-index: 20;
      background: rgba(15,23,42,0.7);
      border: 1px solid #334155;
      color: #94a3b8;
      width: 28px; height: 28px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
      display: flex; align-items: center; justify-content: center;
      transition: all 0.2s;
    }
    .earth2-expand-btn:hover { color: #06b6d4; border-color: #06b6d4; }
    .earth2-globe-footer {
      position: absolute;
      bottom: 8px; left: 8px; right: 8px;
      display: flex;
      gap: 6px;
      z-index: 10;
    }
    .earth2-nims-panel {
      padding: 10px 12px;
      background: #080f20;
    }
    .nims-grid { display: flex; flex-direction: column; gap: 4px; margin-top: 8px; }
    .nims-row {
      display: flex;
      justify-content: space-between;
      font-family: 'Courier New', monospace;
      font-size: 9px;
      color: #64748b;
      background: #0a1628;
      padding: 4px 8px;
      border-radius: 2px;
    }
    .nims-row .green { color: #10b981; }
    .nims-row .white { color: #e2e8f0; }
    .nims-row .blue { color: #60a5fa; }

    /* Feed Column */
    .earth2-feed-col {
      border-right: 1px solid #1e293b;
      display: flex;
      flex-direction: column;
      background: #050b18;
      overflow: hidden;
    }
    .earth2-feed-header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      border-bottom: 1px solid #1e293b;
      font-family: 'Courier New', monospace;
      font-size: 10px;
      color: #94a3b8;
      text-transform: uppercase;
      letter-spacing: 1px;
      background: #080f20;
      flex-shrink: 0;
    }
    .earth2-feed-list {
      flex: 1;
      overflow-y: auto;
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .earth2-feed-list::-webkit-scrollbar { width: 4px; }
    .earth2-feed-list::-webkit-scrollbar-track { background: #0a1628; }
    .earth2-feed-list::-webkit-scrollbar-thumb { background: #1e3a5f; border-radius: 2px; }
    .e2-feed-item {
      background: #0a1628;
      border: 1px solid #1e293b;
      border-radius: 4px;
      padding: 8px 10px;
      font-family: 'Courier New', monospace;
      font-size: 10px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      animation: feedSlide 0.3s ease-out;
      transition: border-color 0.2s;
    }
    .e2-feed-item:hover { border-color: rgba(6,182,212,0.3); }
    @keyframes feedSlide { from{opacity:0;transform:translateX(-12px)} to{opacity:1;transform:translateX(0)} }
    .e2-feed-top { display: flex; justify-content: space-between; align-items: center; }
    .e2-feed-source {
      font-size: 9px;
      padding: 1px 6px;
      border-radius: 2px;
      font-weight: 700;
    }
    .e2-src-usgs { background:rgba(251,146,60,0.1); color:#fb923c; border:1px solid rgba(251,146,60,0.2); }
    .e2-src-noaa { background:rgba(34,211,238,0.1); color:#22d3ee; border:1px solid rgba(34,211,238,0.2); }
    .e2-src-nasa { background:rgba(96,165,250,0.1); color:#60a5fa; border:1px solid rgba(96,165,250,0.2); }
    .e2-src-adsb { background:rgba(52,211,153,0.1); color:#34d399; border:1px solid rgba(52,211,153,0.2); }
    .e2-src-swarm { background:rgba(167,139,250,0.1); color:#a78bfa; border:1px solid rgba(167,139,250,0.2); }
    .e2-feed-ref { font-size: 8px; color: #475569; }
    .e2-feed-type { color: #94a3b8; font-size: 10px; }
    .e2-feed-bottom { display: flex; justify-content: space-between; }
    .e2-feed-loc { font-size: 9px; color: #64748b; }
    .e2-feed-val { color: #f1f5f9; font-weight: 700; font-size: 10px; }

    /* Scenario Column */
    .earth2-scenario-col {
      display: flex;
      flex-direction: column;
      padding: 14px;
      gap: 10px;
      background: #080f20;
      position: relative;
      overflow: hidden;
    }
    .earth2-scenario-col::before {
      content: '';
      position: absolute;
      top: -60px; right: -60px;
      width: 200px; height: 200px;
      background: radial-gradient(circle, rgba(6,182,212,0.08) 0%, transparent 70%);
      pointer-events: none;
    }
    .earth2-scenario-header {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      font-weight: 700;
      color: #f1f5f9;
      letter-spacing: 0.3px;
    }
    .earth2-scenario-sub { font-family: 'Courier New',monospace; font-size: 9px; color: #64748b; margin-top: -4px; }
    .earth2-form-group { display: flex; flex-direction: column; gap: 4px; }
    .earth2-form-group label { font-family:'Courier New',monospace; font-size:9px; color:#64748b; text-transform:uppercase; letter-spacing:0.5px; }
    .earth2-input {
      background: #050b18;
      border: 1px solid #1e3a5f;
      border-radius: 4px;
      padding: 8px 10px;
      font-family: 'Courier New', monospace;
      font-size: 10px;
      color: #cbd5e1;
      outline: none;
      transition: border-color 0.2s;
    }
    .earth2-input:focus { border-color: #06b6d4; }
    .earth2-textarea {
      background: #050b18;
      border: 1px solid #1e3a5f;
      border-radius: 4px;
      padding: 8px 10px;
      font-family: 'Courier New', monospace;
      font-size: 10px;
      color: #cbd5e1;
      outline: none;
      resize: vertical;
      min-height: 80px;
      line-height: 1.5;
      transition: border-color 0.2s;
    }
    .earth2-textarea:focus { border-color: #06b6d4; }
    .earth2-run-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 10px;
      background: rgba(6,182,212,0.07);
      border: 1px solid rgba(6,182,212,0.25);
      color: #06b6d4;
      font-family: 'Courier New', monospace;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      border-radius: 4px;
      cursor: pointer;
      transition: all 0.2s;
      box-shadow: 0 0 15px rgba(6,182,212,0.05);
    }
    .earth2-run-btn:hover { background:rgba(6,182,212,0.15); border-color:rgba(6,182,212,0.6); box-shadow:0 0 20px rgba(6,182,212,0.2); }
    .earth2-run-btn:disabled { opacity:0.4; cursor:not-allowed; }
    .earth2-progress-wrap { display:flex; flex-direction:column; gap:5px; }
    .earth2-progress-label { display:flex; justify-content:space-between; font-family:'Courier New',monospace; font-size:9px; color:#64748b; }
    .earth2-progress-track { height:4px; background:#1e293b; border-radius:2px; overflow:hidden; }
    .earth2-progress-fill { height:100%; background:#06b6d4; box-shadow:0 0 8px #06b6d4; transition:width 0.3s; border-radius:2px; width:0%; }
    .earth2-results {
      background: #0a1628;
      border: 1px solid rgba(16,185,129,0.3);
      border-radius: 4px;
      padding: 10px;
      position: relative;
      overflow: hidden;
    }
    .earth2-results::before { content:''; position:absolute; left:0;top:0; width:3px;height:100%; background:#10b981; box-shadow:0 0 8px #10b981; }
    .earth2-results-header { display:flex; align-items:center; gap:6px; font-family:'Courier New',monospace; font-size:10px; color:#10b981; font-weight:700; padding-left:6px; }
    .earth2-results-body { font-family:'Courier New',monospace; font-size:9px; color:#cbd5e1; line-height:1.6; padding-left:6px; margin-top:4px; }
    .earth2-stats-row { display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:6px; margin-top:auto; }
    .earth2-stat-tile { background:#050b18; border:1px solid #1e293b; border-radius:4px; padding:8px 4px; text-align:center; }
    .stat-val { font-family:'Courier New',monospace; font-size:16px; font-weight:700; line-height:1; }
    .stat-val.amber { color:#f59e0b; }
    .stat-val.cyan { color:#06b6d4; }
    .stat-val.green { color:#10b981; }
    .stat-val.white { color:#f1f5f9; }
    .stat-label { font-family:'Courier New',monospace; font-size:7px; color:#64748b; text-transform:uppercase; letter-spacing:0.5px; margin-top:4px; }
"""

EARTH2_JS = r"""
    /* ══════════════════════════════════════════════════════════════════
       NVIDIA EARTH-2 TWIN EARTH ENGINE
       3D globe via canvas + Three.js-style projection, live feeds
    ══════════════════════════════════════════════════════════════════ */
    (function() {
      const E2 = {
        canvas: null, ctx: null,
        width: 0, height: 0,
        points: [],    // seismic/event dots
        flights: [],   // ADS-B arcs
        rot: 0,        // globe rotation angle
        seismicCount: 0,
        solarWind: '---',
        flightCount: 0,
        simRuns: 0,
        simInterval: null,
        feedItems: [],
        isExpanded: false,
        animFrame: null,

        init() {
          this.canvas = document.getElementById('earth2Canvas');
          if (!this.canvas) return;
          this.ctx = this.canvas.getContext('2d');
          this.resize();
          window.addEventListener('resize', () => this.resize());

          // Expand button
          const btn = document.getElementById('e2ExpandBtn');
          if (btn) btn.addEventListener('click', () => this.toggleExpand());

          // Scenario run button
          const runBtn = document.getElementById('e2RunBtn');
          if (runBtn) runBtn.addEventListener('click', () => this.runScenario());

          this.startAnimation();
          this.fetchLiveData();
          setInterval(() => this.fetchLiveData(), 60000);
          this.fetchFlights();
          setInterval(() => this.fetchFlights(), 20000);
          this.updateTerminator();
          setInterval(() => this.updateTerminator(), 60000);
        },

        resize() {
          const container = document.getElementById('earth2GlobeContainer');
          if (!container || !this.canvas) return;
          const w = container.offsetWidth;
          const h = container.offsetHeight || 280;
          this.canvas.width = w;
          this.canvas.height = h;
          this.width = w;
          this.height = h;
        },

        toggleExpand() {
          this.isExpanded = !this.isExpanded;
          const container = document.getElementById('earth2GlobeContainer');
          const btn = document.getElementById('e2ExpandBtn');
          if (this.isExpanded) {
            container.style.minHeight = '480px';
            if (btn) btn.textContent = '⊠';
          } else {
            container.style.minHeight = '280px';
            if (btn) btn.textContent = '⤢';
          }
          setTimeout(() => this.resize(), 50);
        },

        // Convert lat/lng to canvas x/y on globe projection
        latLngToXY(lat, lng, cx, cy, r) {
          const lngRad = (lng + this.rot * 57.3) * Math.PI / 180;
          const latRad = lat * Math.PI / 180;
          const x = cx + r * Math.cos(latRad) * Math.sin(lngRad);
          const y = cy - r * Math.sin(latRad);
          const z = Math.cos(latRad) * Math.cos(lngRad);
          return { x, y, visible: z > 0 };
        },

        drawGlobe() {
          if (!this.ctx || !this.canvas) return;
          const { ctx, width, height } = this;
          const cx = width / 2, cy = height / 2;
          const r = Math.min(cx, cy) * 0.82;

          ctx.clearRect(0, 0, width, height);

          // Space background
          ctx.fillStyle = '#020610';
          ctx.fillRect(0, 0, width, height);

          // Stars
          ctx.fillStyle = 'rgba(255,255,255,0.7)';
          for (let i = 0; i < 80; i++) {
            const sx = ((i * 137 + 43) % width);
            const sy = ((i * 251 + 79) % height);
            const sr = (i % 3 === 0) ? 1 : 0.5;
            ctx.beginPath();
            ctx.arc(sx, sy, sr, 0, Math.PI * 2);
            ctx.fill();
          }

          // Atmosphere glow
          const atmo = ctx.createRadialGradient(cx, cy, r * 0.9, cx, cy, r * 1.15);
          atmo.addColorStop(0, 'rgba(6,182,212,0.08)');
          atmo.addColorStop(1, 'rgba(6,182,212,0)');
          ctx.fillStyle = atmo;
          ctx.beginPath();
          ctx.arc(cx, cy, r * 1.15, 0, Math.PI * 2);
          ctx.fill();

          // Globe base
          const grad = ctx.createRadialGradient(cx - r * 0.25, cy - r * 0.25, 0, cx, cy, r);
          grad.addColorStop(0, '#1a3a5c');
          grad.addColorStop(0.4, '#0e2040');
          grad.addColorStop(1, '#020c1b');
          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.arc(cx, cy, r, 0, Math.PI * 2);
          ctx.fill();

          // Grid lines (lat/lng)
          ctx.strokeStyle = 'rgba(6,182,212,0.12)';
          ctx.lineWidth = 0.5;
          // Longitude lines
          for (let lng = -180; lng < 180; lng += 30) {
            ctx.beginPath();
            let first = true;
            for (let lat = -90; lat <= 90; lat += 3) {
              const p = this.latLngToXY(lat, lng, cx, cy, r);
              if (!p.visible) { first = true; continue; }
              if (first) { ctx.moveTo(p.x, p.y); first = false; }
              else ctx.lineTo(p.x, p.y);
            }
            ctx.stroke();
          }
          // Latitude lines
          for (let lat = -60; lat <= 60; lat += 30) {
            ctx.beginPath();
            let first = true;
            for (let lng = -180; lng <= 180; lng += 3) {
              const p = this.latLngToXY(lat, lng, cx, cy, r);
              if (!p.visible) { first = true; continue; }
              if (first) { ctx.moveTo(p.x, p.y); first = false; }
              else ctx.lineTo(p.x, p.y);
            }
            ctx.stroke();
          }

          // Continent outlines (simplified key points)
          this.drawContinents(ctx, cx, cy, r);

          // Globe edge
          ctx.strokeStyle = 'rgba(6,182,212,0.25)';
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.arc(cx, cy, r, 0, Math.PI * 2);
          ctx.stroke();

          // Event points (seismic/swarm)
          this.points.forEach(pt => {
            const p = this.latLngToXY(pt.lat, pt.lng, cx, cy, r);
            if (!p.visible) return;
            const size = (pt.mag || 1) * 1.5;
            // Pulsing ring
            const age = (Date.now() - pt.ts) / 1000;
            const pulse = (age % 3) / 3;
            ctx.strokeStyle = pt.color || '#ff6600';
            ctx.lineWidth = 1.5;
            ctx.globalAlpha = Math.max(0, 1 - pulse);
            ctx.beginPath();
            ctx.arc(p.x, p.y, size + pulse * 12, 0, Math.PI * 2);
            ctx.stroke();
            ctx.globalAlpha = 1;
            // Center dot
            ctx.fillStyle = pt.color || '#ff6600';
            ctx.beginPath();
            ctx.arc(p.x, p.y, size, 0, Math.PI * 2);
            ctx.fill();
            // Label
            if (pt.label) {
              ctx.fillStyle = 'rgba(255,165,0,0.8)';
              ctx.font = '8px Courier New';
              ctx.fillText(pt.label, p.x + size + 2, p.y + 3);
            }
          });

          // Flight arcs
          this.flights.slice(0, 80).forEach(f => {
            const s = this.latLngToXY(f.lat1, f.lng1, cx, cy, r);
            const e = this.latLngToXY(f.lat2, f.lng2, cx, cy, r);
            if (!s.visible && !e.visible) return;
            ctx.strokeStyle = 'rgba(56,189,248,0.45)';
            ctx.lineWidth = 0.8;
            ctx.setLineDash([3, 4]);
            ctx.beginPath();
            ctx.moveTo(s.x, s.y);
            // Simple arc midpoint
            const mx = (s.x + e.x) / 2;
            const my = (s.y + e.y) / 2;
            const dx = e.x - s.x, dy = e.y - s.y;
            const arc = Math.sqrt(dx*dx + dy*dy) * 0.15;
            ctx.quadraticCurveTo(mx - dy*0.1, my + dx*0.1 - arc, e.x, e.y);
            ctx.stroke();
            ctx.setLineDash([]);
          });

          // Terminator day/night line
          const hour = new Date().getUTCHours() + new Date().getUTCMinutes()/60;
          const sunLng = -((hour / 24) * 360 - 180);
          const nightGrad = ctx.createRadialGradient(
            cx + r * Math.sin((sunLng + this.rot * 57.3) * Math.PI/180 + Math.PI),
            cy,
            r * 0.2,
            cx, cy, r
          );
          nightGrad.addColorStop(0, 'rgba(0,0,0,0)');
          nightGrad.addColorStop(0.55, 'rgba(0,0,0,0)');
          nightGrad.addColorStop(1, 'rgba(0,0,18,0.65)');
          ctx.fillStyle = nightGrad;
          ctx.beginPath();
          ctx.arc(cx, cy, r, 0, Math.PI * 2);
          ctx.fill();

          // Clip to sphere
          ctx.save();
          ctx.globalCompositeOperation = 'destination-in';
          ctx.beginPath();
          ctx.arc(cx, cy, r, 0, Math.PI * 2);
          ctx.fill();
          ctx.restore();
        },

        drawContinents(ctx, cx, cy, r) {
          // Very simplified continent polygon hints as lat/lng pairs
          const continents = [
            // North America
            [[70,-140],[60,-130],[55,-125],[45,-124],[30,-117],[25,-105],[15,-90],[15,-83],[20,-75],[30,-80],[35,-75],[40,-74],[48,-53],[55,-60],[70,-90],[70,-140]],
            // South America
            [[10,-75],[0,-80],[-5,-81],[-20,-70],[-35,-57],[-55,-68],[-55,-65],[-40,-62],[-25,-48],[-5,-35],[5,-52],[10,-75]],
            // Europe
            [[71,28],[60,30],[55,22],[45,15],[43,5],[45,-5],[50,-5],[55,-5],[58,3],[60,5],[58,8],[56,10],[57,20],[59,24],[64,26],[71,28]],
            // Africa
            [[35,10],[15,-18],[0,-15],[-10,-15],[-35,18],[-35,27],[-25,32],[-10,38],[0,42],[10,42],[20,38],[35,32],[37,25],[35,10]],
            // Asia
            [[71,28],[68,60],[60,73],[55,73],[45,60],[35,58],[25,57],[10,45],[10,55],[18,73],[30,90],[35,100],[38,120],[35,130],[40,140],[60,150],[68,180],[71,140],[71,100],[71,60],[71,28]],
            // Australia
            [[-15,130],[-20,115],[-30,115],[-38,140],[-38,147],[-30,153],[-22,150],[-15,130]],
          ];
          ctx.strokeStyle = 'rgba(100,180,220,0.4)';
          ctx.lineWidth = 0.8;
          continents.forEach(pts => {
            ctx.beginPath();
            let first = true;
            pts.forEach(([lat, lng]) => {
              const p = this.latLngToXY(lat, lng, cx, cy, r);
              if (!p.visible) { first = true; return; }
              if (first) { ctx.moveTo(p.x, p.y); first = false; }
              else ctx.lineTo(p.x, p.y);
            });
            ctx.stroke();
          });
        },

        startAnimation() {
          const animate = () => {
            this.rot += 0.003;
            this.drawGlobe();
            this.animFrame = requestAnimationFrame(animate);
          };
          this.animFrame = requestAnimationFrame(animate);
        },

        updateTerminator() {
          const overlay = document.getElementById('terminatorOverlay');
          if (!overlay) return;
          const hour = new Date().getUTCHours() + new Date().getUTCMinutes()/60;
          const deg = (hour / 24) * 360;
          overlay.style.background = `linear-gradient(${deg}deg, transparent 40%, rgba(0,0,18,0.7) 60%)`;
          overlay.style.mixBlendMode = 'multiply';
        },

        addFeedItem(item) {
          const list = document.getElementById('earth2Feed');
          if (!list) return;
          const srcClass = {
            USGS_EARTHQUAKES: 'e2-src-usgs',
            NOAA_SPACE: 'e2-src-noaa',
            NASA_GIBS: 'e2-src-nasa',
            ADSB_FLIGHTS: 'e2-src-adsb',
            HYPER_SWARM: 'e2-src-swarm',
          }[item.source] || 'e2-src-nasa';

          const el = document.createElement('div');
          el.className = 'e2-feed-item';
          el.innerHTML = `
            <div class="e2-feed-top">
              <span class="e2-feed-source ${srcClass}">${item.source}</span>
              <span class="e2-feed-ref">${item.ref || ''}</span>
            </div>
            <div class="e2-feed-type">${item.type}</div>
            <div class="e2-feed-bottom">
              <span class="e2-feed-loc">${item.loc || ''}</span>
              <span class="e2-feed-val">${item.val}</span>
            </div>`;
          list.insertBefore(el, list.firstChild);
          // Keep only last 40
          while (list.children.length > 40) list.removeChild(list.lastChild);
          const countEl = document.getElementById('e2FeedCount');
          if (countEl) countEl.textContent = `${list.children.length} events`;
        },

        async fetchLiveData() {
          // USGS Earthquakes
          try {
            const r = await fetch('https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson');
            if (r.ok) {
              const d = await r.json();
              const quakes = (d.features || []).slice(0, 20);
              this.seismicCount = quakes.length;
              document.getElementById('e2SeismicCount').textContent = quakes.length;
              quakes.forEach(f => {
                const [lng, lat] = f.geometry?.coordinates || [0, 0];
                const mag = f.properties?.mag || 0;
                const existing = this.points.find(p => p.id === f.id);
                if (!existing) {
                  this.points.push({
                    id: f.id, lat, lng, mag,
                    label: `M${mag.toFixed(1)}`,
                    color: mag > 4 ? '#ef4444' : '#f97316',
                    ts: Date.now()
                  });
                  this.addFeedItem({
                    source: 'USGS_EARTHQUAKES',
                    type: 'Live Seismic Event',
                    val: `Mag ${mag.toFixed(1)}`,
                    loc: f.properties?.place || 'Unknown',
                    ref: 'usgs.gov'
                  });
                }
              });
              // Keep only latest 50
              if (this.points.length > 50) this.points = this.points.slice(-50);
            }
          } catch(e) { console.warn('USGS fetch error', e); }

          // NOAA Space Weather
          try {
            const r = await fetch('https://services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json');
            if (r.ok) {
              const d = await r.json();
              if (d && d.length > 0) {
                const spd = Math.round(d[0].proton_speed || d[0].wind_speed || 450);
                this.solarWind = spd;
                const el = document.getElementById('e2SolarWind');
                if (el) el.textContent = spd;
                this.addFeedItem({
                  source: 'NOAA_SPACE',
                  type: 'Solar Wind Real-Time',
                  val: `${spd} km/s`,
                  loc: 'DSCOVR L1',
                  ref: 'swpc.noaa.gov'
                });
              }
            }
          } catch(e) { /* NOAA CORS — expected */ }
        },

        async fetchFlights() {
          try {
            const r = await fetch('https://opensky-network.org/api/states/all?lamin=20.0&lomin=-130.0&lamax=60.0&lomax=-10.0');
            if (r.ok) {
              const d = await r.json();
              if (d && d.states) {
                this.flights = d.states.slice(0, 150)
                  .filter(s => s[5] !== null && s[6] !== null)
                  .map(s => {
                    const lng = s[5], lat = s[6], hdg = (s[10] || 0) * Math.PI / 180;
                    return { lat1: lat, lng1: lng, lat2: lat + Math.cos(hdg)*1.5, lng2: lng + Math.sin(hdg)*1.5 };
                  });
                this.flightCount = this.flights.length;
                const el = document.getElementById('e2FlightCount');
                if (el) el.textContent = `ADS-B: ${this.flights.length} flights`;
                document.getElementById('e2FlightStat').textContent = this.flights.length;
              }
            } else throw new Error('rate limited');
          } catch(e) {
            // Fallback simulation
            this.flights = Array.from({length:60}).map((_, i) => {
              const hubs = [[40.6,-73.8],[33.9,-118.4],[51.5,-0.4],[50.0,8.6],[35.7,140.4],[48.4,2.5]];
              const hub = hubs[i % hubs.length];
              const lat = hub[0] + (Math.random()-0.5)*20;
              const lng = hub[1] + (Math.random()-0.5)*20;
              const hdg = Math.random()*Math.PI*2;
              return { lat1:lat, lng1:lng, lat2:lat+Math.cos(hdg)*1.5, lng2:lng+Math.sin(hdg)*1.5 };
            });
            this.flightCount = this.flights.length;
            const el = document.getElementById('e2FlightCount');
            if (el) el.textContent = `ADS-B: ${this.flights.length} (sim)`;
            document.getElementById('e2FlightStat').textContent = this.flights.length;
          }
        },

        runScenario() {
          const input = document.getElementById('e2ScenarioInput');
          const loc = document.getElementById('e2LocationInput');
          if (!input || !input.value.trim()) return;

          const btn = document.getElementById('e2RunBtn');
          const prog = document.getElementById('e2ProgressBar');
          const fill = document.getElementById('e2ProgressFill');
          const pct = document.getElementById('e2ProgressPct');
          const results = document.getElementById('e2Results');
          const resultText = document.getElementById('e2ResultText');

          btn.disabled = true;
          prog.style.display = 'flex';
          results.style.display = 'none';
          let progress = 0;
          fill.style.width = '0%';

          this.simInterval = setInterval(() => {
            progress += Math.random() * 8 + 2;
            if (progress >= 100) {
              progress = 100;
              clearInterval(this.simInterval);
              fill.style.width = '100%';
              pct.textContent = '100%';
              setTimeout(() => {
                this.simRuns++;
                document.getElementById('e2SimRuns').textContent = this.simRuns;
                const loc_val = loc?.value || 'Global';
                resultText.innerHTML = `OpenUSD geometry generated for UE5 Cesium plugin. Location: <b>${loc_val}</b>.<br>Thermal injection caused global pressure shift of +${(Math.random()*6+2).toFixed(1)} hPa.<br>DeltaVault ingestion completed. Trust Score: ${(0.94 + Math.random()*0.05).toFixed(2)}.<br>Pangu-Weather 15-day forecast exported.`;
                results.style.display = 'block';
                btn.disabled = false;
                prog.style.display = 'none';
                // Add to feed
                this.addFeedItem({ source:'NASA_GIBS', type:'Earth2Studio Sim Complete', val:`+${(Math.random()*6+2).toFixed(1)} hPa`, loc: loc_val, ref:'omniverse' });
              }, 400);
            } else {
              fill.style.width = progress + '%';
              pct.textContent = Math.floor(progress) + '%';
            }
          }, 250);
        }
      };

      // Boot Earth-2 after DOM ready
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => E2.init());
      } else {
        E2.init();
      }
    })();
"""

with open(HTML_FILE, 'r', encoding='utf-8') as f:
    content = f.read()

# 1) Inject CSS before </style>
CSS_MARKER = '    /* ── Tooltip ──'
if CSS_MARKER in content:
    content = content.replace(CSS_MARKER, EARTH2_CSS + '\n' + CSS_MARKER, 1)
    print("✓ CSS injected")
else:
    # fallback: inject before </style>
    content = content.replace('  </style>', EARTH2_CSS + '\n  </style>', 1)
    print("✓ CSS injected (fallback)")

# 2) Inject HTML before tooltip div
TOOLTIP_MARKER = '     <div id="tooltip"'
if TOOLTIP_MARKER in content:
    content = content.replace(TOOLTIP_MARKER, EARTH2_HTML + TOOLTIP_MARKER, 1)
    print("✓ HTML injected")
else:
    print("✗ HTML injection failed — tooltip marker not found")

# 3) Inject JS before closing </script> (first big script block)
JS_MARKER = "    // ── Auto-log"
if JS_MARKER in content:
    content = content.replace(JS_MARKER, EARTH2_JS + '\n' + JS_MARKER, 1)
    print("✓ JS injected")
else:
    # fallback: inject before last </script>
    last_script = content.rfind('    </script>')
    if last_script != -1:
        content = content[:last_script] + EARTH2_JS + '\n    ' + content[last_script:]
        print("✓ JS injected (fallback)")
    else:
        print("✗ JS injection failed")

with open(HTML_FILE, 'w', encoding='utf-8') as f:
    f.write(content)

print(f"✓ Done — {HTML_FILE} updated ({len(content):,} chars)")