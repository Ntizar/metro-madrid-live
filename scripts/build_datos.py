#!/usr/bin/env python3
"""Construye data/metro.json a partir del GTFS oficial de CRTM (Red de Metro).

Fuente: GTFS Red de Metro, Consorcio Regional de Transportes de Madrid
(arcgis item 5c7f2951962540d69ffe8f640d94c246, feed_version 20250527).
Salida: un JSON compacto pensado para render 3D en el navegador.
"""
import re
import csv, json, math, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
GTFS = os.path.join(BASE, "..", "data", "gtfs")
OUT = os.path.join(BASE, "..", "data", "metro.json")


def rows(name):
    with open(os.path.join(GTFS, name), encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def hav(a, b):
    R = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dla, dlo = la2 - la1, lo2 - lo1
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def proyeccion(st, sh):
    """(distancia en m, distancia recorrida en m) de la estación a su trazado."""
    la0 = math.radians(st["lat"])
    kx = 111320.0 * math.cos(la0)
    ky = 111320.0
    px, py = st["lon"] * kx, st["lat"] * ky
    pts, cum = sh["pts"], sh["cum"]
    mejor = (1e18, 0.0)
    for j in range(len(pts) - 1):
        ax, ay = pts[j][1] * kx, pts[j][0] * ky
        bx, by = pts[j + 1][1] * kx, pts[j + 1][0] * ky
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        if d < mejor[0]:
            mejor = (d, cum[j] + t * (cum[j + 1] - cum[j]))
    return mejor


def rdp(pts, eps):
    """Douglas-Peucker sobre [(lat,lon)]."""
    if len(pts) < 3:
        return pts
    lat0 = math.radians(sum(p[0] for p in pts) / len(pts))
    xy = [(p[1] * math.cos(lat0), p[0]) for p in pts]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        x1, y1 = xy[i]
        x2, y2 = xy[j]
        dx, dy = x2 - x1, y2 - y1
        nrm = math.hypot(dx, dy) or 1e-12
        best, bi = -1.0, -1
        for k in range(i + 1, j):
            x, y = xy[k]
            d = abs(dy * (x - x1) - dx * (y - y1)) / nrm
            if d > best:
                best, bi = d, k
        if best > eps:
            keep[bi] = True
            stack += [(i, bi), (bi, j)]
    return [p for p, k in zip(pts, keep) if k]


def rdp_anillo(pts, eps):
    """Douglas-Peucker que no se rompe con líneas circulares (inicio == fin).

    Con la cuerda degenerada el RDP normal devuelve solo los dos extremos: el
    anillo (L12 MetroSur) perdía los 40,6 km de trazado y se reconstruía a mano.
    Se parte el anillo por el punto más lejano al inicio y se simplifica cada mitad.
    """
    if len(pts) > 4 and hav(pts[0], pts[-1]) < 30:
        k = max(range(len(pts)), key=lambda j: hav(pts[0], pts[j]))
        if k > 1:
            return rdp(pts[:k + 1], eps) + rdp(pts[k:], eps)[1:]
    return rdp(pts, eps)


def hhmmss(t):
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


# --- metadatos de línea: nombre, color oficial, profundidad estimada (m) ---
DEPTH = {"1": 18, "2": 20, "3": 22, "4": 21, "5": 19, "6": 27, "7": 22,
         "8": 26, "9": 27, "10": 31, "11": 23, "12": 16, "R": 20}
NAME = {"1": "Línea 1", "2": "Línea 2", "3": "Línea 3", "4": "Línea 4",
        "5": "Línea 5", "6": "Línea 6", "7": "Línea 7", "8": "Línea 8",
        "9": "Línea 9", "10": "Línea 10", "11": "Línea 11", "12": "Línea 12",
        "R": "Ramal"}

routes = {r["route_id"]: r for r in rows("routes.txt")}
trips = rows("trips.txt")
shapes_raw = {}
for s in rows("shapes.txt"):
    shapes_raw.setdefault(s["shape_id"], []).append(
        (int(s["shape_pt_sequence"]), float(s["shape_pt_lat"]), float(s["shape_pt_lon"])))
for k in shapes_raw:
    shapes_raw[k] = [(la, lo) for _, la, lo in sorted(shapes_raw[k])]

stops = {s["stop_id"]: s for s in rows("stops.txt")}
stop_times_by_trip = {}
for st in rows("stop_times.txt"):
    stop_times_by_trip.setdefault(st["trip_id"], []).append(st)
for k in stop_times_by_trip:
    stop_times_by_trip[k].sort(key=lambda x: int(x["stop_sequence"]))

freqs = {}
for f in rows("frequencies.txt"):
    freqs.setdefault(f["trip_id"], []).append(
        [hhmmss(f["start_time"]), hhmmss(f["end_time"]), int(f["headway_secs"])])
for k in freqs:
    freqs[k].sort()

# --- shapes simplificadas, una por shape_id usado ---
used_shapes = sorted({t["shape_id"] for t in trips if t["shape_id"] in shapes_raw})
shape_index, shapes_out = {}, []
for sid in used_shapes:
    pts = rdp_anillo(shapes_raw[sid], 0.00018)
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + hav(a, b))
    shape_index[sid] = len(shapes_out)
    shapes_out.append({"n": len(pts), "cum": [round(c) for c in cum],
                       "pts": [[round(p[0], 6), round(p[1], 6)] for p in pts]})

