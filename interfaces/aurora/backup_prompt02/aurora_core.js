/**
 * JESSYCA ORB — Núcleo Aurora 3D
 * Motor Gráfico Three.js con Shaders GLSL Personalizados
 * Identidad visual original de JESSYCA (No clon de Perplexity)
 */

class AuroraCore3D {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.scene = null;
    this.camera = null;
    this.renderer = null;

    // Componentes del Núcleo Aurora
    this.nucleusMesh = null;
    this.membraneMesh = null;
    this.orbitalRings = [];
    this.filamentsMesh = null;
    this.particlesMesh = null;
    this.particlePositions = null;
    this.particleVelocities = null;

    // Parámetros dinámicos y Shader Uniforms
    this.clock = new THREE.Clock();
    this.elapsedTime = 0;
    this.audioAmplitude = 0.0;
    this.quality = 'high'; // 'high' | 'medium' | 'low'
    this.reducedMotion = false;

    // Configuración activa interpolada
    this.currentTheme = {
      primaryColor: new THREE.Color('#4CC9F0'),
      secondaryColor: new THREE.Color('#7B2CFB'),
      accentColor: new THREE.Color('#2EE6D6'),
      corePulseSpeed: 0.6,
      noiseDisplacement: 0.15,
      orbitalSpeed: 0.4,
      particleActivity: 0.3,
      glowIntensity: 0.8
    };

    this.targetTheme = Object.assign({}, this.currentTheme);
    this.lerpFactor = 0.05;

    // Métricas de Rendimiento (FPS)
    this.frameCount = 0;
    this.fps = 60;
    this.lastFpsUpdate = 0;

