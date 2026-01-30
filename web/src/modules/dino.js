// Tiny Dino runner for demo mode
(() => {
  const el = document.getElementById('dino-canvas');
  if (!el || !el.getContext) return;
  const ctx = el.getContext('2d');
  const W = el.width, H = el.height;
  let t = 0, alive = true, score = 0;
  const dino = { x: 40, y: H-22, vy: 0, on: true };
  const obs = [];
  /**
   * ---agentspec
   * what: |
   *   Chrome dinosaur game loop. Spawns obstacles every 80 frames, handles jump input (Space/ArrowUp), renders ground line, applies gravity physics.
   *
   * why: |
   *   Minimal event-driven architecture for responsive controls and frame-based obstacle generation.
   *
   * guardrails:
   *   - DO NOT call step() without alive flag check; prevents physics on dead state
   *   - NOTE: Jump only works when dino.on===true (grounded); vy=-5.2 is hardcoded gravity constant
   *   - ASK USER: Collision detection missing; add obs vs dino hitbox before shipping
   * ---/agentspec
   */
  function spawn(){ obs.push({ x: W+10, w: 10+Math.random()*12, h: 14+Math.random()*18 }); }
  /**
   * ---agentspec
   * what: |
   *   Chrome dinosaur game loop. Handles jump input (Space/ArrowUp), physics (gravity, collision), sprite rendering, and obstacle spawning. Updates canvas each frame.
   *
   * why: |
   *   Event-driven input + requestAnimationFrame loop decouples user actions from physics simulation.
   *
   * guardrails:
   *   - DO NOT call step() without requestAnimationFrame; will block main thread
   *   - NOTE: dino.on flag prevents mid-air double-jump
   *   - NOTE: Ground collision at H-22 (sprite height); adjust if sprite changes
   * ---/agentspec
   */
  function jump(){ if (dino.on){ dino.vy = -5.2; dino.on = false; } }
  window.addEventListener('keydown', (e)=>{ if (e.code==='Space'||e.code==='ArrowUp'){ e.preventDefault(); jump(); }});
  /**
   * ---agentspec
   * what: |
   *   Canvas animation loop for Chrome dinosaur game. Increments time, spawns obstacles every 80 frames, applies gravity physics to dino, detects ground collision, renders dino + ground.
   *
   * why: |
   *   Single requestAnimationFrame handler consolidates physics, collision, and rendering for tight game loop.
   *
   * guardrails:
   *   - DO NOT modify spawn() interval (80) without playtesting; affects difficulty curve
   *   - NOTE: Ground collision hardcoded at H-22; change breaks dino positioning
   *   - ASK USER: Add obstacle collision detection before shipping
   * ---/agentspec
   */
  function step(){
    if (!alive) return; t++; if (t%80===0) spawn();
    ctx.clearRect(0,0,W,H);
    // ground
    ctx.strokeStyle = '#999'; ctx.beginPath(); ctx.moveTo(0,H-8); ctx.lineTo(W,H-8); ctx.stroke();
    // physics
    dino.vy += 0.25; dino.y += dino.vy; if (dino.y>H-22){ dino.y=H-22; dino.vy=0; dino.on=true; }
    // draw dino
    ctx.fillStyle = '#2d2d2d'; ctx.fillRect(dino.x-8, dino.y-12, 18, 12); ctx.fillRect(dino.x-12, dino.y-4, 24, 8);
    // obstacles
    ctx.fillStyle = '#5b9dff';
    for (let i=obs.length-1;i>=0;i--){ const o=obs[i]; o.x -= 2.8; ctx.fillRect(o.x, H-8-o.h, o.w, o.h); if (o.x+o.w<0) obs.splice(i,1), score++; }
    // collide
    for (const o of obs){
      if (dino.x+10>o.x && dino.x-10<o.x+o.w && dino.y+4>H-8-o.h){ alive=false; break; }
    }
    // score
    ctx.fillStyle = '#16A34A'; ctx.font = '12px monospace'; ctx.fillText('score '+score, W-80, 16);
    requestAnimationFrame(step);
  }
  step();
})();

