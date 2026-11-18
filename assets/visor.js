// Metro de Madrid bajo tierra — visor 3D
// Datos: GTFS oficial del CRTM (Red de Metro). Ver scripts/build_datos.py

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';

const $ = (s) => document.querySelector(s);
const lienzo = $('#lienzo');
const velo = $('#velo');
const M_PER_DEG = 111320;
// Escala vertical exagerada: a escala real 30 m de túnel son invisibles en 50 km de ciudad
const EXAG = 200;

// ————————————————————————————— estado —————————————————————————————
const estado = {
  datos: null,
  centro: { lat: 40.42, lon: -3.7 },
  lineas: new Map(),      // id -> {meta, visible}
  horaBase: 0,            // segundos desde medianoche
  t0: performance.now(),
  velocidad: 1,
  trenes: [],
  seleccion: null,
  superficie: null,
  opacidadSuperficie: 0.95,
};

// ————————————————————————————— escena —————————————————————————————
const escena = new THREE.Scene();
escena.fog = new THREE.FogExp2(0x05060a, 0.000012);

const camara = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 10, 400000);
camara.position.set(0, 46000, 1000);

const renderer = new THREE.WebGLRenderer({ canvas: lienzo, antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.setClearColor(0x05060a, 1);

// marcador de la estación elegida: un haz vertical que atraviesa el terreno
const marcador = new THREE.Group();
{
  const hazMat = new THREE.MeshBasicMaterial({
    color: 0xffffff, transparent: true, opacity: 0.13, side: THREE.DoubleSide,
    depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
  });
  const haz = new THREE.Mesh(new THREE.CylinderGeometry(7, 7, 1, 12, 1, true), hazMat);
  haz.name = 'haz';
  const punta = new THREE.Mesh(
    new THREE.SphereGeometry(26, 16, 12),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.85, depthTest: false })
  );
  punta.name = 'punta';
  marcador.add(haz, punta);
  marcador.visible = false;
  marcador.renderOrder = 13;
}
escena.add(marcador);

const controles = new OrbitControls(camara, renderer.domElement);
controles.enableDamping = true;
controles.dampingFactor = 0.06;
controles.maxPolarAngle = Math.PI / 2 - 0.02;
controles.minDistance = 900;
controles.maxDistance = 120000;
controles.zoomSpeed = 0.9;
controles.panSpeed = 1.1;

escena.add(new THREE.HemisphereLight(0xffffff, 0x080810, 1.1));
const luz = new THREE.DirectionalLight(0xffffff, 0.9);
luz.position.set(0.4, 1, 0.6);
escena.add(luz);

// ————————————————————————————— proyección —————————————————————————————
let escala = 1;
function aMundo(lat, lon) {
  const x = (lon - estado.centro.lon) * M_PER_DEG * Math.cos(estado.centro.lat * Math.PI / 180);
  const z = -(lat - estado.centro.lat) * M_PER_DEG;
  return [x * escala, z * escala];
}

// ————————————————————————————— superficie (teselas) —————————————————————————————
function lon2tile(lon, z) { return Math.floor((lon + 180) / 360 * 2 ** z); }
function lat2tile(lat, z) {
  const r = lat * Math.PI / 180;
  return Math.floor((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * 2 ** z);
}
function tile2lon(x, z) { return x / 2 ** z * 360 - 180; }
function tile2lat(y, z) {
  const n = Math.PI - 2 * Math.PI * y / 2 ** z;
  return 180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
}

async function construirSuperficie(bbox) {
  const { minLat, maxLat, minLon, maxLon } = bbox;
  let z = 13;
  for (; z > 9; z--) {
    const nx = lon2tile(maxLon, z) - lon2tile(minLon, z) + 1;
    const ny = lat2tile(minLat, z) - lat2tile(maxLat, z) + 1;
    if (nx * ny <= 36) break;
  }
  const x0 = lon2tile(minLon, z), x1 = lon2tile(maxLon, z);
  const y0 = lat2tile(maxLat, z), y1 = lat2tile(minLat, z);
  const nx = x1 - x0 + 1, ny = y1 - y0 + 1;
  const tile = 256;
  const cv = document.createElement('canvas');
  cv.width = nx * tile;
  cv.height = ny * tile;
  const ctx = cv.getContext('2d');
  ctx.fillStyle = '#0a0b0f';
  ctx.fillRect(0, 0, cv.width, cv.height);

  const trabajos = [];
  for (let ty = y0; ty <= y1; ty++) {
    for (let tx = x0; tx <= x1; tx++) {
      const url = `https://tile.openstreetmap.org/${z}/${tx}/${ty}.png`;
      trabajos.push(cargarTile(url).then((img) => {
        if (!img) return;
        ctx.save();
        ctx.filter = 'grayscale(1) invert(1) contrast(1.15) brightness(1)';
        ctx.drawImage(img, (tx - x0) * tile, (ty - y0) * tile, tile, tile);
        ctx.restore();
      }).catch(() => {}));
    }
  }
  await Promise.all(trabajos);

  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
  tex.minFilter = THREE.LinearMipmapLinearFilter;

  // georreferencia del lienzo: esquinas del bloque de teselas
  const lonA = tile2lon(x0, z), lonB = tile2lon(x1 + 1, z);
  const latA = tile2lat(y0, z), latB = tile2lat(y1 + 1, z);
  const [x1m, z1m] = aMundo(latA, lonA);
  const [x2m, z2m] = aMundo(latB, lonB);
  const ancho = Math.abs(x2m - x1m), alto = Math.abs(z2m - z1m);

  const geo = new THREE.PlaneGeometry(ancho, alto, 1, 1);
  const mat = new THREE.MeshBasicMaterial({
    map: tex, transparent: true, opacity: estado.opacidadSuperficie,
    depthWrite: false, side: THREE.DoubleSide, color: 0xffffff,
  });
  const plano = new THREE.Mesh(geo, mat);
  plano.rotation.x = -Math.PI / 2;
  plano.position.set((x1m + x2m) / 2, 0, (z1m + z2m) / 2);
  plano.renderOrder = 2;
  escena.add(plano);
  estado.superficie = plano;

  // bloque de terreno bajo la superficie: da volumen al diorama
  const profMax = Math.max(...[...estado.lineas.values()].map((l) => l.meta.depth)) * EXAG;
  const caja = new THREE.Mesh(
    new THREE.BoxGeometry(ancho, profMax * 1.15, alto),
    new THREE.MeshBasicMaterial({
      color: 0x0e1622, transparent: true, opacity: 0.32,
      depthWrite: false, side: THREE.DoubleSide,
    })
  );
  caja.position.set(plano.position.x, -profMax * 1.15 / 2, plano.position.z);
  caja.renderOrder = -2;
  escena.add(caja);
  const aristas = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(ancho, profMax * 1.15, alto)),
    new THREE.LineBasicMaterial({ color: 0x39485c, transparent: true, opacity: 0.55 })
  );
  aristas.position.copy(caja.position);
  escena.add(aristas);

  // marco del plano: da la lectura de «corte» sin gradientes
  // eje de profundidad: escala vertical en el borde oeste del diorama
  const xEje = plano.position.x + ancho / 2 - 900;
  const zEje = plano.position.z - alto / 2 + 1200;
  const matEje = new THREE.LineBasicMaterial({ color: 0x8ea0bd, transparent: true, opacity: 0.5, depthTest: false });
  const ejePts = [new THREE.Vector3(xEje, 0, zEje), new THREE.Vector3(xEje, -profMax * 1.05, zEje)];
  const eje = new THREE.Line(new THREE.BufferGeometry().setFromPoints(ejePts), matEje);
  eje.renderOrder = 7;
  escena.add(eje);
  for (let m = 10; m <= 40; m += 10) {
    const y = -m * EXAG;
    const tick = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(xEje, y, zEje), new THREE.Vector3(xEje + 900, y, zEje)]),
      matEje);
    tick.renderOrder = 7;
    escena.add(tick);
    const cv = document.createElement('canvas');
    cv.width = 256; cv.height = 64;
    const cx = cv.getContext('2d');
    cx.fillStyle = 'rgba(255,255,255,0.72)';
    cx.font = '500 34px system-ui, sans-serif';
    cx.textBaseline = 'middle';
    cx.fillText(m + ' m', 8, 34);
    const tex2 = new THREE.CanvasTexture(cv);
    tex2.colorSpace = THREE.SRGBColorSpace;
    const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex2, transparent: true, depthTest: false }));
    spr.scale.set(1600, 400, 1);
    spr.position.set(xEje + 2200, y, zEje);
    spr.renderOrder = 7;
    escena.add(spr);
  }

  const borde = new THREE.LineSegments(
    new THREE.EdgesGeometry(geo),
    new THREE.LineBasicMaterial({ color: 0x2b2f3a, transparent: true, opacity: 0.9 })
  );
  borde.rotation.x = -Math.PI / 2;
  borde.position.copy(plano.position);
  escena.add(borde);
}

