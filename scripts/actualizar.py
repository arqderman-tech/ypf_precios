#!/usr/bin/env python3
"""Actualiza los precios de YPF y regenera docs/data.json (lo que lee el mapa).

Uso:
  python scripts/actualizar.py              # consulta precios + regenera el mapa
  python scripts/actualizar.py --solo-build # solo regenera docs/data.json con los precios actuales

Variable opcional: YPF_WORKERS (consultas en paralelo, default 10).
"""
import argparse, hashlib, json, os, random, statistics, sys, time, unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
DB, OUT, HIST = ROOT/"data"/"estaciones.json", ROOT/"docs"/"data.json", ROOT/"data"/"historial.csv"
ART = ZoneInfo("America/Argentina/Buenos_Aires")
PRODUCTOS = ("NS", "IN", "EURO", "D500")
HIST_DIR, EXCL = ROOT/"docs"/"hist", ROOT/"data"/"excluidas.csv"
MAX_DESVIO_NS = 0.22  # estación inválida si su Súper se desvía >22% de la mediana
MAX_FALLAS = 0.30  # si falla más del 30% de las consultas, no se pisa nada


API = "https://transparenciafiscalapi.ypf.com/combustibles/apies"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://transparenciafiscal.ypf.com",
    "Referer": "https://transparenciafiscal.ypf.com/",
}


def hash_apies(apies):
    return hashlib.sha256(str(apies).encode("utf-8")).hexdigest().upper()


def consultar(sess, est):
    """Consulta una estación en la API de transparencia fiscal de YPF. Devuelve dict o None."""
    h = est.get("hash") or hash_apies(est["apies"])
    time.sleep(random.uniform(0.03, 0.08))
    for intento in range(3):
        try:
            r = sess.get(API, params={"apies": h}, timeout=15)
            r.raise_for_status()
            j = r.json()
            if j.get("status") == 200 and j.get("data"):
                return {"hash": h, "productos": j["data"],
                        "consulta": {"status": j.get("status"), "message": j.get("message"), "id": j.get("id")}}
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1.5 * (intento + 1))
    return None


def actualizar_precios(data):
    sess = requests.Session()
    sess.headers.update(HEADERS)
    sess.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=32))
    with ThreadPoolExecutor(int(os.environ.get("YPF_WORKERS", 10))) as ex:
        res = list(ex.map(lambda e: consultar(sess, e), data))
    fallas = sum(r is None for r in res)
    print(f"Consultadas {len(data)} estaciones, {fallas} con error")
    if fallas / len(data) > MAX_FALLAS:
        sys.exit("Demasiados errores (¿bloqueo de la API?): no se modifica nada, se conservan los precios anteriores.")
    for est, r in zip(data, res):
        if r:  # si una estación falla, conserva su precio anterior
            est["productos"], est["hash"], est["consulta"] = r["productos"], r["hash"], r["consulta"]


def compactar(data):
    out = []
    for e in data:
        u = e["ubicacion"]
        if u.get("latitud") is None or u.get("longitud") is None:
            continue
        out.append({
            "id": e["apies"], "o": u.get("operador") or "YPF", "d": u.get("direccion") or "",
            "l": u.get("localidad") or "", "p": u.get("provincia") or "",
            "la": round(u["latitud"], 5), "lo": round(u["longitud"], 5),
            "pr": u.get("precision") or "sin_dato",
            "n": {p["descripcion"]: p["pvp"] for p in e["productos"] if p.get("pvp")},
            "v": max((p.get("vigencia", "")[:10] for p in e["productos"]), default=""),
        })
    return out


PROVINCIAS = ["Buenos Aires", "Catamarca", "Chaco", "Chubut", "Ciudad de Buenos Aires", "Córdoba",
              "Corrientes", "Entre Ríos", "Formosa", "Jujuy", "La Pampa", "La Rioja", "Mendoza",
              "Misiones", "Neuquén", "Río Negro", "Salta", "San Juan", "San Luis", "Santa Cruz",
              "Santa Fe", "Santiago del Estero", "Tierra del Fuego", "Tucumán"]


def _clave(txt):
    t = unicodedata.normalize("NFD", str(txt)).encode("ascii", "ignore").decode().upper()
    return " ".join(t.replace(".", " ").split())


_PROV = {_clave(n): n for n in PROVINCIAS}
_PROV.update({"CAPITAL FEDERAL": "Ciudad de Buenos Aires", "CABA": "Ciudad de Buenos Aires",
              "CIUDAD AUTONOMA DE BUENOS AIRES": "Ciudad de Buenos Aires", "CIUDAD DE BUENOS AIRES": "Ciudad de Buenos Aires"})


