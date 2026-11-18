"""Huellas reales de las estaciones: planta, tamaño y orientación.

Uso:  python scripts/build_osm.py
Lee   data/fuentes/osm_andenes.json  (Overpass: railway=platform,
      public_transport=platform, building=train_station, railway=station)
      data/fuentes/osm_vias.json     (Overpass: railway=subway)
Escribe data/estaciones_osm.json

Prioridad:
 1. andén dibujado en OSM  -> se usa tal cual (tamaño y orientación reales)
 2. sin andén              -> se traza con la dirección de la vía más cercana,
                              largo estándar de la línea y ancho de 8 m
El campo "real" dice cuál es cuál, para que la UI no mienta.
"""
import json
import math
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUENTE = os.path.join(RAIZ, "data", "fuentes", "osm_andenes.json")
VIAS = os.path.join(RAIZ, "data", "fuentes", "osm_vias.json")
SALIDA = os.path.join(RAIZ, "data", "estaciones_osm.json")

RADIO = 260.0          # una huella y su estación no pueden estar más lejos
LARGO = {"estrecho": 90.0, "ancho": 110.0, "ramal": 60.0}
ANCHO = 8.0


def metros(a, b):
    dy = (a[0] - b[0]) * 111_320
    dx = (a[1] - b[1]) * 111_320 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def centroide(pts):
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def area_m2(pts):
    if len(pts) < 3:
        return 0.0
    lat0 = math.radians(centroide(pts)[0])
    xs = [p[1] * 111_320 * math.cos(lat0) for p in pts]
    ys = [p[0] * 111_320 for p in pts]
    s = 0.0
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        s += xs[i] * ys[j] - xs[j] * ys[i]
    return abs(s) / 2


