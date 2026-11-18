#!/usr/bin/env python3
"""Cruce del volumen despachado (Secretaría de Energía, Res. 1104) con las estaciones del mapa.

El dataset oficial "Precios y volúmenes EESS" se publica una vez por mes y trae, por boca y por
período, el volumen despachado y el precio surtidor de cada combustible. Este script baja ese CSV,
se queda con las bocas YPF del canal "Al público", las cruza con data/estaciones.json por
proximidad geográfica (haversine, ≤250 m) y escribe docs/volumen.json con el histórico mes a mes
(volumen + precio oficial por combustible).

El CSV pesa >130 MB y no se guarda en el repo: se baja a una carpeta temporal, se extrae solo lo
que interesa y se borra. Si el recurso oficial no cambió desde la última corrida, no baja nada
(se guía por la fecha de modificación de la API de datos abiertos), así que corre todos los días
sin costo y engancha el mes nuevo apenas se publica.

Uso:
  python scripts/volumen.py                        # baja y reconstruye solo si el recurso cambió
  python scripts/volumen.py --forzar               # reconstruye igual
  python scripts/volumen.py --csv X.csv --registro Y.csv   # usa archivos locales (sin bajar)
"""
import argparse, collections, csv, difflib, json, math, re, shutil, sys, tempfile, unicodedata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "estaciones.json"
OUT = ROOT / "docs" / "volumen.json"

DATASET = "708f9ab4-829b-4f02-b507-f303c5bc4800"
API = f"http://datos.energia.gob.ar/api/3/action/package_show?id={DATASET}"
RES_PRECIOS = "3cbdd364-a12c-46b7-b791-dd8e8bcfb32d"    # precios-eess-2025-.csv (mensual, acumulativo)
RES_REGISTRO = "57d8be8f-520e-4ac3-a59b-8458623e8385"   # eess-y-operadores-res-1104-.csv (coordenadas)
URL_PRECIOS = f"http://datos.energia.gob.ar/dataset/{DATASET}/resource/{RES_PRECIOS}/download/precios-eess-2025-.csv"
URL_REGISTRO = f"http://datos.energia.gob.ar/dataset/{DATASET}/resource/{RES_REGISTRO}/download/eess-y-operadores-res-1104-.csv"

# Producto del dataset -> clave del repo. El GNC queda afuera a pedido (el repo no releva su precio).
MAP = {"Nafta (súper) entre 92 y 95 Ron": "NS", "Nafta (premium) de más de 95 Ron": "IN",
       "Gas Oil Grado 2": "D500", "Gas Oil Grado 3": "EURO"}
MAXD = 0.25  # km: distancia máxima aceptada entre la boca oficial y la del repo
R_TIERRA = 6371.0


def norm(s):
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s)).strip()


def parse_dir(s):
    t = norm(s).replace(" NRO ", " ")
    nums = set(re.findall(r"\b\d{1,6}\b", t))
    txt = " ".join(w for w in re.sub(r"\b\d{1,6}\b", " ", t).split()
                   if w not in {"Y", "ESQ", "ESQUINA", "ENTRE", "E", "D", "DE", "LA", "LAS", "LOS", "EL", "DEL", "KM"})
    return txt, nums


