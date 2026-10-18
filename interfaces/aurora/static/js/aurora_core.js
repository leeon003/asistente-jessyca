/**
 * JESSYCA ORB 4.0 — NÚCLEO AURORA 3D: MOTOR GRÁFICO DINÁMICO MULTI-ESTADO
 * 
 * Animaciones Hiperreactivas por Estado:
 * 1. ESCUCHAR (LISTENING):
 *    - Receptividad acústica total: La singularidad y la membrana de cristal se expanden
 *      y respiran en respuesta directa a la voz del usuario (amplitud de audio).
 *    - Micro-ondulaciones acústicas en las cintas del vórtice.
 *    - El enjambre de partículas converge suavemente hacia el núcleo.
 * 2. BÚSQUEDA / PENSAR (THINKING):
 *    - Giro acelerado del vórtice centrípeto (1.8x - 2.2x).
 *    - Ondas de escaneo cognitivo que viajan hacia adentro.
 *    - Llamarada violeta-cian intensificada y pulsos de datos secuenciales en los nodos orbitales.
 * 3. HABLAR (SPEAKING / TTS):
 *    - Modulación rítmica armónica sincronizada con la cadencia silábica de la voz.
 *    - Ondas de choque radiales expulsadas concéntricamente desde el núcleo hacia el cristal.
 *    - Halos de los nodos satelitales palpitando en resonancia con la locución.
 * 4. ACCIÓN (EXECUTING):
 *    - Sobrecarga cinética: Aceleración orbital máxima (1.6x) y giro veloz de nodos.
 *    - Ondas de energía transversal de alta frecuencia a lo largo de las cintas.
 *    - Ráfagas de potencia periódicas que energizan toda la retícula HUD.
 * 5. REPOSO (IDLE):
 *    - Respiración zen suave y calmada a 0.4 Hz.
 */

class AuroraCore3D {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.scene = null;
    this.camera = null;
    this.renderer = null;

    // Elementos del Núcleo
    this.crystalSphere = null;
    this.innerShell = null;
    this.singularityGroup = null;
    this.centralPoint = null;
    this.centralGlowSprite = null;
    this.outerGlowSprite = null;

    // Sistema de Ondas de Choque Radiales (Shockwaves)
    this.shockwaveRings = [];
    this.lastShockwaveTime = 0;

    // Vórtice de Energía
    this.vortexGroup = null;
    this.vortexRibbons = [];
    this.vortexFilaments = [];
    this.vortexMatrixPoints = null;

    // Sistema Orbital
    this.orbitalGroup = null;
    this.orbitalRings = [];
    this.orbitalNodes = [];

    // Estrellas de fondo
    this.starField = null;

    // Control de tiempo y render
    this.clock = new THREE.Clock();
    this.elapsedTime = 0;
    this.audioAmplitude = 0.44;
    this.quality = 'high';
    this.reducedMotion = false;

    // Paleta cromática oficial de referencia
    this.currentTheme = {
      primaryColor: new THREE.Color('#368BFF'),
      deepColor: new THREE.Color('#020612'),
      iceCyan: new THREE.Color('#70D9FF'),
      electricCyan: new THREE.Color('#00F0FF'),
      violetColor: new THREE.Color('#9D65FF'),
      softWhite: new THREE.Color('#EAFBFF'),
      corePulseSpeed: 1.0,
      vortexSpeed: 0.45,
      orbitalSpeed: 0.35,
      glowIntensity: 1.20
    };

    this.targetTheme = Object.assign({}, this.currentTheme);
    this.lerpFactor = 0.08;
    this.activeState = 'EXECUTING';

    // FPS
    this.frameCount = 0;
    this.fps = 60;
    this.lastFpsUpdate = 0;

