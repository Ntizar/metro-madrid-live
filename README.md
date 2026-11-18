# Metro de Madrid bajo tierra

Réplica del efecto de [ScanPaname](https://x.com/hart_igann/status/2122756511952679249) para Madrid:
el plano del metro se levanta del suelo y cada línea aparece **a su profundidad**, con los trenes
moviéndose en el subsuelo. Diseño con el sistema **Aurora**.

## Qué es y qué no es

- **Datos de red**: GTFS oficial del CRTM (`feed_version 20250527`) — 13 líneas, 268 estaciones,
  trazados reales y frecuencias oficiales por franja horaria.
- **Trenes**: se calculan a partir de esas frecuencias y de la hora de Madrid. **No es telemetría en
  vivo**: el CRTM no publica posiciones en abierto sin clave.
- **Línea 3**: no viene en ese feed (sin servicio en el período del fichero). Su trazado se ha
  reconstruido con las 19 estaciones geocodificadas (OpenStreetMap/Nominatim) y tiempos estimados
  a partir del dato público de 34 min / 17,49 km. Aparece marcada como «reconstruida».
- **Profundidad**: no es un dato oficial. Cada línea tiene una profundidad estimada y la escala
  vertical está exagerada ×200 (a escala real, 30 m de túnel no se ven en 50 km de ciudad).

## Cómo se usa

- **Corte del terreno**: deja la superficie opaca o la atraviesa para ver el subsuelo.
- **Plano / Vuelo / Túnel**: tres encuadres.
- **Líneas**: enciende, apaga y aísla cada una.
- **Pincha una estación** para ver sus líneas y cuántos trenes tiene cerca.

## Estructura

```
scripts/build_datos.py   GTFS -> data/metro.json (simplifica shapes, calcula patrones)
data/metro.json          red + frecuencias, ~96 KB
assets/visor.js          Three.js: superficie, túneles, estaciones, trenes
assets/visor.css         lienzo y HUD (solo geometría; color y tipografía de Aurora)
index.html
```

Rebuild de datos:

```bash
python3 scripts/build_datos.py    # necesita data/gtfs/ (GTFS del CRTM)
```

## Atribución

Datos: Consorcio Regional de Transportes de Madrid (GTFS) y © OpenStreetMap contributors.
Diseño: sistema Aurora de [Ntizar](https://github.com/Ntizar/Aurora).

Hecho con ❤️ por David Antizar
