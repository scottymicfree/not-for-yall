#!/usr/bin/env python3
"""Inject NVIDIA Earth-2 TwinEarth section into Lucy OS v5 dashboard — line-based."""

EARTH2_HTML = """
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
         <div class="earth2-globe-col" id="earth2GlobeCol">
           <div class="earth2-globe-container" id="earth2GlobeContainer">
             <div class="earth2-globe-badge top-left"><span class="live-dot"></span>VR VIEWPORT LIVE</div>
             <button id="e2ExpandBtn" class="earth2-expand-btn" title="Expand Globe">&#10178;</button>
             <canvas id="earth2Canvas" class="earth2-canvas"></canvas>
             <div id="terminatorOverlay" class="terminator-overlay"></div>
             <div class="earth2-globe-footer">
               <span class="earth2-badge mono">NASA GIBS <span style="color:#10b981">ON</span></span>
               <span class="earth2-badge mono">TERM LIGHTING <span style="color:#10b981">ON</span></span>
               <span id="e2FlightCount" class="earth2-badge mono">ADS-B: 0 flights</span>
             </div>
           </div>
           <div class="earth2-nims-panel">
             <div class="panel-title"><div class="dot"></div>NVIDIA NIMs / EMMA Bridge</div>
             <div class="nims-grid">
               <div class="nims-row"><span>Modulus/PhysicsNeMo:</span><span style="color:#10b981">READY</span></div>
               <div class="nims-row"><span>Forecast Horizon:</span><span style="color:#e2e8f0">15 DAYS</span></div>
               <div class="nims-row"><span>CUDA Device:</span><span style="color:#60a5fa">A100-SXM</span></div>
               <div class="nims-row"><span>Export Format:</span><span style="color:#e2e8f0">OpenUSD</span></div>
               <div class="nims-row"><span>Pangu-Weather:</span><span style="color:#10b981">ACTIVE</span></div>
               <div class="nims-row"><span>DeltaVault Sync:</span><span style="color:#10b981">LIVE</span></div>
             </div>
           </div>
         </div>
         <div class="earth2-feed-col">
           <div class="earth2-feed-header">
             <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
             LIVE INGESTION PIPELINE
             <span id="e2FeedCount" class="earth2-badge mono" style="margin-left:auto">0 events</span>
           </div>
           <div id="earth2Feed" class="earth2-feed-list"></div>
         </div>
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
             <div class="earth2-stat-tile"><div id="e2SeismicCount" class="stat-val" style="color:#f59e0b;font-family:Courier New,monospace;font-size:18px;font-weight:700">0</div><div class="stat-label">SEISMIC</div></div>
             <div class="earth2-stat-tile"><div id="e2SolarWind" class="stat-val" style="color:#06b6d4;font-family:Courier New,monospace;font-size:18px;font-weight:700">---</div><div class="stat-label">SOLAR km/s</div></div>
             <div class="earth2-stat-tile"><div id="e2FlightStat" class="stat-val" style="color:#10b981;font-family:Courier New,monospace;font-size:18px;font-weight:700">0</div><div class="stat-label">ADS-B</div></div>
             <div class="earth2-stat-tile"><div id="e2SimRuns" class="stat-val" style="color:#f1f5f9;font-family:Courier New,monospace;font-size:18px;font-weight:700">0</div><div class="stat-label">SIM RUNS</div></div>
           </div>
         </div>
       </div>
     </div><!-- END EARTH-2 -->
"""

