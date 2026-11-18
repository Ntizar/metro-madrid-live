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

## Fichas de estación

Cada una de las 268 estaciones lleva su **esquema axonométrico de niveles, andenes y transbordos**
tomado de [stations.albertguillaumes.cat](http://stations.albertguillaumes.cat/), el proyecto de
Albert Guillaumes que dibuja estación a estación los metros de medio mundo. De ahí salen también
las etiquetas de cada ficha: profunda, elevada, andenes paralelos, transbordo cruzado, andén
tresbolillo, solución Barcelona, corredores largos…

Las 270 imágenes se sirven en local (`assets/esquemas/`, WebP 1000 px) porque el servidor original
va por HTTP y su certificado no cubre el subdominio: en una página HTTPS el navegador las bloquearía.
Se citan y enlazan en cada ficha. Si el autor prefiere que se enlacen en origen, se quitan en un minuto.

Los textos de «El metro, por dentro» (perfil estrecho 1–5 y Ramal, perfil ancho 6–12, 15–25 m de
profundidad, muros pantalla desde los 90, macrohubs de los 2000) son una adaptación al castellano
de la sección Madrid de ese mismo proyecto.

## Atribución

Datos: Consorcio Regional de Transportes de Madrid (GTFS) y © OpenStreetMap contributors.
Esquemas de estación: Albert Guillaumes, *Stations and transfers*.
Diseño: sistema Aurora de [Ntizar](https://github.com/Ntizar/Aurora).

Hecho con ❤️ por David Antizar
