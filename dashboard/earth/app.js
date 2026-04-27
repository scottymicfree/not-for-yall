/**
 * Lucy OS — Earth Intelligence Dashboard
 * =======================================
 * Three.js 3D Earth + Live Data Feeds + QME Visualization
 *
 * Architecture:
 *   EarthRenderer   — Three.js globe, rotation, day/night shader
 *   DataManager     — polls backend API, manages event cache
 *   EventOverlay    — renders dots on globe surface
 *   QMEVisualizer   — renders oscillator field + stability chart
 *   UIController    — tabs, panels, modals, layer toggles
 *   LiveProof       — UTC clock, feed badges, ingestion log
 */

'use strict';

// ══ CONFIG ════════════════════════════════════════════════════════════════
const CFG = {
  API_BASE:      '',           // same origin
  POLL_INTERVAL: 5000,         // ms between data polls
  MAX_EVENTS:    200,
  EARTH_RADIUS:  1.0,
  STAR_COUNT:    3000,
  ROTATION_SPEED: 0.0003,      // radians/frame default
};

// ══ EARTH RENDERER ════════════════════════════════════════════════════════

class EarthRenderer {
  constructor(canvas) {
    this.canvas   = canvas;
    this.scene    = new THREE.Scene();
    this.camera   = null;
    this.renderer = null;
    this.earth    = null;
    this.clouds   = null;
    this.atmo     = null;
    this.sunLight = null;
    this.eventDots = new THREE.Group();
    this.qmeField  = null;

    // State
    this.rotating    = true;
    this.rotSpeed    = CFG.ROTATION_SPEED;
    this.daynight    = true;
    this.showAtmo    = true;
    this.isDragging  = false;
    this.prevMouse   = { x: 0, y: 0 };
    this.dotOpacity  = { seismic: 0.9, weather: 0.8, solar: 0.7, qme: 0.6 };
    this.layers      = { seismic: true, weather: true, solar: false, qme: true };

    this._init();
  }

  _init() {
    const W = this.canvas.clientWidth  || 800;
    const H = this.canvas.clientHeight || 600;

    // Camera
    this.camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 100);
    this.camera.position.set(0, 0, 2.8);

    // Renderer
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: true,
      alpha: true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(W, H);
    this.renderer.shadowMap.enabled = true;

    // Lights
    const ambient = new THREE.AmbientLight(0x223344, 0.4);
    this.scene.add(ambient);

    this.sunLight = new THREE.DirectionalLight(0xffffff, 1.2);
    this.sunLight.position.set(5, 3, 5);
    this.scene.add(this.sunLight);

    // Stars
    this._addStars();

    // Earth
    this._addEarth();

    // Atmosphere
    this._addAtmosphere();

    // Event dots group
    this.scene.add(this.eventDots);

    // Mouse controls
    this._initControls();

    // Resize handler
    window.addEventListener('resize', () => this._onResize());