def eje(pts):
    if len(pts) < 3:
        return (0.0, 0.0, 0.0)
    lat0 = math.radians(centroide(pts)[0])
    xs = [p[1] * 111_320 * math.cos(lat0) for p in pts]
    ys = [p[0] * 111_320 for p in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs) / len(xs)
    syy = sum((y - my) ** 2 for y in ys) / len(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / len(xs)
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
    ux, uy = math.cos(ang), math.sin(ang)
    pu = [x * ux + y * uy for x, y in zip(xs, ys)]
    pv = [-x * uy + y * ux for x, y in zip(xs, ys)]
    return (max(pu) - min(pu), max(pv) - min(pv), math.degrees(ang))


def rotar(c, largo, ancho, ang_deg):
    """rectángulo centrado en c, orientado ang_deg (grados, sentido del eje largo)"""
    a = math.radians(ang_deg)
    ca, sa = math.cos(a), math.sin(a)
    hl, ha = largo / 2, ancho / 2
    dl = hl / 111_320
    da = ha / (111_320 * math.cos(math.radians(c[0])))
    pts = []
    for sl, sa2 in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        # eje largo en el plano: mezcla de lat y lon según el ángulo
        dlat = (sl * dl) * sa + (sa2 * da) * ca
        dlon = (sl * dl) * ca - (sa2 * da) * sa
        pts.append([round(c[0] + dlat, 6), round(c[1] + dlon, 6)])
    return pts


def perfil_de(lineas):
    if "R" in lineas:
        return "ramal"
    if all(l.isdigit() and int(l) >= 6 for l in lineas if l != "R"):
        return "ancho"
    return "estrecho"


def main():
    raw = json.load(open(FUENTE, encoding="utf-8"))
    metro = json.load(open(os.path.join(RAIZ, "data", "metro.json"), encoding="utf-8"))
    estaciones = metro["stations"]

    # vías: puntos con su dirección local, para orientar los andenes sin dibujar
    vias = []
    if os.path.exists(VIAS):
        for e in json.load(open(VIAS, encoding="utf-8"))["elements"]:
            g = e.get("geometry") or []
            for a, b in zip(g, g[1:]):
                p, q = (a["lat"], a["lon"]), (b["lat"], b["lon"])
                ang = math.degrees(math.atan2(
                    (q[0] - p[0]) * 111_320,
                    (q[1] - p[1]) * 111_320 * math.cos(math.radians(p[0]))))
                vias.append((p, q, ang, (e.get("tags") or {}).get("ref", "")))
        print(f"segmentos de vía: {len(vias)}")

    # 1. huellas dibujadas
    huellas = []
    for e in raw["elements"]:
        g = e.get("geometry")
        if not g or len(g) < 3:
            continue
        t = e.get("tags", {})
        pts = [(p["lat"], p["lon"]) for p in g]
        if pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) < 3:
            continue
        tipo = "recinto" if (t.get("building") or t.get("railway") == "station") else "anden"
        ancho, alto, ang = eje(pts)
        huellas.append({
            "id": f"{e['type']}/{e['id']}", "tipo": tipo,
            "pts": pts, "c": centroide(pts), "area": round(area_m2(pts)),
            "largo": round(max(ancho, alto)), "ancho": round(min(ancho, alto)),
            "ang": round(ang, 1), "nombre": t.get("name") or "",
            "ref": t.get("ref") or "", "nivel": t.get("level") or "",
            "sub": t.get("location") == "underground" or t.get("tunnel") == "yes",
        })

    salida = {}
    for h in huellas:
        mejor, mejor_d = None, RADIO
        for st in estaciones:
            d = metros(h["c"], (st["lat"], st["lon"]))
            if d < mejor_d:
                mejor, mejor_d = st, d
        if not mejor:
            continue
        e = salida.setdefault(mejor["id"], {"n": mejor["n"], "recinto": None, "andenes": []})
        reg = {
            "pts": [[round(p[0], 6), round(p[1], 6)] for p in h["pts"]],
            "largo": h["largo"], "ancho": h["ancho"], "ang": h["ang"],
            "area": h["area"], "osm": h["id"], "nombre": h["nombre"],
            "ref": h["ref"], "nivel": h["nivel"], "sub": h["sub"], "real": True,
        }
        if h["tipo"] == "anden" and h["area"] < 250:
            continue   # trozo suelto, no un andén completo
        if h["tipo"] == "recinto":
            if not e["recinto"] or h["area"] > e["recinto"]["area"]:
                e["recinto"] = reg
        else:
            e["andenes"].append(reg)

    # 2. los que faltan: andén trazado sobre la vía real
    creados = 0
    for st in estaciones:
        e = salida.get(st["id"])
        if e and e["andenes"]:
            continue
        c = (st["lat"], st["lon"])
        cerca = sorted(((metros(c, ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)), p, q, ang, ref)
                        for p, q, ang, ref in vias), key=lambda x: x[0])[:1]
        if not cerca or cerca[0][0] > 420:
            continue
        _, p, q, ang, _ref = cerca[0]
        # el andén se centra en el punto de la vía más cercano a la estación
        t = ((c[0] - p[0]) * (q[0] - p[0]) + (c[1] - p[1]) * (q[1] - p[1])) / (
            (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 or 1)
        t = max(0.0, min(1.0, t))
        centro = (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)
        perf = perfil_de(st["l"])
        largo = LARGO[perf]
        reg = {
            "pts": rotar(centro, largo, ANCHO, ang),
            "largo": largo, "ancho": ANCHO, "ang": round(ang, 1),
            "area": round(largo * ANCHO), "osm": "", "nombre": st["n"],
            "ref": "", "nivel": "", "sub": True, "real": False,
        }
        if e:
            e["andenes"].append(reg)
        else:
            salida[st["id"]] = {"n": st["n"], "recinto": None, "andenes": [reg]}
        creados += 1

    con_anden = sum(1 for v in salida.values() if v["andenes"])
    reales = sum(1 for v in salida.values() if any(a["real"] for a in v["andenes"]))
    print(f"estaciones con andén: {con_anden}/{len(estaciones)} "
          f"({reales} con andén dibujado en OSM, {creados} trazados sobre la vía)")
    faltan = [s["n"] for s in estaciones if not salida.get(s["id"], {}).get("andenes")]
    if faltan:
        print(f"sin andén: {len(faltan)} -> {', '.join(faltan[:10])}")

    json.dump(salida, open(SALIDA, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"escrito {SALIDA} ({os.path.getsize(SALIDA)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
