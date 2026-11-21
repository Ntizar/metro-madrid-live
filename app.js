/* Gemelo digital del Metro de Madrid — escena three.js.
   Marco local: x = Este (m), z = -Norte (m), y = cota relativa a la Puerta del Sol.
   Reglas del encaje (medidas, no estimadas):
   · Cada estación define SU cota: el bake deja su vestíbulo a nivel de calle y su
     andén a la profundidad del propio modelo (registro "D").
   · La vía es la MISMA polilínea GTFS para traza, túnel y tren; su altura se interpola
     entre las estaciones que atraviesa (cota del terreno − profundidad del andén).
   · El desnivel global solo venía de un desfase de lectura del DEM: corregido. */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';

const $ = (id) => document.getElementById(id);
const D = 'datos/';
const ARRIBA = new THREE.Vector3(0, 1, 0);
const RADIO_VIA = { metro: 2.7, ligero: 2.2, cercanias: 4.0 };

const estado = {
  opacidad: 0.55,
  velocidad: 30,
  linea: null,
  capas: { estaciones: true, metro: true, ligero: true, cercanias: true, trenes: true, corteza: true, salidas: true },
};

let escena, camara, control, renderer, reloj;
let terreno, falda, arista, grupoEstaciones, grupoPozos, grupoLineas, grupoTrenes, miras;
let cabEstaciones = null, centros = [], cabTerreno = null;
let recorridos = [], trenes = [], alturas = null;
let hover = -1, fps = { t: 0, n: 0 }, matsLinea = [];

/* ---------------- red ---------------- */
async function traer(url, alProgresar) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  const total = Number(r.headers.get('content-length')) || 0;
  if (!total || !alProgresar || !r.body) return r.arrayBuffer();
  const lector = r.body.getReader();
  const trozos = []; let leido = 0;
  for (;;) {
    const { done, value } = await lector.read();
    if (done) break;
    trozos.push(value); leido += value.length;
    alProgresar(leido / total);
  }
  const salida = new Uint8Array(leido); let o = 0;
  for (const t of trozos) { salida.set(t, o); o += t.length; }
  return salida.buffer;
}

function leerMMG(buf) {
  if (String.fromCharCode(...new Uint8Array(buf, 0, 4)) !== 'MMG1') throw new Error('binario no reconocido');
  const dv = new DataView(buf);
  const hlen = dv.getUint32(4, true);
  const cab = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 8, hlen)));
  let off = 8 + hlen;
  const V = cab.vertices, T = cab.triangulos;
  const pos = new Float32Array(buf.slice(off, off + V * 12)); off += V * 12;
  const col = new Uint8Array(buf.slice(off, off + V * 3)); off += V * 3;
  const idx = new Uint32Array(buf.slice(off, off + T * 12));
  return { cab, pos, col, idx };
}

function leerCotas(url, nx, nz) {
  return new Promise((ok, no) => {
    const img = new Image();
    img.onload = () => {
      const c = document.createElement('canvas');
      c.width = nx; c.height = nz;
      const g = c.getContext('2d', { willReadFrequently: true });
      g.drawImage(img, 0, 0, nx, nz);
      const d = g.getImageData(0, 0, nx, nz).data;
      const h = new Float32Array(nx * nz);
      // Mismo empaquetado que escribe hornear.py: v = (cota + 1200) * 10
      for (let i = 0, p = 0; i < h.length; i++, p += 4) h[i] = (((d[p] << 8) | d[p + 1]) / 10) - 1200;
      ok(h);
    };
    img.onerror = () => no(new Error('no se pudo leer ' + url));
    img.src = url;
  });
}