# --- paradas -> estación (parent_station) ---
station_of, station_pos = {}, {}
for sid, s in stops.items():
    p = s.get("parent_station") or sid
    station_of[sid] = p
    la, lo = float(s["stop_lat"]), float(s["stop_lon"])
    prev = station_pos.get(p)
    station_pos[p] = [la, lo] if prev is None else [(prev[0] + la) / 2, (prev[1] + lo) / 2]


def title(name):
    for pref in ("INTERCAMBIADOR DE ", "ESTACIÓN DE ", "ESTACION DE "):
        if name.upper().startswith(pref):
            name = name[len(pref):]
    small = {"de", "del", "la", "las", "los", "el", "y", "a"}
    out = []
    for i, w in enumerate(name.lower().split()):
        out.append(w if (i and w in small) else w[:1].upper() + w[1:])
    return " ".join(out)


# --- vías reales de OSM: sirven para reconstruir los shapes que el GTFS trae vacíos ---
OSM_VIAS = os.path.join(os.path.dirname(BASE), "data", "fuentes", "osm_vias.json")
vias_osm = {}
if os.path.exists(OSM_VIAS):
    _d = json.load(open(OSM_VIAS, encoding="utf-8"))
    for _e in _d["elements"]:
        if not _e.get("geometry"):
            continue
        _ref = (_e.get("tags") or {}).get("ref") or ""
        _ref = _ref.upper().replace("LÍNEA", "L").replace("LINEA", "L").strip()
        if _ref.startswith("L") and _ref[1:].isdigit():
            _ref = _ref[1:]
        elif _ref in ("RAMAL", "R"):
            _ref = "R"
        _pts = [(round(_q["lat"], 6), round(_q["lon"], 6)) for _q in _e["geometry"]]
        vias_osm.setdefault(_ref, []).append(_pts)
    print(f"vías OSM: {sum(len(v) for v in vias_osm.values())} ways en {len(vias_osm)} líneas")


def _encadenar(segs):
    """une ways que comparten extremos en polilíneas continuas"""
    usados = [False] * len(segs)
    ramas = []
    while not all(usados):
        i = usados.index(False)
        linea = segs[i][:]
        usados[i] = True
        crecio = True
        while crecio:
            crecio = False
            for j, sg in enumerate(segs):
                if usados[j]:
                    continue
                if sg[0] == linea[-1]:
                    linea += sg[1:]
                elif sg[-1] == linea[-1]:
                    linea += sg[::-1][1:]
                elif sg[-1] == linea[0]:
                    linea = sg[:-1] + linea
                elif sg[0] == linea[0]:
                    linea = sg[::-1][:-1] + linea
                else:
                    continue
                usados[j] = True
                crecio = True
            # el anillo ya se cerró: no hay que dar otra vuelta
            if len(linea) > 20 and linea[0] == linea[-1]:
                break
        if len(linea) > 3:
            ramas.append(linea)
    return ramas