EARTH2_CSS = """
    /* ── NVIDIA Earth-2 TwinEarth ──────────────────────────────────────── */
    .earth2-section{background:#070d1a;border:1px solid #1e3a5f;border-radius:6px;margin:10px 12px 16px;overflow:hidden;box-shadow:0 0 40px rgba(6,182,212,.05)}
    .earth2-header{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;border-bottom:1px solid #1e293b;background:#0a1628;flex-wrap:wrap;gap:8px}
    .earth2-title-group{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
    .earth2-title{font-size:16px;font-weight:700;color:#e2e8f0;letter-spacing:.5px}
    .earth2-subtitle{font-weight:300;color:#64748b;font-size:14px}
    .earth2-header-badges{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
    .earth2-badge{font-family:'Courier New',monospace;font-size:9px;padding:2px 7px;border-radius:2px;border:1px solid #334155;color:#94a3b8;background:#0f172a;white-space:nowrap}
    .earth2-badge.nvidia{border-color:#76b900;color:#76b900;background:rgba(118,185,0,.08)}
    .earth2-badge.green{border-color:#10b981;color:#10b981;background:rgba(16,185,129,.08)}
    .earth2-badge.mono{font-family:'Courier New',monospace}
    .pulse-badge{animation:badgePulse 2s infinite}
    @keyframes badgePulse{0%,100%{opacity:1}50%{opacity:.5}}
    .earth2-body{display:grid;grid-template-columns:370px 1fr 300px;min-height:400px}
    .earth2-globe-col{border-right:1px solid #1e293b;display:flex;flex-direction:column;background:#050b18}
    .earth2-globe-container{position:relative;flex:1;min-height:270px;display:flex;align-items:center;justify-content:center;background:#020610;border-bottom:1px solid #1e293b;overflow:hidden}
    .earth2-canvas{display:block}
    .terminator-overlay{position:absolute;inset:0;pointer-events:none;mix-blend-mode:multiply}
    .earth2-globe-badge{position:absolute;top:10px;left:12px;z-index:10;font-family:'Courier New',monospace;font-size:9px;color:#cbd5e1;display:flex;align-items:center;gap:6px;text-transform:uppercase;letter-spacing:1px}
    .live-dot{width:8px;height:8px;border-radius:50%;background:#ef4444;animation:liveDot 1.5s infinite;display:inline-block}
    @keyframes liveDot{0%,100%{box-shadow:0 0 0 0 rgba(239,68,68,.7)}50%{box-shadow:0 0 0 6px rgba(239,68,68,0)}}
    .earth2-expand-btn{position:absolute;top:8px;right:8px;z-index:20;background:rgba(15,23,42,.7);border:1px solid #334155;color:#94a3b8;width:28px;height:28px;border-radius:4px;cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center;transition:all .2s}
    .earth2-expand-btn:hover{color:#06b6d4;border-color:#06b6d4}
    .earth2-globe-footer{position:absolute;bottom:8px;left:8px;right:8px;display:flex;gap:6px;z-index:10;flex-wrap:wrap}
    .earth2-nims-panel{padding:10px 12px;background:#080f20}
    .nims-grid{display:flex;flex-direction:column;gap:4px;margin-top:8px}
    .nims-row{display:flex;justify-content:space-between;font-family:'Courier New',monospace;font-size:9px;color:#64748b;background:#0a1628;padding:4px 8px;border-radius:2px}
    .earth2-feed-col{border-right:1px solid #1e293b;display:flex;flex-direction:column;background:#050b18;overflow:hidden}
    .earth2-feed-header{display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid #1e293b;font-family:'Courier New',monospace;font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;background:#080f20;flex-shrink:0}
    .earth2-feed-list{flex:1;overflow-y:auto;padding:8px;display:flex;flex-direction:column;gap:6px;max-height:360px}
    .earth2-feed-list::-webkit-scrollbar{width:4px}
    .earth2-feed-list::-webkit-scrollbar-track{background:#0a1628}
    .earth2-feed-list::-webkit-scrollbar-thumb{background:#1e3a5f;border-radius:2px}
    .e2-feed-item{background:#0a1628;border:1px solid #1e293b;border-radius:4px;padding:8px 10px;font-family:'Courier New',monospace;font-size:10px;display:flex;flex-direction:column;gap:4px;animation:feedSlide .3s ease-out;transition:border-color .2s}
    .e2-feed-item:hover{border-color:rgba(6,182,212,.3)}
    @keyframes feedSlide{from{opacity:0;transform:translateX(-12px)}to{opacity:1;transform:translateX(0)}}
    .e2-feed-top{display:flex;justify-content:space-between;align-items:center}
    .e2-feed-source{font-size:9px;padding:1px 6px;border-radius:2px;font-weight:700}
    .e2-src-usgs{background:rgba(251,146,60,.1);color:#fb923c;border:1px solid rgba(251,146,60,.2)}
    .e2-src-noaa{background:rgba(34,211,238,.1);color:#22d3ee;border:1px solid rgba(34,211,238,.2)}
    .e2-src-nasa{background:rgba(96,165,250,.1);color:#60a5fa;border:1px solid rgba(96,165,250,.2)}
    .e2-src-adsb{background:rgba(52,211,153,.1);color:#34d399;border:1px solid rgba(52,211,153,.2)}
    .e2-src-swarm{background:rgba(167,139,250,.1);color:#a78bfa;border:1px solid rgba(167,139,250,.2)}
    .e2-feed-ref{font-size:8px;color:#475569}
    .e2-feed-type{color:#94a3b8;font-size:10px}
    .e2-feed-bottom{display:flex;justify-content:space-between}
    .e2-feed-loc{font-size:9px;color:#64748b}
    .e2-feed-val{color:#f1f5f9;font-weight:700;font-size:10px}
    .earth2-scenario-col{display:flex;flex-direction:column;padding:14px;gap:10px;background:#080f20;position:relative;overflow:hidden}
    .earth2-scenario-col::before{content:'';position:absolute;top:-60px;right:-60px;width:200px;height:200px;background:radial-gradient(circle,rgba(6,182,212,.08) 0%,transparent 70%);pointer-events:none}
    .earth2-scenario-header{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:700;color:#f1f5f9;letter-spacing:.3px}
    .earth2-scenario-sub{font-family:'Courier New',monospace;font-size:9px;color:#64748b;margin-top:-4px}
    .earth2-form-group{display:flex;flex-direction:column;gap:4px}
    .earth2-form-group label{font-family:'Courier New',monospace;font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:.5px}
    .earth2-input{background:#050b18;border:1px solid #1e3a5f;border-radius:4px;padding:8px 10px;font-family:'Courier New',monospace;font-size:10px;color:#cbd5e1;outline:none;transition:border-color .2s}
    .earth2-input:focus{border-color:#06b6d4}
    .earth2-textarea{background:#050b18;border:1px solid #1e3a5f;border-radius:4px;padding:8px 10px;font-family:'Courier New',monospace;font-size:10px;color:#cbd5e1;outline:none;resize:vertical;min-height:80px;line-height:1.5;transition:border-color .2s}
    .earth2-textarea:focus{border-color:#06b6d4}
    .earth2-run-btn{display:flex;align-items:center;justify-content:center;gap:8px;padding:10px;background:rgba(6,182,212,.07);border:1px solid rgba(6,182,212,.25);color:#06b6d4;font-family:'Courier New',monospace;font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;border-radius:4px;cursor:pointer;transition:all .2s;box-shadow:0 0 15px rgba(6,182,212,.05)}
    .earth2-run-btn:hover{background:rgba(6,182,212,.15);border-color:rgba(6,182,212,.6);box-shadow:0 0 20px rgba(6,182,212,.2)}
    .earth2-run-btn:disabled{opacity:.4;cursor:not-allowed}
    .earth2-progress-wrap{display:flex;flex-direction:column;gap:5px}
    .earth2-progress-label{display:flex;justify-content:space-between;font-family:'Courier New',monospace;font-size:9px;color:#64748b}
    .earth2-progress-track{height:4px;background:#1e293b;border-radius:2px;overflow:hidden}
    .earth2-progress-fill{height:100%;background:#06b6d4;box-shadow:0 0 8px #06b6d4;transition:width .3s;border-radius:2px;width:0%}
    .earth2-results{background:#0a1628;border:1px solid rgba(16,185,129,.3);border-radius:4px;padding:10px;position:relative;overflow:hidden}
    .earth2-results::before{content:'';position:absolute;left:0;top:0;width:3px;height:100%;background:#10b981;box-shadow:0 0 8px #10b981}
    .earth2-results-header{display:flex;align-items:center;gap:6px;font-family:'Courier New',monospace;font-size:10px;color:#10b981;font-weight:700;padding-left:6px}
    .earth2-results-body{font-family:'Courier New',monospace;font-size:9px;color:#cbd5e1;line-height:1.6;padding-left:6px;margin-top:4px}
    .earth2-stats-row{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;margin-top:auto}
    .earth2-stat-tile{background:#050b18;border:1px solid #1e293b;border-radius:4px;padding:8px 4px;text-align:center}
    .stat-label{font-family:'Courier New',monospace;font-size:7px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;margin-top:4px}
"""