/* ---------------- arranque ---------------- */
async function arrancar() {
  const paso = (f, txt) => { $('carga-barra').style.width = (f * 100).toFixed(0) + '%'; if (txt) $('carga-txt').textContent = txt; };
  paso(0.02, 'Leyendo el terreno medido…');
  cabTerreno = await (await fetch(D + 'terreno.json')).json();
  alturas = await leerCotas(D + 'terreno.png', cabTerreno.nx, cabTerreno.nz);
  paso(0.1, 'Cargando la ortofoto del PNOA…');
  prepararEscena();
  await montarTerreno();
  paso(0.32, 'Colocando las 240 estaciones…');
  await montarEstaciones();
  paso(0.72, 'Trazando las vías del CRTM…');
  const mundo = await (await fetch(D + 'mundo.json')).json();
  montarLineas(mundo);
  paso(0.9, 'Subiendo los trenes a la vía…');
  await montarTrenes();
  montarPozos();
  pintarInterfaz(mundo);
  aplicar();
  ENCUADRES.centro();
  paso(1, 'Listo');
  setTimeout(() => { $('carga').hidden = true; }, 250);
}

function prepararEscena() {
  escena = new THREE.Scene();
  escena.background = new THREE.Color(0x0a1118);
  escena.fog = new THREE.Fog(0x0a1118, 30000, 130000);

  camara = new THREE.PerspectiveCamera(45, 1, 4, 300000);
  camara.position.set(-1900, 2400, 2200);

  renderer = new THREE.WebGLRenderer({ canvas: $('lienzo'), antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;

  control = new OrbitControls(camara, renderer.domElement);
  // Mapa, no maqueta: arrastrar desplaza, botón derecho orbita, rueda acerca al cursor
  control.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE };
  control.touches = { ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_ROTATE };
  control.enableDamping = true;
  control.dampingFactor = 0.09;
  control.screenSpacePanning = false;
  control.zoomToCursor = true;
  control.zoomSpeed = 1.15;
  control.rotateSpeed = 0.55;
  control.keyPanSpeed = 60;
  control.minDistance = 60;
  control.maxDistance = 90000;
  control.maxPolarAngle = Math.PI * 0.492;
  control.target.set(0, -12, 0);
  control.listenToKeyEvents(window);

  escena.add(new THREE.HemisphereLight(0xffffff, 0x8d8b84, 2.0));
  const sol = new THREE.DirectionalLight(0xfff4e6, 2.1);
  sol.position.set(-12000, 16000, 8000);
  escena.add(sol);
  const relleno = new THREE.DirectionalLight(0xcfe0ff, 0.7);
  relleno.position.set(9000, 4000, -9000);
  escena.add(relleno);

  grupoEstaciones = new THREE.Group();
  grupoLineas = new THREE.Group();
  grupoTrenes = new THREE.Group();
  grupoPozos = new THREE.Group();
  escena.add(grupoEstaciones, grupoLineas, grupoTrenes, grupoPozos);

  renderer.domElement.addEventListener('dblclick', () => acercar(0.45));

  new ResizeObserver(ajustar).observe($('escena'));
  ajustar();
  renderer.domElement.addEventListener('pointermove', alMover);
  renderer.domElement.addEventListener('click', alPulsar);
  renderer.domElement.addEventListener('pointerleave', () => { hover = -1; pintarFicha(-1); });
  reloj = new THREE.Clock();
  renderer.setAnimationLoop(bucle);
}

function ajustarResolucionLineas() {
  const w = $('escena').clientWidth || 1, h = $('escena').clientHeight || 1;
  for (const m of matsLinea) m.resolution.set(w, h);
}

function ajustar() {
  const caja = $('escena');
  const ancho = caja.clientWidth || 1, alto = caja.clientHeight || 1;
  renderer.setSize(ancho, alto, false);
  camara.aspect = ancho / alto;
  camara.updateProjectionMatrix();
  ajustarResolucionLineas();
}

function cota(x, z) {
  const { x0, z0, nx, nz, ancho, alto } = cabTerreno;
  const fx = Math.min(Math.max((x - x0) / ancho, 0), 1) * (nx - 1);
  const fz = Math.min(Math.max((z - z0) / alto, 0), 1) * (nz - 1);
  const i0 = Math.min(Math.floor(fx), nx - 2), j0 = Math.min(Math.floor(fz), nz - 2);
  const dx = fx - i0, dz = fz - j0;
  const a = alturas[j0 * nx + i0], b = alturas[j0 * nx + i0 + 1];
  const c = alturas[(j0 + 1) * nx + i0], d = alturas[(j0 + 1) * nx + i0 + 1];
  return (a * (1 - dx) + b * dx) * (1 - dz) + (c * (1 - dx) + d * dx) * dz;
}

/* ---------------- terreno ---------------- */
async function montarTerreno() {
  const { x0, z0, nx, nz, ancho, alto } = cabTerreno;
  const segX = 340, segZ = 300;
  const nv = (segX + 1) * (segZ + 1);
  const pos = new Float32Array(nv * 3), uv = new Float32Array(nv * 2);
  let p = 0, q = 0;
  for (let iz = 0; iz <= segZ; iz++) {
    for (let ix = 0; ix <= segX; ix++) {
      const fx = ix / segX, fz = iz / segZ;
      const x = x0 + fx * ancho, z = z0 + fz * alto;
      const jx = Math.round(fx * (nx - 1)), jz = Math.round(fz * (nz - 1));
      pos[p++] = x; pos[p++] = alturas[jz * nx + jx]; pos[p++] = z;
      uv[q++] = fx; uv[q++] = fz;
    }
  }
  const idx = new Uint32Array(segX * segZ * 6);
  let k = 0;
  for (let iz = 0; iz < segZ; iz++) {
    for (let ix = 0; ix < segX; ix++) {
      const a = iz * (segX + 1) + ix, b = a + 1, c = a + segX + 1, d = c + 1;
      idx[k++] = a; idx[k++] = c; idx[k++] = b;
      idx[k++] = b; idx[k++] = c; idx[k++] = d;
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  geo.setIndex(new THREE.BufferAttribute(idx, 1));
  geo.computeVertexNormals();

  const tex = await new Promise((ok, no) => {
    new THREE.TextureLoader().load(D + 'ortofoto.jpg',
      (t) => { t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8; t.flipY = false; ok(t); }, undefined, no);
  });
  terreno = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
    map: tex, transparent: true, opacity: estado.opacidad, depthWrite: false,
    side: THREE.DoubleSide, roughness: 0.98, metalness: 0, color: 0x8e9dab,
  }));
  terreno.renderOrder = 20;
  escena.add(terreno);

  const anillo = [];
  for (let ix = 0; ix <= segX; ix++) anillo.push(ix);
  for (let iz = 1; iz <= segZ; iz++) anillo.push(iz * (segX + 1) + segX);
  for (let ix = segX - 1; ix >= 0; ix--) anillo.push(segZ * (segX + 1) + ix);
  for (let iz = segZ - 1; iz >= 1; iz--) anillo.push(iz * (segX + 1));
  const base = cabTerreno.cota_min - 700;
  const vp = [], vi = [];
  for (const i of anillo) vp.push(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2], pos[i * 3], base, pos[i * 3 + 2]);
  for (let i = 0; i < anillo.length - 1; i++) {
    const a = i * 2;
    vi.push(a, a + 1, a + 2, a + 2, a + 1, a + 3);
  }
  const geoF = new THREE.BufferGeometry();
  geoF.setAttribute('position', new THREE.BufferAttribute(new Float32Array(vp), 3));
  geoF.setIndex(vi);
  geoF.computeVertexNormals();
  falda = new THREE.Mesh(geoF, new THREE.MeshStandardMaterial({
    color: 0x44586f, roughness: 0.9, metalness: 0.05, side: THREE.DoubleSide,
    flatShading: true, emissive: 0x0d1a2a, emissiveIntensity: 0.7,
  }));
  escena.add(falda);

  arista = new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints(anillo.map((i) => new THREE.Vector3(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]))),
    new THREE.LineBasicMaterial({ color: 0xd8e6f5, transparent: true, opacity: 0.55 })
  );
  arista.renderOrder = 25;
  escena.add(arista);
}

