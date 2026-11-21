/* Gemelo digital del Metro de Madrid — sobre el catálogo funcional validado (r2).
   La geometría de la red (560 tramos dirigidos, 587 andenes, cotas de railhead)
   es la del catálogo resuelto y NO se recalcula: se dibuja tal cual.
   Los 240 modelos reales de estación van anclados al punto medio de su andén
   (bake: scripts/anclar_funcional.py). */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const $ = (id) => document.getElementById(id);

const COLOR = {
  '1': '#2DBEF0', '2': '#ED1C24', '3': '#FFD000', '4': '#B65518', '5': '#8FD400',
  '6': '#A0A5AB', '7': '#EE7518', '8': '#EC82B1', '9': '#A60084', '10': '#4A9FE6',
  '11': '#009B3A', '12': '#A49800', 'R': '#8AB4E8',
};
const TREN_DE = { '1': 'narrow', '2': 'narrow', '3': 'narrow', '4': 'narrow', '5': 'narrow', 'R': 'narrow',
  '6': 'ancho', '7': 'ancho', '8': 'ancho', '10': 'ancho', '11': 'ancho', '12': 'ancho', '9': 'nueve' };
const GLB_TREN = { narrow: 'datos/trenes/3000.glb', ancho: 'datos/trenes/9000.glb', nueve: 'datos/trenes/9700.glb' };

const estado = {
  opacidad: 0.55,
  velocidad: 30,
  linea: null,
  capas: { estaciones: true, vias: true, andenes: true, trenes: true, suelo: true },
};

let escena, camara, control, renderer, reloj;
let grupoEstaciones, grupoRed, grupoTrenes, suelo, miras;
let cab = null, red = null, centros = [];
let trenes = [], cadenas = [];
let hover = -1, fps = { t: 0, n: 0 };
const porCodigo = new Map();

/* ---------------- carga ---------------- */
function leerMMG(buf) {
  if (String.fromCharCode(...new Uint8Array(buf, 0, 4)) !== 'MMG1') throw new Error('binario no reconocido');
  const dv = new DataView(buf);
  const hlen = dv.getUint32(4, true);
  const cabecera = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 8, hlen)));
  let off = 8 + hlen;
  const V = cabecera.vertices, T = cabecera.triangulos;
  const pos = new Float32Array(buf.slice(off, off + V * 12)); off += V * 12;
  const col = new Uint8Array(buf.slice(off, off + V * 3)); off += V * 3;
  const idx = new Uint32Array(buf.slice(off, off + T * 12));
  return { cabecera, pos, col, idx };
}

/* ---------------- arranque ---------------- */
async function arrancar() {
  const paso = (f, txt) => { $('carga-barra').style.width = (f * 100).toFixed(0) + '%'; if (txt) $('carga-txt').textContent = txt; };
  paso(0.05, 'Leyendo el catálogo funcional…');
  red = await (await fetch('datos/red.json?v=r2')).json();
  prepararEscena();
  montarSuelo();
  paso(0.2, 'Trazando las 560 vías…');
  montarRed();
  paso(0.55, 'Colocando las 240 estaciones…');
  const buf = await (await fetch('datos/estaciones.bin?v=r2')).arrayBuffer();
  montarEstaciones(leerMMG(buf));
  paso(0.85, 'Subiendo los trenes a la vía…');
  await montarTrenes();
  paso(0.96, 'Interfaz…');
  pintarInterfaz();
  aplicar();
  ENCUADRES.centro();
  paso(1, 'Listo');
  setTimeout(() => { $('carga').hidden = true; }, 250);
}

