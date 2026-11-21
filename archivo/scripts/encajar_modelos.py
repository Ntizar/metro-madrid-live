"""Encaja cada modelo 3D sobre los túneles reales: giro y desplazamiento.

Correlación cruzada por FFT entre la máscara de vías del modelo y la máscara de
túneles reales. Da de golpe el mejor desplazamiento para cada giro; se barren
los giros de 2 en 2 grados y se afina a 1 grado y 2 m en la ventana mejor.

Salida: data/modelos3d.json con ang, dx, dy y encaje de cada modelo.

    python scripts/encajar_modelos.py
"""
import json
import math
import os

import numpy as np

from ajustar_glb_util import CELDA, LADO, tuneles, vertices_via
from analizar_glb import GLB

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(RAIZ, "data", "modelos3d.json")


def rejilla(nube, celda=CELDA, lado=LADO):
    m = np.zeros((lado, lado), dtype=np.float32)
    if len(nube) == 0:
        return m
    cx = np.round(nube[:, 0] / celda).astype(np.int32) + lado // 2
    cy = np.round(nube[:, 1] / celda).astype(np.int32) + lado // 2
    ok = (cx >= 0) & (cx < lado) & (cy >= 0) & (cy < lado)
    m[cy[ok], cx[ok]] = 1.0
    return m


def dilatar(m, n=1):
    for _ in range(n):
        m = np.maximum.reduce([m, np.roll(m, 1, 0), np.roll(m, -1, 0),
                               np.roll(m, 1, 1), np.roll(m, -1, 1)])
    return m


def correlacion(a, b):
    """mapa de correlación cruzada, centrado como en convolución 'same'"""
    fa = np.fft.rfft2(a)
    fb = np.fft.rfft2(b)
    c = np.fft.irfft2(fa * np.conj(fb), s=a.shape)
    return np.fft.fftshift(c)


def puntuar(m_mod, m_real_fft_prev=None, m_real=None):
    c = correlacion(m_mod, m_real)
    i = np.unravel_index(np.argmax(c), c.shape)
    return float(c[i] / max(1e-6, m_mod.sum())), (i[1] - LADO // 2) * CELDA, (i[0] - LADO // 2) * CELDA


def main():
    metro = json.load(open(os.path.join(RAIZ, "data", "metro.json"), encoding="utf-8"))
    info = json.load(open(SALIDA, encoding="utf-8"))
    estaciones = {e["id"]: e for e in metro["stations"]}

    for modelo, m in info.items():
        if not m.get("estacion"):
            continue
        est = estaciones.get(m["estacion"])
        if not est:
            continue
        nube = vertices_via(os.path.join(GLB, f"{modelo}.glb"), metro["lines"])
        real = tuneles(metro, est)
        if len(nube) == 0 or len(real) == 0:
            print(f"!! {modelo}: sin datos")
            continue
        m_real = dilatar(rejilla(real), 3)      # túnel de ~12 m de ancho

        mejor = (-1.0, 0.0, 0.0, 0.0)
        for ang in range(0, 180, 2):
            a = math.radians(ang)
            c, s = math.cos(a), math.sin(a)
            girada = np.column_stack([nube[:, 0] * c - nube[:, 1] * s,
                                      nube[:, 0] * s + nube[:, 1] * c])
            m_mod = dilatar(rejilla(girada), 1)
            sc, dx, dy = puntuar(m_mod, m_real=m_real)
            if sc > mejor[0]:
                mejor = (sc, float(ang), dx, dy)

        # afinar: giro de grado en grado y desplazamiento a 2 m
        ang0, dx0, dy0 = mejor[1], mejor[2], mejor[3]
        fino = mejor
        for ang in [ang0 + d for d in (-1.5, -1, -0.5, 0, 0.5, 1, 1.5)]:
            a = math.radians(ang)
            c, s = math.cos(a), math.sin(a)
            for ox in (-4, -2, 0, 2, 4):
                for oy in (-4, -2, 0, 2, 4):
                    girada = np.column_stack([nube[:, 0] * c - nube[:, 1] * s + dx0 + ox,
                                              nube[:, 0] * s + nube[:, 1] * c + dy0 + oy])
                    m_mod = dilatar(rejilla(girada), 1)
                    inter = float((m_mod * m_real).sum())
                    union = float(((m_mod + m_real) > 0).sum())
                    sc = inter / max(1.0, union)
                    if sc > fino[0]:
                        fino = (sc, float(ang), dx0 + ox, dy0 + oy)

        m.update({
            "ang": round(fino[1] % 360, 1),
            "dx": round(fino[2], 1),
            "dy": round(fino[3], 1),
            "encaje": round(fino[0], 3),
        })
        print(f"{modelo:16s} giro {fino[1]:6.1f}°  desplazamiento ({fino[2]:+6.1f}, {fino[3]:+6.1f}) m"
              f"  encaje {fino[0]*100:5.1f}%   [antes {mejor[0]*100:4.1f}% giro {mejor[1]:.0f}°]")

    json.dump(info, open(SALIDA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