    // Start loop
    this._animate();
  }

  _addStars() {
    const positions = new Float32Array(CFG.STAR_COUNT * 3);
    for (let i = 0; i < CFG.STAR_COUNT; i++) {
      const r = 50 + Math.random() * 50;
      const theta = Math.random() * Math.PI * 2;
      const phi   = Math.acos(2 * Math.random() - 1);
      positions[i*3]   = r * Math.sin(phi) * Math.cos(theta);
      positions[i*3+1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i*3+2] = r * Math.cos(phi);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    const mat = new THREE.PointsMaterial({
      color: 0xffffff, size: 0.06, transparent: true, opacity: 0.8,
    });
    this.scene.add(new THREE.Points(geo, mat));
  }

  _addEarth() {
    const geo = new THREE.SphereGeometry(CFG.EARTH_RADIUS, 64, 64);

    // Create procedural earth texture
    const texCanvas = document.createElement('canvas');
    texCanvas.width  = 1024;
    texCanvas.height = 512;
    const ctx = texCanvas.getContext('2d');

    // Ocean
    const grad = ctx.createLinearGradient(0, 0, 0, 512);
    grad.addColorStop(0.0,  '#0a2040');
    grad.addColorStop(0.3,  '#0d3060');
    grad.addColorStop(0.5,  '#0a4080');
    grad.addColorStop(0.7,  '#0d3060');
    grad.addColorStop(1.0,  '#0a2040');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 1024, 512);

    // Landmass hints (simplified continents as ellipses)
    ctx.fillStyle = '#1a4a20';
    const lands = [
      [240,160,100,80], // N America
      [280,280,60,50],  // S America
      [490,170,80,70],  // Europe
      [520,200,90,80],  // Africa
      [680,180,110,90], // Asia
      [760,300,60,40],  // Australia
    ];
    lands.forEach(([x,y,w,h]) => {
      ctx.beginPath();
      ctx.ellipse(x,y,w,h,0,0,Math.PI*2);
      ctx.fill();
    });

    // Grid lines
    ctx.strokeStyle = 'rgba(0,150,200,0.15)';
    ctx.lineWidth = 0.5;
    for (let lon = 0; lon <= 1024; lon += 1024/12) {
      ctx.beginPath(); ctx.moveTo(lon,0); ctx.lineTo(lon,512); ctx.stroke();
    }
    for (let lat = 0; lat <= 512; lat += 512/6) {
      ctx.beginPath(); ctx.moveTo(0,lat); ctx.lineTo(1024,lat); ctx.stroke();
    }

    const tex = new THREE.CanvasTexture(texCanvas);

    const mat = new THREE.MeshPhongMaterial({
      map: tex,
      specular: new THREE.Color(0x334455),
      shininess: 15,
    });

    this.earth = new THREE.Mesh(geo, mat);
    this.scene.add(this.earth);
    this._earthTexCtx = ctx;
    this._earthTex    = tex;
    this._earthCanvas = texCanvas;
  }

  _addAtmosphere() {
    const geo = new THREE.SphereGeometry(CFG.EARTH_RADIUS * 1.025, 32, 32);
    const mat = new THREE.MeshPhongMaterial({
      color: 0x4488ff,
      transparent: true,
      opacity: 0.07,
      side: THREE.FrontSide,
    });
    this.atmo = new THREE.Mesh(geo, mat);
    this.scene.add(this.atmo);

    // Glow ring
    const glowGeo = new THREE.SphereGeometry(CFG.EARTH_RADIUS * 1.08, 32, 32);
    const glowMat = new THREE.MeshBasicMaterial({
      color: 0x224488,
      transparent: true,
      opacity: 0.04,
      side: THREE.BackSide,
    });
    this.scene.add(new THREE.Mesh(glowGeo, glowMat));
  }

  _animate() {
    requestAnimationFrame(() => this._animate());

    if (this.rotating && this.earth) {
      this.earth.rotation.y += this.rotSpeed;
      if (this.atmo) this.atmo.rotation.y += this.rotSpeed * 1.01;
      this.eventDots.rotation.y += this.rotSpeed;
    }

    // Sun position follows real time (UTC hour → angle)
    if (this.daynight && this.sunLight) {
      const now     = new Date();
      const utcH    = now.getUTCHours() + now.getUTCMinutes() / 60;
      const sunAngle = (utcH / 24) * Math.PI * 2 - Math.PI;
      this.sunLight.position.set(
        Math.cos(sunAngle) * 5,
        1.5,
        Math.sin(sunAngle) * 5
      );
    }

    this.renderer.render(this.scene, this.camera);
  }

  _initControls() {
    const c = this.canvas;
    c.addEventListener('mousedown', e => {
      this.isDragging = true;
      this.prevMouse  = { x: e.clientX, y: e.clientY };
      this.rotating   = false;
    });
    c.addEventListener('mouseup',  () => { this.isDragging = false; });
    c.addEventListener('mouseleave',() => { this.isDragging = false; });
    c.addEventListener('mousemove', e => {
      if (!this.isDragging || !this.earth) return;
      const dx = (e.clientX - this.prevMouse.x) * 0.005;
      const dy = (e.clientY - this.prevMouse.y) * 0.005;
      this.earth.rotation.y     += dx;
      this.earth.rotation.x     += dy;
      this.eventDots.rotation.y += dx;
      this.eventDots.rotation.x += dy;
      this.prevMouse = { x: e.clientX, y: e.clientY };
    });
    c.addEventListener('wheel', e => {
      const delta = e.deltaY * 0.001;
      this.camera.position.z = Math.max(1.4, Math.min(5,
        this.camera.position.z + delta));
    });
    c.addEventListener('mouseup', () => {
      // Resume auto-rotation after a pause
      setTimeout(() => { if (!this.isDragging) this.rotating = true; }, 2000);
    });
  }

  _onResize() {
    const W = this.canvas.clientWidth;
    const H = this.canvas.clientHeight;
    this.camera.aspect = W / H;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(W, H);
  }

  // ── Event Dots ───────────────────────────────────────────────────────

  updateDots(events) {
    // Clear existing
    while (this.eventDots.children.length) {
      this.eventDots.remove(this.eventDots.children[0]);
    }

    events.forEach(ev => {
      if (!this._shouldShowLayer(ev.event_type)) return;

      const { lat, lon, magnitude, event_type, source } = ev;
      const color  = this._dotColor(event_type, magnitude);
      const size   = this._dotSize(magnitude);
      const pos    = this._latLonToVec3(lat, lon, CFG.EARTH_RADIUS + 0.012);

      // Dot
      const geo = new THREE.SphereGeometry(size, 8, 8);
      const mat = new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: this._layerOpacity(event_type),
      });
      const dot = new THREE.Mesh(geo, mat);
      dot.position.copy(pos);
      dot.userData = ev;

      // Pulse ring for large events
      if (magnitude >= 5.0) {
        const ringGeo = new THREE.RingGeometry(size * 1.5, size * 2.5, 16);
        const ringMat = new THREE.MeshBasicMaterial({
          color, transparent: true, opacity: 0.3, side: THREE.DoubleSide,
        });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.position.copy(pos);
        ring.lookAt(0, 0, 0);
        this.eventDots.add(ring);
      }

      this.eventDots.add(dot);
    });
  }

  _shouldShowLayer(type) {
    if (type === 'seismic' && !this.layers.seismic) return false;
    if (type === 'weather'  && !this.layers.weather) return false;
    if (type === 'solar'    && !this.layers.solar)   return false;
    return true;
  }

  _layerOpacity(type) {
    const m = { seismic:'seismic', weather:'weather', solar:'solar' };
    return this.dotOpacity[m[type] || 'seismic'] || 0.8;
  }

  _dotColor(type, mag) {
    if (type === 'seismic') {
      if (mag >= 6.0) return 0xff2244;
      if (mag >= 4.0) return 0xff8800;
      return 0xffcc00;
    }
    if (type === 'weather') return 0x44aaff;
    if (type === 'solar')   return 0xff8844;
    return 0x8844ff;  // synthetic
  }

  _dotSize(mag) {
    return Math.max(0.006, Math.min(0.025, mag * 0.003));
  }

  _latLonToVec3(lat, lon, r) {
    const phi   = (90 - lat)  * (Math.PI / 180);
    const theta = (lon + 180) * (Math.PI / 180);
    return new THREE.Vector3(
      -r * Math.sin(phi) * Math.cos(theta),
       r * Math.cos(phi),
       r * Math.sin(phi) * Math.sin(theta),
    );
  }

  setRotating(v)    { this.rotating = v; }
  setRotSpeed(v)    { this.rotSpeed = v * CFG.ROTATION_SPEED; }
  setDayNight(v)    { this.daynight = v; }
  setAtmo(v)        { if(this.atmo) this.atmo.visible = v; }
  setLayerVisible(layer, v) { this.layers[layer] = v; }
  setLayerOpacity(layer, v) { this.dotOpacity[layer] = v / 100; }

  // Raycasting for click detection
  getClickedEvent(x, y, events) {
    const rect   = this.canvas.getBoundingClientRect();
    const mouse  = new THREE.Vector2(
      ((x - rect.left)  / rect.width)  * 2 - 1,
      -((y - rect.top) / rect.height) * 2 + 1,
    );
    const ray = new THREE.Raycaster();
    ray.setFromCamera(mouse, this.camera);
    const hits = ray.intersectObjects(this.eventDots.children);
    if (hits.length > 0 && hits[0].object.userData.event_type) {
      return hits[0].object.userData;
    }
    return null;
  }
}