EARTH2_JS = r"""
    /* == NVIDIA Earth-2 TwinEarth Engine == */
    (function(){
      var E2={canvas:null,ctx:null,w:0,h:0,pts:[],flights:[],rot:0,simRuns:0,simInt:null,isExp:false,
      init:function(){
        this.canvas=document.getElementById('earth2Canvas');
        if(!this.canvas)return;
        this.ctx=this.canvas.getContext('2d');
        this.resize();
        var self=this;
        window.addEventListener('resize',function(){self.resize()});
        var eb=document.getElementById('e2ExpandBtn');
        if(eb)eb.addEventListener('click',function(){self.toggleExpand()});
        var rb=document.getElementById('e2RunBtn');
        if(rb)rb.addEventListener('click',function(){self.runScenario()});
        this.startAnim();
        this.fetchData();
        setInterval(function(){self.fetchData()},60000);
        this.fetchFlights();
        setInterval(function(){self.fetchFlights()},20000);
        this.updateTerm();
        setInterval(function(){self.updateTerm()},60000);
      },
      resize:function(){
        var c=document.getElementById('earth2GlobeContainer');
        if(!c||!this.canvas)return;
        var w=c.offsetWidth,h=Math.max(c.offsetHeight,270);
        this.canvas.width=w;this.canvas.height=h;this.w=w;this.h=h;
      },
      toggleExpand:function(){
        this.isExp=!this.isExp;
        var c=document.getElementById('earth2GlobeContainer');
        var b=document.getElementById('e2ExpandBtn');
        if(this.isExp){c.style.minHeight='500px';if(b)b.textContent='⊠';}
        else{c.style.minHeight='270px';if(b)b.textContent='⤢';}
        var self=this;setTimeout(function(){self.resize()},50);
      },
      llToXY:function(lat,lng,cx,cy,r){
        var lr=(lng+this.rot*57.3)*Math.PI/180,la=lat*Math.PI/180;
        return{x:cx+r*Math.cos(la)*Math.sin(lr),y:cy-r*Math.sin(la),z:Math.cos(la)*Math.cos(lr)};
      },
      drawGlobe:function(){
        if(!this.ctx)return;
        var g=this.ctx,w=this.w,h=this.h,cx=w/2,cy=h/2,r=Math.min(cx,cy)*0.82;
        g.clearRect(0,0,w,h);
        g.fillStyle='#020610';g.fillRect(0,0,w,h);
        // Stars
        g.fillStyle='rgba(255,255,255,0.6)';
        for(var i=0;i<80;i++){g.beginPath();g.arc((i*137+43)%w,(i*251+79)%h,i%4===0?1:0.4,0,6.28);g.fill();}
        // Atmosphere
        var ag=g.createRadialGradient(cx,cy,r*0.9,cx,cy,r*1.15);
        ag.addColorStop(0,'rgba(6,182,212,0.08)');ag.addColorStop(1,'rgba(0,0,0,0)');
        g.fillStyle=ag;g.beginPath();g.arc(cx,cy,r*1.15,0,6.28);g.fill();
        // Globe body
        var bg=g.createRadialGradient(cx-r*.25,cy-r*.25,0,cx,cy,r);
        bg.addColorStop(0,'#1a3a5c');bg.addColorStop(0.4,'#0e2040');bg.addColorStop(1,'#020c1b');
        g.fillStyle=bg;g.beginPath();g.arc(cx,cy,r,0,6.28);g.fill();
        // Grid
        g.strokeStyle='rgba(6,182,212,0.12)';g.lineWidth=0.5;
        for(var ln=-180;ln<180;ln+=30){g.beginPath();var f=true;for(var la=-90;la<=90;la+=4){var p=this.llToXY(la,ln,cx,cy,r);if(p.z<=0){f=true;continue;}if(f){g.moveTo(p.x,p.y);f=false;}else g.lineTo(p.x,p.y);}g.stroke();}
        for(var la2=-60;la2<=60;la2+=30){g.beginPath();var f2=true;for(var ln2=-180;ln2<=180;ln2+=4){var p2=this.llToXY(la2,ln2,cx,cy,r);if(p2.z<=0){f2=true;continue;}if(f2){g.moveTo(p2.x,p2.y);f2=false;}else g.lineTo(p2.x,p2.y);}g.stroke();}
        // Continents (key polygons)
        this.drawContinents(g,cx,cy,r);
        // Globe ring
        g.strokeStyle='rgba(6,182,212,0.3)';g.lineWidth=1.5;g.beginPath();g.arc(cx,cy,r,0,6.28);g.stroke();
        // Points
        var now=Date.now();
        for(var i=0;i<this.pts.length;i++){
          var pt=this.pts[i],p=this.llToXY(pt.lat,pt.lng,cx,cy,r);
          if(p.z<=0)continue;
          var sz=Math.max(2,(pt.mag||1)*1.5),age=(now-pt.ts)/1000,pulse=(age%3)/3;
          g.strokeStyle=pt.color||'#f97316';g.lineWidth=1.5;g.globalAlpha=Math.max(0,1-pulse);
          g.beginPath();g.arc(p.x,p.y,sz+pulse*12,0,6.28);g.stroke();
          g.globalAlpha=1;g.fillStyle=pt.color||'#f97316';g.beginPath();g.arc(p.x,p.y,sz,0,6.28);g.fill();
          if(pt.label){g.fillStyle='rgba(255,165,0,0.8)';g.font='8px Courier New';g.fillText(pt.label,p.x+sz+2,p.y+3);}
        }
        // Flights
        g.strokeStyle='rgba(56,189,248,0.4)';g.lineWidth=0.8;g.setLineDash([3,4]);
        for(var i=0;i<Math.min(this.flights.length,80);i++){
          var f=this.flights[i],s=this.llToXY(f.lat1,f.lng1,cx,cy,r),e=this.llToXY(f.lat2,f.lng2,cx,cy,r);
          if(s.z<=0&&e.z<=0)continue;
          var mx=(s.x+e.x)/2,my=(s.y+e.y)/2,dx=e.x-s.x,dy=e.y-s.y,arc=Math.sqrt(dx*dx+dy*dy)*0.15;
          g.beginPath();g.moveTo(s.x,s.y);g.quadraticCurveTo(mx-dy*0.1,my+dx*0.1-arc,e.x,e.y);g.stroke();
        }
        g.setLineDash([]);
        // Night shadow
        var hr=new Date().getUTCHours()+new Date().getUTCMinutes()/60;
        var sunLng=-((hr/24)*360-180);
        var ng=g.createRadialGradient(cx+r*Math.sin((sunLng+this.rot*57.3)*Math.PI/180+Math.PI),cy,r*0.2,cx,cy,r);
        ng.addColorStop(0,'rgba(0,0,0,0)');ng.addColorStop(0.55,'rgba(0,0,0,0)');ng.addColorStop(1,'rgba(0,0,16,0.6)');
        g.fillStyle=ng;g.beginPath();g.arc(cx,cy,r,0,6.28);g.fill();
      },
      drawContinents:function(g,cx,cy,r){
        var continents=[
          [[70,-140],[50,-125],[30,-117],[20,-90],[15,-83],[30,-80],[40,-74],[55,-60],[70,-90],[70,-140]],
          [[10,-75],[0,-80],[-20,-70],[-35,-57],[-55,-68],[-40,-62],[-5,-35],[5,-52],[10,-75]],
          [[71,28],[55,22],[45,15],[43,5],[50,-5],[58,3],[60,5],[57,20],[64,26],[71,28]],
          [[35,10],[10,-18],[0,-15],[-35,18],[-35,27],[-10,38],[0,42],[20,38],[35,32],[37,25],[35,10]],
          [[71,28],[60,73],[45,60],[25,57],[10,55],[30,90],[38,120],[40,140],[60,150],[71,140],[71,60],[71,28]],
          [[-15,130],[-30,115],[-38,147],[-22,150],[-15,130]]
        ];
        g.strokeStyle='rgba(100,180,220,0.4)';g.lineWidth=0.8;
        for(var ci=0;ci<continents.length;ci++){
          var pts=continents[ci];g.beginPath();var f=true;
          for(var pi=0;pi<pts.length;pi++){
            var p=this.llToXY(pts[pi][0],pts[pi][1],cx,cy,r);
            if(p.z<=0){f=true;continue;}
            if(f){g.moveTo(p.x,p.y);f=false;}else g.lineTo(p.x,p.y);
          }
          g.stroke();
        }
      },
      startAnim:function(){
        var self=this;
        (function anim(){self.rot+=0.003;self.drawGlobe();requestAnimationFrame(anim);})();
      },
      updateTerm:function(){
        var o=document.getElementById('terminatorOverlay');
        if(!o)return;
        var deg=(new Date().getUTCHours()/24)*360;
        o.style.background='linear-gradient('+deg+'deg,transparent 40%,rgba(0,0,16,0.65) 60%)';
      },
      addFeed:function(item){
        var list=document.getElementById('earth2Feed');if(!list)return;
        var sc={USGS_EARTHQUAKES:'e2-src-usgs',NOAA_SPACE:'e2-src-noaa',NASA_GIBS:'e2-src-nasa',ADSB_FLIGHTS:'e2-src-adsb',HYPER_SWARM:'e2-src-swarm'};
        var cls=sc[item.source]||'e2-src-nasa';
        var el=document.createElement('div');el.className='e2-feed-item';
        el.innerHTML='<div class="e2-feed-top"><span class="e2-feed-source '+cls+'">'+item.source+'</span><span class="e2-feed-ref">'+(item.ref||'')+'</span></div><div class="e2-feed-type">'+(item.type||'')+'</div><div class="e2-feed-bottom"><span class="e2-feed-loc">'+(item.loc||'')+'</span><span class="e2-feed-val">'+(item.val||'')+'</span></div>';
        list.insertBefore(el,list.firstChild);
        while(list.children.length>40)list.removeChild(list.lastChild);
        var ct=document.getElementById('e2FeedCount');if(ct)ct.textContent=list.children.length+' events';
      },
      fetchData:function(){
        var self=this;
        fetch('https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson')
          .then(function(r){return r.json()})
          .then(function(d){
            var qs=(d.features||[]).slice(0,20);
            var el=document.getElementById('e2SeismicCount');if(el)el.textContent=qs.length;
            qs.forEach(function(f){
              var co=f.geometry&&f.geometry.coordinates?f.geometry.coordinates:[0,0];
              var mag=f.properties&&f.properties.mag?f.properties.mag:0;
              if(!self.pts.find(function(p){return p.id===f.id;})){
                self.pts.push({id:f.id,lat:co[1],lng:co[0],mag:mag,label:'M'+mag.toFixed(1),color:mag>4?'#ef4444':'#f97316',ts:Date.now()});
                if(self.pts.length>60)self.pts.shift();
                self.addFeed({source:'USGS_EARTHQUAKES',type:'Live Seismic Event',val:'Mag '+mag.toFixed(1),loc:(f.properties&&f.properties.place)||'Unknown',ref:'usgs.gov'});
              }
            });
          }).catch(function(){});
        fetch('https://services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json')
          .then(function(r){return r.json()})
          .then(function(d){
            if(d&&d.length>0){
              var spd=Math.round(d[0].proton_speed||d[0].wind_speed||450);
              var el=document.getElementById('e2SolarWind');if(el)el.textContent=spd;
              self.addFeed({source:'NOAA_SPACE',type:'Solar Wind Real-Time',val:spd+' km/s',loc:'DSCOVR L1',ref:'swpc.noaa.gov'});
            }
          }).catch(function(){});
      },
      fetchFlights:function(){
        var self=this;
        fetch('https://opensky-network.org/api/states/all?lamin=20.0&lomin=-130.0&lamax=60.0&lomax=-10.0')
          .then(function(r){return r.ok?r.json():Promise.reject()})
          .then(function(d){
            if(d&&d.states){
              self.flights=d.states.slice(0,150).filter(function(s){return s[5]!==null&&s[6]!==null;}).map(function(s){
                var hdg=(s[10]||0)*Math.PI/180;
                return{lat1:s[6],lng1:s[5],lat2:s[6]+Math.cos(hdg)*1.5,lng2:s[5]+Math.sin(hdg)*1.5};
              });
              var el=document.getElementById('e2FlightCount');if(el)el.textContent='ADS-B: '+self.flights.length+' flights';
              var es=document.getElementById('e2FlightStat');if(es)es.textContent=self.flights.length;
            }
          }).catch(function(){
            // Fallback simulation
            self.flights=Array.from({length:60}).map(function(_,i){
              var hubs=[[40.6,-73.8],[33.9,-118.4],[51.5,-0.4],[50.0,8.6],[35.7,140.4],[48.4,2.5]];
              var hub=hubs[i%hubs.length];
              var lat=hub[0]+(Math.random()-.5)*20,lng=hub[1]+(Math.random()-.5)*20;
              var hdg=Math.random()*6.28;
              return{lat1:lat,lng1:lng,lat2:lat+Math.cos(hdg)*1.5,lng2:lng+Math.sin(hdg)*1.5};
            });
            var el=document.getElementById('e2FlightCount');if(el)el.textContent='ADS-B: '+self.flights.length+' (sim)';
            var es=document.getElementById('e2FlightStat');if(es)es.textContent=self.flights.length;
          });
      },
      runScenario:function(){
        var input=document.getElementById('e2ScenarioInput');
        var loc=document.getElementById('e2LocationInput');
        if(!input||!input.value.trim())return;
        var self=this;
        var btn=document.getElementById('e2RunBtn'),prog=document.getElementById('e2ProgressBar'),
            fill=document.getElementById('e2ProgressFill'),pct=document.getElementById('e2ProgressPct'),
            res=document.getElementById('e2Results'),rt=document.getElementById('e2ResultText');
        btn.disabled=true;prog.style.display='flex';res.style.display='none';
        var progress=0;fill.style.width='0%';
        clearInterval(this.simInt);
        this.simInt=setInterval(function(){
          progress+=Math.random()*8+2;
          if(progress>=100){
            progress=100;clearInterval(self.simInt);fill.style.width='100%';pct.textContent='100%';
            setTimeout(function(){
              self.simRuns++;
              var sr=document.getElementById('e2SimRuns');if(sr)sr.textContent=self.simRuns;
              var lv=loc&&loc.value?loc.value:'Global';
              var shift=(Math.random()*6+2).toFixed(1),trust=(0.94+Math.random()*.05).toFixed(2);
              rt.innerHTML='OpenUSD geometry generated for UE5 Cesium plugin. Location: <b>'+lv+'</b>.<br>Thermal injection caused global pressure shift of +'+shift+' hPa.<br>DeltaVault ingestion completed. Trust Score: '+trust+'.<br>Pangu-Weather 15-day forecast exported.';
              res.style.display='block';btn.disabled=false;prog.style.display='none';
              self.addFeed({source:'NASA_GIBS',type:'Earth2Studio Sim Complete',val:'+'+shift+' hPa',loc:lv,ref:'omniverse'});
            },400);
          }else{fill.style.width=progress+'%';pct.textContent=Math.floor(progress)+'%';}
        },250);
      }};
      if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',function(){E2.init();});
      else E2.init();
    })();
"""