function prepararEscena() {
  escena = new THREE.Scene();
  escena.background = new THREE.Color(0x070b12);
  escena.fog = new THREE.Fog(0x070b12, 16000, 90000);

  camara = new THREE.PerspectiveCamera(45, 1, 4, 300000);
  camara.position.set(-1200, 1700, 1500);

  renderer = new THREE.WebGLRenderer({ canvas: $('lienzo'), antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.12;

  control = new OrbitControls(camara, renderer.domElement);
  control.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE };
  control.touches = { ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_ROTATE };
  control.enableDamping = true;
  control.dampingFactor = 0.09;
  control.screenSpacePanning = false;
  control.zoomToCursor = true;
  control.zoomSpeed = 1.2;
  control.rotateSpeed = 0.55;
  control.keyPanSpeed = 60;
  control.minDistance = 40;
  control.maxDistance = 80000;
  control.maxPolarAngle = Math.PI * 0.495;
  control.target.set(0, -14, 0);
  control.listenToKeyEvents(window);
  renderer.domElement.addEventListener('dblclick', () => acercar(0.45));

  escena.add(new THREE.HemisphereLight(0xdfeaff, 0x1a2028, 2.2));
  const sol = new THREE.DirectionalLight(0xffffff, 1.6);
  sol.position.set(-8000, 12000, 6000);
  escena.add(sol);

  grupoEstaciones = new THREE.Group();
  grupoRed = new THREE.Group();
  grupoTrenes = new THREE.Group();
  escena.add(grupoEstaciones, grupoRed, grupoTrenes);

  new ResizeObserver(ajustar).observe($('escena'));
  ajustar();
  renderer.domElement.addEventListener('pointermove', alMover);
  renderer.domElement.addEventListener('click', alPulsar);
  renderer.domElement.addEventListener('pointerleave', () => { hover = -1; pintarFicha(-1); });
  reloj = new THREE.Clock();
  renderer.setAnimationLoop(bucle);
}

function ajustar() {
  const caja = $('escena');
  const ancho = caja.clientWidth || 1, alto = caja.clientHeight || 1;
  renderer.setSize(ancho, alto, false);
  camara.aspect = ancho / alto;
  camara.updateProjectionMatrix();
}

/* ---------------- suelo (la calle del catálogo: vestíbulo a y = 0) ---------------- */
function montarSuelo() {
  suelo = new THREE.Mesh(
    new THREE.PlaneGeometry(42000, 38000),
    new THREE.MeshStandardMaterial({
      color: 0x2c3e57, transparent: true, opacity: Math.min(1, estado.opacidad),
      depthWrite: false, roughness: 0.95, metalness: 0,
    })
  );
  suelo.rotation.x = -Math.PI / 2;
  suelo.renderOrder = 10;
  escena.add(suelo);
}

/* ---------------- red: cada tramo tal cual, sin splines ---------------- */
function montarRed() {
  const porLinea = new Map();
  for (const r of red.rutas) {
    if (!porLinea.has(r.l)) porLinea.set(r.l, []);
    porLinea.get(r.l).push(r);
  }

  const andenesLine = [];
  for (const est of red.estaciones) {
    for (const a of est.andenes) {
      for (let i = 0; i < a.path.length - 1; i++) andenesLine.push(...a.path[i], ...a.path[i + 1]);
    }
  }
  const geoA = new THREE.BufferGeometry();
  geoA.setAttribute('position', new THREE.BufferAttribute(new Float32Array(andenesLine), 3));
  const mallaAndenes = new THREE.LineSegments(geoA, new THREE.LineBasicMaterial({
    color: 0x9fb6d0, transparent: true, opacity: 0.4,
  }));
  mallaAndenes.renderOrder = 2;
  grupoRed.add(mallaAndenes);

  for (const [linea, rutas] of porLinea) {
    const col = new THREE.Color(COLOR[linea] || '#8a92a0');
    const g = new THREE.Group();
    g.userData.ref = linea;

    // base: un LineSegments por LÍNEA (13 llamadas de dibujo, sin saltos entre tramos)
    const paradas = [];
    for (const r of rutas) {
      for (let i = 0; i < r.p.length - 1; i++) paradas.push(...r.p[i], ...r.p[i + 1]);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(paradas), 3));
    const nVert = paradas.length / 3;
    const colorArr = new Float32Array(nVert * 3);
    for (let i = 0; i < nVert; i++) { colorArr[i * 3] = col.r; colorArr[i * 3 + 1] = col.g; colorArr[i * 3 + 2] = col.b; }
    geo.setAttribute('color', new THREE.BufferAttribute(colorArr, 3));
    const base = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.9,
    }));
    base.renderOrder = 3;
    g.add(base);
    grupoRed.add(g);

    // cadenas de circulación: tramos encadenados greedy (ida de la línea)
    const usados = new Set();
    for (const r0 of rutas) {
      if (usados.has(r0)) continue;
      const cadena = [r0];
      usados.add(r0);
      let cola = r0.arr;
      for (let v = 0; v < rutas.length; v++) {
        const sig = rutas.find((r) => !usados.has(r) && (r.dep === cola || r.arr === cola));
        if (!sig) break;
        usados.add(sig);
        if (sig.dep !== cola) { sig.p.reverse(); const t = sig.dep; sig.dep = sig.arr; sig.arr = t; }
        cadena.push(sig);
        cola = sig.arr;
      }
      cadenas.push({ linea, cadena });
    }
  }
}