/* ---------------- estaciones ---------------- */
async function montarEstaciones() {
  const buf = await traer(D + 'estaciones.bin', (f) => { $('carga-barra').style.width = (32 + f * 42).toFixed(0) + '%'; });
  const { cab, pos, col, idx } = leerMMG(buf);
  cabEstaciones = cab;
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(new Uint8Array(col), 3, true));
  geo.setIndex(new THREE.BufferAttribute(idx, 1));
  geo.computeVertexNormals();
  const malla = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
    vertexColors: true, roughness: 0.55, metalness: 0.08, side: THREE.DoubleSide,
    emissive: 0x0a0f18, emissiveIntensity: 0.5,
  }));
  grupoEstaciones.add(malla);
  centros = cab.estaciones.map((e) => new THREE.Vector3(e.c[0], e.c[1], e.c[2]));

  miras = new THREE.Group();
  const anillo = new THREE.Mesh(new THREE.TorusGeometry(46, 3.2, 8, 48),
    new THREE.MeshBasicMaterial({ color: 0xff6a00 }));
  anillo.rotation.x = -Math.PI / 2;
  miras.add(anillo);
  const poste = new THREE.Mesh(new THREE.CylinderGeometry(1.2, 1.2, 1, 6),
    new THREE.MeshBasicMaterial({ color: 0xff6a00, transparent: true, opacity: 0.5 }));
  poste.name = 'poste';
  miras.add(poste);
  miras.visible = false;
  escena.add(miras);
}

