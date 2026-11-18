"""Asigna a cada estación su modelo de Blender y los datos para colocarlo.

Lee  data/metro.json (estaciones y líneas) y data/estaciones.json (etiquetas de
stations.albertguillaumes.cat) y data/estaciones_osm.json (planta y ángulo).
Escribe data/estaciones_3d.json

Tipologías (blender/arquetipos.py):
  lateral      dos andenes laterales, lo más común
  central      andén central entre las dos vías
  paralelo     andenes paralelos con pasillo central
  tresbolillo  tres andenes, el central compartido
  dos_niveles  transbordo en dos cotas con vestíbulo
  elevada      en superficie, con marquesina
"""
import json
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LARGO = {"estrecho": 90, "ancho": 110, "ramal": 60}


def tipo_de(st, tags):
    t = " ".join(tags).lower()
    if "elevada" in t or "viaducto" in t:
        return "elevada"
    if "tresbolillo" in t or "barcelona" in t:
        return "tresbolillo"
    if "transbordo cruzado" in t or len(st["l"]) >= 3:
        return "dos_niveles"
    if "andenes paralelos" in t or "paso inferior" in t or len(st["l"]) == 2:
        return "paralelo"
    if len(st["l"]) == 1 and "profunda" in t:
        return "central"
    return "lateral"


def main():
    metro = json.load(open(os.path.join(RAIZ, "data", "metro.json"), encoding="utf-8"))
    fichas = json.load(open(os.path.join(RAIZ, "data", "estaciones.json"), encoding="utf-8"))
    osm = json.load(open(os.path.join(RAIZ, "data", "estaciones_osm.json"), encoding="utf-8"))

    salida = {}
    cuenta = {}
    for st in metro["stations"]:
        tags = (fichas.get(st["id"]) or {}).get("tags") or []
        tipo = tipo_de(st, tags)
        perf = "ramal" if "R" in st["l"] else (
            "ancho" if all(x.isdigit() and int(x) >= 6 for x in st["l"] if x != "R") else "estrecho")
        h = osm.get(st["id"]) or {}
        anden = (h.get("andenes") or [{}])[0]
        salida[st["id"]] = {
            "tipo": tipo,
            "largo": LARGO[perf],
            "lat": st["lat"], "lon": st["lon"],
            "ang": anden.get("ang", 0.0),
            "prof": st.get("_prof") or 20,
            "l": st["l"],
        }
        cuenta[tipo] = cuenta.get(tipo, 0) + 1

    json.dump(salida, open(os.path.join(RAIZ, "data", "estaciones_3d.json"), "w",
                           encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("estaciones:", len(salida))
    for t, n in sorted(cuenta.items(), key=lambda x: -x[1]):
        print(f"  {t:12s} {n:3d}")


if __name__ == "__main__":
    main()