    this.init();
  }

  init() {
    this.scene = new THREE.Scene();

    const width = this.container.clientWidth || window.innerWidth;
    const height = this.container.clientHeight || window.innerHeight;

    // Cámara con perspectiva cinematográfica
    this.camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 1000);
    this.camera.position.set(0, 0, 8.8);

    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance'
    });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.45;
    this.container.appendChild(this.renderer.domElement);

    // 1. Texturas procedurales de halo suave
    this.createGlowTextures();

    // 2. Singularidad Central
    this.buildCentralSingularity();

    // 3. Sistema de Ondas de Choque Radiales (Shockwaves)
    this.buildShockwaveSystem();

    // 4. Vórtice de Energía Cósmica (Cintas sedosas + Filamentos + Matriz)
    this.buildEnergyVortex();

    // 5. Esfera de Cristal Óptico con Reflejo en Media Luna y Fresnel
    this.buildHolographicCrystalSphere();

    // 6. Sistema Orbital (Anillo vertical violeta con nodo ápice 11:30h, anillo cian y elipse)
    this.buildOrbitalSystem();

    // 7. Polvo Cósmico y Estrellas de Fondo
    this.buildBackgroundStarfield();

    window.addEventListener('resize', () => this.onResize());
    this.animate();
  }

  // Generador de textura de halo suave radial sin bordes duros
  createGlowTextures() {
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 256;
    const ctx = canvas.getContext('2d');

    const grad = ctx.createRadialGradient(128, 128, 0, 128, 128, 128);
    grad.addColorStop(0.0, 'rgba(255, 255, 255, 1.0)');
    grad.addColorStop(0.18, 'rgba(112, 217, 255, 0.88)');
    grad.addColorStop(0.45, 'rgba(54, 139, 255, 0.38)');
    grad.addColorStop(0.75, 'rgba(157, 101, 255, 0.14)');
    grad.addColorStop(1.0, 'rgba(0, 0, 0, 0.0)');

    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 256, 256);

    this.glowTexture = new THREE.CanvasTexture(canvas);
  }

  // --- 1. SINGULARIDAD CENTRAL HIPERLUMINOSA ---
  buildCentralSingularity() {
    this.singularityGroup = new THREE.Group();

    // Punto blanco central hiperconcentrado
    const pointGeo = new THREE.SphereGeometry(0.040, 16, 16);
    const pointMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
    this.centralPoint = new THREE.Mesh(pointGeo, pointMat);
    this.singularityGroup.add(this.centralPoint);

    // Halo Sprite suave cian-blanco
    const spriteMat = new THREE.SpriteMaterial({
      map: this.glowTexture,
      color: new THREE.Color('#70D9FF'),
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });
    this.centralGlowSprite = new THREE.Sprite(spriteMat);
    this.centralGlowSprite.scale.set(1.35, 1.35, 1.0);
    this.singularityGroup.add(this.centralGlowSprite);

    // Corona externa violeta suave
    const outerSpriteMat = new THREE.SpriteMaterial({
      map: this.glowTexture,
      color: new THREE.Color('#9D65FF'),
      transparent: true,
      opacity: 0.40,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });
    this.outerGlowSprite = new THREE.Sprite(outerSpriteMat);
    this.outerGlowSprite.scale.set(2.2, 2.2, 1.0);
    this.singularityGroup.add(this.outerGlowSprite);

    this.scene.add(this.singularityGroup);
  }

  // --- 2. SISTEMA DE ONDAS DE CHOQUE RADIALES (SHOCKWAVES) ---
  buildShockwaveSystem() {
    this.shockwaveGroup = new THREE.Group();
    this.shockwaveRings = [];

    // Creamos 4 anillos expansivos reutilizables
    for (let i = 0; i < 4; i++) {
      const ringGeo = new THREE.RingGeometry(0.1, 0.14, 64);
      const ringMat = new THREE.MeshBasicMaterial({
        color: new THREE.Color('#70D9FF'),
        transparent: true,
        opacity: 0.0,
        blending: THREE.AdditiveBlending,
        side: THREE.DoubleSide,
        depthWrite: false
      });
      const ringMesh = new THREE.Mesh(ringGeo, ringMat);
      ringMesh.userData = {
        active: false,
        progress: 0.0,
        speed: 1.2,
        maxRadius: 1.65,
        colorHex: '#70D9FF'
      };
      this.shockwaveRings.push(ringMesh);
      this.shockwaveGroup.add(ringMesh);
    }

    this.scene.add(this.shockwaveGroup);
  }

  triggerShockwave(colorHex = '#70D9FF', speed = 1.3) {
    // Buscar un anillo inactivo para disparar
    const ring = this.shockwaveRings.find(r => !r.userData.active);
    if (ring) {
      ring.userData.active = true;
      ring.userData.progress = 0.0;
      ring.userData.speed = speed;
      ring.userData.colorHex = colorHex;
      ring.material.color.set(colorHex);
      ring.material.opacity = 0.85;
      ring.scale.set(0.1, 0.1, 0.1);
    }
  }

  // --- 3. VÓRTICE ENERGÉTICO ESPIRAL MULTICAPA ---
  buildEnergyVortex() {
    this.vortexGroup = new THREE.Group();
    this.vortexGroup.rotation.x = 0.16;
    this.vortexGroup.rotation.y = -0.10;

    this.vortexRibbons = [];
    this.vortexFilaments = [];

    // Helper: Creación de cintas espirales sedosas con shader de modulación
    const createVortexRibbon = (options) => {
      const {
        startR, endR, turns, startAngle,
        wStart, wEnd, zDepth, colorHex, opacity, segments
      } = options;

      const numSteps = segments || 50;
      const positions = [];
      const uvs = [];
      const colors = [];
      const baseColor = new THREE.Color(colorHex);

      for (let i = 0; i <= numSteps; i++) {
        const t = i / numSteps;
        const r = startR + (endR - startR) * Math.pow(t, 0.72);
        const theta = startAngle + t * Math.PI * 2 * turns;
        const w = wStart + (wEnd - wStart) * Math.sin(t * Math.PI * 0.95);
        const z = Math.sin(t * Math.PI) * zDepth + Math.sin(theta * 1.5) * 0.12;

        const nx = -Math.sin(theta);
        const ny = Math.cos(theta);

        positions.push(
          Math.cos(theta) * r + nx * (w * 0.5),
          Math.sin(theta) * r + ny * (w * 0.5),
          z + (w * 0.18)
        );
        positions.push(
          Math.cos(theta) * r - nx * (w * 0.5),
          Math.sin(theta) * r - ny * (w * 0.5),
          z - (w * 0.18)
        );

        uvs.push(0, t);
        uvs.push(1, t);

        const c = baseColor.clone();
        if (t < 0.25) {
          c.lerp(new THREE.Color('#FFFFFF'), (0.25 - t) * 3.5);
        }
        colors.push(c.r, c.g, c.b);
        colors.push(c.r, c.g, c.b);
      }

      const indices = [];
      for (let i = 0; i < numSteps; i++) {
        const v1 = i * 2;
        const v2 = i * 2 + 1;
        const v3 = (i + 1) * 2;
        const v4 = (i + 1) * 2 + 1;
        indices.push(v1, v2, v3);
        indices.push(v2, v4, v3);
      }

      const geom = new THREE.BufferGeometry();
      geom.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      geom.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
      geom.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
      geom.setIndex(indices);
      geom.computeVertexNormals();

      const mat = new THREE.ShaderMaterial({
        vertexShader: `
          varying vec2 vUv;
          varying vec3 vColor;
          void main() {
            vUv = uv;
            vColor = color;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }
        `,
        fragmentShader: `
          uniform float uOpacity;
          varying vec2 vUv;
          varying vec3 vColor;
          void main() {
            float edgeFade = smoothstep(0.0, 0.35, vUv.x) * smoothstep(1.0, 0.65, vUv.x);
            float lengthFade = smoothstep(0.0, 0.10, vUv.y) * smoothstep(1.0, 0.85, vUv.y);
            float wave = 0.88 + 0.12 * sin(vUv.x * 24.0);
            float alpha = edgeFade * lengthFade * uOpacity * wave;
            gl_FragColor = vec4(vColor * 1.35, alpha);
          }
        `,
        uniforms: {
          uOpacity: { value: opacity }
        },
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        side: THREE.DoubleSide
      });

      const mesh = new THREE.Mesh(geom, mat);
      mesh.userData = {
        speed: options.speed,
        baseOpacity: opacity,
        isViolet: colorHex.includes('9D') || colorHex.includes('8A') || colorHex.includes('BA')
      };
      return mesh;
    };

    // Crear 14 Cintas Sedosas Amplias
    const ribbonDefs = [
      { startR: 0.08, endR: 1.48, turns: 0.95, startAngle: 0.0, wStart: 0.08, wEnd: 0.42, zDepth: 0.38, colorHex: '#70D9FF', opacity: 0.55, speed: 0.18 },
      { startR: 0.10, endR: 1.45, turns: 1.05, startAngle: Math.PI * 0.65, wStart: 0.06, wEnd: 0.38, zDepth: -0.32, colorHex: '#00F0FF', opacity: 0.52, speed: 0.20 },
      { startR: 0.12, endR: 1.50, turns: 0.90, startAngle: Math.PI * 1.35, wStart: 0.08, wEnd: 0.44, zDepth: 0.42, colorHex: '#368BFF', opacity: 0.48, speed: 0.19 },
      { startR: 0.15, endR: 1.46, turns: 0.85, startAngle: 0.85, wStart: 0.10, wEnd: 0.48, zDepth: 0.35, colorHex: '#9D65FF', opacity: 0.62, speed: 0.22 },
      { startR: 0.18, endR: 1.42, turns: 0.92, startAngle: 2.85, wStart: 0.08, wEnd: 0.40, zDepth: -0.36, colorHex: '#8A4FFF', opacity: 0.58, speed: 0.21 },
      { startR: 0.22, endR: 1.48, turns: 0.88, startAngle: 4.65, wStart: 0.09, wEnd: 0.45, zDepth: 0.30, colorHex: '#BA68C8', opacity: 0.50, speed: 0.23 },
      { startR: 0.05, endR: 0.85, turns: 1.25, startAngle: 1.4, wStart: 0.04, wEnd: 0.24, zDepth: 0.22, colorHex: '#EAFBFF', opacity: 0.70, speed: 0.30 },
      { startR: 0.06, endR: 0.90, turns: 1.15, startAngle: 3.6, wStart: 0.04, wEnd: 0.22, zDepth: -0.20, colorHex: '#70D9FF', opacity: 0.65, speed: 0.28 },
      { startR: 0.40, endR: 1.52, turns: 0.75, startAngle: 0.45, wStart: 0.14, wEnd: 0.50, zDepth: -0.42, colorHex: '#368BFF', opacity: 0.38, speed: 0.15 },
      { startR: 0.45, endR: 1.54, turns: 0.70, startAngle: 3.25, wStart: 0.15, wEnd: 0.48, zDepth: 0.40, colorHex: '#70D9FF', opacity: 0.42, speed: 0.16 }
    ];

    ribbonDefs.forEach(def => {
      const ribbon = createVortexRibbon(def);
      this.vortexRibbons.push(ribbon);
      this.vortexGroup.add(ribbon);
    });

    // 42 Filamentos Cuánticos Finos
    const filamentCount = 42;
    for (let f = 0; f < filamentCount; f++) {
      const points = [];
      const turns = 0.95 + (f % 4) * 0.15;
      const baseAngle = (f / filamentCount) * Math.PI * 2;
      const maxR = 1.48 - (Math.random() * 0.10);
      const zAmp = Math.sin(baseAngle * 2.0) * 0.32;

      for (let s = 0; s <= 36; s++) {
        const u = s / 36;
        const r = 0.06 + Math.pow(u, 0.72) * maxR;
        const theta = baseAngle + u * Math.PI * 2 * turns;
        const x = r * Math.cos(theta);
        const y = r * Math.sin(theta) * 0.92;
        const z = Math.sin(u * Math.PI) * zAmp;
        points.push(new THREE.Vector3(x, y, z));
      }

      const curve = new THREE.CatmullRomCurve3(points);
      const curveGeo = new THREE.BufferGeometry().setFromPoints(curve.getPoints(45));

      let col = (f % 3 === 0) ? this.currentTheme.violetColor : ((f % 3 === 1) ? this.currentTheme.iceCyan : this.currentTheme.electricCyan);
      const opacity = 0.35 + Math.random() * 0.35;

      const mat = new THREE.LineBasicMaterial({
        color: col,
        transparent: true,
        opacity: opacity,
        blending: THREE.AdditiveBlending,
        depthWrite: false
      });

      const line = new THREE.Line(curveGeo, mat);
      line.userData = { speed: 0.16 + Math.random() * 0.18, baseOpacity: opacity };
      this.vortexFilaments.push(line);
      this.vortexGroup.add(line);
    }

    // Matriz de Polvo Estelar Holográfico
    const matrixCount = 1000;
    const matrixGeo = new THREE.BufferGeometry();
    const matrixPos = new Float32Array(matrixCount * 3);
    const matrixCol = new Float32Array(matrixCount * 3);

    let pIdx = 0;
    for (let band = 0; band < 24; band++) {
      const lat = ((band / 24) - 0.5) * Math.PI * 0.82;
      const r = 1.46 * Math.cos(lat);
      const z = 1.46 * Math.sin(lat) * 0.70;
      const dotsInBand = Math.floor(20 + 34 * Math.cos(lat));

      for (let d = 0; d < dotsInBand && pIdx < matrixCount; d++) {
        const lon = (d / dotsInBand) * Math.PI * 2.0 + (band * 0.20);
        const density = 0.5 + 0.5 * Math.sin(lon + lat * 1.4);
        if (Math.random() > density * 0.85) continue;

        matrixPos[pIdx * 3] = r * Math.cos(lon);
        matrixPos[pIdx * 3 + 1] = r * Math.sin(lon) * 0.92;
        matrixPos[pIdx * 3 + 2] = z;

        const pCol = (d % 3 === 0) ? this.currentTheme.violetColor : this.currentTheme.iceCyan;
        matrixCol[pIdx * 3] = pCol.r;
        matrixCol[pIdx * 3 + 1] = pCol.g;
        matrixCol[pIdx * 3 + 2] = pCol.b;

        pIdx++;
      }
    }

    matrixGeo.setAttribute('position', new THREE.BufferAttribute(matrixPos.subarray(0, pIdx * 3), 3));
    matrixGeo.setAttribute('color', new THREE.BufferAttribute(matrixCol.subarray(0, pIdx * 3), 3));

    const matrixMat = new THREE.PointsMaterial({
      size: 0.022,
      vertexColors: true,
      transparent: true,
      opacity: 0.75,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });

    this.vortexMatrixPoints = new THREE.Points(matrixGeo, matrixMat);
    this.vortexGroup.add(this.vortexMatrixPoints);

    this.scene.add(this.vortexGroup);
  }

  // --- 4. ESFERA DE CRISTAL HOLOGRÁFICA (FRESNEL + REFLEJO EN MEDIA LUNA) ---
  buildHolographicCrystalSphere() {
    const radius = 1.56;
    const detail = 80;

    const outerGeo = new THREE.SphereGeometry(radius, detail, detail);

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
      uniform vec3 uColorIceCyan;
      uniform vec3 uColorSoftWhite;
      uniform vec3 uColorEnergyBlue;
      uniform float uGlowIntensity;
      varying vec3 vNormal;
      varying vec3 vViewPosition;

      void main() {
        vec3 normal = normalize(vNormal);
        vec3 viewDir = normalize(vViewPosition);

        float NdotV = max(dot(normal, viewDir), 0.0);
        float fresnel = pow(1.0 - NdotV, 2.7);

        // Reflejo especular en media luna en cuadrante superior izquierdo
        float crescentMask = smoothstep(-0.2, 0.7, -normal.x * 0.9 + normal.y * 1.1);
        float crescentRim = pow(fresnel, 1.8) * crescentMask * 1.6;

        // Brillo secundario tenue en el limbo derecho
        float rightRimMask = smoothstep(0.3, 0.9, normal.x - normal.y * 0.2);
        float rightRim = pow(fresnel, 2.4) * rightRimMask * 0.65;

        vec3 rimColor = mix(uColorIceCyan, uColorSoftWhite, pow(fresnel, 1.8));
        vec3 finalColor = (rimColor * fresnel * 1.1) + ((crescentRim + rightRim) * uColorSoftWhite);

        float alpha = clamp(0.015 + fresnel * 0.68 + crescentRim * 0.55, 0.0, 0.95);
        gl_FragColor = vec4(finalColor * uGlowIntensity, alpha);
      }
    `;

    this.outerGlassMaterial = new THREE.ShaderMaterial({
      vertexShader: vertexShader,
      fragmentShader: fragmentShader,
      uniforms: {
        uColorIceCyan: { value: this.currentTheme.iceCyan },
        uColorSoftWhite: { value: this.currentTheme.softWhite },
        uColorEnergyBlue: { value: this.currentTheme.primaryColor },
        uGlowIntensity: { value: this.currentTheme.glowIntensity }
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.NormalBlending,
      side: THREE.FrontSide
    });

    this.crystalSphere = new THREE.Mesh(outerGeo, this.outerGlassMaterial);
    this.scene.add(this.crystalSphere);

    const innerGeo = new THREE.SphereGeometry(radius * 0.98, 48, 48);
    const innerMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color('#368BFF'),
      transparent: true,
      opacity: 0.035,
      side: THREE.BackSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });
    this.innerShell = new THREE.Mesh(innerGeo, innerMat);
    this.scene.add(this.innerShell);
  }

  // --- 5. SISTEMA ORBITAL: 3 ANILLOS Y NODOS PERLA ---
  buildOrbitalSystem() {
    this.orbitalGroup = new THREE.Group();
    this.orbitalRings = [];
    this.orbitalNodes = [];

    const createRing = (radius, thickness, colorHex, rotX, rotY, rotZ, opacity) => {
      const ringGeo = new THREE.TorusGeometry(radius, thickness, 16, 200);
      const ringMat = new THREE.MeshBasicMaterial({
        color: new THREE.Color(colorHex),
        transparent: true,
        opacity: opacity,
        blending: THREE.AdditiveBlending,
        depthWrite: false
      });
      const mesh = new THREE.Mesh(ringGeo, ringMat);
      mesh.rotation.x = rotX;
      mesh.rotation.y = rotY;
      mesh.rotation.z = rotZ;
      mesh.userData = {
        radius, rotX, rotY, rotZ, speed: 0.14
      };
      return mesh;
    };

    const createPearlNode = (size, haloColorHex) => {
      const group = new THREE.Group();

      const pearlGeo = new THREE.SphereGeometry(size, 16, 16);
      const pearlMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
      const pearl = new THREE.Mesh(pearlGeo, pearlMat);
      group.add(pearl);

      const spriteMat = new THREE.SpriteMaterial({
        map: this.glowTexture,
        color: new THREE.Color(haloColorHex),
        transparent: true,
        opacity: 0.85,
        blending: THREE.AdditiveBlending,
        depthWrite: false
      });
      const sprite = new THREE.Sprite(spriteMat);
      sprite.scale.set(size * 5.5, size * 5.5, 1.0);
      group.add(sprite);

      group.userData = { baseSize: size, sprite: sprite };
      return group;
    };

    // ANILLO 1: VIOLETA CASI VERTICAL (~70° inclinación)
    const ring1 = createRing(2.15, 0.0050, '#9D65FF', 0.15, Math.PI * 0.38, -0.32, 0.70);
    ring1.userData.speed = 0.16;
    this.orbitalRings.push(ring1);
    this.orbitalGroup.add(ring1);

    // Nodo Maestro en el ÁPICE SUPERIOR (~11:30h)
    const node1A = createPearlNode(0.032, '#BA68C8');
    node1A.userData.ringIndex = 0;
    node1A.userData.angle = Math.PI * 0.48;
    node1A.userData.speed = 0.16;
    this.orbitalNodes.push(node1A);
    this.orbitalGroup.add(node1A);

    // Nodo Inferior Derecho del Anillo 1
    const node1B = createPearlNode(0.026, '#8A4FFF');
    node1B.userData.ringIndex = 0;
    node1B.userData.angle = Math.PI * 1.54;
    node1B.userData.speed = 0.16;
    this.orbitalNodes.push(node1B);
    this.orbitalGroup.add(node1B);

    // ANILLO 2: CIAN HIELO DIAGONAL CRUZADO
    const ring2 = createRing(2.05, 0.0050, '#70D9FF', -0.22, -Math.PI * 0.34, 0.42, 0.65);
    ring2.userData.speed = -0.15;
    this.orbitalRings.push(ring2);
    this.orbitalGroup.add(ring2);

    const node2A = createPearlNode(0.028, '#70D9FF');
    node2A.userData.ringIndex = 1;
    node2A.userData.angle = Math.PI * 0.15;
    node2A.userData.speed = -0.15;
    this.orbitalNodes.push(node2A);
    this.orbitalGroup.add(node2A);

    const node2B = createPearlNode(0.024, '#00F0FF');
    node2B.userData.ringIndex = 1;
    node2B.userData.angle = Math.PI * 1.15;
    node2B.userData.speed = -0.15;
    this.orbitalNodes.push(node2B);
    this.orbitalGroup.add(node2B);

    // ANILLO 3: GRAN ELIPSE ECUATORIAL EXTERIOR
    const ring3 = createRing(2.38, 0.0040, '#368BFF', Math.PI * 0.40, -0.15, -0.25, 0.45);
    ring3.userData.speed = 0.12;
    this.orbitalRings.push(ring3);
    this.orbitalGroup.add(ring3);

    const node3A = createPearlNode(0.028, '#70D9FF');
    node3A.userData.ringIndex = 2;
    node3A.userData.angle = Math.PI * 0.85;
    node3A.userData.speed = 0.12;
    this.orbitalNodes.push(node3A);
    this.orbitalGroup.add(node3A);

    const node3B = createPearlNode(0.024, '#EAFBFF');
    node3B.userData.ringIndex = 2;
    node3B.userData.angle = Math.PI * 1.88;
    node3B.userData.speed = 0.12;
    this.orbitalNodes.push(node3B);
    this.orbitalGroup.add(node3B);

    this.scene.add(this.orbitalGroup);
  }

  // --- 6. POLVO CÓSMICO Y ESTRELLAS DE FONDO ---
  buildBackgroundStarfield() {
    const count = 300;
    const geo = new THREE.BufferGeometry();
    const pos = new Float32Array(count * 3);
    const col = new Float32Array(count * 3);

    for (let i = 0; i < count; i++) {
      const u = Math.random();
      const r = 2.4 + Math.pow(u, 1.4) * 3.6;
      const theta = Math.random() * Math.PI * 2;
      const phi = (Math.random() - 0.5) * Math.PI;

      pos[i * 3] = r * Math.cos(theta) * Math.cos(phi);
      pos[i * 3 + 1] = r * Math.sin(phi);
      pos[i * 3 + 2] = r * Math.sin(theta) * Math.cos(phi);

      const colorVariant = Math.random();
      let pCol = this.currentTheme.softWhite;
      if (colorVariant < 0.45) pCol = this.currentTheme.iceCyan;
      else if (colorVariant < 0.70) pCol = this.currentTheme.violetColor;

      col[i * 3] = pCol.r;
      col[i * 3 + 1] = pCol.g;
      col[i * 3 + 2] = pCol.b;
    }

    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(col, 3));

    const mat = new THREE.PointsMaterial({
      size: 0.022,
      vertexColors: true,
      transparent: true,
      opacity: 0.50,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });

    this.starField = new THREE.Points(geo, mat);
    this.scene.add(this.starField);
  }

  // --- MÉTODOS DE ESTADO Y CONTROL ---
  setTheme(theme, stateName = 'EXECUTING') {
    this.activeState = stateName;

    // Configuraciones cinéticas específicas por acción
    let vSpd = 0.45;
    let orbSpd = theme.orbital_speed;
    let glow = theme.glow_intensity;

    if (stateName === 'THINKING') {
      vSpd = 1.10; // BÚSQUEDA / PENSAMIENTO: Aceleración centrípeta rápida
      orbSpd = 0.85;
      glow = 1.35;
    } else if (stateName === 'EXECUTING') {
      vSpd = 0.80; // ACCIÓN / EJECUCIÓN: Alta energía y rotación orbital rápida
      orbSpd = 1.25;
      glow = 1.40;
    } else if (stateName === 'SPEAKING') {
      vSpd = 0.60; // HABLA: Ondulación armónica
      orbSpd = 0.60;
      glow = 1.30;
    } else if (stateName === 'LISTENING') {
      vSpd = 0.40; // ESCUCHA: Receptividad acústica
      orbSpd = 0.45;
      glow = 1.25;
    }

    this.targetTheme = {
      primaryColor: new THREE.Color(theme.primary_color),
      deepColor: new THREE.Color(theme.secondary_color),
      iceCyan: new THREE.Color(theme.accent_color),
      electricCyan: new THREE.Color('#00F0FF'),
      violetColor: new THREE.Color(theme.primary_color).lerp(new THREE.Color('#9D65FF'), 0.55),
      softWhite: new THREE.Color('#EAFBFF'),
      corePulseSpeed: theme.core_pulse_speed,
      vortexSpeed: vSpd,
      orbitalSpeed: orbSpd,
      glowIntensity: glow
    };

    // Disparar onda de choque al cambiar a un estado activo
    if (stateName === 'EXECUTING') {
      this.triggerShockwave('#00F0FF', 1.8);
    } else if (stateName === 'THINKING') {
      this.triggerShockwave('#9D65FF', 1.4);
    } else if (stateName === 'SPEAKING') {
      this.triggerShockwave('#70D9FF', 1.5);
    } else if (stateName === 'LISTENING') {
      this.triggerShockwave('#00F0FF', 1.1);
    }
  }

  setAudioAmplitude(amp) {
    this.audioAmplitude = Math.max(0.0, Math.min(1.0, Number(amp) || 0.0));
    this.lastAudioUpdateTime = performance.now();
  }

  setQuality(level) {
    this.quality = level;
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

  // --- BUCLE DE RENDERIZADO PRINCIPAL (ANIMACIONES DINÁMICAS) ---
  animate() {
    requestAnimationFrame(() => this.animate());

    const delta = this.clock.getDelta();
    this.elapsedTime += delta;

    // Medición de FPS
    this.frameCount++;
    if (this.elapsedTime - this.lastFpsUpdate >= 1.0) {
      this.fps = this.frameCount;
      this.frameCount = 0;
      this.lastFpsUpdate = this.elapsedTime;
      const fpsEl = document.getElementById('metric-fps');
      if (fpsEl) fpsEl.textContent = `${this.fps} FPS`;
    }

    // Interpolación LERP suave de temas cromáticos
    const factor = this.lerpFactor;
    this.currentTheme.primaryColor.lerp(this.targetTheme.primaryColor, factor);
    this.currentTheme.iceCyan.lerp(this.targetTheme.iceCyan, factor);
    this.currentTheme.glowIntensity += (this.targetTheme.glowIntensity - this.currentTheme.glowIntensity) * factor;

    const motionMul = this.reducedMotion ? 0.15 : 1.0;
    const isListening = (this.activeState === 'LISTENING');
    const isThinking = (this.activeState === 'THINKING');
    const isSpeaking = (this.activeState === 'SPEAKING');
    const isExecuting = (this.activeState === 'EXECUTING');

    // ── 1. MODULACIÓN DE LOCUCIÓN Y AUDIO SEGÚN ESTADO ──
    const nowMs = performance.now();
    const hasLiveAudio = (nowMs - (this.lastAudioUpdateTime || 0)) < 400;

    let dynamicAudio = this.audioAmplitude;
    let voicePulse = 0.0;

    if (isSpeaking) {
      if (hasLiveAudio && this.audioAmplitude > 0.02) {
        // Voz en vivo (telemetría WebSocket o control de intensidad): suavizado con ataque reactivo
        this.smoothedVoice = (this.smoothedVoice || 0.2) + (this.audioAmplitude - (this.smoothedVoice || 0.2)) * 0.44;
        voicePulse = this.smoothedVoice;
      } else {
        // Cadencia autónoma silábica orgánica (ritmo de habla humana de Jessyca: ~4.25 sílabas/s)
        const phraseCycle = this.elapsedTime % 2.75;
        if (phraseCycle < 2.40) {
          const sylFreq = 4.25;
          const sylPhase = (this.elapsedTime * sylFreq) % 1.0;
          const env = sylPhase < 0.22 ? (sylPhase / 0.22) : Math.max(0.18, 1.0 - (sylPhase - 0.22) * 1.05);
          const harmonics = 0.14 * Math.sin(this.elapsedTime * 22.0) + 0.08 * Math.sin(this.elapsedTime * 36.0);
          voicePulse = Math.max(0.15, Math.min(0.96, env * 0.72 + harmonics + 0.12));
        } else {
          voicePulse = 0.09; // Micro-pausa natural entre frases
        }
        this.smoothedVoice = (this.smoothedVoice || 0.2) + (voicePulse - (this.smoothedVoice || 0.2)) * 0.38;
        voicePulse = this.smoothedVoice;
      }

      dynamicAudio = voicePulse;

      // Disparar ondas de choque radiales en los picos silábicos de voz
      if (this.elapsedTime - this.lastShockwaveTime > 0.46 && voicePulse > 0.65) {
        this.triggerShockwave('#70D9FF', 1.45);
        this.lastShockwaveTime = this.elapsedTime;
      }
    } else if (isListening) {
      this.smoothedVoice = (this.smoothedVoice || 0.15) + (this.audioAmplitude - (this.smoothedVoice || 0.15)) * 0.30;
      dynamicAudio = this.smoothedVoice;
    } else if (isExecuting) {
      // Pulsos periódicos de potencia de ejecución cada 2 segundos
      if (this.elapsedTime - this.lastShockwaveTime > 2.0) {
        this.triggerShockwave('#00F0FF', 1.8);
        this.lastShockwaveTime = this.elapsedTime;
      }
    }

    // ── 2. SINGULARIDAD CENTRAL Y RESPLANDOR REACTIVO ──
    if (this.centralPoint) {
      let pScale = 1.0;
      if (isListening) {
        // Expansión directa reactiva a la voz del usuario
        pScale = 1.0 + Math.sin(this.elapsedTime * 4.0) * 0.08 + (dynamicAudio * 0.50);
      } else if (isThinking) {
        // Pulso cuántico cognitivo rápido
        pScale = 1.0 + Math.sin(this.elapsedTime * 7.5) * 0.18;
      } else if (isSpeaking) {
        // Palpitación vigorosa sincronizada con cada sílaba de la voz (+65% diámetro en picos)
        pScale = 1.0 + dynamicAudio * 0.65;
      } else if (isExecuting) {
        // Pulso energético constante
        pScale = 1.0 + Math.sin(this.elapsedTime * 3.5) * 0.12 + (dynamicAudio * 0.20);
      } else {
        // Reposo suave
        pScale = 1.0 + Math.sin(this.elapsedTime * 1.5) * 0.06;
      }
      this.centralPoint.scale.set(pScale, pScale, pScale);
    }

    if (this.centralGlowSprite) {
      let sScale = 1.35;
      if (isListening) {
        sScale = 1.35 + dynamicAudio * 0.85;
      } else if (isThinking) {
        sScale = 1.30 + Math.sin(this.elapsedTime * 6.0) * 0.25;
      } else if (isSpeaking) {
        // Resplandor expansivo fúlgido con cada sílaba de voz
        sScale = 1.35 + dynamicAudio * 1.05;
      } else if (isExecuting) {
        sScale = 1.45 + Math.sin(this.elapsedTime * 3.0) * 0.20 + (dynamicAudio * 0.35);
      } else {
        sScale = 1.30 + Math.sin(this.elapsedTime * 1.6) * 0.10;
      }
      this.centralGlowSprite.scale.set(sScale, sScale, 1.0);
      if (isSpeaking) {
        this.centralGlowSprite.material.opacity = (0.70 + dynamicAudio * 0.35) * this.currentTheme.glowIntensity;
      } else {
        this.centralGlowSprite.material.opacity = (0.75 + Math.sin(this.elapsedTime * 2.2) * 0.15) * this.currentTheme.glowIntensity;
      }
    }

    if (this.outerGlowSprite) {
      let oScale = 2.2 + (dynamicAudio * 0.40);
      if (isSpeaking) {
        oScale = 2.1 + (dynamicAudio * 0.75);
      } else if (isThinking) {
        oScale = 2.4 + Math.sin(this.elapsedTime * 5.0) * 0.30;
      }
      this.outerGlowSprite.scale.set(oScale, oScale, 1.0);
    }

    // ── 3. ONDAS DE CHOQUE EXPANSIVAS (SHOCKWAVES) ──
    this.shockwaveRings.forEach(ring => {
      if (ring.userData.active) {
        ring.userData.progress += delta * ring.userData.speed;
        const p = ring.userData.progress;
        if (p >= 1.0) {
          ring.userData.active = false;
          ring.material.opacity = 0.0;
        } else {
          const currentR = p * ring.userData.maxRadius;
          ring.scale.set(currentR, currentR, 1.0);
          ring.material.opacity = (1.0 - p) * 0.75 * this.currentTheme.glowIntensity;
        }
      }
    });

    // ── 4. VÓRTICE ESPIRAL DINÁMICO MULTICAPA ──
    if (this.vortexGroup) {
      let vSpeed = this.targetTheme.vortexSpeed * motionMul;
      if (isThinking) vSpeed *= 1.35; // Aceleración extra en búsqueda
      if (isExecuting) vSpeed *= 1.15; // Aceleración extra en ejecución

      this.vortexGroup.rotation.z += vSpeed * delta;

      // Ondulación orgánica y reactiva de cintas
      this.vortexRibbons.forEach((ribbon, i) => {
        let rSpeed = ribbon.userData.speed * delta * 0.40 * motionMul;
        if (isThinking) rSpeed *= 1.4;
        ribbon.rotation.z += rSpeed;

        let waveFreq = 2.0;
        let waveAmp = 0.08;

        if (isListening) {
          waveFreq = 8.0;
          waveAmp = 0.10 + dynamicAudio * 0.35; // Micro-vibraciones acústicas
        } else if (isSpeaking) {
          waveFreq = 7.0 + dynamicAudio * 9.0;
          waveAmp = 0.12 + dynamicAudio * 0.38; // Ondulación viva al ritmo de la voz
        } else if (isExecuting) {
          waveFreq = 4.0;
          waveAmp = 0.14; // Ondulación de potencia
        }

        const wave = Math.sin(this.elapsedTime * waveFreq + i) * waveAmp;

        // Si es cinta violeta y estamos en THINKING, iluminar intensamente
        let extraBoost = 0.0;
        if (isThinking && ribbon.userData.isViolet) {
          extraBoost = 0.30;
        }

        ribbon.material.uniforms.uOpacity.value = (ribbon.userData.baseOpacity + wave + extraBoost + (isSpeaking ? dynamicAudio * 0.32 : dynamicAudio * 0.15)) * this.currentTheme.glowIntensity;
      });

      // Movimiento de filamentos cuánticos
      this.vortexFilaments.forEach((line) => {
        let fSpd = line.userData.speed * delta * 0.40 * motionMul;
        if (isThinking) fSpd *= 1.5;
        line.rotation.z += fSpd;
      });

      // Rotación de la matriz holográfica
      if (this.vortexMatrixPoints) {
        this.vortexMatrixPoints.rotation.z += vSpeed * 0.25 * delta;
      }
    }

    // ── 5. ESFERA DE CRISTAL HOLOGRÁFICA (RESPIRACIÓN Y FRESNEL) ──
    if (this.outerGlassMaterial) {
      this.outerGlassMaterial.uniforms.uColorIceCyan.value = this.currentTheme.iceCyan;
      this.outerGlassMaterial.uniforms.uColorEnergyBlue.value = this.currentTheme.primaryColor;
      
      let glowMultiplier = this.currentTheme.glowIntensity;
      if (isListening) {
        glowMultiplier += dynamicAudio * 0.35;
      } else if (isSpeaking) {
        glowMultiplier += dynamicAudio * 0.70; // El halo de cristal fulgura al ritmo de la voz
      }
      this.outerGlassMaterial.uniforms.uGlowIntensity.value = glowMultiplier;
    }

    if (this.crystalSphere) {
      let sphereRot = 0.0012 * motionMul;
      if (isExecuting) sphereRot *= 1.8;
      this.crystalSphere.rotation.y += sphereRot;

      // Palpitación física de la membrana al ritmo de la voz
      if (isSpeaking) {
        const membraneBreath = 1.0 + dynamicAudio * 0.06; // Palpitar orgánico del 6%
        this.crystalSphere.scale.set(membraneBreath, membraneBreath, membraneBreath);
      } else if (isListening) {
        const membraneBreath = 1.0 + dynamicAudio * 0.03;
        this.crystalSphere.scale.set(membraneBreath, membraneBreath, membraneBreath);
      } else {
        this.crystalSphere.scale.set(1.0, 1.0, 1.0);
      }
    }

    // ── 6. SISTEMA ORBITAL Y NODOS PERLA DINÁMICOS ──
    if (this.orbitalGroup) {
      let orbSpeedMul = this.targetTheme.orbitalSpeed * motionMul;
      if (isExecuting) orbSpeedMul *= 1.45; // Rotación rápida en EXECUTING
      if (isThinking) orbSpeedMul *= 1.25;

      this.orbitalRings.forEach((ring) => {
        ring.rotation.z += ring.userData.speed * orbSpeedMul * delta;
      });

      this.orbitalNodes.forEach((node, idx) => {
        const ring = this.orbitalRings[node.userData.ringIndex];
        if (ring) {
          let nSpeed = node.userData.speed * orbSpeedMul * delta;
          node.userData.angle += nSpeed;
          const a = node.userData.angle;
          const r = ring.userData.radius;

          const localPos = new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, 0);
          localPos.applyAxisAngle(new THREE.Vector3(1, 0, 0), ring.userData.rotX);
          localPos.applyAxisAngle(new THREE.Vector3(0, 1, 0), ring.userData.rotY);
          localPos.applyAxisAngle(new THREE.Vector3(0, 0, 1), ring.userData.rotZ);
          node.position.copy(localPos);

          // Pulsación dinámica del nodo según acción
          if (node.userData.sprite) {
            let haloScale = node.userData.baseSize * 5.5;
            if (isSpeaking) {
              haloScale *= (1.0 + dynamicAudio * 0.75); // Perlas orbitales palpitando con la voz
            } else if (isThinking) {
              // Destellos neuronales alternados
              const pulseFlash = Math.sin(this.elapsedTime * 8.0 + idx * 1.5);
              haloScale *= (1.0 + Math.max(0.0, pulseFlash) * 0.50);
            } else if (isExecuting) {
              haloScale *= 1.25;
            }
            node.userData.sprite.scale.set(haloScale, haloScale, 1.0);
          }
        }
      });
    }

    // ── 7. POLVO CÓSMICO ──
    if (this.starField) {
      let starSpd = 0.0005 * motionMul;
      if (isThinking) starSpd *= 1.8;
      this.starField.rotation.y += starSpd;
    }

    this.renderer.render(this.scene, this.camera);
  }
}