def normalizar_provincia(valor):
    """Unifica mayúsculas/minúsculas y acentos. Acepta variantes como 'CA CATAMARCA'."""
    if not valor:
        return valor
    k = _clave(valor)
    if k in _PROV:
        return _PROV[k]
    if k.startswith("CA ") and k[3:] in _PROV:
        return _PROV[k[3:]]
    print(f"AVISO: provincia no reconocida: {valor!r}")
    return str(valor).strip().title()


def precio(e, prod):
    return next((p["pvp"] for p in e["productos"] if p.get("descripcion") == prod and p.get("pvp")), None)


def filtrar_outliers(data):
    """Descarta estaciones cuyo Nafta Súper difiere >22% de la mediana (precio no vigente/erróneo)."""
    med = statistics.median(v for v in (precio(e, "NS") for e in data) if v)
    validas, excl = [], []
    for e in data:
        v = precio(e, "NS")
        (excl if v and abs(v / med - 1) > MAX_DESVIO_NS else validas).append(e)
    with open(EXCL, "w", encoding="utf-8") as f:
        f.write("apies,operador,localidad,pvp_NS,mediana_NS,desvio_pct\n")
        for e in excl:
            v, u = precio(e, "NS"), e["ubicacion"]
            f.write(f'{e["apies"]},"{u.get("operador")}","{u.get("localidad")}",{v},{med},{(v/med-1)*100:.1f}\n')
    return validas, excl, med


def historial_estaciones(validas, hoy):
    """Historial por estación y combustible, en partes (docs/hist/<2 primeros dígitos del APIES>.json).

    Guarda cada precio solo cuando cambia: [[fecha, precio], ...]. El valor de cualquier día se
    reconstruye con el último cambio anterior, así que no se pierde ningún día y el peso queda mínimo.
    Primer registro = fecha de vigencia que informa YPF.
    """
    HIST_DIR.mkdir(parents=True, exist_ok=True)
    partes, cambios = {}, 0
    for e in validas:
        b = e["apies"][:2]
        if b not in partes:
            f = HIST_DIR / f"{b}.json"
            partes[b] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        h = partes[b].setdefault(e["apies"], {})
        for p in e["productos"]:
            prod, pvp = p.get("descripcion"), p.get("pvp")
            if prod not in PRODUCTOS or not pvp:
                continue
            vig = (p.get("vigencia") or "")[:10]
            serie = h.setdefault(prod, [])
            if not serie:
                serie.append([vig or hoy, pvp]); cambios += 1
            elif serie[-1][1] != pvp:
                fecha = vig if serie[-1][0] < vig <= hoy else hoy
                if serie[-1][0] == fecha:
                    serie[-1][1] = pvp
                else:
                    serie.append([fecha, pvp])
                cambios += 1
    for b, contenido in partes.items():
        f = HIST_DIR / f"{b}.json"
        f.write_text(json.dumps(contenido, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
        if f.stat().st_size > 40_000_000:  # GitHub bloquea archivos >100 MB; avisamos mucho antes
            print(f"AVISO: {f.name} pesa {f.stat().st_size/1e6:.0f} MB, conviene dividir más las partes")
    print(f"Historial: {cambios} cambios nuevos en {len(partes)} partes")


def historial(est, hoy):
    previo = [l for l in HIST.read_text().splitlines() if l] if HIST.exists() else ["fecha,producto,estaciones,min,mediana,promedio,max"]
    previo = [l for l in previo if not l.startswith(hoy + ",")]
    for prod in PRODUCTOS:
        v = [e["n"][prod] for e in est if prod in e["n"] and e["pr"] != "sospechosa"]
        if v:
            previo.append(f"{hoy},{prod},{len(v)},{min(v)},{statistics.median(v)},{statistics.mean(v):.2f},{max(v)}")
    HIST.write_text("\n".join(previo) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-build", action="store_true")
    solo = ap.parse_args().solo_build
    data = json.loads(DB.read_text(encoding="utf-8"))
    for e in data:
        e["ubicacion"]["provincia"] = normalizar_provincia(e["ubicacion"].get("provincia"))
    ahora = datetime.now(ART)
    if not solo:
        actualizar_precios(data)
        DB.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    hoy = ahora.strftime("%Y-%m-%d")
    validas, excl, med = filtrar_outliers(data)
    print(f"Excluidas por Súper >{MAX_DESVIO_NS:.0%} de la mediana (${med:.0f}): {len(excl)} -> data/excluidas.csv")
    historial_estaciones(validas, hoy)
    DB.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    est = compactar(validas)
    meta = {"actualizado": None if solo else ahora.isoformat(timespec="minutes"),
            "vigencia": max((e["v"] for e in est), default=""), "mediana_ns": med,
            "excluidas": len(excl), "estaciones": est}
    OUT.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if not solo:
        historial(est, hoy)
    print(f"OK: {len(est)} estaciones con coordenadas -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
