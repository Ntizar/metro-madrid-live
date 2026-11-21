/* Gemelo digital del Metro de Madrid — escena three.js.
   Marco local: x = Este (m), z = -Norte (m), y = cota real (m).
   Fuentes: modelos glTF del respaldo 2026-11-20, GTFS del CRTM, DEM y ortofoto del IGN. */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';

const $ = (id) => document.getElementById(id);
const D = 'datos/';

const estado = {
  profundidad: 22,
  opacidad: 0.55,
  velocidad: 30,
  linea: null,
  capas: { estaciones: true, metro: true, ligero: true, cercanias: true, trenes: true, corteza: true, salidas: true },
};

let escena, camara, control, renderer, reloj;
let terreno, grupoEstaciones, grupoPozos, grupoLineas, grupoTrenes, grupoSuperficie;
let mallaEstaciones = null, cabEstaciones = null, centros = [], miras = null;
let curvas = [], trenes = [], alturas = null, cabTerreno = null;
let hover = -1, activo = true, fps = { t: 0, n: 0 };

/* ---------- utilidades ---------- */
async function traer(url, alProgresar) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  const total = Number(r.headers.get('content-length')) || 0;
  if (!total || !alProgresar || !r.body) return r.arrayBuffer();
  const lector = r.body.getReader();
  const trozos = [];
  let leido = 0;
  for (;;) {
    const { done, value } = await lector.read();
    if (done) break;
    trozos.push(value);
    leido += value.length;
    alProgresar(leido / total);
  }
  const salida = new Uint8Array(leido);
  let o = 0;
  for (const t of trozos) { salida.set(t, o); o += t.length; }
  return salida.buffer;
}

function leerMMG(buf) {
  const cabecera = new Uint8Array(buf, 0, 4);
  if (String.fromCharCode(...cabecera) !== 'MMG1') throw new Error('binario no reconocido');
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
      const lienzo = document.createElement('canvas');
      lienzo.width = nx; lienzo.height = nz;
      const g = lienzo.getContext('2d', { willReadFrequently: true });
      g.drawImage(img, 0, 0, nx, nz);
      const d = g.getImageData(0, 0, nx, nz).data;
      const h = new Float32Array(nx * nz);
      for (let i = 0, p = 0; i < h.length; i++, p += 4) h[i] = (((d[p] << 8) | d[p + 1]) / 10) - 1000;
      ok(h);
    };
    img.onerror = () => no(new Error('no se pudo leer ' + url));
    img.src = url;
  });
}

/* ---------- montaje ---------- */
async function arrancar() {
  const paso = (f, txt) => { $('carga-barra').style.width = (f * 100).toFixed(0) + '%'; if (txt) $('carga-txt').textContent = txt; };

  paso(0.02, 'Leyendo el terreno medido…');
  cabTerreno = await (await fetch(D + 'terreno.json')).json();
  const [mundo] = await Promise.all([fetch(D + 'mundo.json').then((r) => r.json())]);
  alturas = await leerCotas(D + 'terreno.png', cabTerreno.nx, cabTerreno.nz);
  paso(0.12, 'Cargando la ortofoto del IGN…');

  prepararEscena();
  await montarTerreno();
  paso(0.35, 'Colocando las 240 estaciones…');
  await montarEstaciones();
  paso(0.78, 'Trazando túneles y cercanías…');
  montarLineas(mundo);
  paso(0.88, 'Subiendo los trenes a la vía…');
  await montarTrenes();
  paso(0.97, 'Últimos ajustes…');
  montarPozos();
  pintarInterfaz(mundo);
  aplicar();
  ENCUADRES.centro();
  paso(1, 'Listo');
  setTimeout(() => { $('carga').hidden = true; }, 260);
}