function cargarTile(url) {
  return new Promise((res) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => res(img);
    img.onerror = () => res(null);
    img.src = url;
    setTimeout(() => res(img.complete && img.naturalWidth ? img : null), 6000);
  });
}

// ————————————————————————————— red —————————————————————————————
const resolucion = new THREE.Vector2(innerWidth, innerHeight);

// servicio del día (calendar.txt del GTFS): laborable, viernes, sábado o domingo
function serviciosActivos(calendar) {
  const dia = new Intl.DateTimeFormat('en-US', { timeZone: 'Europe/Madrid', weekday: 'long' })
    .format(new Date()).toLowerCase();
  const activos = new Set();
  for (const [svc, dias] of Object.entries(calendar || {})) if (dias[dia] === 1) activos.add(svc);
  if (!activos.size) Object.keys(calendar || {}).forEach((k) => activos.add(k));
  return activos;
}

function construirRed() {
  const { lines, shapes, stations } = estado.datos;
  const activos = serviciosActivos(estado.datos.calendar);
  const patterns = estado.datos.patterns.filter((p) => activos.has(p.svc));
  const ETIQUETA = { '4_I12': 'Sábado', '4_I13': 'Domingo y festivo', '4_I14': 'Laborable', '4_I15': 'Viernes' };
  estado.servicio = [...activos].map((s) => ETIQUETA[s] || s).join(', ');
  const colorPorLinea = new Map();

  for (const l of lines) {
    colorPorLinea.set(l.id, new THREE.Color(l.color));
    estado.lineas.set(l.id, { meta: l, visible: true });
  }

  for (const sh of shapes) {
    const pts = sh.pts;
    const grupos = new Map();
    for (const p of patterns) {
      if (p.s !== shapes.indexOf(sh)) continue;
      const depth = estado.lineas.get(p.l).meta.depth;
      const clave = p.l + '|' + depth;
      if (!grupos.has(clave)) grupos.set(clave, { l: p.l, depth, dirs: [] });
      grupos.get(clave).dirs.push(p.d);
    }
    for (const [clave, g] of grupos) {
      const posiciones = [];
      for (const [lat, lon] of pts) {
        const [x, z] = aMundo(lat, lon);
        posiciones.push(x, -g.depth * EXAG, z);
      }
      const geo = new LineGeometry();
      geo.setPositions(posiciones);
      const color = colorPorLinea.get(g.l);
      const mat = new LineMaterial({
        color: color.clone().multiplyScalar(0.95).getHex(),
        linewidth: 2.6,
        resolution: resolucion,
        transparent: true,
        opacity: 0.95,
        depthTest: false,
        blending: THREE.AdditiveBlending,
      });
      const linea = new Line2(geo, mat);
      linea.computeLineDistances();
      linea.renderOrder = 10;
      linea.userData = { tipo: 'linea', id: g.l };
      escena.add(linea);
      (estado.objetosLinea ||= []).push(linea);

      const halo = new LineMaterial({
        color: color.getHex(), linewidth: 12, resolution: resolucion,
        transparent: true, opacity: 0.13, depthWrite: false, depthTest: false,
        blending: THREE.AdditiveBlending,
      });
      const haloLinea = new Line2(geo, halo);
      haloLinea.renderOrder = 9;
      haloLinea.userData = { tipo: 'halo', id: g.l };
      escena.add(haloLinea);
      (estado.objetosLinea ||= []).push(haloLinea);
    }
  }

  // estaciones: punto de tamaño constante en pantalla + pozo hasta el túnel
  const n = stations.length;
  const pozoGeo = new THREE.CylinderGeometry(1, 1, 1, 10, 1, true);
  const pozoMat = new THREE.MeshBasicMaterial({
    color: 0x8ea0bd, transparent: true, opacity: 0.085, side: THREE.DoubleSide, depthWrite: false, depthTest: true,
  });
  const pozos = new THREE.InstancedMesh(pozoGeo, pozoMat, n);

  const posEst = new Float32Array(n * 3);
  const tamEst = new Float32Array(n);
  const m4 = new THREE.Matrix4();
  stations.forEach((st, i) => {
    const [x, z] = aMundo(st.lat, st.lon);
    st._x = x; st._z = z; st._i = i;
    const prof = Math.max(...st.l.map((id) => estado.lineas.get(id)?.meta.depth ?? 20));
    st._prof = prof;
    posEst[i * 3] = x; posEst[i * 3 + 1] = 0; posEst[i * 3 + 2] = z;
    tamEst[i] = st.l.length > 1 ? 1 : 0;   // correspondencia = más grande
    m4.compose(
      new THREE.Vector3(x, -prof * EXAG / 2, z),
      new THREE.Quaternion(),
      new THREE.Vector3(11, prof * EXAG, 11)
    );
    pozos.setMatrixAt(i, m4);
  });
  pozos.instanceMatrix.needsUpdate = true;
  pozos.renderOrder = 8;
  pozos.visible = false;   // se conserva solo como referencia; el andén manda
  escena.add(pozos);

  // las estaciones se dibujan como puntos de tamaño fijo en píxeles: a 20 km de altura
  // un disco de 50 m mide dos píxeles y desaparece
  const geoEst = new THREE.BufferGeometry();
  geoEst.setAttribute('position', new THREE.BufferAttribute(posEst, 3));
  geoEst.setAttribute('aGrande', new THREE.BufferAttribute(tamEst, 1));
  const matEst = new THREE.ShaderMaterial({
    uniforms: {
      foco: { value: new THREE.Vector3() },
      tamBase: { value: 7 },
      escala: { value: 1 },
    },
    vertexShader: `
      attribute float aGrande;
      uniform vec3 foco;
      uniform float tamBase;
      uniform float escala;
      varying float vGrande;
      void main() {
        vGrande = aGrande;
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * mv;
        float lejos = distance(cameraPosition, position);
        float s = (aGrande > 0.5 ? tamBase * 1.55 : tamBase) * escala;
        s *= mix(1.0, 2.2, clamp(lejos / 30000.0, 0.0, 1.0));
        float cerca = 1.0 - clamp(distance(position.xz, foco.xz) / 1.0, 0.0, 1.0);
        s *= 1.0 + cerca * 1.1;
        gl_PointSize = s;
      }`,
    fragmentShader: `
      varying float vGrande;
      void main() {
        vec2 d = gl_PointCoord - 0.5;
        float r = length(d);
        if (r > 0.5) discard;
        float nucleo = smoothstep(0.5, 0.34, r);
        float borde = smoothstep(0.5, 0.44, r) - smoothstep(0.42, 0.30, r);
        vec3 col = mix(vec3(1.0), vec3(1.0), vGrande);
        float a = nucleo * 0.95 + borde * 0.55;
        gl_FragColor = vec4(col, a);
      }`,
    transparent: true, depthWrite: false, depthTest: false,
  });
  const puntosEst = new THREE.Points(geoEst, matEst);
  puntosEst.frustumCulled = false;
  puntosEst.renderOrder = 10;
  escena.add(puntosEst);
  estado.discos = puntosEst;
  estado._posEst = posEst;
  estado._matEst = matEst;

  // ——— huellas reales: cada estación se dibuja con la planta de su andén, a su
  // tamaño y con su orientación. 60 salen dibujadas en OSM; el resto se trazan
  // sobre la vía, que da la dirección y la posición exactas.
  const huellas = estado.huellas || {};
  const vRelleno = [], vContorno = [], vVestibulo = [];
  let andenesDibujados = 0, reales = 0;

  function poligono(pts, y, destino) {
    const n = pts.length;
    if (n < 3) return;
    let cx = 0, cz = 0;
    for (const [x, z] of pts) { cx += x; cz += z; }
    cx /= n; cz /= n;
    for (let i = 0; i < n; i++) {
      const [x1, z1] = pts[i], [x2, z2] = pts[(i + 1) % n];
      destino.push(cx, y, cz, x1, y, z1, x2, y, z2);
    }
  }

  function contorno(pts, y, destino) {
    const n = pts.length;
    for (let i = 0; i < n; i++) {
      const [x1, z1] = pts[i], [x2, z2] = pts[(i + 1) % n];
      destino.push(x1, y, z1, x2, y, z2);
    }
  }

  for (const st of stations) {
    const h = huellas[st.id];
    if (!h) continue;
    const cota = -st._prof * EXAG;
    st._andenes = [];
    for (const a of h.andenes || []) {
      const pts = a.pts.map(([la, lo]) => aMundo(la, lo));
      poligono(pts, cota + 0.6, vRelleno);
      contorno(pts, cota + 1.2, vContorno);
      st._andenes.push({ pts, cota, largo: a.largo, ancho: a.ancho, real: a.real });
      andenesDibujados++;
      if (a.real) reales++;
    }
    if (h.recinto) {
      const pts = h.recinto.pts.map(([la, lo]) => aMundo(la, lo));
      contorno(pts, 1.5, vVestibulo);
    }
  }

  function malla(puntos, color, opacidad) {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(puntos, 3));
    const m = new THREE.MeshBasicMaterial({
      color, transparent: true, opacity: opacidad, side: THREE.DoubleSide,
      depthWrite: false, depthTest: true,
    });
    const mesh = new THREE.Mesh(g, m);
    mesh.renderOrder = 6;
    mesh.frustumCulled = false;
    escena.add(mesh);
    return mesh;
  }
  function lineas(puntos, color, opacidad) {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(puntos, 3));
    const l = new THREE.LineSegments(g, new THREE.LineBasicMaterial({
      color, transparent: true, opacity: opacidad, depthWrite: false,
    }));
    l.renderOrder = 7;
    l.frustumCulled = false;
    escena.add(l);
    return l;
  }



  const mallaAndenes = malla(vRelleno, 0xffffff, 0.30);
  const bordeAndenes = lineas(vContorno, 0xffffff, 0.8);
  const bordeVestibulo = lineas(vVestibulo, 0xcfd8e6, 0.22);
  estado._huellas = { mallaAndenes, bordeAndenes, bordeVestibulo };
  console.info(`huellas: ${andenesDibujados} andenes (${reales} dibujados en OSM)`);

  // contorno grueso de la estación elegida
  const focoGeo = new THREE.BufferGeometry();
  const focoLinea = new THREE.LineSegments(focoGeo, new THREE.LineBasicMaterial({
    color: 0xffffff, transparent: true, opacity: 0.95, depthTest: false,
  }));
  focoLinea.renderOrder = 14;
  focoLinea.frustumCulled = false;
  focoLinea.visible = false;
  escena.add(focoLinea);
  estado._focoLinea = focoLinea;

  // trenes: puntos de tamaño constante en pantalla (visibles a cualquier zoom)
  const nMax = 1400;
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(nMax * 3);
  const col = new Float32Array(nMax * 3);
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3).setUsage(THREE.DynamicDrawUsage));
  geo.setDrawRange(0, 0);
  const puntos = new THREE.Points(geo, new THREE.PointsMaterial({
    size: 8, sizeAttenuation: false, color: 0xffffff,
    transparent: true, opacity: 0.98, depthWrite: false, depthTest: false,
  }));
  puntos.frustumCulled = false;
  puntos.renderOrder = 12;
  escena.add(puntos);

  const geoHalo = new THREE.BufferGeometry();
  geoHalo.setAttribute('position', new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
  geoHalo.setAttribute('color', new THREE.BufferAttribute(col, 3).setUsage(THREE.DynamicDrawUsage));
  geoHalo.setDrawRange(0, 0);
  const halo = new THREE.Points(geoHalo, new THREE.PointsMaterial({
    size: 34, sizeAttenuation: false, vertexColors: true, transparent: true,
    opacity: 0.34, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
  }));
  halo.frustumCulled = false;
  halo.renderOrder = 11;
  escena.add(halo);

  estado.puntosTrenes = puntos;
  estado.haloTrenes = halo;

  // precalcular color de cada patrón
  estado.patrones = patterns.map((p) => ({
    ...p,
    color: colorPorLinea.get(p.l).clone(),
    depth: estado.lineas.get(p.l).meta.depth,
    shape: shapes[p.s],
  }));
}

