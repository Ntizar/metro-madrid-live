# Metro de Madrid · gemelo digital

Visor 3D del Metro de Madrid: las **240 estaciones modeladas** del respaldo del 20-nov-2026, las **12 líneas + Ramal** del CRTM con sus ramas reales (MetroEste, Rivas, norte), el **Metro Ligero** y **Cercanías**, todo colocado sobre la **corteza del terreno medida con LiDAR** (497–873 m de cota absoluta) que se puede hacer semitransparente para ver el subsuelo.

**En vivo:** https://ntizar.github.io/metro-madrid-live/ · la versión clásica (planos por tipologías y las 268 fichas de estación) vive en [`/archivo/`](https://ntizar.github.io/metro-madrid-live/archivo/)

## Qué hay montado

| Pieza | Fuente | Cifra |
|---|---|---|
| Estaciones modeladas | 240 glTF del respaldo `METRO_LOTE_01..05` | 352.013 vértices · 408.103 triángulos · 14,1 MB de GLB |
| Anclaje geográfico | `colocacion_interpretada.json` (EPSG:25830) | desvío mediano **2,1 m** al punto medio de las dos vías · giro mediano 27° |
| Trazados | GTFS oficial del CRTM (`datos.crtm.es`) | 13 líneas de metro (29 tramos con ramas) + 3 de Metro Ligero + 11 de Cercanías |
| Terreno | DEM terrarium z13 (≈14,6 m/px) | 2.001 × 1.739 px · desnivel 375,9 m |
| Ortofoto | IGN PNOA WMTS `OI.OrthoimageCoverage` z13 | 1 MB JPEG |
| Tren | `SERIE_9000_ORIGINAL.glb` (6 coches) | 114,4 × 4,4 × 5,4 m · 75.748 triángulos · 16 circulando |

## Las tres decisiones que importan

1. **No hay que «pasar de Blender a Three.js»: los modelos ya son glTF 2.0.** El respaldo trae `.blend`, `.glb` y `.json` por estación. El `.glb` es exactamente lo que three.js carga, sin pérdida (el inventario declara un redondeo máximo de 1,9·10⁻⁶ unidades al pasar de float64 a float32). Blender solo haría falta para *editar* geometría, no para publicarla.

2. **Los 240 GLB se fusionan en un único binario.** `scripts/hornear.py` los parsea (chunks JSON+BIN, accessors, jerarquía de nodos, `baseColorFactor`) y los convierte a un solo `estaciones.bin` con cabecera JSON + posiciones float32 + colores uint8 + índices uint32, ya transformados al marco local. Resultado: **1 llamada de dibujo** para las 240 estaciones en lugar de 240.

3. **Datum vertical relativo a Sol.** El DEM viene en cota absoluta (660,5 m en la Puerta del Sol); los andenes, a −22 m. Sin corrección el subsuelo flotaba 650 m por debajo de la corteza. Ahora la cota 0 es el suelo de Sol y todo lo demás cuelga de ahí.

## Marco de coordenadas

```
x = E − 440.291,28   (Este, UTM 30N, metros)
z = −(N − 4.474.254,60)   (Norte invertido: z crece hacia el sur)
y = cota relativa a la Puerta del Sol (metros)
```

Conversión WGS84 ↔ UTM 30N implementada a mano en `scripts/geo.py` (sin pyproj): ida y vuelta con error de 0,1 mm.

## Cómo se regenera

```bash
python3 scripts/hornear.py lineas     # GTFS → datos/mundo.json
python3 scripts/hornear.py estaciones # 240 GLB → datos/estaciones.bin (+ tren.bin)
python3 scripts/hornear.py terreno    # DEM + PNOA → datos/terreno.png, ortofoto.jpg, terreno.json
python3 -m http.server 8777           # y abrir http://127.0.0.1:8777
```

Requiere `numpy` y `Pillow`. Descarga 182 teselas de elevación y 182 de ortofoto (≈2 min).

## Límites, dichos como son

- **Los modelos son esquemáticos, no arquitectónicos.** El propio respaldo los clasifica `RESPALDO_ESQUEMATICO_SIN_CERTIFICAR`: son trazas interpretadas desde croquis de 2D (crédito de origen: Albert Guillaumes). Tienen plataformas, vestíbulo y escala aproximada, no fachadas ni detalle constructivo. La cifra lo dice: 382 triángulos de mediana por estación.
- **La profundidad es un parámetro, no un dato.** Ningún paquete trae cota de andén (`vertical_datum: null`, `physical_elevation_m: null`). El deslizador mueve túneles y estaciones entre 0 y 60 m; por defecto 22 m. Para poner la profundidad real hace falta el levantamiento de cada estación.
- **El anclaje es interpretado**, no topográfico: el propio JSON dice `APPROXIMATE_INTERPRETED_NOT_SURVEYED`. El test de la mediana (2,6 m) mide coherencia con el eje del CRTM, no exactitud absoluta.
- **El GTFS del CRTM no trae la línea 3** (cero viajes, cero shapes, cierre por obras). Su eje se reconstruye uniendo sus 18 paradas oficiales en orden (`TRAZAS_MANUALES` en el hornador) y así se declara en `mundo.json`.
- **La corteza es el DEM a 14,6 m/px**: sirve para leer dónde está cada cosa y a qué cota, no para medir rasantes.

## Siguientes pasos naturales

- Paradas de autobús: los GTFS de EMT (21 MB) e interurbanos ya están descargados; falta hornear sus 10 MB de `shapes.txt`.
- Profundidad por estación y por túnel cuando exista dato.
- Etiquetas de estación y buscador.
- GTFS-RT (posiciones reales de trenes) en lugar del movimiento ilustrativo.

## Fuentes y licencias

- Modelos de estación: respaldo propio del 20-nov-2026, reconstrucción interpretativa desde croquis de **Albert Guillaumes** (`estacions.albertguillaumes.cat`).
- Red y horarios: **CRTM** — datos abiertos, `https://www.crtm.es/licencia-de-uso` (CC-BY-SA).
- Elevación: AWS terrain-tiles (terrarium), z13.
- Ortofoto: **IGN** PNOA, WMTS `OI.OrthoimageCoverage`.
- Tren Serie 9000: modelo de trabajo del 20-nov-2026, en revisión.
- Escena: three.js r170 · interfaz: Aurora v10.10.0.

Hecho con ❤️ por David Antizar


## Fuentes, método y límites

Todo el detalle (de dónde sale cada pieza, cómo funciona el encaje, qué NO es exacto) está en el
botón **«El proyecto»** del propio visor, y en `scripts/hornear.py`, que es la definición ejecutable
de las reglas:

1. las trazas del GTFS van **por dirección** — son los dos carriles, separados 4,4–6,2 m;
2. cada estación **define su cota**: su vestíbulo se coloca a nivel de la calle del terreno y su
   andén a la profundidad que dicta el propio modelo (mediana 22 m);
3. el túnel —traza, tubo y tren comparten la MISMA polilínea— pasa 2,2 m por debajo de cada andén
   y su altura se interpola entre estaciones a lo largo del carril;
4. hay una **corrección global** del desfase horizontal de los anclajes contra la red real del CRTM
   (la mediana de los 240 desvíos), porque Madrid manda sobre los croquis.

`python3 scripts/hornear.py estaciones --factor=0.7` regenera el binario con todos los andenes al
70 % de su profundidad nominal. Requiere las cotas de `terreno.png` (hay que hornear el terreno antes).