// ══ DATA MANAGER ══════════════════════════════════════════════════════════

class DataManager {
  constructor() {
    this.events    = [];
    this.feedStatus= {};
    this.qmeState  = null;
    this.callbacks = [];
    this._lastFetch= 0;
    this._fetchCount = 0;
  }

  start() {
    this._poll();
    setInterval(() => this._poll(), CFG.POLL_INTERVAL);
  }

  async _poll() {
    try {
      // Fetch events
      const evResp = await fetch(`${CFG.API_BASE}/api/earth/events?limit=100`);
      if (evResp.ok) {
        const data = await evResp.json();
        this.events = data.events || [];
        this._lastFetch = Date.now();
        this._fetchCount++;
      }
    } catch (e) {
      // Fall back to synthetic demo data
      if (!this.events.length) this._generateSyntheticDemo();
    }

    try {
      const fsResp = await fetch(`${CFG.API_BASE}/api/earth/feeds`);
      if (fsResp.ok) this.feedStatus = await fsResp.json();
    } catch (e) { /* use last known */ }

    try {
      const qResp = await fetch(`${CFG.API_BASE}/api/qme/snapshot`);
      if (qResp.ok) this.qmeState = await qResp.json();
    } catch (e) { /* use last known */ }

    this._notify();
  }