/* ---------------- vías con perfil de cota ---------------- */
/* El perfil de altura de cada carril lo definen las estaciones que atraviesa:
   en cada una, el túnel pasa 2,2 m por debajo del andén (andén a la profundidad
   del propio modelo); entre estaciones mantiene profundidad constante bajo la calle. */
function curvaVia(via, anclas) {
  const pts = via.p;
  const total = pts.length - 1;
  const puntos3 = pts.map(([x, z], i) => {
    const s = i / total;
    let sube;
    if (!anclas.length) {
      sube = 20;
    } else if (s <= anclas[0].s) {
      sube = anclas[0].D;
    } else if (s >= anclas[anclas.length - 1].s) {
      sube = anclas[anclas.length - 1].D;
    } else {
      let j = 0;
      while (j < anclas.length - 1 && anclas[j + 1].s < s) j++;
      const a = anclas[j], b = anclas[j + 1];
      const t = (s - a.s) / Math.max(1e-9, b.s - a.s);
      const k = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; // suavizado
      sube = a.D + (b.D - a.D) * k;
    }
    const y = cota(x, z) - sube - 2.2;
    return new THREE.Vector3(x, y, z);
  });
  const curva = new THREE.CatmullRomCurve3(puntos3, false, 'centripetal', 0.5);
  curva.largo = curva.getLength();
  return curva;
}

