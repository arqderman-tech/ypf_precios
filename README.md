# Mapa de precios YPF

Mapa web con los precios de nafta y diésel de ~1.300 estaciones YPF. Un GitHub Action actualiza los precios **todos los días a las 07:11 (hora Argentina)** y republica el mapa en GitHub Pages.

## Puesta en marcha
1. Creá un repo en GitHub y subí todo esto a la rama `main`.
2. **Settings → Pages → Source: GitHub Actions**.
3. **Actions → Actualizar precios y publicar mapa → Run workflow** para probar. El mapa queda en `https://TU_USUARIO.github.io/NOMBRE_REPO/`.

## Cómo funciona
- `data/estaciones.json`: base de estaciones (ubicación + últimos precios). Se actualiza sola.
- `scripts/actualizar.py`: consulta cada estación, guarda precios, genera `docs/data.json` y suma una fila diaria a `data/historial.csv` (mín, mediana, promedio, máx por producto).
- `docs/index.html`: el mapa. Lee `docs/data.json`.
- `docs/estacion.html`: dashboard de una estación (evolución por período, desglose de impuestos, puesto vs país/provincia/localidad, comparador de estaciones, costo de tanque y facturación mensual estimada por combustible, con el historial mes a mes). Se abre desde el popup del mapa y lee `docs/data.json` + `docs/hist/NN.json` + `docs/volumen.json`.
- `docs/argentina.html`: panorama nacional (KPIs, evolución de la mediana con banda mín–máx, ranking y matriz de provincias, distribución de precios). Se abre desde el botón del panel del mapa y lee `docs/data.json` + `docs/serie.json`.
- `docs/ranking.html`: dashboard de ventas (KPIs, mezcla por producto, ranking de estaciones ordenable por facturación o por volumen, filtros por provincia y localidad, y comparador de hasta 5 estaciones con su evolución de 12 meses). Se abre desde el panel del mapa y lee `docs/data.json` + `docs/volumen.json`.
- `docs/serie.json`: series nacionales (mín, mediana, promedio, máx por producto y día), generadas desde `data/historial.csv`.
- `docs/volumen.json`: volumen despachado y precio surtidor mes a mes por boca (fuente oficial: Secretaría de Energía, Res. 1104, canal “Al público”), cruzado con las estaciones del mapa por proximidad geográfica (haversine, ≤250 m). Guarda el histórico completo de períodos. Lo arma `scripts/volumen.py`, que **corre todos los días** pero solo baja el CSV cuando cambió el recurso oficial (≈1 vez por mes): así engancha el mes nuevo apenas se publica y reintenta a diario mientras no esté. El CSV pesa ~134 MB y **nunca se guarda en el repo**: se baja a una carpeta temporal, se extrae solo lo que interesa (volumen + precio por boca/mes) y se borra. La ficha y el ranking multiplican volumen × precio surtidor para estimar facturación. Solo naftas y gasoil (el volumen de GNC no se usa). Se descartan los meses con volumen atípico (errores de carga del dataset oficial: un mes disparado respecto de la mediana de la misma boca).
- Los precios salen de la API de transparencia fiscal de YPF, consultando solo las estaciones que ya están en la base (no escanea todo el rango).
- Si más del 30% de las consultas fallan, no se pisa nada. Si falla una estación suelta, conserva su precio anterior.

## Filtro de datos inválidos
Si el precio de Nafta Súper de una estación difiere más de 22% de la mediana nacional, se descarta la estación completa (se asume que sus precios no están vigentes). Queda registrada en `data/excluidas.csv`; el umbral es `MAX_DESVIO_NS` en `scripts/actualizar.py`.

## Historial de precios
`docs/hist/NN.json` guarda el historial de cada estación y combustible, repartido en partes por los 2 primeros dígitos del APIES (~15 archivos). Se anota el precio solo cuando cambia (`[[fecha, precio], ...]`), por lo que cada día queda cubierto sin repetir datos. El mapa carga solo la parte de la estación que tocás. Si alguna parte supera 40 MB el script avisa (GitHub bloquea archivos de 100 MB).

## Actualización mensual del volumen (automática)
El dataset de Energía se republica una vez por mes y el CSV pesa ~134 MB (más de lo que GitHub acepta por archivo, y no interesa versionarlo). Por eso:
- `scripts/volumen.py` consulta la API de datos abiertos y compara el `last_modified` del recurso contra el guardado en `docs/volumen.json`. Si no cambió, no baja nada y termina en segundos.
- Si cambió, baja el CSV y el registro de coordenadas a una carpeta temporal, se queda solo con las bocas YPF del canal “Al público”, las cruza con el mapa y escribe **únicamente** los datos que sirven (volumen y precio surtidor por boca y mes), con el histórico completo. Los CSV temporales se borran.
- Como el workflow corre todos los días, alcanza con que el mes nuevo aparezca en cualquier momento: se detecta en la corrida siguiente y, si todavía no está, se reintenta al día siguiente. No hay que tocar nada.
- Si falla la descarga (corte de red, servidor caído), conserva el `docs/volumen.json` anterior y reintenta en la corrida siguiente.
- Historización: el script fusiona lo nuevo con lo ya guardado, así los meses viejos nunca se pierden aunque el CSV deje de traerlos.

## Probar en tu PC
```
pip install -r requirements.txt
python scripts/actualizar.py --solo-build     # sin consultar precios
python scripts/volumen.py                     # baja y cruza el volumen mensual (opcional, baja ~134 MB)
cd docs && python -m http.server 8000         # abrir http://localhost:8000
```
(El mapa no funciona con doble clic en el archivo: el navegador bloquea la lectura de `data.json`.)

## Notas
- GitHub puede demorar unos minutos los horarios programados.
- Si el repo no tiene actividad por 60 días, GitHub pausa los workflows programados; los commits diarios del bot lo evitan.
- Si YPF bloquea las IP de GitHub Actions, las consultas fallan y el guard evita pisar datos; en ese caso se puede correr `python scripts/actualizar.py` desde tu PC/Raspberry y hacer push.
- Estaciones nuevas de YPF no aparecen solas: necesitan geocodificación (ypf.py/apies.py aparte).
