"""Ancla los 240 modelos reales al catálogo funcional (r2).

Mejoras v2 (tras auditoría en navegador):
· Si el GLB lleva piezas marcadas por línea (L1_, L11_, …), cada grupo se ancla
  al andén de SU línea; las piezas comunes (vestíbulo, pasajes) van al del grupo mayor.
· Modelo RÍGIDO: sin estiramiento vertical. El andén cae a la cota de railhead del
  catálogo y el pozo hasta la calle lo dibuja el visor (comunica la salida sin
  deformar la geometría).
· Emparejamiento: catalogue_ids ↔ station_ids (sNNN), respaldo por nombre.
"""
import json
import math
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hornear import glb_a_triangulos, normaliza, escribir_binario

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRADA = os.environ.get("METRO_MODELO", r"C:/Users/d_ant/AppData/Local/hermes/cache/scratch/mmodo/modelo.json")
DATOS = os.path.join(RAIZ, "datos")

PAT_LINEA = re.compile(r"^L(\d{1,2}|R)[_\-]", re.IGNORECASE)


def grupos_de_linea(piezas):
    grupos = {}
    comunes = []
    for pz in piezas:
        nombre = (pz[3] or "").strip() if len(pz) > 3 else ""
        m = PAT_LINEA.match(nombre)
        if m:
            grupos.setdefault(m.group(1).upper(), []).append(pz)
        else:
            comunes.append(pz)
    return grupos, comunes


def pca_planta(todos):
    dxs = todos[:, 0] - todos[:, 0].mean()
    dzs = todos[:, 2] - todos[:, 2].mean()
    w, v = np.linalg.eigh(np.cov(np.vstack([dxs, dzs])))
    u = v[:, int(np.argmax(w))]
    return math.atan2(u[1], u[0])


def nivel_anden(todos):
    return float(np.percentile(todos[:, 1], 6))


def rumbo_path(path):
    p = np.asarray(path, dtype=np.float64)
    a, b = p[0], p[-1]
    return math.atan2(b[2] - a[2], b[0] - a[0])


def dif180(x):
    while x > math.pi / 2:
        x -= math.pi
    while x < -math.pi / 2:
        x += math.pi
    return x