def hav(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 2 * R_TIERRA * math.asin(math.sqrt(x))


def per_mes(s):
    """'2026/09' -> '2026-09'."""
    m = re.match(r"(\d{4})\D+(\d{1,2})", str(s or ""))
    return f"{int(m.group(1))}-{int(m.group(2)):02d}" if m else None


def recurso_info():
    """URLs y fecha de modificación del recurso de precios, vía la API de datos abiertos (CKAN)."""
    r = requests.get(API, timeout=30)
    r.raise_for_status()
    res = r.json()["result"]["resources"]
    pre = next((x for x in res if x.get("id") == RES_PRECIOS), {})
    reg = next((x for x in res if x.get("id") == RES_REGISTRO), {})
    return {"precios": pre.get("url") or URL_PRECIOS, "registro": reg.get("url") or URL_REGISTRO,
            "mod": pre.get("last_modified")}


def descargar(url, dest):
    print(f"Descargando {url}")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        n = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                n += len(chunk)
    print(f"  {n / 1e6:.1f} MB -> {dest.name} (temporal, no se guarda en el repo)")
    return dest


def leer_registro(path):
    """{idempresa: {lat, lon}} desde la columna geojson del registro de EESS."""
    out = {}
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            gj = (r.get("geojson") or "").strip()
            if not gj:
                continue
            try:
                c = json.loads(gj)["coordinates"]
            except (ValueError, KeyError, TypeError):
                continue
            out[r["idempresa"]] = {"lat": c[1], "lon": c[0]}
    return out


def _precio(r, i):
    """Precio surtidor ($/litro) del propio dataset; si falta, el precio con impuestos."""
    for col in ("precio_surtidor", "precio_con_impuestos"):
        try:
            v = float((r[i(col)] or "").strip())
        except ValueError:
            continue
        if v > 0:
            return round(v)
    return None


def leer_datos(path):
    """Volumen y precio oficial por boca YPF, producto y período.

    Devuelve {nro_inscripcion: {op,dir,loc,prov, m:{'YYYY-MM':{prod:[vol_m3, precio]}}}},
    la cantidad de filas con volumen corregido y la lista de períodos encontrados.
    """
    out, ajustados, periodos = {}, 0, set()
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        rd = csv.reader(f)
        hdr = next(rd)
        i = hdr.index
        for r in rd:
            if r[i("bandera")] != "YPF" or r[i("canal_de_comercializacion")] != "Al público":
                continue
            # OJO: NO se filtra por fecha_de_baja. El dataset trae bocas con una fecha de baja vieja
            # (ej. 18/2022/08) que igual siguen declarando volumen todos los meses (~28 casos reales,
            # como la Opessa de Figueroa Alcorta). Lo que manda es que el período tenga volumen.
            prod = MAP.get(r[i("producto")])
            if not prod:
                continue
            per = per_mes(r[i("periodo")])
            if not per:
                continue
            try:
                v = float((r[i("volumen")] or "").strip())
            except ValueError:
                continue
            if v <= 0:
                continue
            if v > 1000:                    # el dataset mezcla unidades: filas sueltas vienen en litros
                v /= 1000.0
                ajustados += 1
            d = out.setdefault(r[i("nro_inscripcion")],
                               {"op": r[i("operador")].strip(), "dir": r[i("direccion")].strip(),
                                "loc": r[i("localidad")].strip(), "prov": r[i("provincia")].strip(), "m": {}})
            mes = d["m"].setdefault(per, {})
            cel = mes.get(prod)
            precio = _precio(r, i)
            if cel:
                cel[0] += v
                if precio and not cel[1]:
                    cel[1] = precio
            else:
                mes[prod] = [round(v, 3), precio]
            periodos.add(per)
    print(f"Períodos en el CSV: {len(periodos)} ({min(periodos)} … {max(periodos)}) | bocas YPF: {len(out)}"
          f" | filas con volumen ajustado litros->m3: {ajustados}")
    return out, sorted(periodos)


def limpiar_atipicos(final, k=20, min_meses=5):
    """Descarta meses con volumen disparatado (errores de carga del dataset oficial).

    El dataset trae meses sueltos con volúmenes absurdos (ej. una boca que factura ~450.000 L/mes
    y un mes aparece con 346 millones). Se compara el total del mes contra la mediana de los meses
    de la misma boca: si lo supera k veces, se descarta. Solo se aplica si hay historia suficiente.
    """
    quitados = []
    for apies, s in final.items():
        meses = s["m"]
        tot = {p: sum(c[0] for c in m.values()) for p, m in meses.items()}   # m3
        if len(tot) < min_meses:
            continue
        vals = sorted(tot.values())
        med = vals[len(vals) // 2]
        if med <= 0:
            continue
        for p, v in tot.items():
            if v > med * k:
                quitados.append((apies, p, v, med))
                del meses[p]
    return quitados


def construir(csv_path, reg_path, mod, previo):
    registro = leer_registro(reg_path)
    datos, periodos = leer_datos(csv_path)

    st = [s for s in json.loads(DB.read_text(encoding="utf-8")) if s["ubicacion"].get("latitud") is not None]
    print(f"Estaciones del repo con coordenadas: {len(st)}")

    def nearest(lat, lon, direccion):
        best = (9e9, None, 0.0, 0.0)
        t1, n1 = parse_dir(direccion)
        for s in st:
            u = s["ubicacion"]
            if abs(u["latitud"] - lat) > 0.05 or abs(u["longitud"] - lon) > 0.05:
                continue
            dd = hav(lat, lon, u["latitud"], u["longitud"])
            if dd < best[0]:
                t2, n2 = parse_dir(u["direccion"])
                best = (dd, s, difflib.SequenceMatcher(None, t1, t2).ratio(), 1.0 if (n1 & n2) else 0.0)
        return best

    cand, sinreg = collections.defaultdict(list), 0
    for k, d in datos.items():
        reg = registro.get(k)
        if not reg:
            sinreg += 1
            continue
        dd, s, sm, num = nearest(reg["lat"], reg["lon"], d["dir"])
        if not s or dd > MAXD:
            continue
        cand[s["apies"]].append((0.6 * sm + 0.4 * num + max(0.0, 0.35 - dd) * 0.6, dd, k, d))
    print(f"Bocas sin coordenadas en el registro: {sinreg}")

    prev = previo.get("estaciones") or {}
    final, conflictos, nuevos = {}, 0, set(prev.get("periodos") or [])
    for apies, lst in cand.items():
        lst.sort(key=lambda x: (-x[0], x[1]))
        if len(lst) > 1 and max(x[1] for x in lst) - min(x[1] for x in lst) > 0.02:
            conflictos += 1
        _, dd, k, d = lst[0]
        meses = dict((prev.get(apies) or {}).get("m") or {})      # conserva meses viejos si el CSV los dejara caer
        meses.update(d["m"])                                     # lo nuevo pisa lo viejo
        final[apies] = {"nro": k, "op": d["op"], "dir": d["dir"], "loc": d["loc"], "prov": d["prov"],
                        "d": round(dd, 4), "m": {p: meses[p] for p in sorted(meses)}}
    print(f"Estaciones del repo con volumen: {len(final)} de {len(st)} | bocas con >1 candidata: {conflictos}")

    quitados = limpiar_atipicos(final)
    if quitados:
        for apies, p, v, med in quitados:
            print(f"  mes atípico descartado: boca {apies} {p}: {v * 1000:,.0f} L"
                  f" (mediana de la boca {med * 1000:,.0f} L)")
    print(f"Meses atípicos descartados: {len(quitados)}")

    todos = sorted(set(periodos) | nuevos | {p for s in final.values() for p in s["m"]})
    nuevos = sorted(set(todos) - nuevos)
    print(f"Histórico: {len(todos)} períodos ({todos[0]} … {todos[-1]})"
          + (f" | nuevos: {', '.join(nuevos)}" if nuevos else " | sin meses nuevos"))
    return {"fuente": "Energía (Res. 1104) · volumen canal Al público + precio surtidor oficial",
            "recurso_mod": mod, "periodos": todos, "estaciones": final}


def main():
    ap = argparse.ArgumentParser(description="Volumen y facturación oficial (Res. 1104) -> docs/volumen.json")
    ap.add_argument("--forzar", action="store_true", help="reconstruye aunque el recurso no haya cambiado")
    ap.add_argument("--csv", help="usa un CSV de precios/volúmenes local en vez de descargarlo")
    ap.add_argument("--registro", help="usa un CSV de registro local en vez de descargarlo")
    a = ap.parse_args()

    previo = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    try:
        if a.csv:
            mod, csv_url, reg_url = None, None, None
        else:
            info = recurso_info()
            csv_url, reg_url, mod = info["precios"], info["registro"], info["mod"]
            if not a.forzar and mod and previo.get("recurso_mod") == mod and previo.get("estaciones"):
                print(f"Sin cambios (recurso {mod}). docs/volumen.json ya está al día.")
                return

        tmp = Path(tempfile.mkdtemp(prefix="volumen_"))
        try:
            csv_path = Path(a.csv) if a.csv else descargar(csv_url, tmp / "precios.csv")
            reg_path = Path(a.registro) if a.registro else descargar(reg_url, tmp / "registro.csv")
            salida = construir(csv_path, reg_path, mod, previo)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except requests.RequestException as e:
        print(f"AVISO: no se pudo actualizar el volumen ({e}). Se conserva docs/volumen.json.")
        return

    OUT.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"OK: {len(salida['estaciones'])} estaciones · {len(salida['periodos'])} meses -> "
          f"{OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