// ————————————————————————————— simulación —————————————————————————————
function horaMadridSegundos(fecha) {
  const f = new Intl.DateTimeFormat('es-ES', {
    timeZone: 'Europe/Madrid', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  });
  const partes = f.formatToParts(fecha);
  const v = (t) => parseInt(partes.find((p) => p.type === t).value, 10);
  return v('hour') * 3600 + v('minute') * 60 + v('second');
}

function puntoEnShape(shape, s) {
  const cum = shape.cum, pts = shape.pts;
  if (s <= 0) return pts[0];
  if (s >= cum[cum.length - 1]) return pts[pts.length - 1];
  let lo = 0, hi = cum.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (cum[mid] <= s) lo = mid; else hi = mid;
  }
  const span = cum[hi] - cum[lo] || 1;
  const f = (s - cum[lo]) / span;
  return [pts[lo][0] + (pts[hi][0] - pts[lo][0]) * f,
          pts[lo][1] + (pts[hi][1] - pts[lo][1]) * f];
}

const m4 = new THREE.Matrix4();
const q = new THREE.Quaternion();
const v3 = new THREE.Vector3();
const esc = new THREE.Vector3();

function actualizarTrenes(tSeg) {
  const visibles = [];
  const dia = 86400;
  for (const p of estado.patrones) {
    if (!estado.lineas.get(p.l).visible) continue;
    const dur = p.dur;
    for (const [ini, fin, head] of p.w) {
      // ventanas de hoy y de la víspera (trenes que siguen circulando tras medianoche)
      for (const off of [0, -dia]) {
        const iniD = ini + off, finD = fin + off;
        let k = Math.ceil((tSeg - dur - iniD) / head);
        if (k < 0) k = 0;
        for (let s = iniD + k * head; s <= finD && s <= tSeg; s += head) {
          const tt = tSeg - s;
          if (tt < 0 || tt > dur) continue;
          let i = 0;
          while (i + 1 < p.o.length && p.o[i + 1] <= tt) i++;
          const j = Math.min(i + 1, p.o.length - 1);
          const tramo = (p.o[j] - p.o[i]) || 1;
          const f = Math.min(1, Math.max(0, (tt - p.o[i]) / tramo));
          const sDist = p.sp[i] + (p.sp[j] - p.sp[i]) * f;
          const [lat, lon] = puntoEnShape(p.shape, sDist);
          const [x, z] = aMundo(lat, lon);
          visibles.push({ x, z, y: -p.depth * EXAG - 60, color: p.color, linea: p.l });
        }
        if (visibles.length > 1380) break;
      }
    }
  }
  estado.trenes = visibles;

  const n = Math.min(visibles.length, 1400);
  const pos = estado.puntosTrenes.geometry.attributes.position.array;
  const col = estado.puntosTrenes.geometry.attributes.color.array;
  const posH = estado.haloTrenes.geometry.attributes.position.array;
  const colH = estado.haloTrenes.geometry.attributes.color.array;
  for (let i = 0; i < n; i++) {
    const t = visibles[i];
    pos[i * 3] = t.x; pos[i * 3 + 1] = t.y; pos[i * 3 + 2] = t.z;
    posH[i * 3] = t.x; posH[i * 3 + 1] = t.y; posH[i * 3 + 2] = t.z;
    col[i * 3] = t.color.r; col[i * 3 + 1] = t.color.g; col[i * 3 + 2] = t.color.b;
    colH[i * 3] = t.color.r; colH[i * 3 + 1] = t.color.g; colH[i * 3 + 2] = t.color.b;
  }
  const g = estado.puntosTrenes.geometry, gh = estado.haloTrenes.geometry;
  g.setDrawRange(0, n); gh.setDrawRange(0, n);
  g.attributes.position.needsUpdate = true; g.attributes.color.needsUpdate = true;
  gh.attributes.position.needsUpdate = true; gh.attributes.color.needsUpdate = true;
}