  _generateSyntheticDemo() {
    // Demo events so the UI isn't empty when backend isn't running
    const zones = [
      { lat: 35.6, lon: 139.7, type: 'seismic', mag: 4.2, title: 'M4.2 near Tokyo, Japan' },
      { lat: 37.8, lon: -122.4,type: 'seismic', mag: 3.1, title: 'M3.1 near San Francisco, CA' },
      { lat: 19.4, lon: -155.3,type: 'seismic', mag: 2.8, title: 'M2.8 near Hawaii, HI' },
      { lat: -33.9,lon: 151.2, type: 'seismic', mag: 3.5, title: 'M3.5 near Sydney, Australia' },
      { lat: 51.5, lon: -0.1,  type: 'weather', mag: 7.0, title: 'Severe Storm Warning — London' },
      { lat: 40.7, lon: -74.0, type: 'weather', mag: 5.0, title: 'Wind Advisory — New York' },
      { lat: -22.9,lon: -43.2, type: 'weather', mag: 6.0, title: 'Heavy Rain — Rio de Janeiro' },
      { lat: 0.0,  lon: 0.0,   type: 'solar',   mag: 4.0, title: 'Geomagnetic Activity Kp=4.0' },
      { lat: 64.1, lon: -21.9, type: 'seismic', mag: 3.8, title: 'M3.8 near Reykjavik, Iceland' },
      { lat: -38.4,lon: -63.6, type: 'seismic', mag: 5.1, title: 'M5.1 near Argentina' },
    ];
    const now = new Date().toISOString();
    this.events = zones.map((z, i) => ({
      ...z,
      source:    'synthetic',
      event_type: z.type,
      magnitude:  z.mag,
      depth_km:   Math.random() * 100,
      timestamp:  now,
      url:        'synthetic://lucy',
      raw:        {},
      grid_x:     (z.lon + 180) / 360,
      grid_y:     (90 - z.lat) / 180,
      qme_amplitude: z.mag / 9,
      qme_radius: 0.15,
      id:         i,
    }));
  }

  subscribe(fn) { this.callbacks.push(fn); }
  _notify() { this.callbacks.forEach(fn => fn()); }

  getLagSeconds() {
    return this._lastFetch ? (Date.now() - this._lastFetch) / 1000 : 9999;
  }
}

// ══ QME VISUALIZER ════════════════════════════════════════════════════════

class QMEVisualizer {
  constructor() {
    this._miniCtx  = null;
    this._bigCtx   = null;
    this._history  = [];
  }

  initMini(canvasId) {
    const c = document.getElementById(canvasId);
    if (c) this._miniCtx = c.getContext('2d');
  }

  initBig(canvasId) {
    const c = document.getElementById(canvasId);
    if (c) this._bigCtx = c.getContext('2d');
  }

  update(state) {
    if (!state || !state.ready) return;

    // Track history
    if (state.stability_score !== undefined) {
      this._history.push(state.stability_score);
      if (this._history.length > 200) this._history.shift();
    }

    if (this._miniCtx) this._drawMini(this._miniCtx, 280, 60);
    if (this._bigCtx)  this._drawBig(this._bigCtx, 900, 120);

    // Update text values
    this._setText('qme-stability', state.stability_score?.toFixed(3) ?? '—');
    this._setText('qme-regime',    state.regime ?? '—');
    this._setText('qme-coherence', state.phase_coherence?.toFixed(3) ?? '—');
    this._setText('qme-attractors',state.attractor_count?.toString() ?? '—');
    this._setText('qme-trend',     state.trend ?? '—');
    this._setText('qme-episode',   state.episode?.toString() ?? '—');

    this._setText('qme-stab-big',  state.stability_score?.toFixed(3) ?? '—');
    this._setText('qme-regime-big',state.regime ?? '—');
    this._setText('qme-attr-big',  state.attractor_count?.toString() ?? '—');
    this._setText('qme-coh-big',   state.phase_coherence?.toFixed(3) ?? '—');
    this._setText('qme-steps-big', state.total_steps?.toLocaleString() ?? '—');
    this._setText('qme-ep-big',    state.episode?.toString() ?? '—');

    // Color-code regime
    const regimeEl = document.getElementById('qme-regime');
    if (regimeEl) {
      const colors = {
        harmony:'#00ff88', transition:'#ffaa00',
        instability:'#ff8800', chaos:'#ff2244', unknown:'#7a9ab0',
      };
      regimeEl.style.color = colors[state.regime] || '#c8dde8';
    }

    // Render oscillator mini-grid
    if (state.oscillators?.length) {
      this._renderOscGrid(state.oscillators);
    }
  }

  _drawMini(ctx, w, h) {
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#0a1520';
    ctx.fillRect(0, 0, w, h);
    this._drawStabilityLine(ctx, w, h, this._history, 1);
  }

