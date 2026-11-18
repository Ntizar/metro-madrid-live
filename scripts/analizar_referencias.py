"""Mide los modelos de referencia (otras ciudades) para sacar de ellos lo que sí
se puede copiar: cuántos niveles tiene un transbordo real y a qué distancia
vertical, y qué altura libre hay sobre el andén.

    python scripts/analizar_referencias.py
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analizar_glb import leer_glb, recolectar

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(RAIZ, "referencias")


def niveles(ys, paso=0.5):
    """cotas donde se acumula geometría horizontal: las losas de andén"""
    lo, hi = float(ys.min()), float(ys.max())
    if hi - lo < 2:
        return []
    cortes = np.arange(lo, hi + paso, paso)
    hist, bordes = np.histogram(ys, bins=cortes)
    # suavizado de 3 y picos locales por encima de la media
    suave = np.convolve(hist, [0.25, 0.5, 0.25], mode="same")
    umbral = suave.mean() * 1.35
    picos = []
    for i in range(1, len(suave) - 1):
        if suave[i] >= umbral and suave[i] >= suave[i - 1] and suave[i] >= suave[i + 1]:
            cotas = bordes[i]
            if not picos or cotas - picos[-1] > 3.0:      # separación mínima 3 m
                picos.append(float(cotas))
    return picos


def main():
    filas = []
    for f in sorted(os.listdir(REF)):
        if not f.endswith(".glb"):
            continue
        try:
            gltf, binario = leer_glb(os.path.join(REF, f))
            pts = recolectar(gltf, binario)
        except Exception as e:
            print(f"!! {f}: {e}")
            continue
        if not pts:
            continue
        a = np.array(pts)
        ys = a[:, 1]
        pisos = niveles(ys)
        # hueco entre el suelo y la losa más alta: altura libre aproximada
        alto = float(ys.max() - ys.min())
        filas.append({
            "modelo": f[:-4],
            "huella_m": round(float(np.ptp(a[:, 0])), 1),
            "fondo_m": round(float(np.ptp(a[:, 2])), 1),
            "alto_m": round(alto, 1),
            "niveles": len(pisos),
            "separacion_m": [round(b - a_, 1) for a_, b in zip(pisos, pisos[1:])],
            "vertices": len(pts),
        })
        r = filas[-1]
        print(f"{r['modelo']:22s} {r['huella_m']:6.0f} x {r['fondo_m']:6.0f} m  "
              f"alto {r['alto_m']:5.1f}  niveles {r['niveles']}  "
              f"separación {r['separacion_m']}")

    if filas:
        sep = [s for r in filas for s in r["separacion_m"]]
        nv = [r["niveles"] for r in filas]
        print(f"\n{len(filas)} modelos · niveles: media {np.mean(nv):.1f}, "
              f"máx {max(nv)} · separación vertical media "
              f"{np.mean(sep) if sep else 0:.1f} m")
        json.dump(filas, open(os.path.join(RAIZ, "data", "referencias_ciudades.json"), "w",
                              encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