// ————————————————————————————— etiquetas —————————————————————————————
const capaEtiquetas = document.createElement('div');
capaEtiquetas.style.cssText = 'position:fixed;inset:0;pointer-events:none;overflow:hidden';
document.body.appendChild(capaEtiquetas);
const etiquetas = new Map();

function crearEtiqueta(st) {
  const d = document.createElement('div');
  d.className = 'etiqueta';
  d.textContent = st.n;
  capaEtiquetas.appendChild(d);
  etiquetas.set(st.id, d);
  return d;
}

function actualizarEtiquetas() {
  const foco = estado._foco;
  const t = controles.target;
  const elegida = estado._estacion;
  let lista;
  if (foco) {
    // con una estación abierta solo se rotulan las de su entorno
    lista = estado.datos.stations
      .filter((st) => Math.hypot(st._x - t.x, st._z - t.z) < 2600)
      .slice(0, 24);
    if (elegida && !lista.includes(elegida)) lista.unshift(elegida);
  } else {
    lista = estado.datos.stations.filter((st) => st.l.length > 1).slice(0, 70);
  }

  const vistas = new Set();
  const ocupadas = [];
  const orden = [...lista].sort((a, b) => {
    if (a === elegida) return -1;
    if (b === elegida) return 1;
    return b.l.length - a.l.length;
  });
  for (const st of orden) {
    const d = etiquetas.get(st.id) || crearEtiqueta(st);
    vistas.add(st.id);
    v3.set(st._x, cotaEstacion(st), st._z).project(camara);
    const x = (v3.x * 0.5 + 0.5) * innerWidth;
    const y = (-v3.y * 0.5 + 0.5) * innerHeight;
    const dentro = v3.z < 1 && v3.z > -1 && x > 380 && x < innerWidth - 20 && y > 60 && y < innerHeight - 40;
    const w = d.offsetWidth || 96;
    const choque = ocupadas.some(([ox, oy, ow]) => Math.abs(ox - x) < (w + ow) / 2 + 6 && Math.abs(oy - y) < 15);
    const visible = dentro && (!choque || st === elegida);
    if (visible) ocupadas.push([x, y, w]);
    d.classList.toggle('is-visible', visible);
    d.classList.toggle('is-foco', st === elegida);
    d.style.left = x.toFixed(1) + 'px';
    d.style.top = y.toFixed(1) + 'px';
  }
  for (const [id, d] of etiquetas) {
    if (!vistas.has(id)) { d.classList.remove('is-visible'); d.classList.remove('is-foco'); }
  }
}

// ————————————————————————————— cámara —————————————————————————————
let transicion = null;
function irA(pos, target, ms = 1300) {
  transicion = {
    desde: camara.position.clone(), hasta: new THREE.Vector3(...pos),
    tDesde: controles.target.clone(), tHasta: new THREE.Vector3(...target),
    inicio: performance.now(), ms,
  };
}