function prepararEscena() {
  escena = new THREE.Scene();
  escena.background = new THREE.Color(0x0a1118);
  escena.fog = new THREE.Fog(0x0a1118, 30000, 130000);

  camara = new THREE.PerspectiveCamera(42, 1, 5, 260000);
  camara.position.set(-2100, 2900, 2600);

  renderer = new THREE.WebGLRenderer({ canvas: $('lienzo'), antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;

  control = new OrbitControls(camara, renderer.domElement);
  control.enableDamping = true;
  control.dampingFactor = 0.08;
  control.maxPolarAngle = Math.PI * 0.495;
  control.minDistance = 90;
  control.maxDistance = 90000;
  control.target.set(0, -10, 0);

  escena.add(new THREE.HemisphereLight(0xffffff, 0x8d8b84, 2.0));
  const sol = new THREE.DirectionalLight(0xfff4e6, 2.1);
  sol.position.set(-12000, 16000, 8000);
  escena.add(sol);
  const relleno = new THREE.DirectionalLight(0xcfe0ff, 0.75);
  relleno.position.set(9000, 4000, -9000);
  escena.add(relleno);

  grupoEstaciones = new THREE.Group();
  grupoLineas = new THREE.Group();
  grupoTrenes = new THREE.Group();
  grupoPozos = new THREE.Group();
  escena.add(grupoEstaciones, grupoLineas, grupoTrenes, grupoPozos);

  new ResizeObserver(ajustar).observe($('escena'));
  ajustar();

  $('lienzo').addEventListener('pointermove', alMover);
  $('lienzo').addEventListener('click', alPulsar);
  $('lienzo').addEventListener('pointerleave', () => { hover = -1; pintarFicha(-1); });
  reloj = new THREE.Clock();
  renderer.setAnimationLoop(bucle);
}

const matsLinea = [];
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

/* cota bilineal en el marco local */
function cota(x, z) {
  const { x0, z0, nx, nz, ancho, alto } = cabTerreno;
  const fx = Math.min(Math.max((x - x0) / ancho, 0), 1) * (nx - 1);
  const fz = Math.min(Math.max((z - z0) / alto, 0), 1) * (nz - 1);
  const x0i = Math.min(Math.floor(fx), nx - 2), z0i = Math.min(Math.floor(fz), nz - 2);
  const dx = fx - x0i, dz = fz - z0i;
  const a = alturas[z0i * nx + x0i], b = alturas[z0i * nx + x0i + 1];
  const c = alturas[(z0i + 1) * nx + x0i], d = alturas[(z0i + 1) * nx + x0i + 1];
  return (a * (1 - dx) + b * dx) * (1 - dz) + (c * (1 - dx) + d * dx) * dz;
}

async function montarTerreno() {
  const { x0, z0, nx, nz, ancho, alto } = cabTerreno;
  const segX = 340, segZ = 300;
  const verts = (segX + 1) * (segZ + 1);
  const pos = new Float32Array(verts * 3);
  const uv = new Float32Array(verts * 2);
  let p = 0, q = 0;
  for (let iz = 0; iz <= segZ; iz++) {
    const fz = iz / segZ;
    for (let ix = 0; ix <= segX; ix++) {
      const fx = ix / segX;
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
    const l = new THREE.TextureLoader();
    l.load(D + 'ortofoto.jpg', (t) => { t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8; t.flipY = false; ok(t); }, undefined, no);
  });
  const mat = new THREE.MeshStandardMaterial({
    map: tex, transparent: true, opacity: estado.opacidad, depthWrite: false,
    side: THREE.DoubleSide, roughness: 0.98, metalness: 0, color: 0x7d8b99,
  });
  terreno = new THREE.Mesh(geo, mat);
  terreno.renderOrder = 20;
  terreno.name = 'corteza';
  escena.add(terreno);

  // falda: paredes del bloque hasta 600 m por debajo de la cota mínima
  const cotaMin = cabTerreno.cota_min - 600;
  const anillo = [];
  for (let ix = 0; ix <= segX; ix++) anillo.push(0 * (segX + 1) + ix);
  for (let iz = 1; iz <= segZ; iz++) anillo.push(iz * (segX + 1) + segX);
  for (let ix = segX - 1; ix >= 0; ix--) anillo.push(segZ * (segX + 1) + ix);
  for (let iz = segZ - 1; iz >= 1; iz--) anillo.push(iz * (segX + 1));
  const vp = [], vi = [];
  for (let k = 0; k < anillo.length; k++) {
    const a = anillo[k] * 3;
    vp.push(pos[a], pos[a + 1], pos[a + 2]);
    vp.push(pos[a], cotaMin, pos[a + 2]);
  }
  for (let k = 0; k < anillo.length - 1; k++) {
    const a = k * 2, b = a + 1, c = a + 2, d = a + 3;
    vi.push(a, b, c, c, b, d);
  }
  const geoF = new THREE.BufferGeometry();
  geoF.setAttribute('position', new THREE.BufferAttribute(new Float32Array(vp), 3));
  geoF.setIndex(vi);
  geoF.computeVertexNormals();
  const falda = new THREE.Mesh(geoF, new THREE.MeshStandardMaterial({
    color: 0x40566f, roughness: 0.88, metalness: 0.06, side: THREE.DoubleSide, flatShading: true,
    emissive: 0x0a1524, emissiveIntensity: 0.6,
  }));
  falda.name = 'falda';
  escena.add(falda);

  // arista del bloque: hace que la corteza se lea como sección y no como mapa flotante
  const arista = new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints(anillo.map((i) => new THREE.Vector3(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]))),
    new THREE.LineBasicMaterial({ color: 0xcfe0f2, transparent: true, opacity: 0.5 })
  );
  arista.name = 'arista';
  arista.renderOrder = 25;
  escena.add(arista);
}