function montarLineas(mundo) {
  // índice de anclas por (ref, carril)
  const porCarril = new Map();
  for (const e of cabEstaciones.estaciones) {
    if (!e.L || e.kv === undefined) continue;
    const clave = e.L + '#' + e.kv;
    if (!porCarril.has(clave)) porCarril.set(clave, []);
    porCarril.get(clave).push({ s: e.s, D: Math.max(8, e.D) });
  }
  for (const list of porCarril.values()) list.sort((a, b) => a.s - b.s);

  for (const linea of mundo.lineas) {
    const g = new THREE.Group();
    g.userData.red = linea.red;
    g.userData.ref = linea.ref;
    const col = new THREE.Color(linea.color);

    linea.vias.forEach((via, k) => {
      const clave = linea.ref + '#' + k;
      const anclas = (porCarril.get(clave) || []).map((a) => ({ s: a.s, D: a.D }));
      const curva = curvaVia(via, anclas);

      const segTubo = Math.min(1400, Math.max(16, Math.round(curva.largo / 14)));
      const tubo = new THREE.Mesh(
        new THREE.TubeGeometry(curva, segTubo, RADIO_VIA[linea.red] || 2.6, 6, false),
        new THREE.MeshStandardMaterial({
          color: col, roughness: 0.5, metalness: 0.1, emissive: col, emissiveIntensity: 0.22,
          transparent: true, opacity: 0.34, depthWrite: false,
        })
      );
      g.add(tubo);

      const n = Math.min(2200, Math.max(12, Math.round(curva.largo / 9)));
      const muestras = curva.getSpacedPoints(n);
      const plano = [];
      for (const v of muestras) plano.push(v.x, v.y, v.z);
      const gl = new LineGeometry();
      gl.setPositions(plano);
      const ml = new LineMaterial({
        color: col, linewidth: linea.red === 'cercanias' ? 2.0 : 2.6,
        transparent: true, opacity: 0.95,
      });
      matsLinea.push(ml);
      const traza = new Line2(gl, ml);
      traza.computeLineDistances();
      traza.renderOrder = 4;
      g.add(traza);

      recorridos.push({ linea, curva, largo: curva.largo, dir: via.d });
    });
    grupoLineas.add(g);
  }
}

/* ---------------- trenes ---------------- */
async function montarTrenes() {
  let geo;
  try {
    const { cab, pos, col, idx } = leerMMG(await traer(D + 'tren.bin'));
    geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(new Uint8Array(col), 3, true));
    geo.setIndex(new THREE.BufferAttribute(idx, 1));
    geo.computeVertexNormals();
    geo.userData.largo = cab.largo;
  } catch (e) {
    console.warn('sin trenes:', e.message);
    return;
  }
  const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.42, metalness: 0.35, side: THREE.DoubleSide });
  recorridos.filter((r) => r.linea.red === 'metro').forEach((r, i) => {
    const m = new THREE.Mesh(geo, mat);
    m.userData = { curva: r.curva, largo: r.largo, t: (i * 0.37) % 1 };
    colocarTren(m, m.userData.t);
    grupoTrenes.add(m);
    trenes.push(m);
  });
}

function colocarTren(m, t) {
  const c = m.userData.curva;
  const p = c.getPointAt(t);
  const tan = c.getTangentAt(t);
  if (tan.lengthSq() < 1e-9) return;
  tan.normalize();
  const der = new THREE.Vector3().crossVectors(ARRIBA, tan).normalize();
  const arr = new THREE.Vector3().crossVectors(tan, der).normalize();
  m.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(der, arr, tan));
  // la base del tren (rueda y=0) apoya bajo el eje del túnel: sobre la vía
  m.position.set(p.x, p.y + (RADIO_VIA.metro || 2.7) * 0.32, p.z);
}

/* ---------------- pozos a superficie ---------------- */
function montarPozos() {
  grupoPozos.clear();
  if (!cabEstaciones) return;
  const lista = cabEstaciones.estaciones;
  const n = lista.length;
  const pos = new Float32Array(n * 6), col = new Float32Array(n * 6);
  lista.forEach((e, i) => {
    const x = e.c[0], z = e.c[2];
    const calle = (e.y_calle !== undefined) ? e.y_calle : cota(x, z);
    pos.set([x, calle + 14, z, x, e.c[1], z], i * 6);   // calle → andén
    const c = new THREE.Color(e.color);
    col.set([c.r, c.g, c.b, c.r, c.g, c.b], i * 6);
  });
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  grupoPozos.add(new THREE.LineSegments(geo,
    new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.3 })));
}