function vista(nombre) {
  const c = estado.centro;
  if (nombre === 'plano') irA([0, 46000, 200], [0, 0, 0], 1400);
  else if (nombre === 'vuelo') irA([-11000, 12000, 15000], [0, -1600, 0], 1400);
  else {
    escena.fog.density = 0.00028;
    irA([900, -2400, 2400], [0, -3000, 0], 1400);
  }
  if (nombre !== 'tunel') escena.fog.density = 0.000012;
}

// ————————————————————————————— interacción —————————————————————————————
const _v3 = new THREE.Vector3();

// con la cámara bajo tierra (tras el zoom) las estaciones se anclan a la cota del túnel
function cotaEstacion(st) {
  return camara.position.y < -200 ? -st._prof * EXAG : 0;
}

function estacionEn(cx, cy, umbral = 20) {
  let mejor = null, mejorD = umbral;
  for (const st of estado.datos.stations) {
    _v3.set(st._x, cotaEstacion(st), st._z).project(camara);
    if (_v3.z > 1) continue;
    const x = (_v3.x * 0.5 + 0.5) * innerWidth;
    const y = (-_v3.y * 0.5 + 0.5) * innerHeight;
    const d = Math.hypot(x - cx, y - cy);
    if (d < mejorD) { mejorD = d; mejor = st; }
  }
  return mejor;
}

renderer.domElement.addEventListener('pointerdown', (e) => {
  estado._down = { x: e.clientX, y: e.clientY, t: performance.now() };
});
renderer.domElement.addEventListener('pointermove', (e) => {
  if (estado._down) return;
  const st = estacionEn(e.clientX, e.clientY);
  renderer.domElement.style.cursor = st ? 'pointer' : 'grab';
  const tip = $('#puntero-nombre');
  if (st) {
    tip.textContent = st.n;
    tip.style.transform = `translate(${e.clientX + 14}px, ${e.clientY - 12}px)`;
    tip.classList.add('is-visible');
  } else {
    tip.classList.remove('is-visible');
  }
});
renderer.domElement.addEventListener('pointerup', (e) => {
  const d = estado._down;
  estado._down = null;
  if (!d) return;
  if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 6 || performance.now() - d.t > 600) return;
  const st = estacionEn(e.clientX, e.clientY);
  if (st) seleccionar(st);
  else cerrarFicha();
});

function seleccionar(st) {
  estado.seleccion = st.l[0] ?? null;
  pintarFicha(st);
  actualizarLineasUI();
  const p = $('#panel');
  if (p) p.scrollTop = 0;
  enfocarEstacion(st);
}

// vuelo a la estación: se planta la cámara a su altura, mirando el pozo en tres cuartos
function enfocarEstacion(st) {
  // la niebla del modo túnel se come el andén: aquí se abre
  escena.fog.density = 0.000012;
  document.querySelectorAll('[data-vista]').forEach((x) => x.classList.remove('is-active'));
  document.querySelector('[data-vista="plano"]')?.classList.add('is-active');
  if (!estado._vistaGeneral) {
    estado._vistaGeneral = {
      pos: camara.position.clone(),
      target: controles.target.clone(),
    };
  }
  const y = -st._prof * EXAG;
  // la cámara se planta a media altura del túnel y a ~420 m: a esa distancia el
  // andén (90-110 m) ocupa media pantalla y se lee su orientación
  const d = 300;
  // vista en tres cuartos alta: se lee la planta del andén, no su canto
  const pos = new THREE.Vector3(st._x + d * 0.30, y + d * 0.95, st._z + d * 0.52);
  const tgt = new THREE.Vector3(st._x, y, st._z);
  // la ficha ocupa la izquierda: se desplaza el encuadre para que la estación
  // quede centrada en el trozo de mapa que sigue viéndose
  const panel = $('#panel');
  if (panel && !panel.classList.contains('is-oculto') && innerWidth > 720) {
    const anchoVisible = 2 * d * Math.tan(THREE.MathUtils.degToRad(camara.fov / 2)) * camara.aspect;
    const corrimiento = (panel.getBoundingClientRect().width / 2) * (anchoVisible / innerWidth);
    const derecha = new THREE.Vector3().subVectors(pos, tgt).cross(camara.up).normalize();
    pos.addScaledVector(derecha, corrimiento);
    tgt.addScaledVector(derecha, corrimiento);
  }
  irA(pos.toArray(), tgt.toArray(), 1300);
  // haz vertical: se ve dónde está el pozo aunque el terreno esté opaco
  const haz = marcador.getObjectByName('haz');
  const punta = marcador.getObjectByName('punta');
  haz.scale.set(1, st._prof * EXAG + 600, 1);
  haz.position.set(0, -(st._prof * EXAG + 600) / 2 + 300, 0);
  punta.position.set(0, y, 0);
  marcador.position.set(st._x, 0, st._z);
  marcador.visible = true;
  estado._foco = new THREE.Vector3(st._x, y, st._z);
  estado._estacion = st;

  // contorno de la estación elegida, encima de todo
  const focoLinea = estado._focoLinea;
  const puntos = [];
  for (const a of st._andenes || []) {
    const n = a.pts.length;
    for (let i = 0; i < n; i++) {
      const [x1, z1] = a.pts[i], [x2, z2] = a.pts[(i + 1) % n];
      puntos.push(x1, a.cota + 2, z1, x2, a.cota + 2, z2);
    }
  }
  if (focoLinea && puntos.length) {
    focoLinea.geometry.dispose();
    focoLinea.geometry = new THREE.BufferGeometry();
    focoLinea.geometry.setAttribute('position', new THREE.Float32BufferAttribute(puntos, 3));
    focoLinea.visible = true;
  } else {
    focoLinea.visible = false;
  }
  if (estado._matEst) estado._matEst.uniforms.foco.value.copy(estado._foco);
}

function cerrarFicha() {
  marcador.visible = false;
  if (estado._focoLinea) estado._focoLinea.visible = false;
  estado.seleccion = null;
  pintarFicha(null);
  actualizarLineasUI();
  if (estado._vistaGeneral) {
    const g = estado._vistaGeneral;
    irA(g.pos.toArray(), g.target.toArray(), 1100);
    estado._vistaGeneral = null;
  }
  estado._foco = null;
  estado._estacion = null;
}

function esClaro(hex) {
  const h = hex.replace('#', '');
  const n = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.55;
}