async function montarEstaciones() {
  const buf = await traer(D + 'estaciones.bin', (f) => {
    $('carga-barra').style.width = (35 + f * 43).toFixed(0) + '%';
  });
  const { cab, pos, col, idx } = leerMMG(buf);
  cabEstaciones = cab;
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(new Uint8Array(col), 3, true));
  geo.setIndex(new THREE.BufferAttribute(idx, 1));
  geo.computeVertexNormals();
  const mat = new THREE.MeshStandardMaterial({
    vertexColors: true, roughness: 0.58, metalness: 0.06, side: THREE.DoubleSide,
    emissive: 0x0a0f18, emissiveIntensity: 0.55,
  });
  mallaEstaciones = new THREE.Mesh(geo, mat);
  mallaEstaciones.name = 'estaciones';
  grupoEstaciones.add(mallaEstaciones);

  // mapa triángulo → estación (para selección fina si hiciera falta)
  const porTri = new Int32Array(cab.triangulos);
  centros = cab.estaciones.map((e, i) => {
    porTri.fill(i, e.i0 / 3, (e.i0 + e.in) / 3);
    return new THREE.Vector3(e.c[0], e.c[1], e.c[2]);
  });
  mallaEstaciones.userData.porTri = porTri;

  // mira de selección
  miras = new THREE.Group();
  const anillo = new THREE.Mesh(
    new THREE.TorusGeometry(46, 3.2, 8, 48),
    new THREE.MeshBasicMaterial({ color: 0xff6a00, transparent: true, opacity: 0.95 })
  );
  anillo.rotation.x = -Math.PI / 2;
  miras.add(anillo);
  const poste = new THREE.Mesh(
    new THREE.CylinderGeometry(1.2, 1.2, 1, 6),
    new THREE.MeshBasicMaterial({ color: 0xff6a00, transparent: true, opacity: 0.55 })
  );
  poste.name = 'poste';
  miras.add(poste);
  miras.visible = false;
  escena.add(miras);
}