/* ---------------- estado ---------------- */
function aplicar() {
  if (terreno) {
    terreno.material.opacity = estado.opacidad;
    terreno.material.depthWrite = estado.opacidad > 0.94;
    terreno.material.needsUpdate = true;
    terreno.visible = estado.capas.corteza;
    falda.visible = estado.capas.corteza;
    arista.visible = estado.capas.corteza;
  }
  if (grupoEstaciones) grupoEstaciones.visible = estado.capas.estaciones;
  if (grupoPozos) grupoPozos.visible = estado.capas.salidas;
  if (grupoTrenes) grupoTrenes.visible = estado.capas.trenes;
  grupoLineas.children.forEach((g) => {
    g.visible = estado.capas[g.userData.red] !== false;
    const atenuar = estado.linea && g.userData.ref !== estado.linea;
    g.traverse((o) => {
      if (!o.material) return;
      o.material.transparent = true;
      o.material.opacity = atenuar ? 0.05 : (o.isLine2 ? 0.95 : 0.34);
    });
  });
  $('o-opacidad').textContent = Math.round(estado.opacidad * 100) + ' %';
  $('o-velocidad').textContent = 'x' + estado.velocidad;
  $('k-linea').textContent = estado.linea ? 'L' + estado.linea + ' aislada' : 'toda la red';
  if (hover >= 0) mostrarMira(hover);
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
  if (!cabEstaciones) return;
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
    if (hover >= 0) mostrarMira(hover); else miras.visible = false;
  }
}

function mostrarMira(i) {
  const e = cabEstaciones.estaciones[i];
  miras.position.set(e.c[0], e.c[1], e.c[2]);
  miras.visible = true;
  const poste = miras.getObjectByName('poste');
  const yCalle = (e.y_calle !== undefined) ? e.y_calle : cota(e.c[0], e.c[2]);
  const alto = Math.max(4, yCalle - e.c[1] + 14);
  poste.scale.set(1, alto, 1);
  poste.position.y = alto / 2 + 8;
  miras.scale.setScalar(Math.max(0.5, Math.min(2.4, 900 / camara.position.distanceTo(miras.position))));
}

function pintarFicha(i) {
  const ficha = $('ficha');
  if (i < 0 || !cabEstaciones) {
    ficha.classList.remove('is-on');
    $('f-nota').textContent = 'Pasa el cursor por una estación.';
    return;
  }
  const e = cabEstaciones.estaciones[i];
  ficha.classList.add('is-on');
  $('f-nombre').textContent = e.nombre;
  $('f-tri').textContent = e.tri.toLocaleString('es-ES');
  $('f-eje').textContent = e.dist >= 0 ? `${e.dist} m · ${e.giro}°` : 'sin línea';
  $('f-profundidad').textContent = Math.round(e.D) + ' m';
  const cont = $('f-lineas');
  cont.innerHTML = '';
  (e.lineas.length ? e.lineas : ['—']).forEach((ref) => {
    const b = document.createElement('span');
    b.className = 'nz-badge nz-badge--neutral';
    b.textContent = 'L' + ref;
    b.style.borderColor = e.color;
    cont.appendChild(b);
  });
  $('f-nota').textContent = e.sep_vias
    ? `Vestíbulo a la calle · andén a ${Math.round(e.D)} m · vías a ${e.sep_vias} m`
    : `Vestíbulo a la calle · andén a ${Math.round(e.D)} m`;
}