def main():
    md = json.load(open(ENTRADA, encoding="utf-8"))
    E0, N0 = md["origin_epsg25830"]
    por_scode = {}
    for st in md["stations"]:
        for c in (st.get("catalogue_ids") or []):
            por_scode.setdefault(str(c), []).append(st)
    por_nombre = {}
    for st in md["stations"]:
        por_nombre.setdefault(normaliza(st["name"]), []).append(st)

    meta = json.load(open(os.path.join(DATOS, "estaciones.json"), encoding="utf-8"))
    pos_t, col_t, idx_t = [], [], []
    cabecera, base_v, base_i = [], 0, 0
    sin_par, giros, grupos_total = [], [], 0

    for m in sorted(meta, key=lambda x: x["id"]):
        ruta = os.path.join(DATOS, "estaciones", m["id"] + ".glb")
        if not os.path.exists(ruta):
            continue
        piezas = glb_a_triangulos(ruta)
        if not piezas:
            continue

        cands = []
        for sid in m["station_ids"]:
            for st in por_scode.get(str(sid), []):
                if st not in cands:
                    cands.append(st)
        if not cands and m["estaciones"]:
            cands = por_nombre.get(normaliza(m["estaciones"]), [])

        grupos, comunes = grupos_de_linea(piezas)
        if cands:
            lineas_cat = {str(p.get("line", "")).upper() for c2 in cands for p in c2["ports"]}
            for ref in list(grupos):
                if ref not in lineas_cat and len(grupos) > 1:
                    comunes.extend(grupos.pop(ref))
        else:
            sin_par.append(m["estaciones"])

        lotes = []
        if cands:
            for ref, ps in sorted(grupos.items(), key=lambda kv: -sum(len(p2[0]) for p2 in kv[1])):
                todos_g = np.vstack([pz[0] for pz in ps])
                ang_propio = pca_planta(todos_g)
                mejor = None
                for st in cands:
                    for p in st["ports"]:
                        if str(p.get("line", "")).upper() != ref:
                            continue
                        path = p.get("platform_path_xyz_m")
                        if not path or len(path) < 2:
                            continue
                        r = rumbo_path(path)
                        d = abs(((r - ang_propio + math.pi / 2) % math.pi) - math.pi / 2)
                        if mejor is None or d < mejor[0]:
                            mejor = (d, st, p, r)
                if mejor:
                    lotes.append((ps, mejor[2], mejor[1], mejor[3]))
                    giros.append(abs(math.degrees(dif180(mejor[3] - ang_propio))))
            if comunes and lotes:
                lotes.append((comunes, lotes[0][1], lotes[0][2], lotes[0][3]))
            elif comunes:
                todos = np.vstack([pz[0] for pz in comunes])
                ang_propio = pca_planta(todos)
                mejor = None
                for st in cands:
                    for p in st["ports"]:
                        path = p.get("platform_path_xyz_m")
                        if not path or len(path) < 2:
                            continue
                        r = rumbo_path(path)
                        d = abs(((r - ang_propio + math.pi / 2) % math.pi) - math.pi / 2)
                        if mejor is None or d < mejor[0]:
                            mejor = (d, st, p, r)
                if mejor:
                    lotes.append((comunes, mejor[2], mejor[1], mejor[3]))
                    giros.append(abs(math.degrees(dif180(mejor[3] - ang_propio))))
                else:
                    sin_par.append(m["estaciones"])
                    lotes.append((comunes, None, None, None))
        else:
            lotes.append((piezas, None, None, None))

        if not lotes:
            lotes = [(piezas, None, None, None)]
            sin_par.append(m["estaciones"])
        v_ini_global, i_ini_global, pieza_ini = base_v, base_i, len(pos_t)
        grupos_colocados = 0
        for ps, port, st, rumbo_anden in lotes:
            todos = np.vstack([pz[0] for pz in ps])
            if port is not None:
                path = np.asarray(port["platform_path_xyz_m"])
                mid = path.mean(axis=0)
                ax, az = float(mid[0]), float(mid[2])
                rail_y = float(port["railhead_y"])
                grupos_colocados += 1
                anclado = True
            else:
                cx0 = m["E0"] - E0
                cz0 = -(m["N0"] - N0)
                ax, az = cx0 + float(todos[:, 0].mean()), cz0 + float(todos[:, 2].mean())
                rail_y = -20.0
                anclado = False
            cx = float(todos[:, 0].mean())
            cz = float(todos[:, 2].mean())
            plat = nivel_anden(todos)
            ang = dif180(rumbo_anden - pca_planta(todos)) if (rumbo_anden is not None and anclado) else 0.0
            ca, sa = math.cos(ang), math.sin(ang)
            for pz in ps:
                pos, idx, col = pz[0], pz[1], pz[2]
                p = pos.astype(np.float64).copy()
                dx, dz = p[:, 0] - cx, p[:, 2] - cz
                p[:, 0] = ax + dx * ca - dz * sa
                p[:, 2] = az + dx * sa + dz * ca
                p[:, 1] = rail_y + (p[:, 1] - plat)     # rígido: andén → railhead
                p = p.astype(np.float32)
                c = np.array(col, dtype=np.float32)
                base0 = np.array([0.60, 0.62, 0.66], dtype=np.float32)
                mezcla = c * 0.55 + base0 * 0.45
                colores = np.clip(np.repeat(mezcla[None, :], len(p), axis=0), 0, 1)
                pos_t.append(p)
                col_t.append((colores * 255).astype(np.uint8))
                idx_t.append((idx + base_v).astype(np.uint32))
                base_v += len(p)
                base_i += idx.size

        grupos_total += grupos_colocados
        if base_v == v_ini_global:
            print("SIN PIEZAS:", m["id"], "grupos:", len(grupos), "comunes:", len(comunes), "lotes:", len(lotes), "cands:", len(cands))
            sin_par.append(m["estaciones"])
            continue
        slice_t = pos_t[pieza_ini:]
        if not slice_t:
            sin_par.append(m["estaciones"])
            continue
        pq = np.vstack(slice_t)
        cc = pq.mean(axis=0)
        cabecera.append({
            "id": m["id"], "nombre": m["estaciones"], "code": (cands[0]["code"] if cands else None),
            "v0": v_ini_global, "vn": base_v - v_ini_global, "i0": i_ini_global, "in": base_i - i_ini_global,
            "c": [round(float(v), 1) for v in cc],
            "r": round(float(np.linalg.norm(pq[:, [0, 2]] - cc[[0, 2]], axis=1).max()), 1),
            "tri": (base_i - i_ini_global) // 3,
            "grupos": grupos_colocados,
            "pozo": [round(float(cc[0]), 1), round(float(cc[2]), 1)],
            "pozo_y": round(float(np.percentile(pq[:, 1], 98)), 1),
        })

    pos = np.vstack(pos_t)
    col = np.vstack(col_t)
    idx = np.concatenate(idx_t)

    def med(v):
        return round(float(np.median(v)), 1) if v else None

    cab = {
        "origen": {"E": E0, "N": N0},
        "datum": md.get("vertical_datum"),
        "estaciones": cabecera,
        "vertices": int(len(pos)), "triangulos": int(len(idx)),
        "sin_par": sin_par,
        "registro": {
            "criterio": "anclaje por grupos de línea al andén del catálogo; modelo rígido; pozo hasta la calle",
            "grupos_colocados": grupos_total,
            "giro_mediano_deg": med(giros),
            "sin_emparejar": len(sin_par),
        },
    }
    escribir_binario(os.path.join(DATOS, "estaciones.bin"),
                     json.dumps(cab, ensure_ascii=False).encode("utf-8"),
                     [pos.astype(np.float32).tobytes(), col.tobytes(), idx.astype(np.uint32).tobytes()])
    print(f"  emparejados {len(cabecera) - len(sin_par)}/{len(cabecera)} · grupos de línea colocados {grupos_total} · "
          f"giro mediano {cab['registro']['giro_mediano_deg']}°")
    print(f"  {len(pos)} vert · {len(idx)} tri · {os.path.getsize(os.path.join(DATOS, 'estaciones.bin'))/1e6:.2f} MB")
    if sin_par:
        print("  sin emparejar:", ", ".join(sin_par[:12]))


if __name__ == "__main__":
    main()