/* ---------------- estaciones reales ---------------- */
async function montarEstaciones(mm) {
  cab = mm.cabecera;
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(mm.pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(new Uint8Array(mm.col), 3, true));
  geo.setIndex(new THREE.BufferAttribute(mm.idx, 1));
  geo.computeVertexNormals();
  const malla = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
    vertexColors: true, roughness: 0.6, metalness: 0.05, side: THREE.DoubleSide,
    emissive: 0x0c1220, emissiveIntensity: 0.5,
  }));
  grupoEstaciones.add(malla);
  centros = cab.estaciones.map((e) => new THREE.Vector3(e.c[0], e.c[1], e.c[2]));

  for (const e of red.estaciones) porCodigo.set(e.code, e);

  miras = new THREE.Group();
  const anillo = new THREE.Mesh(new THREE.TorusGeometry(34, 2.6, 8, 44),
    new THREE.MeshBasicMaterial({ color: 0xff7a2a }));
  anillo.rotation.x = -Math.PI / 2;
  miras.add(anillo);
  miras.visible = false;
  escena.add(miras);

  // pozos: del techo del vestíbulo a la calle (y = 0 del catálogo)
  const pozos = new Float32Array(cab.estaciones.length * 6);
  cab.estaciones.forEach((e, i) => {
    const [x, , z] = e.pozo;
    const top = Math.min(e.pozo_y, 0);
    pozos.set([x, 0.4, z, x, top, z], i * 6);
  });
  const geoP2 = new THREE.BufferGeometry();
  geoP2.setAttribute('position', new THREE.BufferAttribute(pozos, 3));
  grupoEstaciones.add(new THREE.LineSegments(geoP2, new THREE.LineBasicMaterial({
    color: 0x7f96b5, transparent: true, opacity: 0.45,
  })));
  // remate del pozo en la calle: disco plano por estación
  const discos = [];
  for (const e of cab.estaciones) {
    const [x, , z] = e.pozo;
    if (e.pozo_y < 0) { discos.push(x, 0.5, z); }
  }
  const geoD = new THREE.BufferGeometry();
  geoD.setAttribute('position', new THREE.BufferAttribute(new Float32Array(discos), 3));
  const puntosDisco = new THREE.Points(geoD, new THREE.PointsMaterial({
    color: 0xd9e6f6, size: 26, sizeAttenuation: true, transparent: true, opacity: 0.85,
  }));
  puntosDisco.renderOrder = 6;
  grupoEstaciones.add(puntosDisco);
}

/* ---------------- trenes del catálogo sobre sus polilíneas ---------------- */
function montarCurvaCadena(cadena) {
  const puntos = [];
  for (const r of cadena) {
    if (puntos.length) puntos.pop();
    for (const p of r.p) puntos.push(p[0], p[1], p[2]);
  }
  const n = puntos.length / 3;
  let largo = 0;
  const secciones = new Float64Array(n);
  secciones[0] = 0;
  for (let i = 1; i < n; i++) {
    largo += Math.hypot(puntos[i * 3] - puntos[(i - 1) * 3],
                        puntos[i * 3 + 1] - puntos[(i - 1) * 3 + 1],
                        puntos[i * 3 + 2] - puntos[(i - 1) * 3 + 2]);
    secciones[i] = largo;
  }
  return { puntos, secciones, largo, n };
}

function puntoEn(cad, s) {
  const { puntos, secciones, n } = cad;
  let lo = 0;
  while (lo + 1 < n - 1 && secciones[lo + 1] <= s) lo++;
  const t = (s - secciones[lo]) / Math.max(1e-9, secciones[lo + 1] - secciones[lo]);
  const i0 = lo * 3, i1 = Math.min(lo + 1, n - 1) * 3;
  return {
    p: [puntos[i0], puntos[i0 + 1], puntos[i0 + 2]],
    q: [puntos[i1], puntos[i1 + 1], puntos[i1 + 2]],
  };
}