function montarLineas(mundo) {
  const radio = { metro: 4.2, ligero: 3.2, cercanias: 7.5 };
  for (const linea of mundo.lineas) {
    const g = new THREE.Group();
    g.name = `${linea.red}-${linea.ref}`;
    for (const tramo of linea.tramos) {
      if (tramo.length < 2) continue;
      const pts = tramo.map(([x, z]) => new THREE.Vector3(x, 0, z));
      const curva = new THREE.CatmullRomCurve3(pts, false, 'centripetal', 0.5);
      const seg = Math.min(900, Math.max(12, Math.round(curva.getLength() / 22)));
      const geo = new THREE.TubeGeometry(curva, seg, radio[linea.red] || 4, 5, false);
      const mat = new THREE.MeshStandardMaterial({
        color: new THREE.Color(linea.color), roughness: 0.45, metalness: 0.15,
        emissive: new THREE.Color(linea.color), emissiveIntensity: 0.3,
        transparent: true, opacity: 0.42, depthWrite: false,
      });
      const malla = new THREE.Mesh(geo, mat);
      malla.userData.curva = curva;
      g.add(malla);
      // traza con grosor en píxeles: legible a cualquier escala (el tubo manda de cerca)
      const plano = [];
      for (const v of pts) plano.push(v.x, v.y, v.z);
      const gl = new LineGeometry();
      gl.setPositions(plano);
      const ml = new LineMaterial({
        color: new THREE.Color(linea.color), linewidth: linea.red === 'cercanias' ? 2.2 : 2.8,
        transparent: true, opacity: 0.95,
      });
      matsLinea.push(ml);
      const traza = new Line2(gl, ml);
      traza.computeLineDistances();
      traza.renderOrder = 4;
      g.add(traza);
      if (linea.red === 'metro') curvas.push({ linea, curva });
    }
    g.userData.red = linea.red;
    g.userData.ref = linea.ref;
    g.userData.trazas = g.children.length;
    grupoLineas.add(g);
  }
}

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
  const mat = new THREE.MeshStandardMaterial({
    vertexColors: true, roughness: 0.42, metalness: 0.35, side: THREE.DoubleSide,
  });
  for (const { linea, curva } of curvas) {
    const m = new THREE.Mesh(geo, mat);
    m.userData = { curva, t: Math.random(), curvaLargo: curva.getLength() };
    grupoTrenes.add(m);
    trenes.push(m);
  }
}

function montarPozos() {
  if (!cabEstaciones) return;
  const n = cabEstaciones.estaciones.length;
  const pos = new Float32Array(n * 6);
  const col = new Float32Array(n * 6);
  cabEstaciones.estaciones.forEach((e, i) => {
    const x = e.c[0], z = e.c[2];
    const sup = cota(x, z) + 24;
    pos.set([x, sup, z, x, -estado.profundidad + 2, z], i * 6);
    const c = new THREE.Color(e.color);
    col.set([c.r, c.g, c.b, c.r, c.g, c.b], i * 6);
  });
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  grupoPozos.add(new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.32 })));
}

function aislarLinea(ref) {
  estado.linea = estado.linea === ref ? null : ref;
  grupoLineas.children.forEach((g) => {
    const on = !estado.linea || g.userData.ref === estado.linea;
    g.traverse((o) => {
      if (!o.material) return;
      o.material.transparent = true;
      o.material.opacity = on ? (o.isLine2 ? 0.95 : 0.42) : 0.05;
    });
  });
  document.querySelectorAll('#leyenda .mm-chispa').forEach((el) => {
    el.classList.toggle('is-on', !!estado.linea && el.dataset.ref === estado.linea);
  });
  $('k-linea').textContent = estado.linea ? 'L' + estado.linea + ' aislada' : 'toda la red';
}

/* ---------- aplicación de estado ---------- */
function aplicar() {
  const d = estado.profundidad;
  if (grupoEstaciones) grupoEstaciones.position.y = 40 - d;
  if (grupoLineas) grupoLineas.position.y = -d;
  if (grupoTrenes) grupoTrenes.position.y = -d + 0.6;
  if (terreno) {
    terreno.material.opacity = estado.opacidad;
    terreno.material.depthWrite = estado.opacidad > 0.94;
    terreno.material.needsUpdate = true;
    terreno.visible = estado.capas.corteza;
  }
  if (grupoEstaciones) grupoEstaciones.visible = estado.capas.estaciones;
  if (grupoPozos) grupoPozos.visible = estado.capas.salidas;
  if (grupoTrenes) grupoTrenes.visible = estado.capas.trenes;
  if (grupoLineas) {
    grupoLineas.children.forEach((g) => {
      g.visible = estado.capas[g.userData.red] !== false;
      if (estado.linea) {
        const on = g.userData.ref === estado.linea;
        g.traverse((o) => { if (o.material) { o.material.transparent = true; o.material.opacity = on ? (o.isLine2 ? 0.95 : 0.42) : 0.05; } });
      }
    });
  }
  $('o-opacidad').textContent = Math.round(estado.opacidad * 100) + ' %';
  $('o-profundidad').textContent = d + ' m';
  $('o-velocidad').textContent = 'x' + estado.velocidad;
  if (hover >= 0) mostrarMira(hover);
}