function pintarFicha(st) {
  const f = $('#ficha');
  const bloque = $('#bloque-ficha');
  if (!st) {
    bloque.hidden = true;
    $('#panel').classList.remove('panel--ficha');
    f.innerHTML = '';
    return;
  }
  bloque.hidden = false;
  $('#panel').classList.add('panel--ficha');
  const ficha = estado.fichas?.[st.id];
  const cercanos = estado.trenes.filter((t) =>
    st.l.includes(t.linea) && Math.hypot(t.x - st._x, t.z - st._z) < 2500).length;
  const etiqueta = st.l.length > 1 ? 'Correspondencia' : 'Estación';
  const huella = estado.huellas?.[st.id];
  const anden = huella?.andenes?.length
    ? huella.andenes.reduce((a, b) => (a.area >= b.area ? a : b))
    : null;
  const medida = anden
    ? `<span class="ficha__meta">Andén ${Math.round(anden.largo)} × ${Math.round(anden.ancho)} m · ${
        anden.real ? 'planta dibujada en OSM' : 'trazado sobre la vía'}</span>`
    : '';
  const tags = ficha?.tags?.length
    ? `<ul class="ficha__tags">${ficha.tags.map((t) => `<li class="tag">${t}</li>`).join('')}</ul>`
    : '';
  const esquema = ficha?.esquema
    ? `<span class="ficha__marco"><img class="ficha__esquema" src="${ficha.esquema}" alt="Esquema de niveles y andenes de ${ficha.n}" loading="lazy"></span>
       <p class="ficha__credito">Esquema de niveles · Albert Guillaumes</p>`
    : '';
  f.innerHTML = `
    <strong class="ficha__nombre">${st.n}</strong>
    <span class="ficha__meta">${etiqueta} · pozo de ${Math.round(st._prof)} m (estimado)</span>
    ${medida}
    ${ficha && ficha.n !== st.n ? `<span class="ficha__meta">En el esquema: ${ficha.n}</span>` : ''}
    <div class="ficha__lineas">${st.l.map((id) => {
      const m = estado.lineas.get(id)?.meta;
      const col = m ? m.color : '#fff';
      return `<span class="pastilla${esClaro(col) ? ' is-clara' : ''}" style="--c:${col}">${m ? m.name.replace('Línea ', 'L') : id}</span>`;
    }).join('')}</div>
    ${tags}
    ${esquema}
    <span class="ficha__meta">${cercanos} tren${cercanos === 1 ? '' : 'es'} de estas líneas a menos de 2,5 km, según horario</span>
    <div class="ficha__pie">
      <button class="ficha__volver" type="button">← Volver al plano</button>
      ${ficha?.fuente ? '<a class="ficha__enlace" href="' + ficha.fuente + '" target="_blank" rel="noopener">Ficha original ↗</a>' : ''}
    </div>`;

  f.querySelector('.ficha__volver').addEventListener('click', cerrarFicha);
  const img = f.querySelector('.ficha__esquema');
  if (img) img.addEventListener('click', () => abrirLupa(img.src, img.alt));
}

function abrirLupa(src, alt) {
  const l = $('#lupa');
  l.querySelector('img').src = src;
  l.querySelector('img').alt = alt || '';
  l.classList.add('is-abierta');
}

// ————————————————————————————— UI —————————————————————————————
const PERFIL = (id) => {
  const n = id === 'R' ? 0 : parseInt(id, 10);
  return n >= 1 && n <= 5 ? 'estrecho' : 'ancho';
};

function construirPerfil() {
  const cont = $('#perfil');
  const profMax = Math.max(...[...estado.lineas.values()].map((l) => l.meta.depth));
  for (const [id, { meta }] of estado.lineas) {
    const fila = document.createElement('div');
    fila.className = 'perfil__fila';
    fila.innerHTML = `<b>${id === 'R' ? 'Ramal' : 'L' + id}</b>
      <span class="perfil__barra"><i style="width:${Math.round(meta.depth / profMax * 100)}%;background:${meta.color}"></i></span>
      <span>${meta.depth} m · ${PERFIL(id)}</span>`;
    cont.appendChild(fila);
  }
}

function construirListaLineas() {
  const ul = $('#lineas');
  ul.innerHTML = '';
  for (const [id, { meta }] of estado.lineas) {
    const li = document.createElement('li');
    const b = document.createElement('button');
    b.className = 'linea-chip';
    b.dataset.linea = id;
    b.title = `${meta.name} · ${meta.long}${meta.reconstruida ? ' (reconstruida)' : ''}`;
    b.innerHTML = `<span class="linea-chip__color" style="background:${meta.color}"></span>
      <span class="linea-chip__nombre">${id === 'R' ? 'Ramal' : 'L' + id}</span>
      <span class="linea-chip__rec">${meta.long.split('-')[0]}</span>`;
    b.addEventListener('click', () => {
      const l = estado.lineas.get(id);
      l.visible = !l.visible;
      aplicarVisibilidad();
      actualizarLineasUI();
    });
    li.appendChild(b);
    ul.appendChild(li);
  }
}

function actualizarLineasUI() {
  document.querySelectorAll('.linea-chip').forEach((b) => {
    const { meta } = estado.lineas.get(b.dataset.linea);
    b.classList.toggle('is-apagada', !estado.lineas.get(b.dataset.linea).visible);
    b.classList.toggle('is-sel', estado.seleccion === meta.id);
  });
}

function aplicarVisibilidad() {
  for (const o of estado.objetosLinea || []) {
    o.visible = estado.lineas.get(o.userData.id).visible;
  }
}

$('#corte').addEventListener('input', (e) => {
  const v = +e.target.value / 100;
  estado.opacidadSuperficie = v;
  $('#corte-val').textContent = Math.round(v * 100) + ' %';
  if (estado.superficie) estado.superficie.material.opacity = v;
  velo.classList.toggle('is-claro', v < 0.4);
});

$('#velocidad').addEventListener('click', (e) => {
  const escala = [1, 60, 300];
  const i = (escala.indexOf(estado.velocidad) + 1) % escala.length;
  // se congela el instante actual antes de cambiar de marcha: así el reloj no salta
  estado.horaBase = estado.horaBase + (performance.now() - estado.t0) / 1000 * estado.velocidad;
  estado.t0 = performance.now();
  estado.velocidad = escala[i];
  e.target.textContent = '×' + estado.velocidad;
  estado._refrescarBadge = true;
});

$('#todas').addEventListener('click', () => {
  for (const l of estado.lineas.values()) l.visible = true;
  aplicarVisibilidad();
  actualizarLineasUI();
});

document.querySelectorAll('[data-vista]').forEach((b) => {
  b.addEventListener('click', () => {
    document.querySelectorAll('[data-vista]').forEach((x) => x.classList.remove('is-active'));
    b.classList.add('is-active');
    vista(b.dataset.vista);
  });
});

$('#ahora').addEventListener('click', () => {
  estado.horaBase = horaMadridSegundos(new Date());
  estado.t0 = performance.now();
  actualizarTrenes(estado.horaBase);
  estado._refrescarBadge = true;
});

$('#lupa').addEventListener('click', () => $('#lupa').classList.remove('is-abierta'));
addEventListener('keydown', (e) => { if (e.key === 'Escape') $('#lupa').classList.remove('is-abierta'); });