async function montarTrenes() {
  const cargador = new GLTFLoader();
  const familias = {};
  for (const [familia, url] of Object.entries(GLB_TREN)) {
    try {
      const gltf = await cargador.loadAsync(url);
      const modelo = gltf.scene;
      modelo.traverse((o) => {
        if (o.isMesh && o.material) {
          o.material = o.material.clone();
          if (o.material.emissive) { o.material.emissive.set(0x39516e); o.material.emissiveIntensity = 0.55; }
        }
      });
      const caja = new THREE.Box3().setFromObject(modelo);
      const centro = caja.getCenter(new THREE.Vector3());
      const tam = caja.getSize(new THREE.Vector3());
      modelo.position.set(-centro.x, -caja.min.y, -centro.z);
      const g = new THREE.Group();
      g.add(modelo);
      g.updateMatrixWorld(true);
      familias[familia] = { escena: g, largo: tam.z };
    } catch (e) {
      console.warn('tren', familia, e.message);
    }
  }

  // top-2 cadenas por línea (las más largas): 26 trenes, no 179
  const porLinea = new Map();
  for (const c of cadenas) {
    const largo = c.cadena.reduce((n, r) => {
      let m = 0;
      for (let i = 1; i < r.p.length; i++) m += Math.hypot(r.p[i][0] - r.p[i-1][0], r.p[i][1] - r.p[i-1][1], r.p[i][2] - r.p[i-1][2]);
      return n + m;
    }, 0);
    c._largo = largo;
    if (!porLinea.has(c.linea)) porLinea.set(c.linea, []);
    porLinea.get(c.linea).push(c);
  }
  const elegidas = [];
  for (const arr of porLinea.values()) {
    arr.sort((a, b) => b._largo - a._largo);
    elegidas.push(arr[0]);
    if (arr[1]) elegidas.push(arr[1]);
  }
  for (const c of elegidas) {
    if (!c) continue;
    const familia = TREN_DE[c.linea];
    const fam = familias[familia];
    if (!fam) continue;
    const curva = montarCurvaCadena(c.cadena);
    const m = new THREE.Group();
    m.add(fam.escena.clone(true));
    m.userData = { curva, fase: Math.random() * 2, familia };
    colocarTren(m, m.userData.fase);
    grupoTrenes.add(m);
    trenes.push(m);
  }
}

const ARRIBA = new THREE.Vector3(0, 1, 0);
function colocarTren(m, fase) {
  const { curva } = m.userData;
  const L = curva.largo;
  const ciclo = 2 * L;                       // ida y vuelta sobre la misma cadena
  let s = (fase % 2) * L;
  let invertir = false;
  if (s > L) { s = ciclo - s; invertir = true; }
  const { p, q } = puntoEn(curva, s);
  const tan = new THREE.Vector3(q[0] - p[0], q[1] - p[1], q[2] - p[2]);
  if (tan.lengthSq() < 1e-9) return;
  tan.normalize();
  if (invertir) tan.negate();
  const der = new THREE.Vector3().crossVectors(ARRIBA, tan).normalize();
  const arr = new THREE.Vector3().crossVectors(tan, der).normalize();
  m.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(der, arr, tan));
  m.position.set(p[0], p[1] + 0.14, p[2]);
}

/* ---------------- estado ---------------- */
function aplicar() {
  if (suelo) {
    suelo.material.opacity = Math.min(1, estado.opacidad * 1.45);
    suelo.visible = estado.capas.suelo;
  }
  if (grupoEstaciones) grupoEstaciones.visible = estado.capas.estaciones;
  if (grupoTrenes) grupoTrenes.visible = estado.capas.trenes;
  if (grupoRed) {
    grupoRed.children.forEach((o) => {
      if (o.userData.ref) {
        o.visible = estado.capas.vias;
        const atenuar = estado.linea && o.userData.ref !== estado.linea;
        o.traverse((h) => {
          if (!h.material) return;
          h.material.transparent = true;
          h.material.opacity = atenuar ? 0.04 : 0.9;
        });
      } else {
        o.visible = estado.capas.andenes;
      }
    });
  }
  $('o-opacidad').textContent = Math.round(estado.opacidad * 100) + ' %';
  $('o-velocidad').textContent = 'x' + estado.velocidad;
  $('k-linea').textContent = estado.linea ? 'L' + estado.linea + ' aislada' : 'toda la red';
}