def _proyectar(c, linea):
    """punto más cercano de la polilínea y su índice"""
    mejor, bj = 1e18, 0
    for j, q in enumerate(linea):
        d = (q[0] - c[0]) ** 2 + (q[1] - c[1]) ** 2
        if d < mejor:
            mejor, bj = d, j
    return bj, mejor ** 0.5 * 111_320


def reconstruir_shape(coords, ref):
    """Trazado real de una línea que el GTFS trae sin geometría.

    Las paradas dan el orden; las vías de OSM dan la curva. Entre dos paradas se
    usa el trozo de vía que las une si existe y avanza en el mismo sentido; si no
    (tramo sin mapear), se une con una recta suavizada.
    """
    ramas = _encadenar(vias_osm.get(ref, []))
    if not ramas:
        return None
    rama = min(ramas, key=lambda r: sum(_proyectar(c, r)[1] for c in coords))
    idx, dist = zip(*[_proyectar(c, rama) for c in coords])
    dentro = [d < 300 for d in dist]

    salida = []
    for i, c in enumerate(coords):
        if i == 0:
            salida.append(rama[idx[0]] if dentro[0] else c)
            continue
        avanza = dentro[i] and dentro[i - 1] and idx[i] > idx[i - 1]
        if avanza:
            salida += rama[idx[i - 1] + 1: idx[i] + 1]
        else:
            a = salida[-1]
            for k in range(1, 9):
                t = k / 9
                salida.append((a[0] + (c[0] - a[0]) * t, a[1] + (c[1] - a[1]) * t))
            salida.append(c)
    suave = [salida[0]]
    for a, b in zip(salida, salida[1:]):
        suave.append((a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25))
        suave.append((a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75))
    suave.append(salida[-1])
    salida = [(round(x, 6), round(y, 6)) for x, y in suave]
    if len(salida) > 320:
        paso = len(salida) / 320
        salida = [salida[int(i * paso)] for i in range(320)] + [salida[-1]]
    return salida