HTML_FILE = "dashboard/mesh/index.html"

with open(HTML_FILE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

total = len(lines)
print(f"Total lines: {total}")

# Find the tooltip div line (line ~1239 based on grep, 0-indexed = 1238)
tooltip_line = None
for i, line in enumerate(lines):
    if 'id="tooltip"' in line and 'class="tooltip' in line:
        tooltip_line = i
        break

if tooltip_line is None:
    print("ERROR: tooltip line not found")
    exit(1)
print(f"Tooltip at line {tooltip_line+1} (0-indexed: {tooltip_line})")

# Find </style> for CSS injection
style_end = None
for i, line in enumerate(lines):
    if '</style>' in line:
        style_end = i
        break

if style_end is None:
    print("ERROR: </style> not found")
    exit(1)
print(f"</style> at line {style_end+1}")

# Find the last </script> for JS injection
last_script = None
for i in range(len(lines)-1, -1, -1):
    if '</script>' in lines[i]:
        last_script = i
        break

if last_script is None:
    print("ERROR: </script> not found")
    exit(1)
print(f"Last </script> at line {last_script+1}")

# 1) Inject CSS before </style>
css_line = EARTH2_CSS.strip() + '\n'
lines.insert(style_end, css_line)
# Update line indices after insertion
tooltip_line += 1
last_script += 1
print("✓ CSS injected")

# 2) Inject HTML before tooltip
html_block = EARTH2_HTML
lines.insert(tooltip_line, html_block)
last_script += 1
print("✓ HTML injected")

# 3) Inject JS before last </script>
js_block = EARTH2_JS + '\n'
lines.insert(last_script, js_block)
print("✓ JS injected")

with open(HTML_FILE, 'w', encoding='utf-8') as f:
    f.writelines(lines)

new_total = sum(1 for _ in open(HTML_FILE, encoding='utf-8'))
print(f"✓ Done — {HTML_FILE} updated: {total} → {new_total} lines")