function aislarLinea(ref) {
  estado.linea = estado.linea === ref ? null : ref;
  document.querySelectorAll('#leyenda .mm-chispa').forEach((el) => {
    el.classList.toggle('is-on', !!estado.linea && el.dataset.ref === estado.linea);
  });
  aplicar();
}

/* ---------------- interacción ---------------- */
const proy = new THREE.Vector3();
function alMover(ev) {
  if (!centros.length) return;
  const r = renderer.domElement.getBoundingClientRect();
  const mx = ev.clientX - r.left, my = ev.clientY - r.top;
  let mejor = -1, mejorD = 36;
  for (let i = 0; i < centros.length; i++) {
    proy.copy(centros[i]);
    proy.project(camara);
    if (proy.z > 1) continue;
    const px = (proy.x * 0.5 + 0.5) * r.width;
    const py = (-proy.y * 0.5 + 0.5) * r.height;
    const d = Math.hypot(px - mx, py - my);
    if (d < mejorD) { mejorD = d; mejor = i; }
  }
  if (mejor !== hover) {
    hover = mejor;
    pintarFicha(hover);
    miras.visible = hover >= 0;
    if (hover >= 0) miras.position.copy(centros[hover]);
  }
}

function pintarFicha(i) {
  const ficha = $('ficha');
  if (i < 0) {
    ficha.classList.remove('is-on');
    $('f-nota').textContent = 'Pasa el cursor por una estación.';
    return;
  }
  const e = cab.estaciones[i];
  const cat = porCodigo.get(e.code);
  ficha.classList.add('is-on');
  $('f-nombre').textContent = cat ? cat.nombre : e.nombre;
  $('f-rail').textContent = e.grupos;
  $('f-andenes').textContent = cat ? cat.andenes.length : '—';
  const cont = $('f-lineas');
  cont.innerHTML = '';
  ((cat && cat.l.length ? cat.l : ['—'])).forEach((ref) => {
    const b = document.createElement('span');
    b.className = 'nz-badge nz-badge--neutral';
    b.textContent = 'L' + ref;
    b.style.borderColor = COLOR[ref] || '';
    cont.appendChild(b);
  });
  $('f-nota').textContent = e.grupos > 1
    ? `${e.grupos} bloques (uno por línea), cada uno sobre su andén`
    : 'Sobre su andén del catálogo · el pozo sube hasta la calle';
}

function alPulsar() {
  if (hover < 0) return;
  const c = centros[hover];
  volarA(new THREE.Vector3(c.x, c.y, c.z), 340, 0.3);
}

function acercar(factor) {
  const d = camara.position.clone().sub(control.target);
  const n = Math.max(control.minDistance, Math.min(control.maxDistance, d.length() * factor));
  camara.position.copy(control.target).add(d.setLength(n));
}

function volarA(destino, dist, elev = 0.5) {
  const desdeT = control.target.clone();
  const desdeC = camara.position.clone();
  const dxz = new THREE.Vector3(desdeC.x - desdeT.x, 0, desdeC.z - desdeT.z);
  if (dxz.lengthSq() < 1) dxz.set(-0.7, 0, 0.7);
  dxz.normalize();
  const horiz = dist / Math.sqrt(1 + elev * elev);
  const hastaC = new THREE.Vector3(destino.x + dxz.x * horiz, destino.y + elev * horiz, destino.z + dxz.z * horiz);
  if (document.hidden) { control.target.copy(destino); camara.position.copy(hastaC); control.update(); return; }
  const t0 = performance.now(), dur = 850;
  const paso = () => {
    const k = Math.min(1, (performance.now() - t0) / dur);
    const s = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    control.target.lerpVectors(desdeT, destino, s);
    camara.position.lerpVectors(desdeC, hastaC, s);
    if (k < 1) requestAnimationFrame(paso);
  };
  paso();
}

const ENCUADRES = {
  centro() { volarA(new THREE.Vector3(-600, -16, 700), 6200, 0.45); },
  red() { volarA(new THREE.Vector3(-1000, -10, 800), 18000, 0.55); },
  bilbao() {
    const i = cab.estaciones.findIndex((e) => (porCodigo.get(e.code)?.nombre || '').toLowerCase().includes('bilbao'));
    const e = cab.estaciones[i >= 0 ? i : 0];
    volarA(new THREE.Vector3(e.c[0], e.c[1], e.c[2]), 360, 0.3);
  },
  plano() {
    const t = control.target.clone();
    const hasta = new THREE.Vector3(t.x, t.y + 22000, t.z + 1);
    const desde = camara.position.clone();
    const t0 = performance.now();
    const paso = () => {
      const k = Math.min(1, (performance.now() - t0) / 800);
      camara.position.lerpVectors(desde, hasta, k);
      if (k < 1) requestAnimationFrame(paso);
    };
    paso();
  },
};

