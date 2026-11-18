#!/usr/bin/env python3
"""Comprueba que cada vía pasa por la cota de su estación.

Regla del visor: el andén de una estación y TODAS las vías que la cruzan están
a la misma cota (la media de las profundidades de sus líneas, redondeada a medio
metro); la vía interpola entre cotas de estación a lo largo del trazado.

Comprueba, sobre data/metro.json, el desajuste vertical entre cada vía y el
andén de cada estación que sirve. Sale 0 si ningún desajuste supera 0,5 m.
"""
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(BASE, "..", "data", "metro.json")
TOL = 0.5          # m de desajuste admitido
CERCA = 300.0      # m: distancia máxima de la estación a su trazado


def hav(a, b):
    R = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dla, dlo = la2 - la1, lo2 - lo1
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def proyeccion(st, sh):
    """(distancia en m, s en m) de la estación al trazado, sobre el segmento más cercano."""
    la0 = math.radians(st[0])
    kx = 111320.0 * math.cos(la0)
    ky = 111320.0
    px, py = st[1] * kx, st[0] * ky
    pts, cum = sh["pts"], sh["cum"]
    mejor = (1e18, 0.0)
    for j in range(len(pts) - 1):
        ax, ay = pts[j][1] * kx, pts[j][0] * ky
        bx, by = pts[j + 1][1] * kx, pts[j + 1][0] * ky
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        cx, cy = ax + t * dx, ay + t * dy
        dist = math.hypot(px - cx, py - cy)
        if dist < mejor[0]:
            mejor = (dist, cum[j] + t * (cum[j + 1] - cum[j]))
    return mejor


def cota_en(pares, s):
    """Cota interpolada en la distancia s (m) sobre el trazado."""
    if s <= pares[0][0]:
        return pares[0][1]
    if s >= pares[-1][0]:
        return pares[-1][1]
    lo, hi = 0, len(pares) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if pares[mid][0] <= s:
            lo = mid
        else:
            hi = mid
    s0, c0 = pares[lo]
    s1, c1 = pares[hi]
    if s1 == s0:
        return c1
    return c0 + (c1 - c0) * (s - s0) / (s1 - s0)


def main():
    d = json.load(open(DATOS, encoding="utf-8"))
    lineas = {l["id"]: l for l in d["lines"]}
    shapes = d["shapes"]

    perfiles = {int(k): v for k, v in (d.get("perfiles") or {}).items()}
    shapes_de = {}
    for p in d["patterns"]:
        shapes_de.setdefault(p["l"], set()).add(p["s"])
    if not perfiles:
        print("FALLO: metro.json no trae perfiles de cota; regenera con build_datos.py")
        return 1

    errores = []
    sin_cota = [s["n"] for s in d["stations"] if "cota" not in s]
    max_gap, max_gap_txt = 0.0, "-"
    revisados = 0
    for st in d["stations"]:
        # regla anterior (referencia): andén a la cota de la línea más profunda
        cota = st.get("cota")
        if cota is None:
            cota = max(lineas[l]["depth"] for l in st["l"])
        for lid in st["l"]:
            mejor = None
            for si in shapes_de.get(lid, ()):
                pares = perfiles.get(si)
                if not pares:
                    continue
                dist, s = proyeccion((st["lat"], st["lon"]), shapes[si])
                if mejor is None or dist < mejor[0]:
                    mejor = (dist, pares, s)
            if mejor is None or mejor[0] > CERCA:
                errores.append(f"{st['n']} (L{lid}): sin trazado a menos de {CERCA:.0f} m")
                continue
            dist, pares, s = mejor
            y_via = cota_en(pares, s)
            gap = abs(y_via - cota)
            revisados += 1
            if gap > max_gap:
                max_gap, max_gap_txt = gap, f"{st['n']} (L{lid}): vía {y_via:.1f} m, andén {cota:.1f} m"
            if gap > TOL:
                errores.append(f"{st['n']} (L{lid}): vía {y_via:.1f} m vs andén {cota:.1f} m ({gap:.1f} m)")

    if sin_cota:
        errores.append(f"{len(sin_cota)} estaciones sin cota: {', '.join(sin_cota[:5])}")

    print(f"estaciones={len(d['stations'])} pares estacion-linea={revisados} "
          f"perfiles={len(perfiles)}")
    print(f"desajuste máximo={max_gap:.2f} m ({max_gap_txt})")
    if errores:
        print(f"FALLO: {len(errores)} desajustes")
        for e in errores[:12]:
            print("  -", e)
        return 1
    print("OK: todas las vías pasan por la cota de su andén")
    return 0


if __name__ == "__main__":
    sys.exit(main())
