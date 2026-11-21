"""Geodesia mínima sin dependencias: WGS84 <-> UTM 30N (ETRS89) y teselas web.

Zona 30 (meridiano central -3 grados) cubre toda la Comunidad de Madrid.
Diferencia ETRS89/WGS84 < 1 m: despreciable para el gemelo.
"""
import math

A = 6378137.0
F = 1.0 / 298.257223563
E2 = F * (2.0 - F)
EP2 = E2 / (1.0 - E2)
K0 = 0.9996
LON0 = math.radians(-3.0)   # zona 30


def latlon_a_utm(lat, lon):
    """WGS84 lat/lon (grados) -> E, N (metros, UTM 30N)."""
    phi = math.radians(lat)
    lam = math.radians(lon)
    N = A / math.sqrt(1.0 - E2 * math.sin(phi) ** 2)
    T = math.tan(phi) ** 2
    C = EP2 * math.cos(phi) ** 2
    Aa = math.cos(phi) * (lam - LON0)
    M = A * ((1 - E2 / 4 - 3 * E2 ** 2 / 64 - 5 * E2 ** 3 / 256) * phi
             - (3 * E2 / 8 + 3 * E2 ** 2 / 32 + 45 * E2 ** 3 / 1024) * math.sin(2 * phi)
             + (15 * E2 ** 2 / 256 + 45 * E2 ** 3 / 1024) * math.sin(4 * phi)
             - (35 * E2 ** 3 / 3072) * math.sin(6 * phi))
    E = K0 * N * (Aa + (1 - T + C) * Aa ** 3 / 6
                  + (5 - 18 * T + T ** 2 + 72 * C - 58 * EP2) * Aa ** 5 / 120) + 500000.0
    Nn = K0 * (M + N * math.tan(phi) * (Aa ** 2 / 2
                + (5 - T + 9 * C + 4 * C ** 2) * Aa ** 4 / 24
                + (61 - 58 * T + T ** 2 + 600 * C - 330 * EP2) * Aa ** 6 / 720))
    if lat < 0:
        Nn += 10000000.0
    return E, Nn


def utm_a_latlon(E, N):
    """E, N (UTM 30N) -> lat, lon en grados."""
    x = E - 500000.0
    y = N
    M = y / K0
    mu = M / (A * (1 - E2 / 4 - 3 * E2 ** 2 / 64 - 5 * E2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - E2)) / (1 + math.sqrt(1 - E2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    sin1, cos1, tan1 = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    C1 = EP2 * cos1 ** 2
    T1 = tan1 ** 2
    N1 = A / math.sqrt(1 - E2 * sin1 ** 2)
    R1 = A * (1 - E2) / (1 - E2 * sin1 ** 2) ** 1.5
    D = x / (N1 * K0)
    lat = phi1 - (N1 * tan1 / R1) * (D ** 2 / 2
        - (5 + 3 * T1 + 10 * C1 - 4 * C1 ** 2 - 9 * EP2) * D ** 4 / 24
        + (61 + 90 * T1 + 298 * C1 + 45 * T1 ** 2 - 252 * EP2 - 3 * C1 ** 2) * D ** 6 / 720)
    lon = LON0 + (D - (1 + 2 * T1 + C1) * D ** 3 / 6
        + (5 - 2 * C1 + 28 * T1 - 3 * C1 ** 2 + 8 * EP2 + 24 * T1 ** 2) * D ** 5 / 120) / cos1
    return math.degrees(lat), math.degrees(lon)


# ---- Web Mercator (para teselas de DEM y ortofoto) ----
def latlon_a_tesela(lat, lon, z):
    """lat/lon -> tesela x,y (flotante) en esquema Web Mercator (XYZ)."""
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def tesela_a_latlon(x, y, z):
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


def resolucion_m(z, lat):
    """Metros por píxel de una tesela de 256 px a esa latitud."""
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** z)


if __name__ == "__main__":
    # Sol, Puerta del Sol (Madrid)
    lat, lon = 40.416775, -3.703790
    E, N = latlon_a_utm(lat, lon)
    print(f"Sol -> E={E:.2f} N={N:.2f}")
    lat2, lon2 = utm_a_latlon(E, N)
    print(f"vuelta -> {lat2:.7f} {lon2:.7f}  error={(abs(lat2-lat)*111320):.4f} m")
    # Referencias conocidas (ETRS89/UTM30N publicadas)
    for nombre, la, lo, e_ref, n_ref in [
        ("Sol", 40.416775, -3.703790, 440448.0, 4474253.0),
        ("Abrantes", None, None, 438229.92, 4470310.27),
    ]:
        if la is None:
            la, lo = utm_a_latlon(e_ref, n_ref)
        e, n = latlon_a_utm(la, lo)
        if e_ref:
            print(f"{nombre}: calculado {e:.0f},{n:.0f} ref {e_ref:.0f},{n_ref:.0f} dif {abs(e-e_ref):.1f},{abs(n-n_ref):.1f} m")
    print("resolucion z13 madrid:", round(resolucion_m(13, 40.42), 2), "m/px")
    print("resolucion z15 madrid:", round(resolucion_m(15, 40.42), 2), "m/px")