    this.init();
  }

  init() {
    // 1. Escena
    this.scene = new THREE.Scene();

    // 2. Cámara
    const width = this.container.clientWidth || window.innerWidth;
    const height = this.container.clientHeight || window.innerHeight;
    this.camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
    this.camera.position.set(0, 0, 7.5);

    // 3. Renderizador WebGL
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance'
    });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.2;
    this.container.appendChild(this.renderer.domElement);

    // 4. Construcción de componentes tridimensionales
    this.buildNucleus();
    this.buildMembrane();
    this.buildOrbitalRings();
    this.buildFilaments();
    this.buildParticleSwarm();
    this.buildLighting();

    // 5. Event Listeners
    window.addEventListener('resize', () => this.onResize());

    // 6. Iniciar bucle de renderizado
    this.animate();
  }

  // --- COMPONENTE 1: NÚCLEO CENTRAL ORGÁNICO ---
  buildNucleus() {
    const detail = this.quality === 'low' ? 3 : 5;
    const geometry = new THREE.IcosahedronGeometry(1.2, detail);

    // Vertex Shader con desplazamiento de ruido 3D
    const vertexShader = `
      uniform float uTime;
      uniform float uNoiseStrength;
      uniform float uPulseSpeed;
      uniform float uAudioAmp;
      varying vec3 vNormal;
      varying vec3 vPosition;
      varying float vDisplacement;

      // Pseudo-random noise function
      vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
      vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
      vec4 permute(vec4 x) { return mod289(((x*34.0)+1.0)*x); }
      vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

      float snoise(vec3 v) {
        const vec2 C = vec2(1.0/6.0, 1.0/3.0);
        const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
        vec3 i  = floor(v + dot(v, C.yyy));
        vec3 x0 = v - i + dot(i, C.xxx);
        vec3 g = step(x0.yzx, x0.xyz);
        vec3 l = 1.0 - g;
        vec3 i1 = min(g.xyz, l.zxy);
        vec3 i2 = max(g.xyz, l.zxy);
        vec3 x1 = x0 - i1 + C.xxx;
        vec3 x2 = x0 - i2 + C.yyy;
        vec3 x3 = x0 - D.yyy;
        i = mod289(i);
        vec4 p = permute(permute(permute(
                  i.z + vec4(0.0, i1.z, i2.z, 1.0))
                + i.y + vec4(0.0, i1.y, i2.y, 1.0))
                + i.x + vec4(0.0, i1.x, i2.x, 1.0));
        float n_ = 0.142857142857;
        vec3  ns = n_ * D.wyz - D.xzx;
        vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
        vec4 x_ = floor(j * ns.z);
        vec4 y_ = floor(j - 7.0 * x_);
        vec4 x = x_ *ns.x + ns.yyyy;
        vec4 y = y_ *ns.x + ns.yyyy;
        vec4 h = 1.0 - abs(x) - abs(y);
        vec4 b0 = vec4(x.xy, y.xy);
        vec4 b1 = vec4(x.zw, y.zw);
        vec4 s0 = floor(b0)*2.0 + 1.0;
        vec4 s1 = floor(b1)*2.0 + 1.0;
        vec4 sh = -step(h, vec4(0.0));
        vec4 a0 = b0.xzyw + s0.xzyw*sh.xxyy;
        vec4 a1 = b1.xzyw + s1.xzyw*sh.zzww;
        vec3 p0 = vec3(a0.xy, h.x);
        vec3 p1 = vec3(a0.zw, h.y);
        vec3 p2 = vec3(a1.xy, h.z);
        vec3 p3 = vec3(a1.zw, h.w);
        vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2, p2), dot(p3,p3)));
        p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
        vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
        m = m * m;
        return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
      }

      void main() {
        vNormal = normalize(normalMatrix * normal);
        vPosition = position;
        float pulse = sin(uTime * uPulseSpeed) * 0.08 + (uAudioAmp * 0.25);
        float noise = snoise(position * 1.8 + vec3(uTime * 0.4));
        vDisplacement = noise;
        vec3 newPos = position + normal * (noise * uNoiseStrength + pulse);
        gl_Position = projectionMatrix * modelViewMatrix * vec4(newPos, 1.0);
      }
    `;

    // Fragment Shader con gradiente cromático y dispersión de luz
    const fragmentShader = `
      uniform vec3 uColorPrimary;
      uniform vec3 uColorSecondary;
      uniform vec3 uColorAccent;
      uniform float uGlowIntensity;
      varying vec3 vNormal;
      varying vec3 vPosition;
      varying float vDisplacement;

      void main() {
        float fresnel = pow(1.0 - abs(dot(vNormal, vec3(0.0, 0.0, 1.0))), 2.2);
        vec3 baseColor = mix(uColorSecondary, uColorPrimary, vDisplacement * 0.5 + 0.5);
        vec3 finalColor = mix(baseColor, uColorAccent, fresnel * 0.8) * uGlowIntensity;
        gl_FragColor = vec4(finalColor, 0.88);
      }
    `;

    this.nucleusMaterial = new THREE.ShaderMaterial({
      vertexShader: vertexShader,
      fragmentShader: fragmentShader,
      uniforms: {
        uTime: { value: 0 },
        uNoiseStrength: { value: this.currentTheme.noiseDisplacement },
        uPulseSpeed: { value: this.currentTheme.corePulseSpeed },
        uAudioAmp: { value: 0 },
        uColorPrimary: { value: this.currentTheme.primaryColor },
        uColorSecondary: { value: this.currentTheme.secondaryColor },
        uColorAccent: { value: this.currentTheme.accentColor },
        uGlowIntensity: { value: this.currentTheme.glowIntensity }
      },
      transparent: true,
      wireframe: false
    });

    this.nucleusMesh = new THREE.Mesh(geometry, this.nucleusMaterial);
    this.scene.add(this.nucleusMesh);
  }

  // --- COMPONENTE 2: MEMBRANA ENERGÉTICA HOLOGRÁFICA ---
  buildMembrane() {
    const geometry = new THREE.SphereGeometry(1.65, 32, 32);

    const vertexShader = `
      varying vec3 vNormal;
      varying vec3 vViewPosition;
      void main() {
        vNormal = normalize(normalMatrix * normal);
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        vViewPosition = -mvPosition.xyz;
        gl_Position = projectionMatrix * mvPosition;
      }
    `;

    const fragmentShader = `
      uniform vec3 uColorPrimary;
      uniform vec3 uColorAccent;
      uniform float uTime;
      varying vec3 vNormal;
      varying vec3 vViewPosition;

      void main() {
        vec3 normal = normalize(vNormal);
        vec3 viewDir = normalize(vViewPosition);
        float fresnel = pow(1.0 - abs(dot(normal, viewDir)), 3.0);
        float wave = sin(vViewPosition.y * 3.0 + uTime * 2.0) * 0.15 + 0.85;
        vec3 color = mix(uColorPrimary, uColorAccent, fresnel) * wave;
        gl_FragColor = vec4(color, fresnel * 0.45);
      }
    `;

    this.membraneMaterial = new THREE.ShaderMaterial({
      vertexShader: vertexShader,
      fragmentShader: fragmentShader,
      uniforms: {
        uTime: { value: 0 },
        uColorPrimary: { value: this.currentTheme.primaryColor },
        uColorAccent: { value: this.currentTheme.accentColor }
      },
      transparent: true,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
      depthWrite: false
    });

    this.membraneMesh = new THREE.Mesh(geometry, this.membraneMaterial);
    this.scene.add(this.membraneMesh);
  }

  // --- COMPONENTE 3: TRES ANILLOS ORBITALES ASIMÉTRICOS ---
  buildOrbitalRings() {
    const ringConfigs = [
      { radius: 2.15, tube: 0.022, rotX: 0.8, rotY: 0.2, speed: 0.5, color: '#4CC9F0' },
      { radius: 2.50, tube: 0.016, rotX: -0.5, rotY: 1.1, speed: -0.35, color: '#7B2CFB' },
      { radius: 2.85, tube: 0.012, rotX: 0.3, rotY: -0.9, speed: 0.25, color: '#2EE6D6' }
    ];

    ringConfigs.forEach((cfg, idx) => {
      const geometry = new THREE.TorusGeometry(cfg.radius, cfg.tube, 16, 100);
      const material = new THREE.MeshBasicMaterial({
        color: new THREE.Color(cfg.color),
        transparent: true,
        opacity: 0.65,
        blending: THREE.AdditiveBlending
      });

      const ringMesh = new THREE.Mesh(geometry, material);
      ringMesh.rotation.x = cfg.rotX;
      ringMesh.rotation.y = cfg.rotY;
      ringMesh.userData = { speed: cfg.speed, baseSpeed: cfg.speed };

      this.orbitalRings.push(ringMesh);
      this.scene.add(ringMesh);
    });
  }

  // --- COMPONENTE 4: FILAMENTOS DE LUZ CUÁNTICA ---
  buildFilaments() {
    const count = 48;
    const points = [];
    for (let i = 0; i < count; i++) {
      const u = Math.random();
      const v = Math.random();
      const theta = u * 2.0 * Math.PI;
      const phi = Math.acos(2.0 * v - 1.0);
      const r = 1.25;
      const x = r * Math.sin(phi) * Math.cos(theta);
      const y = r * Math.sin(phi) * Math.sin(theta);
      const z = r * Math.cos(phi);
      points.push(new THREE.Vector3(x, y, z));
    }

    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    this.filamentsMaterial = new THREE.LineBasicMaterial({
      color: this.currentTheme.accentColor,
      transparent: true,
      opacity: 0.35,
      blending: THREE.AdditiveBlending
    });

    this.filamentsMesh = new THREE.LineSegments(geometry, this.filamentsMaterial);
    this.scene.add(this.filamentsMesh);
  }

  // --- COMPONENTE 5: ENJAMBRE DE PARTÍCULAS ORBITALES ---
  buildParticleSwarm() {
    const particleCount = this.quality === 'low' ? 300 : (this.quality === 'medium' ? 650 : 1100);
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    const velocities = new Float32Array(particleCount * 3);
    const colors = new Float32Array(particleCount * 3);

    const c1 = this.currentTheme.primaryColor;
    const c2 = this.currentTheme.accentColor;

    for (let i = 0; i < particleCount; i++) {
      // Distribución en toroide espiral asimétrico (no esfera plana)
      const u = Math.random() * Math.PI * 2;
      const v = Math.random() * Math.PI * 2;
      const rOrb = 1.8 + Math.random() * 1.5;

      const x = (rOrb + 0.3 * Math.cos(v)) * Math.cos(u);
      const y = (rOrb + 0.3 * Math.cos(v)) * Math.sin(u) * 0.7;
      const z = 0.6 * Math.sin(v) + (Math.random() - 0.5) * 0.5;

      positions[i * 3] = x;
      positions[i * 3 + 1] = y;
      positions[i * 3 + 2] = z;

      velocities[i * 3] = (Math.random() - 0.5) * 0.01;
      velocities[i * 3 + 1] = (Math.random() - 0.5) * 0.01;
      velocities[i * 3 + 2] = (Math.random() - 0.5) * 0.01;

      // Gradiente cromático por partícula
      const mixRatio = Math.random();
      const pColor = c1.clone().lerp(c2, mixRatio);
      colors[i * 3] = pColor.r;
      colors[i * 3 + 1] = pColor.g;
      colors[i * 3 + 2] = pColor.b;
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    this.particlePositions = positions;
    this.particleVelocities = velocities;

    this.particlesMaterial = new THREE.PointsMaterial({
      size: 0.035,
      vertexColors: true,
      transparent: true,
      opacity: 0.75,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });

    this.particlesMesh = new THREE.Points(geometry, this.particlesMaterial);
    this.scene.add(this.particlesMesh);
  }

  buildLighting() {
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    this.scene.add(ambientLight);

    const pointLight = new THREE.PointLight(0x4cc9f0, 2.0, 20);
    pointLight.position.set(2, 3, 4);
    this.scene.add(pointLight);

    const backLight = new THREE.PointLight(0x7b2cfb, 1.5, 20);
    backLight.position.set(-2, -3, -4);
    this.scene.add(backLight);
  }

  setTheme(theme) {
    this.targetTheme = {
      primaryColor: new THREE.Color(theme.primary_color),
      secondaryColor: new THREE.Color(theme.secondary_color),
      accentColor: new THREE.Color(theme.accent_color),
      corePulseSpeed: theme.core_pulse_speed,
      noiseDisplacement: theme.noise_displacement,
      orbitalSpeed: theme.orbital_speed,
      particleActivity: theme.particle_activity,
      glowIntensity: theme.glow_intensity
    };
  }

  setAudioAmplitude(amp) {
    this.audioAmplitude = Math.max(0.0, Math.min(1.0, amp));
  }

  setQuality(level) {
    this.quality = level;
    // Reconstruir enjambre y geometría según calidad
    if (this.particlesMesh) {
      this.scene.remove(this.particlesMesh);
      this.buildParticleSwarm();
    }
  }

  setReducedMotion(enabled) {
    this.reducedMotion = enabled;
  }

  onResize() {
    const width = this.container.clientWidth || window.innerWidth;
    const height = this.container.clientHeight || window.innerHeight;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  animate() {
    requestAnimationFrame(() => this.animate());

    const delta = this.clock.getDelta();
    this.elapsedTime += delta;

    // Medición de FPS en tiempo real
    this.frameCount++;
    if (this.elapsedTime - this.lastFpsUpdate >= 1.0) {
      this.fps = this.frameCount;
      this.frameCount = 0;
      this.lastFpsUpdate = this.elapsedTime;
      const fpsEl = document.getElementById('hud-fps');
      if (fpsEl) fpsEl.textContent = `${this.fps} FPS`;
    }

    // Interpolación suave (LERP) hacia targetTheme
    const factor = this.lerpFactor;
    this.currentTheme.primaryColor.lerp(this.targetTheme.primaryColor, factor);
    this.currentTheme.secondaryColor.lerp(this.targetTheme.secondaryColor, factor);
    this.currentTheme.accentColor.lerp(this.targetTheme.accentColor, factor);
    this.currentTheme.corePulseSpeed += (this.targetTheme.corePulseSpeed - this.currentTheme.corePulseSpeed) * factor;
    this.currentTheme.noiseDisplacement += (this.targetTheme.noiseDisplacement - this.currentTheme.noiseDisplacement) * factor;
    this.currentTheme.orbitalSpeed += (this.targetTheme.orbitalSpeed - this.currentTheme.orbitalSpeed) * factor;
    this.currentTheme.particleActivity += (this.targetTheme.particleActivity - this.currentTheme.particleActivity) * factor;
    this.currentTheme.glowIntensity += (this.targetTheme.glowIntensity - this.currentTheme.glowIntensity) * factor;

    // Factor de movimiento reducido
    const motionMultiplier = this.reducedMotion ? 0.15 : 1.0;

    // 1. Actualizar Shader del Núcleo Central
    if (this.nucleusMaterial) {
      this.nucleusMaterial.uniforms.uTime.value = this.elapsedTime * motionMultiplier;
      this.nucleusMaterial.uniforms.uNoiseStrength.value = this.currentTheme.noiseDisplacement;
      this.nucleusMaterial.uniforms.uPulseSpeed.value = this.currentTheme.corePulseSpeed;
      this.nucleusMaterial.uniforms.uAudioAmp.value = this.audioAmplitude;
      this.nucleusMaterial.uniforms.uColorPrimary.value = this.currentTheme.primaryColor;
      this.nucleusMaterial.uniforms.uColorSecondary.value = this.currentTheme.secondaryColor;
      this.nucleusMaterial.uniforms.uColorAccent.value = this.currentTheme.accentColor;
      this.nucleusMaterial.uniforms.uGlowIntensity.value = this.currentTheme.glowIntensity;
    }

    // Rotación suave del núcleo
    if (this.nucleusMesh) {
      this.nucleusMesh.rotation.y += 0.004 * motionMultiplier;
      this.nucleusMesh.rotation.x += 0.002 * motionMultiplier;
    }

    // 2. Actualizar Membrana Holográfica
    if (this.membraneMaterial) {
      this.membraneMaterial.uniforms.uTime.value = this.elapsedTime * motionMultiplier;
      this.membraneMaterial.uniforms.uColorPrimary.value = this.currentTheme.primaryColor;
      this.membraneMaterial.uniforms.uColorAccent.value = this.currentTheme.accentColor;
    }
    if (this.membraneMesh) {
      this.membraneMesh.rotation.y -= 0.003 * motionMultiplier;
    }

    // 3. Rotación de los 3 Anillos Orbitales Asimétricos
    this.orbitalRings.forEach((ring, idx) => {
      const spd = ring.userData.baseSpeed * this.currentTheme.orbitalSpeed * motionMultiplier;
      ring.rotation.z += spd * delta;
      ring.rotation.x += spd * 0.4 * delta;
    });

    // 4. Filamentos cuánticos
    if (this.filamentsMesh) {
      this.filamentsMesh.rotation.y += 0.006 * motionMultiplier;
      this.filamentsMaterial.color = this.currentTheme.accentColor;
    }

    // 5. Enjambre de Partículas Orbitales
    if (this.particlesMesh && this.particlePositions) {
      const positions = this.particlePositions;
      const count = positions.length / 3;
      const act = this.currentTheme.particleActivity * motionMultiplier;

      for (let i = 0; i < count; i++) {
        // Rotación orbital alrededor del eje Y
        const x = positions[i * 3];
        const z = positions[i * 3 + 2];
        const angle = 0.008 * act;
        positions[i * 3] = x * Math.cos(angle) - z * Math.sin(angle);
        positions[i * 3 + 2] = x * Math.sin(angle) + z * Math.cos(angle);
      }
      this.particlesMesh.geometry.attributes.position.needsUpdate = true;
    }

    // Renderizar escena final
    this.renderer.render(this.scene, this.camera);
  }
}