  _drawBig(ctx, w, h) {
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#0d1a27';
    ctx.fillRect(0, 0, w, h);

    // Grid lines
    ctx.strokeStyle = '#1a3048';
    ctx.lineWidth = 0.5;
    for (let y = 0; y <= h; y += h/4) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }
    // Zero line
    ctx.strokeStyle = '#2a4060';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, h/2); ctx.lineTo(w, h/2); ctx.stroke();

    this._drawStabilityLine(ctx, w, h, this._history, 2);

    // Labels
    ctx.fillStyle = '#4a6a80';
    ctx.font = '10px Courier New';
    ctx.fillText('1.0', 4, 12);
    ctx.fillText('0.0', 4, h/2 + 4);
    ctx.fillText('-1.0', 4, h - 4);
  }

  _drawStabilityLine(ctx, w, h, history, lw) {
    if (!history.length) return;
    const midY  = h / 2;
    const scaleY = h / 2;
    const step  = w / Math.max(history.length, 1);

    ctx.lineWidth = lw;
    ctx.beginPath();
    history.forEach((v, i) => {
      const x = i * step;
      const y = midY - v * scaleY;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });

    // Gradient stroke
    const grad = ctx.createLinearGradient(0, 0, w, 0);
    grad.addColorStop(0, 'rgba(0,200,255,0.3)');
    grad.addColorStop(1, 'rgba(0,255,136,0.9)');
    ctx.strokeStyle = grad;
    ctx.stroke();

    // Fill under curve
    if (history.length > 1) {
      ctx.lineTo(w, h);
      ctx.lineTo(0, h);
      ctx.closePath();
      const fillGrad = ctx.createLinearGradient(0, 0, 0, h);
      fillGrad.addColorStop(0, 'rgba(0,200,255,0.15)');
      fillGrad.addColorStop(1, 'rgba(0,100,200,0.0)');
      ctx.fillStyle = fillGrad;
      ctx.fill();
    }
  }

  _renderOscGrid(oscillators) {
    const container = document.getElementById('qme-oscillator-grid');
    if (!container) return;

    let canvas = container.querySelector('canvas');
    if (!canvas) {
      canvas = document.createElement('canvas');
      canvas.width  = 800;
      canvas.height = 200;
      canvas.style.cssText = 'width:100%;border:1px solid #1a3048;border-radius:4px;background:#050a0f';
      container.appendChild(canvas);
    }

    const ctx  = canvas.getContext('2d');
    const W    = canvas.width;
    const H    = canvas.height;
    const COLS = 20;
    const ROWS = 10;
    const cw   = W / COLS;
    const ch   = H / ROWS;

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#050a0f';
    ctx.fillRect(0, 0, W, H);

    oscillators.forEach(o => {
      const col = o.id % COLS;
      const row = Math.floor(o.id / COLS);
      const x   = col * cw + cw/2;
      const y   = row * ch + ch/2;
      const r   = Math.max(2, o.energy * (Math.min(cw, ch)/2 - 2));

      // Color by group
      const groupColors = {
        earth:  [0,  180, 120],
        plasma: [0,  180, 255],
        free:   [200, 80, 255],
      };
      const [cr, cg, cb] = groupColors[o.group] || [200, 200, 200];
      const alpha = 0.3 + o.energy * 0.7;

      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${cr},${cg},${cb},${alpha})`;
      ctx.fill();

      // Phase indicator
      const px = x + r * Math.cos(o.phase);
      const py = y + r * Math.sin(o.phase);
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(px, py);
      ctx.strokeStyle = `rgba(${cr},${cg},${cb},0.6)`;
      ctx.lineWidth = 1;
      ctx.stroke();
    });

    // Group label
    ctx.fillStyle = 'rgba(0,150,200,0.4)';
    ctx.font = '9px Courier New';
    ctx.fillText('● earth (low-freq)', 4, H - 30);
    ctx.fillStyle = 'rgba(0,180,255,0.4)';
    ctx.fillText('● plasma (mid-freq)', 4, H - 18);
    ctx.fillStyle = 'rgba(200,80,255,0.4)';
    ctx.fillText('● free (high-freq)', 4, H - 6);
  }

  _setText(id, v) {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  }
}

// ══ LIVE PROOF ════════════════════════════════════════════════════════════

class LiveProof {
  constructor() {
    this._ingestLog = [];
    this._maxLog    = 50;
  }

  startClock() {
    const tick = () => {
      const now   = new Date();
      const hh    = String(now.getUTCHours()).padStart(2,'0');
      const mm    = String(now.getUTCMinutes()).padStart(2,'0');
      const ss    = String(now.getUTCSeconds()).padStart(2,'0');
      const yyyy  = now.getUTCFullYear();
      const mo    = String(now.getUTCMonth()+1).padStart(2,'0');
      const dd    = String(now.getUTCDate()).padStart(2,'0');
      this._setText('utc-clock', `${hh}:${mm}:${ss}`);
      this._setText('utc-date',  `${yyyy}/${mo}/${dd}`);
    };
    tick();
    setInterval(tick, 1000);
  }

  updateFeeds(feedStatus) {
    ['USGS','NOAA','NASA'].forEach(name => {
      const el  = document.getElementById(`badge-${name.toLowerCase()}`);
      const fs  = feedStatus?.[name];
      if (!el) return;
      el.className = 'feed-badge';
      if (!fs) return;
      if (fs.live && fs.lag_seconds < 300) {
        el.classList.add('live');
        el.title = `${name}: ✅ Live | ${fs.events_60s} events/60s | Updated ${Math.round(fs.lag_seconds)}s ago`;
      } else if (fs.lag_seconds < 900) {
        el.classList.add('stale');
        el.title = `${name}: ⚠️ ${Math.round(fs.lag_seconds)}s stale`;
      } else {
        el.classList.add('dead');
        el.title = `${name}: ❌ ${fs.last_error || 'No data'}`;
      }
    });
  }

  updateStats(events, feedStatus) {
    const total = Object.values(feedStatus || {})
                        .reduce((s, f) => s + (f.total_ingested || 0), 0);
    const per60 = Object.values(feedStatus || {})
                        .reduce((s, f) => s + (f.events_60s || 0), 0);
    this._setText('total-ingested', total.toLocaleString());
    this._setText('events-per-min', per60.toString());
    this._setText('feed-count', events.length.toString());
  }

  updateFreshness(lagSeconds) {
    const el   = document.getElementById('last-update-text');
    const dot  = document.getElementById('data-freshness');
    if (el) el.textContent = `Last updated: ${lagSeconds < 5 ? 'just now' :
                               lagSeconds < 60 ? `${Math.round(lagSeconds)}s ago` :
                               `${Math.round(lagSeconds/60)}m ago`}`;
    if (dot) {
      dot.className = lagSeconds < 60 ? 'freshness-ok' :
                      lagSeconds < 300 ? 'freshness-warn' : 'freshness-bad';
      dot.textContent = lagSeconds < 60  ? '● Fresh' :
                        lagSeconds < 300 ? '⚠ Updating' : '✕ Stale';
    }
  }

  addIngestLog(source, count, ts) {
    this._ingestLog.unshift({ source, count, ts });
    if (this._ingestLog.length > this._maxLog) this._ingestLog.pop();
    this._renderLog();
  }

  _renderLog() {
    const el = document.getElementById('ingest-log');
    if (!el) return;
    el.innerHTML = this._ingestLog.slice(0,15).map(l => {
      const t = new Date(l.ts);
      const ts = `${String(t.getUTCHours()).padStart(2,'0')}:${String(t.getUTCMinutes()).padStart(2,'0')}:${String(t.getUTCSeconds()).padStart(2,'0')}`;
      return `<div class="log-line">
        <span class="log-ts">${ts}</span>
        <span class="log-src">${l.source}</span>
        <span class="log-msg">${l.count} event${l.count!==1?'s':''} ingested</span>
      </div>`;
    }).join('');
  }

  _setText(id, v) {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  }
}

// ══ UI CONTROLLER ═════════════════════════════════════════════════════════

class UIController {
  constructor(earth, dataManager, qmeViz, liveProof) {
    this.earth       = earth;
    this.data        = dataManager;
    this.qme         = qmeViz;
    this.proof       = liveProof;
    this.activeTab   = 'earth';
    this._prevEventCount = 0;
  }

  init() {
    this._initTabs();
    this._initLayerToggles();
    this._initControls();
    this._initModal();
    this._initFilters();

    // Canvas click → event detail
    document.getElementById('earth-canvas')?.addEventListener('click', e => {
      const ev = this.earth.getClickedEvent(e.clientX, e.clientY, this.data.events);
      if (ev) this._openModal(ev);
    });
  }

  onDataUpdate() {
    const evs = this._filteredEvents();
    this.earth.updateDots(evs);
    this.qme.update(this.data.qmeState);
    this.proof.updateFeeds(this.data.feedStatus);
    this.proof.updateStats(evs, this.data.feedStatus);
    this.proof.updateFreshness(this.data.getLagSeconds());
    this._renderEventFeed(evs);
    this._updateSubDashboards(evs);
    this._updateEarthStatus(evs);

    // Ingest log
    if (evs.length !== this._prevEventCount) {
      const diff = evs.length - this._prevEventCount;
      if (diff > 0) {
        const sources = [...new Set(evs.slice(0, diff).map(e => e.source.toUpperCase()))];
        sources.forEach(src => {
          this.proof.addIngestLog(src, diff, new Date().toISOString());
        });
      }
      this._prevEventCount = evs.length;
    }
  }

  _filteredEvents() {
    const minMag = parseFloat(document.getElementById('mag-filter')?.value || 25) / 10;
    return this.data.events.filter(e => {
      if (e.event_type === 'seismic' && e.magnitude < minMag) return false;
      if (e.event_type === 'seismic' && !this.earth.layers.seismic) return false;
      if (e.event_type === 'weather' && !this.earth.layers.weather) return false;
      if (e.event_type === 'solar'   && !this.earth.layers.solar)   return false;
      return true;
    });
  }

  _renderEventFeed(events) {
    const el = document.getElementById('event-list');
    if (!el) return;
    const recent = events.slice(0, 40);
    el.innerHTML = recent.map(ev => {
      const dotClass = this._dotClass(ev);
      const ts = ev.timestamp ? new Date(ev.timestamp).toUTCString().slice(0,-4) : '—';
      return `<div class="event-item" data-id="${ev.id || 0}"
                   onclick='window._openEventModal(${JSON.stringify(ev).replace(/'/g,"&#39;")})'>
        <span class="event-dot ${dotClass}"></span>
        <div class="event-body">
          <div class="event-title">${ev.title || 'Event'}</div>
          <div class="event-meta">M${ev.magnitude?.toFixed(1)} · ${ts.slice(0,22)}Z</div>
        </div>
        <span class="event-source-tag">${(ev.source||'').toUpperCase()}</span>
      </div>`;
    }).join('');
  }

  _dotClass(ev) {
    if (ev.event_type === 'weather') return 'weather';
    if (ev.event_type === 'solar')   return 'solar';
    if (ev.source === 'synthetic')   return 'synthetic';
    const m = ev.magnitude || 0;
    if (m >= 6.0) return 'seismic-high';
    if (m >= 4.0) return 'seismic-med';
    return 'seismic-low';
  }

  _updateSubDashboards(events) {
    const seismic = events.filter(e => e.event_type === 'seismic');
    const weather = events.filter(e => e.event_type === 'weather');
    const solar   = events.filter(e => e.event_type === 'solar');

    // Seismic
    this._setText('seismic-count',    seismic.length.toString());
    this._setText('seismic-max-mag',  seismic.length ?
      'M' + Math.max(...seismic.map(e=>e.magnitude)).toFixed(1) : '—');
    this._setText('seismic-regions',  new Set(seismic.map(e=>
      `${Math.round(e.lat/10)*10},${Math.round(e.lon/10)*10}`)).size.toString());
    this._setText('seismic-last-update', `Updated: ${new Date().toUTCString().slice(0,-4)}Z`);
    this._renderTable('seismic-tbody', seismic, 'seismic');

    // Weather
    this._setText('weather-count',    weather.length.toString());
    const sevMap = {9:'Extreme',7:'Severe',5:'Moderate',3:'Minor'};
    const maxSev = weather.length ? Math.max(...weather.map(e=>e.magnitude)) : 0;
    this._setText('weather-severity', sevMap[Math.round(maxSev)] || (weather.length ? 'Active':'—'));
    this._setText('weather-regions',  new Set(weather.map(e=>e.title?.split('—')?.[1]?.trim())).size.toString());
    this._setText('weather-last-update', `Updated: ${new Date().toUTCString().slice(0,-4)}Z`);
    this._renderTable('weather-tbody', weather, 'weather');

    // Space
    this._setText('space-kp',     solar.length ? solar[0].magnitude.toFixed(1) : '—');
    this._setText('space-events', solar.length.toString());
    const kp = solar.length ? solar[0].magnitude : 0;
    this._setText('space-storm',  kp >= 7 ? 'Severe G4' : kp >= 5 ? 'Strong G3' :
                                  kp >= 4 ? 'Moderate G2' : kp >= 3 ? 'Minor G1' : 'Quiet');
  }

  _renderTable(tbodyId, events, type) {
    const el = document.getElementById(tbodyId);
    if (!el) return;
    el.innerHTML = events.slice(0, 50).map(ev => {
      const ts = ev.timestamp ? ev.timestamp.replace('T', ' ').slice(0,19) + 'Z' : '—';
      if (type === 'seismic') {
        return `<tr>
          <td class="mono">${ts}</td>
          <td class="mag-cell">M${ev.magnitude?.toFixed(1)}</td>
          <td>${ev.title || '—'}</td>
          <td>${ev.depth_km ? ev.depth_km.toFixed(0)+'km' : '—'}</td>
          <td>${(ev.source||'').toUpperCase()}</td>
          <td><button class="trace-btn" onclick="window._openEventModal(${
            JSON.stringify(ev).replace(/"/g,"'")
          })">🔗 Trace</button></td>
        </tr>`;
      }
      return `<tr>
        <td class="mono">${ts}</td>
        <td>${ev.event_type}</td>
        <td>${ev.title || '—'}</td>
        <td>${ev.magnitude?.toFixed(0) || '—'}</td>
        <td>${(ev.source||'').toUpperCase()}</td>
        <td><button class="trace-btn" onclick="window._openEventModal(${
          JSON.stringify(ev).replace(/"/g,"'")
        })">🔗 Trace</button></td>
      </tr>`;
    }).join('');
  }

  _updateEarthStatus(events) {
    const el = document.getElementById('earth-status');
    if (el) el.textContent = `${events.length} events · ${this.data.qmeState?.regime || 'initializing'} regime`;
  }

  _initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const tab = btn.dataset.tab;
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const tabPanels = document.getElementById('tab-panels');
        const panels    = document.querySelectorAll('.tab-panel');
        if (tab === 'earth') {
          tabPanels.classList.remove('visible');
          panels.forEach(p => p.classList.remove('active'));
        } else {
          tabPanels.classList.add('visible');
          panels.forEach(p => p.classList.remove('active'));
          const p = document.getElementById(`tab-${tab}`);
          if (p) p.classList.add('active');
        }
        this.activeTab = tab;
      });
    });
  }

  _initLayerToggles() {
    ['seismic','weather','solar','qme'].forEach(layer => {
      const cb = document.getElementById(`layer-${layer}`);
      const sl = document.getElementById(`opacity-${layer}`);
      cb?.addEventListener('change', () => {
        this.earth.setLayerVisible(layer, cb.checked);
        this.onDataUpdate();
      });
      sl?.addEventListener('input', () => {
        this.earth.setLayerOpacity(layer, parseInt(sl.value));
        this.onDataUpdate();
      });
    });
  }

  _initControls() {
    document.getElementById('btn-rotate')?.addEventListener('click', e => {
      const b = e.currentTarget;
      b.classList.toggle('active');
      this.earth.setRotating(b.classList.contains('active'));
    });
    document.getElementById('rotation-speed')?.addEventListener('input', e => {
      this.earth.setRotSpeed(parseInt(e.target.value) / 20);
    });
    document.getElementById('btn-daynight')?.addEventListener('click', e => {
      const b = e.currentTarget;
      b.classList.toggle('active');
      this.earth.setDayNight(b.classList.contains('active'));
    });
    document.getElementById('btn-atmo')?.addEventListener('click', e => {
      const b = e.currentTarget;
      b.classList.toggle('active');
      this.earth.setAtmo(b.classList.contains('active'));
    });
  }

  _initFilters() {
    document.getElementById('mag-filter')?.addEventListener('input', e => {
      const v = parseInt(e.target.value) / 10;
      this._setText('mag-value', v.toFixed(1));
      this.onDataUpdate();
    });
  }

  _initModal() {
    document.getElementById('modal-close')?.addEventListener('click', () => {
      document.getElementById('event-modal')?.classList.add('hidden');
    });
    document.getElementById('event-modal')?.addEventListener('click', e => {
      if (e.target.id === 'event-modal')
        document.getElementById('event-modal')?.classList.add('hidden');
    });
    // Global handler for dynamically generated buttons
    window._openEventModal = (ev) => this._openModal(ev);
  }

  _openModal(ev) {
    const modal = document.getElementById('event-modal');
    if (!modal) return;

    const badge = document.getElementById('modal-source-badge');
    const colors = {usgs:'#ff8800', noaa:'#44aaff', nasa:'#ff8844', synthetic:'#8844ff'};
    if (badge) {
      badge.textContent  = (ev.source || 'UNKNOWN').toUpperCase();
      badge.style.background = colors[ev.source?.toLowerCase()] || '#1a3048';
      badge.style.color  = '#fff';
    }

    this._setText('modal-title',  ev.title || 'Event');
    this._setText('modal-ts',     ev.timestamp || '—');
    this._setText('modal-loc',    `${ev.lat?.toFixed(3)}°, ${ev.lon?.toFixed(3)}°`);
    this._setText('modal-mag',    `${ev.event_type === 'seismic' ? 'M' : ''}${ev.magnitude?.toFixed(2)}`);
    this._setText('modal-depth',  ev.depth_km ? `${ev.depth_km.toFixed(1)} km` : 'N/A');
    this._setText('modal-source', (ev.source||'').toUpperCase());
    this._setText('modal-qme',    `amp=${ev.qme_amplitude?.toFixed(3)} r=${ev.qme_radius?.toFixed(3)}`);

    const rawEl = document.getElementById('modal-raw');
    if (rawEl) rawEl.textContent = JSON.stringify(ev.raw || ev, null, 2).slice(0, 800);

    const link = document.getElementById('modal-source-link');
    if (link) link.href = ev.url || '#';

    // Inject to QME button
    document.getElementById('modal-inject-btn')?.addEventListener('click', async () => {
      try {
        await fetch('/api/qme/inject', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            x: ev.grid_x, y: ev.grid_y,
            amplitude: ev.qme_amplitude,
            radius: ev.qme_radius,
            source: ev.title,
          }),
        });
        document.getElementById('modal-inject-btn').textContent = '✅ Injected!';
        setTimeout(() => {
          document.getElementById('modal-inject-btn').textContent = '🎛 Inject to QME';
        }, 2000);
      } catch(e) { console.warn('QME inject failed:', e); }
    });

    modal.classList.remove('hidden');
  }

  _setText(id, v) {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  }
}

// ══ BOOTSTRAP ═════════════════════════════════════════════════════════════

window.addEventListener('DOMContentLoaded', () => {
  // Init Three.js Earth
  const canvas  = document.getElementById('earth-canvas');
  const earth   = new EarthRenderer(canvas);

  // Init data
  const data    = new DataManager();

  // Init QME visualizer
  const qme     = new QMEVisualizer();
  qme.initMini('stability-chart');
  qme.initBig('qme-big-chart');

  // Init live proof
  const proof   = new LiveProof();
  proof.startClock();

  // Init UI
  const ui      = new UIController(earth, data, qme, proof);
  ui.init();

  // Wire data → UI updates
  data.subscribe(() => ui.onDataUpdate());

  // Start polling
  data.start();

  // Initial synthetic render
  setTimeout(() => {
    data._generateSyntheticDemo();
    ui.onDataUpdate();
  }, 100);
});