/* ---------- interacción ---------- */
const proy = new THREE.Vector3();
function alMover(ev) {
  if (!cabEstaciones) return;
  const r = renderer.domElement.getBoundingClientRect();
  const mx = ev.clientX - r.left, my = ev.clientY - r.top;
  let mejor = -1, mejorD = 34;
  for (let i = 0; i < centros.length; i++) {
    proy.copy(centros[i]);
    proy.y += grupoEstaciones.position.y;
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
  const y = e.c[1] + grupoEstaciones.position.y;
  miras.position.set(e.c[0], y, e.c[2]);
  miras.visible = true;
  const sup = cota(e.c[0], e.c[2]) + 24;
  const poste = miras.getObjectByName('poste');
  const alto = Math.max(4, sup - y);
  poste.scale.set(1, alto, 1);
  poste.position.y = alto / 2 + 8;
  const s = Math.max(0.6, Math.min(2.4, 900 / camara.position.distanceTo(miras.position)));
  miras.scale.setScalar(s);
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
  $('f-eje').textContent = e.lineas.length ? Math.round(e.dist || 0) + ' m' : 'sin línea';
  const cont = $('f-lineas');
  cont.innerHTML = '';
  (e.lineas.length ? e.lineas : ['—']).forEach((ref) => {
    const b = document.createElement('span');
    b.className = 'nz-badge nz-badge--neutral';
    b.textContent = 'L' + ref;
    if (e.color) b.style.borderColor = e.color;
    cont.appendChild(b);
  });
  $('f-nota').textContent = `EPSG:25830 · ${Math.round(e.E)} / ${Math.round(e.N)}`;
}

function alPulsar() {
  if (hover < 0 || !cabEstaciones) return;
  const e = cabEstaciones.estaciones[hover];
  volarA(new THREE.Vector3(e.c[0], e.c[1] + grupoEstaciones.position.y, e.c[2]), 620);
}

function volarA(destino, dist, elev = 0.55) {
  const desdeT = control.target.clone();
  const desdeC = camara.position.clone();
  const dxz = new THREE.Vector3(desdeC.x - desdeT.x, 0, desdeC.z - desdeT.z);
  if (dxz.lengthSq() < 1) dxz.set(-0.62, 0, 0.78);
  dxz.normalize();
  const horiz = dist / Math.sqrt(1 + elev * elev);
  const hastaC = new THREE.Vector3(
    destino.x + dxz.x * horiz, destino.y + elev * horiz, destino.z + dxz.z * horiz);
  if (document.hidden) { control.target.copy(destino); camara.position.copy(hastaC); control.update(); return; }
  const t0 = performance.now(), dur = 900;
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
  red() {
    volarA(new THREE.Vector3(-1200, -10, 900), 21000, 0.55);
  },
  centro() {
    volarA(new THREE.Vector3(-900, -18, 700), 8200, 0.46);
  },
  sol() {
    const i = cabEstaciones.estaciones.findIndex((e) => /sol/i.test(e.id) || /^sol/i.test(e.nombre));
    const e = cabEstaciones.estaciones[i >= 0 ? i : 0];
    const d = new THREE.Vector3(e.c[0], e.c[1] + grupoEstaciones.position.y, e.c[2]);
    volarA(d, 1200, 0.38);
  },
  corte() {
    estado.opacidad = 0.34;
    $('r-opacidad').value = 34;
    aplicar();
    const t = new THREE.Vector3(0, -estado.profundidad, 0);
    control.target.copy(t);
    camara.position.set(-420, 240, 2600);
  },
  orbita() {
    volarA(control.target.clone(), 9000, 0.5);
  },
};

/* ---------- interfaz ---------- */
function pintarInterfaz(mundo) {
  const metro = mundo.lineas.filter((l) => l.red === 'metro');
  const ligero = mundo.lineas.filter((l) => l.red === 'ligero');
  const cerc = mundo.lineas.filter((l) => l.red === 'cercanias');
  const leyenda = $('leyenda');
  [...metro, ...ligero].forEach((l) => {
    const s = document.createElement('button');
    s.type = 'button';
    s.className = 'mm-chispa';
    s.dataset.ref = l.ref;
    s.title = `${l.nombre} · ${l.largo_km} km · ${l.trazas} traza(s) — pulsa para aislar`;
    s.innerHTML = `<i style="background:${l.color}"></i>${l.ref}`;
    s.addEventListener('click', () => aislarLinea(l.ref));
    leyenda.appendChild(s);
  });
  const c = document.createElement('span');
  c.className = 'mm-chispa';
  c.innerHTML = `<i style="background:#868584"></i>Cercanías (${cerc.length})`;
  leyenda.appendChild(c);

  $('k-est').textContent = cabEstaciones.estaciones.length;
  $('k-lin').textContent = metro.length + ligero.length;
  $('k-desn').textContent = Math.round(cabTerreno.desnivel) + ' m';
  $('k-reg').textContent = (cabEstaciones.registro ? cabEstaciones.registro.mediana_m : '—') + ' m';
  $('chip-estaciones').textContent = cabEstaciones.estaciones.length + ' estaciones';
  $('chip-tri').textContent = cabEstaciones.triangulos.toLocaleString('es-ES') + ' triángulos';
  document.title = `Metro de Madrid · ${cabEstaciones.estaciones.length} estaciones · gemelo digital`;
}

function conectar() {
  const capas = { 'c-estaciones': 'estaciones', 'c-metro': 'metro', 'c-ligero': 'ligero', 'c-cercanias': 'cercanias', 'c-trenes': 'trenes', 'c-corteza': 'corteza', 'c-salidas': 'salidas' };
  for (const [id, clave] of Object.entries(capas)) {
    $(id).addEventListener('change', (e) => { estado.capas[clave] = e.target.checked; aplicar(); });
  }
  $('r-opacidad').addEventListener('input', (e) => { estado.opacidad = Number(e.target.value) / 100; aplicar(); });
  $('r-profundidad').addEventListener('input', (e) => {
    estado.profundidad = Number(e.target.value);
    grupoPozos.clear(); montarPozos(); aplicar();
  });
  $('r-velocidad').addEventListener('input', (e) => { estado.velocidad = Number(e.target.value); aplicar(); });
  $('b-sol').addEventListener('click', ENCUADRES.sol);
  $('b-red').addEventListener('click', ENCUADRES.red);
  $('b-corte').addEventListener('click', ENCUADRES.corte);
  $('b-orbita').addEventListener('click', ENCUADRES.orbita);
  $('btn-panel').addEventListener('click', () => {
    const p = $('panel-movil');
    p.classList.toggle('is-on');
    if (p.classList.contains('is-on') && !p.childElementCount) {
      p.appendChild($('panel-izq').cloneNode(true));
      p.querySelectorAll('input').forEach((inp, i) => {
        inp.addEventListener('input', () => {
          const orig = $('panel-izq').querySelectorAll('input')[i];
          orig.value = inp.value; if (inp.type === 'checkbox') orig.checked = inp.checked;
          orig.dispatchEvent(new Event('input')); orig.dispatchEvent(new Event('change'));
        });
      });
    }
  });
}

/* ---------- bucle ---------- */
function bucle() {
  try { pasoBucle(); } catch (e) {
    if (!bucle.avisado) { bucle.avisado = true; console.error('bucle', e); $('k-fps').textContent = 'error: ' + e.message; }
  }
}

function pasoBucle() {
  const dt = reloj.getDelta();
  control.update();
  if (estado.capas.trenes && estado.velocidad > 0) {
    const v = 16.7 * estado.velocidad; // m/s · x1 = 60 km/h
    for (const m of trenes) {
      const largo = m.userData.curvaLargo || 1;
      m.userData.t = (m.userData.t + (dt * v) / largo) % 1;
      const t = m.userData.t;
      const p = m.userData.curva.getPointAt(t);
      const p2 = m.userData.curva.getPointAt(Math.min(0.9999, t + 2 / largo));
      m.position.set(p.x, 0, p.z);
      m.lookAt(p2.x, 0, p2.z);
    }
  }
  if (miras && miras.visible && hover >= 0) mostrarMira(hover);
  renderer.render(escena, camara);

  fps.n++;
  fps.t += dt;
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
window.__metro = { get estado() { return estado; }, get escena() { return escena; }, get camara() { return camara; },
  get renderer() { return renderer; }, get control() { return control; }, get hover() { return hover; },
  ENCUADRES, centros: () => centros, cabecera: () => cabEstaciones };