$('#plegar').addEventListener('click', () => {
  const p = $('#panel');
  p.classList.add('is-oculto');
  $('#abrir-panel').hidden = false;
  $('#plegar').setAttribute('aria-expanded', 'false');
});

$('#abrir-panel').addEventListener('click', () => {
  $('#panel').classList.remove('is-oculto');
  $('#abrir-panel').hidden = true;
  $('#plegar').setAttribute('aria-expanded', 'true');
});

// ————————————————————————————— bucle —————————————————————————————
let ultimoTick = 0;
// barra de escala honesta: metros por píxel a la altura del punto que se mira
function ajustarEscala() {
  const el = $('#escala');
  if (!el) return;
  const d = camara.position.distanceTo(controles.target);
  if (d > 26000) { el.hidden = true; return; }
  const altoMundo = 2 * d * Math.tan(THREE.MathUtils.degToRad(camara.fov / 2));
  const mPorPx = altoMundo / innerHeight;
  const opciones = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000];
  let m = opciones[0];
  for (const o of opciones) if (o / mPorPx <= 130) m = o;
  el.hidden = false;
  el.querySelector('i').style.width = (m / mPorPx).toFixed(0) + 'px';
  el.querySelector('span').textContent = m >= 1000 ? m / 1000 + ' km' : m + ' m';
}

function ajustarHuellas() {
  const h = estado._huellas;
  if (!h) return;
  const d = camara.position.distanceTo(controles.target);
  h.mallaAndenes.visible = d < 9000;
  h.bordeAndenes.visible = d < 9000;
  h.bordeVestibulo.visible = d < 3000;
  if (estado._grupoModelos) estado._grupoModelos.visible = d < 2600;
  if (estado._modelosReales) {
    estado._modelosReales.visible = d < 4200;
    // en las 8 estaciones con modelo del autor, el arquetipo sobra
    for (const o of estado._modelosReales.children) {
      o.visible = d < 4200;
    }
  }
  // con el modelo encendido, la planta plana sobra
  h.mallaAndenes.visible = estado._grupoModelos?.visible ? false : d < 9000;
}

// Los modelos de Blender (blender/arquetipos.py): seis tipologías modeladas una
// vez y colocadas en su sitio con la posición y el ángulo reales. 18 ficheros de
// ~40 KB (6 tipos × 3 largos).
// Para que 242 estaciones no cuesten 242 draw calls, cada prototipo se fusiona en
// dos geometrías (opaco y translúcido, con el color metido en los vértices) y las
// estaciones se pintan con InstancedMesh: unas 36 llamadas en total.
async function cargarModelos(tipologias) {
  const grupo = new THREE.Group();
  grupo.name = 'estaciones3d';
  escena.add(grupo);
  estado._grupoModelos = grupo;

  // reparto de estaciones por prototipo
  // las estaciones con modelo del autor no llevan arquetipo
  const conModeloReal = new Set(Object.values(estado.modelos3d || {})
    .map((m) => m.estacion).filter(Boolean));
  const porModelo = new Map();
  for (const st of estado.datos.stations) {
    if (conModeloReal.has(st.id)) continue;
    const t = tipologias[st.id];
    if (!t) continue;
    const nombre = `estacion_${t.tipo}_${t.largo}`;
    if (!porModelo.has(nombre)) porModelo.set(nombre, []);
    porModelo.get(nombre).push({ st, t });
  }

  const loader = new GLTFLoader();

  function fusionar(raiz) {
    raiz.updateMatrixWorld(true);
    const opacos = [], translucidos = [];
    raiz.traverse((o) => {
      if (!o.isMesh || !o.geometry) return;
      const g = o.geometry.clone();
      g.applyMatrix4(o.matrixWorld);
      g.deleteAttribute('normal');
      g.deleteAttribute('uv');
      g.deleteAttribute('tangent');
      const col = o.material.color || { r: 1, g: 1, b: 1 };
      const n = g.attributes.position.count;
      const arr = new Float32Array(n * 3);
      for (let i = 0; i < n; i++) {
        arr[i * 3] = col.r; arr[i * 3 + 1] = col.g; arr[i * 3 + 2] = col.b;
      }
      g.setAttribute('color', new THREE.Float32BufferAttribute(arr, 3));
      (o.material.transparent && o.material.opacity < 0.9 ? translucidos : opacos).push(g);
    });
    return {
      opaco: opacos.length ? mergeGeometries(opacos, false) : null,
      translucido: translucidos.length ? mergeGeometries(translucidos, false) : null,
    };
  }

  const matOpaco = new THREE.MeshBasicMaterial({ vertexColors: true, toneMapped: false });
  const matTrans = new THREE.MeshBasicMaterial({
    vertexColors: true, transparent: true, opacity: 0.10,
    depthWrite: false, side: THREE.DoubleSide, toneMapped: false,
  });

  let colocados = 0;
  await Promise.all([...porModelo.entries()].map(async ([nombre, lista]) => {
    let gltf;
    try { gltf = await loader.loadAsync(`blender/salida/${nombre}.glb`); }
    catch { return; }
    const { opaco, translucido } = fusionar(gltf.scene);
    for (const [geo, mat, orden] of [[opaco, matOpaco, 5], [translucido, matTrans, 6]]) {
      if (!geo) continue;
      const im = new THREE.InstancedMesh(geo, mat, lista.length);
      im.renderOrder = orden;
      im.frustumCulled = false;
      lista.forEach(({ st, t }, i) => {
        const andenOsm = estado.huellas[st.id]?.andenes?.[0];
        const k = andenOsm?.largo
          ? Math.min(1.8, Math.max(0.5, andenOsm.largo / t.largo)) : 1;
        const m4 = new THREE.Matrix4();
        m4.compose(
          new THREE.Vector3(st._x, -st._prof * EXAG, st._z),
          new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0),
            -THREE.MathUtils.degToRad(t.ang || 0)),
          new THREE.Vector3(k, 1, 1),
        );
        im.setMatrixAt(i, m4);
        colocados++;
      });
      im.instanceMatrix.needsUpdate = true;
      grupo.add(im);
    }
  }));

  grupo.visible = false;   // se enciende al acercarse
  console.info(`modelos Blender: ${colocados} estaciones en ${grupo.children.length} mallas`);
  return grupo;
}