# --- patrones de servicio ---
patterns = []
line_stations = {}
for t in trips:
    tid = t["trip_id"]
    if tid not in freqs:
        continue
    sts = stop_times_by_trip.get(tid, [])
    if len(sts) < 2:
        continue
    rid = t["route_id"]
    short = routes[rid]["route_short_name"]
    sid = t["shape_id"]
    if sid not in shape_index:
        continue
    sh = shapes_out[shape_index[sid]]
    pts, cum = sh["pts"], sh["cum"]
    if len(pts) < 10:
        # el GTFS del CRTM deja las líneas 12 y Ramal con 2-5 puntos: se rehace el trazado
        nuevo_trazado = reconstruir_shape(
            [(float(stops[x["stop_id"]]["stop_lat"]), float(stops[x["stop_id"]]["stop_lon"]))
             for x in sts], short)
        if nuevo_trazado:
            pts = nuevo_trazado
            cum = [0.0]
            for a, b in zip(pts, pts[1:]):
                dy = (a[0] - b[0]) * 111_320
                dx = (a[1] - b[1]) * 111_320 * math.cos(math.radians(a[0]))
                cum.append(cum[-1] + math.hypot(dx, dy))
            sh["pts"], sh["cum"], sh["n"] = pts, cum, len(pts)
    coords = [(stops[x["stop_id"]]["stop_lat"], stops[x["stop_id"]]["stop_lon"])
              for x in sts]
    coords = [(float(a), float(b)) for a, b in coords]
    # distancia sobre el shape de cada parada: punto mas cercano
    s_on_shape = []
    for c in coords:
        best, bj = 1e18, 0
        for j, p in enumerate(pts):
            d = (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2
            if d < best:
                best, bj = d, j
        s_on_shape.append(cum[bj])
    # las líneas circulares repiten la primera parada al final: ahí se cierra el
    # recorrido, y ninguna parada puede retroceder sobre el trazado
    for _i in range(1, len(s_on_shape)):
        if _i == len(s_on_shape) - 1 and abs(coords[_i][0] - coords[0][0]) < 1e-5 \
                and abs(coords[_i][1] - coords[0][1]) < 1e-5:
            s_on_shape[_i] = cum[-1]
        elif s_on_shape[_i] <= s_on_shape[_i - 1]:
            s_on_shape[_i] = s_on_shape[_i - 1] + 1.0
    # offsets temporales desde la salida
    t0 = hhmmss(sts[0]["departure_time"] or sts[0]["arrival_time"])
    offs = [hhmmss(x["arrival_time"] or x["departure_time"]) - t0 for x in sts]
    if max(offs) <= 0:
        continue
    pat = {
        "l": short,
        "d": int(t["direction_id"]),
        "s": shape_index[sid],
        "o": offs,
        "sp": [round(x) for x in s_on_shape],
        "_est": [station_of[x["stop_id"]] for x in sts],
        "w": freqs[tid],
        "dur": max(offs),
        "h": t.get("trip_headsign", ""),
        "svc": t["service_id"],
    }
    patterns.append(pat)
    line_stations.setdefault(short, set()).update(
        station_of[x["stop_id"]] for x in sts)

# --- estaciones con sus lineas ---
stations = []
for pid in sorted({p for v in line_stations.values() for p in v}):
    la, lo = station_pos[pid]
    s = stops[pid] if pid in stops else {}
    name = title(s.get("stop_name", pid))
    lines = sorted([l for l, v in line_stations.items() if pid in v],
                   key=lambda x: (x == "R", len(x), x))
    stations.append({"id": pid, "n": name, "lat": round(la, 6), "lon": round(lo, 6),
                     "l": lines})

lines_out = []
for rid, r in routes.items():
    short = r["route_short_name"]
    if short not in line_stations:
        continue
    col = "#" + r["route_color"].lower() if r["route_color"] else "#d9d9d9"
    lines_out.append({"id": short, "name": NAME.get(short, short),
                      "long": r["route_long_name"], "color": col,
                      "depth": DEPTH.get(short, 20),
                      "dirs": sorted({p["d"] for p in patterns if p["l"] == short})})
lines_out.sort(key=lambda x: (x["id"] == "R", int(x["id"]) if x["id"].isdigit() else 99))

# --- Línea 3: no viene en el feed GTFS (sin servicio en el feed 20250527) ---
# Trazado reconstruido con las 19 estaciones geocodificadas (Nominatim/OSM) y
# tiempos estimados a partir del dato público de 34 min / 17,49 km.
L3 = ["Moncloa", "Argüelles", "Ventura Rodríguez", "Plaza de España", "Callao",
      "Sol", "Lavapiés", "Embajadores", "Palos de la Frontera", "Delicias",
      "Legazpi", "Almendrales", "Hospital 12 de Octubre", "San Fermín-Orcasur",
      "Ciudad de los Ángeles", "Villaverde Bajo-Cruce", "San Cristóbal",
      "Villaverde Alto", "El Casar"]
try:
    import json as _json
    geo = _json.load(open(os.path.join(BASE, "..", "data", "l3_nominatim.json"),
                          encoding="utf-8"))
except Exception:
    geo = {}

by_name = {s["n"].lower(): s for s in stations}
ALIAS_L3 = {"sol": "puerta del sol", "plaza de espana": "plaza de espana",
            "hospital 12 de octubre": "hospital 12 de octubre"}
l3_pts = []
l3_ids = []
for n in L3:
    key = n.lower()
    st = by_name.get(ALIAS_L3.get(key, key))
    # si el nombre no coincide, se busca la estación existente a menos de 250 m
    if st is None and n in geo:
        cand = min(stations, key=lambda x: hav((x["lat"], x["lon"]), (geo[n][0], geo[n][1])),
                   default=None)
        if cand and hav((cand["lat"], cand["lon"]), (geo[n][0], geo[n][1])) < 250:
            st = cand
    if st is not None:
        l3_pts.append((st["lat"], st["lon"]))
        l3_ids.append(st["id"])
        if "3" not in st["l"]:
            st["l"] = sorted(set(st["l"] + ["3"]))
    elif n in geo:
        la, lo = geo[n][0], geo[n][1]
        l3_pts.append((la, lo))
        st = {"id": "l3_" + n.lower().replace(" ", "_").replace("-", "_"),
              "n": n, "lat": round(la, 6), "lon": round(lo, 6), "l": ["3"]}
        stations.append(st)
        l3_ids.append(st["id"])
        by_name[key] = st
    else:
        print("AVISO: sin coordenadas para", n, file=sys.stderr)

if len(l3_pts) == len(L3):
    pts = []
    for a, b in zip(l3_pts, l3_pts[1:]):
        pts.append(a)
        for k in (1, 2):  # densificar para curvas suaves
            pts.append((a[0] + (b[0] - a[0]) * k / 3, a[1] + (b[1] - a[1]) * k / 3))
    pts.append(l3_pts[-1])
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + hav(a, b))
    sidx = len(shapes_out)
    shapes_out.append({"n": len(pts), "cum": [round(c) for c in cum],
                       "pts": [[round(p[0], 6), round(p[1], 6)] for p in pts]})
    DUR = 34 * 60
    span = cum[-1]
    stop_s = [cum[int(i * (len(pts) - 1) / (len(L3) - 1))] for i in range(len(L3))]
    offs = [round(DUR * s / span) for s in stop_s]
    lines_out.append({"id": "3", "name": "Línea 3", "color": "#ffd000",
                      "long": "Moncloa-El Casar", "depth": DEPTH["3"],
                      "dirs": [0, 1], "reconstruida": True})
    for d in (0, 1):
        sp = [round(x) for x in stop_s] if d == 0 else [round(span - x) for x in reversed(stop_s)]
        patterns.append({"l": "3", "d": d, "s": sidx,
                         "o": offs if d == 0 else [round(DUR - o) for o in reversed(offs)],
                         "sp": sp,
                         "_est": l3_ids if d == 0 else list(reversed(l3_ids)),
                         "w": [[6 * 3600, 9 * 3600, 300], [9 * 3600, 17 * 3600, 330],
                               [17 * 3600, 21 * 3600, 300], [21 * 3600, 25 * 3600 + 1800, 420]],
                         "dur": DUR, "h": "El Casar" if d == 0 else "Moncloa",
                         "svc": "4_I14"})
    lines_out.sort(key=lambda x: (x["id"] == "R", int(x["id"]) if x["id"].isdigit() else 99))

