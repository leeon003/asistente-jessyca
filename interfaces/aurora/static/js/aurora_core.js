/** Obsidiana — expressive, dependency-free canvas orb.
 * AuroraCore3D public API retained for Studio and the Aurora controller.
 */
class AuroraCore3D {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    if (!this.container) throw new Error('Orb container not found');
    this.canvas = document.createElement('canvas');
    this.ctx = this.canvas.getContext('2d');
    if (!this.ctx) throw new Error('Canvas 2D unavailable');
    this.canvas.style.cssText = 'display:block;width:100%;height:100%;pointer-events:none';
    this.canvas.setAttribute('role', 'img');
    this.container.appendChild(this.canvas);
    this.activeState = 'IDLE';
    this.audioAmplitude = 0;
    this.lastAudioUpdateTime = -Infinity;
    this.reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || false;
    this.quality = 'high';
    this.disposed = false;
    this.frame = null;
    this._resize = () => this.onResize();
    this._visibility = () => {
      if (this.frame !== null) cancelAnimationFrame(this.frame);
      this.frame = null;
      if (!document.hidden && !this.disposed) this.animate(performance.now());
    };
    window.addEventListener('resize', this._resize);
    document.addEventListener('visibilitychange', this._visibility);
    this.observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(this._resize) : null;
    this.observer?.observe(this.container);
    this.setTheme({}, 'IDLE');
    this.onResize();
    this._visibility();
  }

  setTheme(theme = {}, stateName = 'IDLE') {
    this.currentTheme = theme;
    this.activeState = String(stateName).toUpperCase();
    const groups = {
      LISTENING: ['LISTENING', 'WAKEWORD'],
      THINKING: ['THINKING', 'TRANSCRIBING', 'ROUTING', 'EXECUTING', 'SEARCHING'],
      SPEAKING: ['SPEAKING', 'RESPONDING'],
      SUCCESS: ['SUCCESS', 'COMPLETED', 'COMPLETE'],
      CLARIFYING: ['CLARIFYING', 'CONFIRMING', 'AWAITING_CONFIRMATION'],
      ERROR: ['ERROR', 'BLOCKED', 'FAILED']
    };
    this.expression = Object.keys(groups).find(key => groups[key].includes(this.activeState)) || 'IDLE';
    const labels = {IDLE:'En reposo', LISTENING:'Escuchando', THINKING:'Procesando', SPEAKING:'Hablando', SUCCESS:'Completado', CLARIFYING:'Esperando aclaración o confirmación', ERROR:'Necesita atención'};
    this.canvas.setAttribute('aria-label', `Jessyca · ${labels[this.expression]}`);
  }
  setAudioAmplitude(value) {
    this.audioAmplitude = Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
    this.lastAudioUpdateTime = performance.now();
  }
  setQuality(level) { this.quality = level; this.onResize(); }
  setReducedMotion(enabled) { this.reducedMotion = Boolean(enabled); }
  // Compatibility with the optional Aurora FX controller; never changes task state.
  triggerShockwave() { this.highlightUntil = performance.now() + 650; }
  onResize() {
    const box = this.container.getBoundingClientRect();
    this.width = Math.max(1, box.width);
    this.height = Math.max(1, box.height);
    this.dpr = Math.min(window.devicePixelRatio || 1, this.quality === 'low' ? 1 : 2);
    this.canvas.width = Math.round(this.width * this.dpr);
    this.canvas.height = Math.round(this.height * this.dpr);
  }
  animate(now) {
    if (this.disposed || document.hidden) return;
    this.draw(now);
    this.frame = requestAnimationFrame(time => this.animate(time));
  }
  draw(now) {
    const c = this.ctx, w = this.width, h = this.height;
    const t = this.reducedMotion ? 0 : now / 1000;
    const amp = now - this.lastAudioUpdateTime < 250 ? this.audioAmplitude : 0;
    const motionAmp = this.reducedMotion ? 0 : amp;
    const state = this.expression;
    const thinking = state === 'THINKING', listening = state === 'LISTENING';
    const success = state === 'SUCCESS', unsure = state === 'CLARIFYING', error = state === 'ERROR';
    c.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    c.clearRect(0, 0, w, h);
    c.save();
    const scale = Math.min(w, h) / 560;
    c.translate(w / 2, h / 2 + Math.sin(t * 1.2) * 2 * scale);
    c.scale(scale, scale);
    const ellipse = (x,y,rx,ry,fill) => { c.beginPath(); c.ellipse(x,y,rx,ry,0,0,Math.PI*2); c.fillStyle=fill; c.fill(); };
    const stroke = (x1,y1,cx,cy,x2,y2,color,width=4) => { c.beginPath(); c.moveTo(x1,y1); c.quadraticCurveTo(cx,cy,x2,y2); c.strokeStyle=color;c.lineWidth=width;c.lineCap='round';c.stroke(); };
    const accent = error ? '#e7ac90' : '#9bddee';
    let glow = c.createRadialGradient(0,35,150,0,35,248);
    glow.addColorStop(0,'rgba(83,167,198,.16)');glow.addColorStop(1,'rgba(83,167,198,0)');
    ellipse(0,35,250,250,glow);
    let rim = c.createLinearGradient(-170,-190,180,210);
    rim.addColorStop(0,'#c3cbd2');rim.addColorStop(.23,'#343b46');rim.addColorStop(.48,'#10151e');rim.addColorStop(.77,'#7c929f');rim.addColorStop(1,'#26303b');
    ellipse(0,0,205,205,rim);
    ellipse(0,0,201,201,'#06090f');
    let glass = c.createRadialGradient(-85,-115,10,25,40,260);
    glass.addColorStop(0,'#303642');glass.addColorStop(.45,'#10151f');glass.addColorStop(1,'#030509');
    ellipse(0,0,196,196,glass);
    c.save();c.beginPath();c.arc(0,0,195,0,Math.PI*2);c.clip();
    let sheen = c.createLinearGradient(-100,-190,30,40);
    sheen.addColorStop(0,'rgba(255,255,255,.12)');sheen.addColorStop(1,'rgba(255,255,255,0)');
    ellipse(-40,-155,220,115,sheen);
    c.restore();
    c.beginPath();c.arc(0,0,201,.28,Math.PI-.28);c.strokeStyle=accent;c.globalAlpha=.3 + motionAmp*.4 + (!this.reducedMotion && now < this.highlightUntil ? .2 : 0);c.lineWidth=1.5;c.stroke();c.globalAlpha=1;
    // Brows and pupils carry the gesture; no success is inferred from silence.
    const gazeX = thinking ? 9 : listening ? Math.sin(t*.7)*3 : 0;
    const gazeY = thinking ? -12 : 0;
    // Smooth eyelid closure; reduced motion keeps the chosen expression static.
    const blinkPhase = t % 5.8;
    const openness = this.reducedMotion ? 1 : 1 - Math.max(0, 1 - Math.abs(blinkPhase - 5.62) / .14);
    const eyeHeight = Math.max(2, (listening ? 46 : unsure ? 40 : error ? 36 : 42) * openness);
    c.shadowColor='rgba(199,232,255,.45)';c.shadowBlur=12;
    for (const side of [-1,1]) {
      const x=side*66;
      if(success) {
        stroke(x-27,-15,x,-49,x+27,-15,'#fff1df',6);
        stroke(x+side*25,-17,x+side*34,-19,x+side*38,-26,'#fff1df',2.5);
      } else {
        // Tall oval eyes and clipped pupils remain inside the lids while blinking.
        ellipse(x,-24,29,eyeHeight,'#fff1df');
        c.save();
        c.beginPath();c.ellipse(x,-24,29,eyeHeight,0,0,Math.PI*2);c.clip();
        c.shadowBlur=0;
        ellipse(x+gazeX,-22+gazeY,16,26,'#090e17');
        ellipse(x+gazeX-5,-33+gazeY,3.5,5,'#ecf5ff');
        ellipse(x+gazeX+6,-13+gazeY,1.5,2,'#90a8bb');
        c.restore();
        // A subtle upper lid and swept outer lash, mirrored on each eye.
        stroke(x-28,-24-eyeHeight*.35,x,-24-eyeHeight*1.55,x+28,-24-eyeHeight*.35,'#c8d1dc',1.8);
        const outerX=x+side*28, outerY=-24-eyeHeight*.35;
        stroke(outerX,outerY,outerX+side*9,outerY+1,outerX+side*14,outerY-8,'#dbe3ec',2.5);
      }
      const browY = unsure && side===1 ? -103 : thinking && side===-1 ? -102 : listening ? -103 : -94;
      // Tapered arched brows: pronounced silhouette without a heavy straight bar.
      c.beginPath();
      c.moveTo(x-28,browY+8);
      c.bezierCurveTo(x-10,browY-10,x+11,browY-13,x+28,browY+2+(error?8:0));
      c.bezierCurveTo(x+9,browY-3,x-7,browY-2,x-28,browY+8);
      c.fillStyle='#f1e8dc';c.fill();
    }
    c.shadowBlur=0;
    if(state==='SPEAKING') ellipse(0,62,13+motionAmp*8,5+motionAmp*22,'#e5edf0');
    else if(unsure) stroke(-15,62,0,56,15,64,'#c7d3dc',3);
    else if(error) stroke(-15,66,0,54,15,66,'#c7d3dc',3);
    else stroke(-19,57,0,success?79:68,19,57,'#e1e8ec',3);
    // Quiet at zero amplitude. Speaking/listening react only to supplied audio.
    for(let i=0;i<17;i++) {
      const x=(i-8)*9, y=153-Math.abs(i-8)*1.15;
      const envelope=Math.max(0,1-Math.abs(i-8)/9);
      const height=2+motionAmp*22*envelope*(.6+.4*Math.sin(t*13+i));
      c.globalAlpha=thinking ? .35+.3*Math.sin(t*2-i*.35) : .35+motionAmp*.6;
      stroke(x,y-height/2,x,y,x,y+height/2,accent,2.5);
    }
    c.globalAlpha=1;
    c.restore();
  }
  dispose() {
    if(this.disposed) return;
    this.disposed=true;
    if(this.frame!==null) cancelAnimationFrame(this.frame);
    window.removeEventListener('resize',this._resize);
    document.removeEventListener('visibilitychange',this._visibility);
    this.observer?.disconnect();
    this.canvas.remove();
  }
}
