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
- Los precios salen de la API de transparencia fiscal de YPF, consultando solo las estaciones que ya están en la base (no escanea todo el rango).
- Si más del 30% de las consultas fallan, no se pisa nada. Si falla una estación suelta, conserva su precio anterior.

## Filtro de datos inválidos
Si el precio de Nafta Súper de una estación difiere más de 22% de la mediana nacional, se descarta la estación completa (se asume que sus precios no están vigentes). Queda registrada en `data/excluidas.csv`; el umbral es `MAX_DESVIO_NS` en `scripts/actualizar.py`.

## Historial de precios
`docs/hist/NN.json` guarda el historial de cada estación y combustible, repartido en partes por los 2 primeros dígitos del APIES (~15 archivos). Se anota el precio solo cuando cambia (`[[fecha, precio], ...]`), por lo que cada día queda cubierto sin repetir datos. El mapa carga solo la parte de la estación que tocás. Si alguna parte supera 40 MB el script avisa (GitHub bloquea archivos de 100 MB).

## Probar en tu PC
```
pip install -r requirements.txt
python scripts/actualizar.py --solo-build     # sin consultar precios
cd docs && python -m http.server 8000         # abrir http://localhost:8000
```
(El mapa no funciona con doble clic en el archivo: el navegador bloquea la lectura de `data.json`.)

## Notas
- GitHub puede demorar unos minutos los horarios programados.
- Si el repo no tiene actividad por 60 días, GitHub pausa los workflows programados; los commits diarios del bot lo evitan.
- Si YPF bloquea las IP de GitHub Actions, las consultas fallan y el guard evita pisar datos; en ese caso se puede correr `python scripts/actualizar.py` desde tu PC/Raspberry y hacer push.
- Estaciones nuevas de YPF no aparecen solas: necesitan geocodificación (ypf.py/apies.py aparte).