/* ---------------- interfaz ---------------- */
function pintarInterfaz() {
  const orden = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', 'R'];
  const leyenda = $('leyenda');
  orden.forEach((ref) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'mm-chispa';
    b.dataset.ref = ref;
    b.title = 'Pulsa para aislar la línea ' + ref;
    b.innerHTML = `<i style="background:${COLOR[ref]}"></i>${ref}`;
    b.addEventListener('click', () => aislarLinea(ref));
    leyenda.appendChild(b);
  });

  $('k-est').textContent = cab.estaciones.length;
  $('k-vias').textContent = red.rutas.length;
  $('k-andenes').textContent = red.estaciones.reduce((n, e) => n + e.andenes.length, 0);
  $('k-trenes').textContent = trenes.length;
  $('chip-estaciones').textContent = cab.estaciones.length + ' estaciones';
  document.title = `Metro de Madrid · ${cab.estaciones.length} estaciones · gemelo digital`;
}

function conectar() {
  const capas = { 'c-estaciones': 'estaciones', 'c-vias': 'vias', 'c-andenes': 'andenes', 'c-trenes': 'trenes', 'c-suelo': 'suelo' };
  for (const [id, clave] of Object.entries(capas)) {
    $(id).addEventListener('change', (e) => { estado.capas[clave] = e.target.checked; aplicar(); });
  }
  $('r-opacidad').addEventListener('input', (e) => { estado.opacidad = Number(e.target.value) / 100; aplicar(); });
  $('r-velocidad').addEventListener('input', (e) => { estado.velocidad = Number(e.target.value); aplicar(); });
  $('b-bilbao').addEventListener('click', ENCUADRES.bilbao);
  $('b-red').addEventListener('click', ENCUADRES.red);
  $('b-plano').addEventListener('click', ENCUADRES.plano);
  $('btn-panel').addEventListener('click', () => {
    const p = $('panel-movil');
    p.classList.toggle('is-on');
    if (p.classList.contains('is-on') && !p.childElementCount) {
      p.appendChild($('panel-izq').cloneNode(true));
      p.querySelectorAll('input').forEach((inp, i) => {
        inp.addEventListener('input', () => {
          const orig = $('panel-izq').querySelectorAll('input')[i];
          orig.value = inp.value;
          if (inp.type === 'checkbox') orig.checked = inp.checked;
          orig.dispatchEvent(new Event('input'));
          orig.dispatchEvent(new Event('change'));
        });
      });
    }
  });
}

/* ---------------- bucle ---------------- */
function bucle() {
  try { pasoBucle(); } catch (e) {
    if (!bucle.aviso) { bucle.aviso = true; console.error('bucle', e); $('k-fps').textContent = 'error: ' + e.message; }
  }
}

function pasoBucle() {
  const dt = reloj.getDelta();
  control.update();
  if (estado.capas.trenes && estado.velocidad > 0) {
    const v = 16.7 * estado.velocidad;
    for (const m of trenes) {
      m.userData.fase = (m.userData.fase + (dt * v) / m.userData.curva.largo) % 2;
      colocarTren(m, m.userData.fase);
    }
  }
  renderer.render(escena, camara);
  fps.n++; fps.t += dt;
  if (fps.t > 0.5) {
    $('k-fps').textContent = `${Math.round(fps.n / fps.t)} fps · ${renderer.info.render.calls} llamadas · ` +
      `${(renderer.info.render.triangles / 1000).toFixed(0)} k triángulos`;
    fps.n = 0; fps.t = 0;
  }
}

conectar();
arrancar().catch((e) => {
  console.error(e);
  $('carga-txt').textContent = 'No se ha podido montar la escena: ' + e.message;
});

window.__metro = {
  get estado() { return estado; }, get escena() { return escena; }, get camara() { return camara; },
  get control() { return control; }, get trenes() { return trenes; },
  ENCUADRES, cabecera: () => cab, red: () => red,
};