function alPulsar() {
  if (hover < 0 || !cabEstaciones) return;
  const e = cabEstaciones.estaciones[hover];
  volarA(new THREE.Vector3(e.c[0], e.c[1], e.c[2]), 520, 0.35);
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
  centro() { volarA(new THREE.Vector3(-700, -6, 600), 7000, 0.45); },
  red() { volarA(new THREE.Vector3(-1200, -10, 900), 21000, 0.55); },
  sol() {
    const i = cabEstaciones.estaciones.findIndex((e) => /sol/i.test(e.id) || /^sol\b/i.test(e.nombre));
    const e = cabEstaciones.estaciones[i >= 0 ? i : 0];
    volarA(new THREE.Vector3(e.c[0], e.c[1], e.c[2]), 420, 0.3);
  },
  plano() {
    const t = control.target.clone();
    estado.opacidad = 0.92;
    $('r-opacidad').value = 92;
    aplicar();
    const hasta = new THREE.Vector3(t.x, t.y + 26000, t.z + 1);
    if (document.hidden) { camara.position.copy(hasta); control.update(); return; }
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
function pintarInterfaz(mundo) {
  const metro = mundo.lineas.filter((l) => l.red === 'metro');
  const ligero = mundo.lineas.filter((l) => l.red === 'ligero');
  const cerc = mundo.lineas.filter((l) => l.red === 'cercanias');
  const leyenda = $('leyenda');
  [...metro, ...ligero].forEach((l) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'mm-chispa';
    b.dataset.ref = l.ref;
    b.title = `${l.nombre} · ${l.largo_km} km · ${l.trazas} vía(s) — pulsa para aislar`;
    b.innerHTML = `<i style="background:${l.color}"></i>${l.ref}`;
    b.addEventListener('click', () => aislarLinea(l.ref));
    leyenda.appendChild(b);
  });
  const c = document.createElement('span');
  c.className = 'mm-chispa';
  c.innerHTML = `<i style="background:#868584"></i>Cercanías (${cerc.length})`;
  leyenda.appendChild(c);

  const reg = cabEstaciones.registro || {};
  $('k-est').textContent = cabEstaciones.estaciones.length;
  $('k-vias').textContent = recorridos.length;
  $('k-profundidad').textContent = (reg.profundidad_anden_mediana_m ?? '—') + ' m';
  $('k-reg').textContent = (reg.mediana_m ?? '—') + ' m';
  $('chip-estaciones').textContent = cabEstaciones.estaciones.length + ' estaciones';
  $('chip-tri').textContent = cabEstaciones.triangulos.toLocaleString('es-ES') + ' triángulos de estación';
  document.title = `Metro de Madrid · ${cabEstaciones.estaciones.length} estaciones · gemelo digital`;
}

function conectar() {
  const capas = { 'c-estaciones': 'estaciones', 'c-metro': 'metro', 'c-ligero': 'ligero', 'c-cercanias': 'cercanias', 'c-trenes': 'trenes', 'c-corteza': 'corteza', 'c-salidas': 'salidas' };
  for (const [id, clave] of Object.entries(capas)) {
    $(id).addEventListener('change', (e) => { estado.capas[clave] = e.target.checked; aplicar(); });
  }
  $('r-opacidad').addEventListener('input', (e) => { estado.opacidad = Number(e.target.value) / 100; aplicar(); });
  $('r-velocidad').addEventListener('input', (e) => { estado.velocidad = Number(e.target.value); aplicar(); });
  $('b-sol').addEventListener('click', ENCUADRES.sol);
  $('b-red').addEventListener('click', ENCUADRES.red);
  $('b-orbita').addEventListener('click', ENCUADRES.plano);
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
      m.userData.t = (m.userData.t + (dt * v) / m.userData.largo) % 1;
      colocarTren(m, m.userData.t);
    }
  }
  if (miras && miras.visible && hover >= 0) mostrarMira(hover);
  renderer.render(escena, camara);
  fps.n++; fps.t += dt;
  if (fps.t > 0.5) {
    $('k-fps').textContent = `${Math.round(fps.n / fps.t)} fps · ${renderer.info.render.calls} llamadas · ` +
      `${(renderer.info.render.triangles / 1000).toFixed(0)} k triángulos de escena`;
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
  get control() { return control; }, get renderer() { return renderer; }, get hover() { return hover; },
  get trenes() { return trenes; }, ENCUADRES, centros: () => centros, cabecera: () => cabEstaciones,
  recorridos: () => recorridos.map((r) => ({ ref: r.linea.ref, dir: r.dir, largo: Math.round(r.largo) })),
};