# --- fusionar paradas duplicadas (el GTFS repite transbordos como stop_id distintos) ---
import unicodedata as _ud


def _norm(s):
    s = _ud.normalize("NFD", s.lower())
    s = "".join(c for c in s if _ud.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


grupos = {}
for st in stations:
    grupos.setdefault(_norm(st["n"]), []).append(st)

fusionadas = []
fusion_de = {}
for k, g in grupos.items():
    base = g[0]
    for x in g:
        fusion_de[x["id"]] = base["id"]
    lineas = sorted({l for x in g for l in x["l"]},
                    key=lambda l: (l == "R", int(l) if l.isdigit() else 99))
    lat = round(sum(x["lat"] for x in g) / len(g), 6)
    lon = round(sum(x["lon"] for x in g) / len(g), 6)
    fusionadas.append({"id": base["id"], "n": base["n"], "lat": lat, "lon": lon, "l": lineas})
if fusionadas:
    stations = sorted(fusionadas, key=lambda s: s["n"])

# --- cota por estación y perfil de cota de cada patrón ---
# El andén y TODAS las vías que lo cruzan comparten cota. Se estima como la media
# de las profundidades base de las líneas de la estación, redondeada a medio metro:
# así ninguna vía pasa 10-15 m por encima del andén de un intercambiador.
COTA = {}
for st in stations:
    ds = [DEPTH.get(l, 20) for l in st["l"]]
    COTA[st["id"]] = round(sum(ds) / len(ds) * 2) / 2
    st["cota"] = COTA[st["id"]]

# perfil de cota de cada trazado. La meseta plana se centra en la proyección del
# centro de la estación sobre la vía: es el mismo punto donde el visor planta el
# andén, así que la vía pasa plana justo por debajo de la plataforma y solo hay
# rampa entre estaciones.
linea_de_shape = {}
for p in patterns:
    p.pop("_est", None)
    linea_de_shape[p["s"]] = p["l"]
shapes_de_linea = {}
for si, lid in linea_de_shape.items():
    shapes_de_linea.setdefault(lid, []).append(si)

PARES = {si: {} for si in linea_de_shape}
for st in stations:
    for lid in st["l"]:
        for si in shapes_de_linea.get(lid, ()):
            dist, s = proyeccion(st, shapes_out[si])
            if dist <= 300:
                PARES[si][int(round(s))] = st["cota"]

# rampa entre estaciones: la vía va plana al llegar y al salir del andén y sube o
# baja en el tercio central del tramo (rampa máx. 400 m)
RAMPA = 400.0
PERFILES = {}
for si, pares in PARES.items():
    L = shapes_out[si]["cum"][-1]
    ss = sorted(pares)
    puntos = []
    if ss:
        puntos.append([0, pares[ss[0]]])
    for i in range(len(ss)):
        s, c = ss[i], pares[ss[i]]
        puntos.append([int(s), c])
        if i + 1 < len(ss):
            s2, c2 = ss[i + 1], pares[ss[i + 1]]
            g = s2 - s
            r = min(RAMPA, max(60.0, g * 0.5))
            ini, fin = s + (g - r) / 2, s + (g + r) / 2
            puntos.append([int(ini), c])
            puntos.append([int(fin), c2])
    if ss:
        puntos.append([int(L), pares[ss[-1]]])
    limpio = []
    for s, c in sorted(puntos):
        if limpio and s - limpio[-1][0] < 1:
            continue
        limpio.append([s, c])
    PERFILES[str(si)] = limpio

# la profundidad de la línea pasa a ser la media real de sus estaciones
for l in lines_out:
    cs = [st["cota"] for st in stations if l["id"] in st["l"]]
    if cs:
        l["depth"] = round(sum(cs) / len(cs), 1)
        l["cotaMin"], l["cotaMax"] = min(cs), max(cs)

data = {
    "meta": {
        "fuente": "GTFS Red de Metro · CRTM (feed_version 20250527)",
        "generado": "2026-11-18",
        "nota_profundidad": "Cota estimada por estación (media de las profundidades de sus líneas, no dato oficial); la vía interpola entre cotas",
        "nota_simulacion": "Trenes calculados con las frecuencias oficiales del GTFS",
        "nota_l3": "Línea 3 no viene en el feed: trazado reconstruido con estaciones OSM",
    },
    "lines": lines_out,
    "shapes": shapes_out,
    "patterns": patterns,
    "perfiles": PERFILES,
    "stations": stations,
    "calendar": {r["service_id"]: {d: int(r[d]) for d in
                 ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")}
                 for r in rows("calendar.txt")},
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

size = os.path.getsize(OUT)
print(f"OK {OUT} {size/1024:.0f} KB")
print(f"lineas={len(lines_out)} shapes={len(shapes_out)} patrones={len(patterns)} estaciones={len(stations)}")
for l in lines_out:
    n = sum(1 for s in stations if l["id"] in s["l"])
    print(f"  {l['id']:>2} {l['long'][:40]:<42} {n:>3} est  {l['color']}  "
          f"{l['depth']}m ({l.get('cotaMin')}-{l.get('cotaMax')})")