// ——— los 8 intercambiadores con modelo 3D del autor (estacions.albertguillaumes.cat)
// Se cargan al vuelo cuando la estación se acerca: son 8 ficheros de 0,4-3,3 MB.
async function cargarModelosReales() {
  const grupo = new THREE.Group();
  grupo.name = 'modelosReales';
  escena.add(grupo);
  estado._modelosReales = grupo;
  const loader = new GLTFLoader();
  const porId = new Map();
  for (const [nombre, m] of Object.entries(estado.modelos3d || {})) {
    if (m.estacion) porId.set(m.estacion, { nombre, ...m });
  }
  for (const [id, m] of porId) {
    const st = estado.datos.stations.find((x) => x.id === id);
    if (!st) continue;
    let gltf;
    try {
      gltf = await loader.loadAsync(`assets/modelos3d/${m.nombre}.glb`);
    } catch { continue; }
    const obj = gltf.scene;
    // dx/dy son metros al este y al norte, calculados encajando el modelo con
    // los túneles reales; en el visor la z crece hacia el sur
    obj.position.set(st._x + (m.dx || 0), -st._prof * EXAG, st._z - (m.dy || 0));
    obj.rotation.y = THREE.MathUtils.degToRad(-(m.ang || 0));
    // la red entera va con la altura x200; el modelo se levanta lo justo para que
    // se lean sus niveles sin convertirse en una torre
    obj.scale.y = 18;
    obj.userData.st = st;
    obj.traverse((o) => {
      if (o.isMesh) {
        o.material.side = THREE.DoubleSide;
        o.material.transparent = false;
      }
    });
    grupo.add(obj);
    st._modeloReal = obj;
  }
  grupo.visible = false;
  console.info(`modelos del autor: ${grupo.children.length}`);
  return grupo;
}

function animar(ahora) {
  requestAnimationFrame(animar);
  const dt = ahora - ultimoTick;
  ultimoTick = ahora;

  if (transicion) {
    const t = Math.min(1, (ahora - transicion.inicio) / transicion.ms);
    const e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
    camara.position.lerpVectors(transicion.desde, transicion.hasta, e);
    controles.target.lerpVectors(transicion.tDesde, transicion.tHasta, e);
    if (t >= 1) transicion = null;
  }

  const tSeg = estado.horaBase + (ahora - estado.t0) / 1000 * estado.velocidad;
  const h = Math.floor(tSeg / 3600) % 24;
  const m = Math.floor(tSeg / 60) % 60;
  const hhmm = String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
  $('#reloj').textContent = hhmm;
  if (estado.velocidad === 1) {
    $('#reloj').title = 'Hora actual de Madrid';
    if (ahora - (estado._ultimoBadge || 0) > 5000 || estado._refrescarBadge) {
      estado._ultimoBadge = ahora;
      estado._refrescarBadge = false;
      $('#badge-estado').textContent = `Ahora · ${hhmm} · ${estado.servicio.toLowerCase()}`;
    }
  } else {
    $('#reloj').title = `Simulación ×${estado.velocidad}`;
    if (estado._refrescarBadge) {
      estado._refrescarBadge = false;
      $('#badge-estado').textContent = `Simulación ×${estado.velocidad} · ${estado.servicio.toLowerCase()}`;
    }
  }

  if (ahora - (estado._ultimoTren || 0) > 220) {
    estado._ultimoTren = ahora;
    actualizarTrenes(tSeg % 86400);
    $('#contador').textContent = `${estado.trenes.length} trenes en circulación · ${estado.datos.stations.length} estaciones · ${estado.lineas.size} líneas`;
  }

  actualizarEtiquetas();
  controles.update();
  ajustarHuellas();
  ajustarEscala();
  renderer.render(escena, camara);
}

// ————————————————————————————— arranque —————————————————————————————
async function iniciar() {
  const aviso = document.createElement('div');
  aviso.id = 'aviso-carga';
  aviso.textContent = 'Cargando la red…';
  document.body.appendChild(aviso);

  const [datos, fichas, huellas, tipologias, modelos3d] = await Promise.all([
    fetch('data/metro.json').then((r) => r.json()),
    fetch('data/estaciones.json').then((r) => r.json()).catch(() => ({})),
    fetch('data/estaciones_osm.json').then((r) => r.json()).catch(() => ({})),
    fetch('data/estaciones_3d.json').then((r) => r.json()).catch(() => ({})),
    fetch('data/modelos3d.json').then((r) => r.json()).catch(() => ({})),
  ]);
  estado.datos = datos;
  estado.fichas = fichas;
  estado.huellas = huellas;
  estado.tipologias = tipologias;
  estado.modelos3d = modelos3d;

  // centro y bbox
  let minLat = 90, maxLat = -90, minLon = 180, maxLon = -180;
  for (const sh of datos.shapes) {
    for (const [la, lo] of sh.pts) {
      if (la < minLat) minLat = la;
      if (la > maxLat) maxLat = la;
      if (lo < minLon) minLon = lo;
      if (lo > maxLon) maxLon = lo;
    }
  }
  estado.centro = { lat: (minLat + maxLat) / 2, lon: (minLon + maxLon) / 2 };
  const anchoKm = (maxLon - minLon) * M_PER_DEG * Math.cos(estado.centro.lat * Math.PI / 180) / 1000;
  escala = anchoKm > 1 ? 1 : 1;

  construirRed();
  construirListaLineas();
  construirPerfil();
  await cargarModelos(tipologias);
  await cargarModelosReales();
  await construirSuperficie({ minLat, maxLat, minLon, maxLon });

  estado.horaBase = horaMadridSegundos(new Date());
  estado.t0 = performance.now();
  actualizarTrenes(estado.horaBase);
  estado._refrescarBadge = true;
  aviso.remove();

  window.__mm = estado; // depuración
  window.__sel = seleccionar;
  window.__cerrar = cerrarFicha;
  window.__pantalla = (nombre) => {
    const st = estado.datos.stations.find((x) => x.n.toLowerCase().includes(nombre.toLowerCase()));
    if (!st) return null;
    _v3.set(st._x, cotaEstacion(st), st._z).project(camara);
    return { x: Math.round((_v3.x * 0.5 + 0.5) * innerWidth), y: Math.round((-_v3.y * 0.5 + 0.5) * innerHeight), n: st.n };
  };
  window.__cam = camara;
  window.__ctrl = controles;
  controles.target.set(0, -1400, 0);
  irA([0, 15500, 17500], [0, -1400, 0], 2200);
  // el terreno se abre solo: de plano a corte geológico en 2,6 s
  const t0 = performance.now();
  const desde = estado.opacidadSuperficie, hasta = 0.34;
  const fundido = (t) => {
    const k = Math.min(1, (t - t0) / 2600);
    const e = 1 - (1 - k) ** 3;
    const v = desde + (hasta - desde) * e;
    estado.opacidadSuperficie = v;
    if (estado.superficie) estado.superficie.material.opacity = v;
    const sl = $('#corte');
    sl.value = Math.round(v * 100);
    $('#corte-val').textContent = Math.round(v * 100) + ' %';
    velo.classList.toggle('is-claro', v < 0.4);
    if (k < 1) requestAnimationFrame(fundido);
  };
  requestAnimationFrame(fundido);
  requestAnimationFrame(animar);
}

addEventListener('resize', () => {
  camara.aspect = innerWidth / innerHeight;
  camara.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
  resolucion.set(innerWidth, innerHeight);
  for (const o of estado.objetosLinea || []) o.material.resolution.copy(resolucion);
});

iniciar().catch((err) => {
  console.error(err);
  const b = $('#badge-estado');
  b.textContent = 'Error al cargar los datos';
  b.classList.add('nz-badge--danger');
});
