"""
Extractor de la API abierta de Venezuela Reporta.

Reemplaza al webscraping (scraper.py): el sitio ahora publica una API oficial,
YA deduplicada ("solo devolvemos la ficha canónica"), con sexo/edad estructurados.

Endpoints (GET, lectura pública, sin clave):
  /personas  registro de desaparecidos/encontrados (1 fila = 1 persona canónica)
  /ingresos  listas de hospitales/refugios aportadas por la comunidad (SIN estado)
  - limit máx 100 · paginación por offset · campo `total` global · envoltorio {personas:[...]}
  - rate limit 120 req/min por origen · caché 60s
  - atribución obligatoria: "Venezuela Reporta — venezuelareporta.org"

Salida: data/raw/api_<endpoint>.csv

Uso:
  python3 api_extractor.py                              # baja todo /personas
  python3 api_extractor.py --status buscando            # solo desaparecidos
  python3 api_extractor.py --endpoint ingresos          # baja /ingresos (hospitales)
  python3 api_extractor.py --endpoint personas --out data/raw/api_personas.csv
"""

import argparse
import csv
import sys
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://venezuelareporta.org/api/v1"
PAGE = 100              # máximo permitido por la API
MIN_INTERVALO = 0.55   # ~110 req/min, por debajo del límite de 120/min

# campos por endpoint (orden de columnas del CSV)
ENDPOINTS = {
    "personas": [
        "id", "status", "nombre", "cedula", "genero", "edad", "menor",
        "ciudad", "zona", "ultima_vez", "descripcion", "foto_url",
        "origen", "verificado", "verificado_por", "verificado_at",
        "created_at", "ficha_url",
    ],
    # /ingresos NO trae sexo poblado (viene null) ni descripcion/menor:
    # el sexo se infiere por nombre aguas abajo. edad ~66% presente.
    "ingresos": [
        "id", "nombre", "cedula", "edad", "sexo", "procedencia", "ubicacion",
        "fecha", "recopilado_de", "fuente", "ficha_url", "created_at",
    ],
}


def get_session():
    s = requests.Session()
    s.headers.update({"User-Agent": "olds2030-duplicados/1.0 (+venezuelareporta API)"})
    adapter = HTTPAdapter(
        max_retries=Retry(
            total=5, backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            respect_retry_after_header=True,
        )
    )
    s.mount("https://", adapter)
    return s


def fetch_page(s, url, params):
    r = s.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser(description="Baja datos de la API abierta de Venezuela Reporta.")
    ap.add_argument("--endpoint", default="personas", choices=list(ENDPOINTS),
                    help="personas (desaparecidos) | ingresos (hospitales)")
    ap.add_argument("--out", default=None, help="por defecto data/raw/api_<endpoint>.csv")
    ap.add_argument("--status", default=None, help="solo /personas: buscando | encontrado | a_salvo")
    ap.add_argument("--ciudad", default=None, help="solo /personas")
    args = ap.parse_args()

    campos = ENDPOINTS[args.endpoint]
    url = f"{BASE}/{args.endpoint}"
    out = args.out or f"data/raw/api_{args.endpoint}.csv"

    s = get_session()
    base_params = {"limit": PAGE, "offset": 0}
    if args.endpoint == "personas":
        if args.status:
            base_params["status"] = args.status
        if args.ciudad:
            base_params["ciudad"] = args.ciudad

    first = fetch_page(s, url, base_params)
    total = first["total"]
    atrib = first.get("atribucion", "")
    print(f"Fuente: {atrib}")
    print(f"generado_at: {first.get('generado_at')}")
    print(f"total a bajar: {total}")

    seen = set()
    rows = []
    offset = 0
    last = 0.0
    while offset < total:
        dt = MIN_INTERVALO - (time.monotonic() - last)
        if dt > 0:
            time.sleep(dt)
        last = time.monotonic()
        params = dict(base_params, offset=offset)
        data = first if offset == 0 else fetch_page(s, url, params)
        personas = data.get("personas", [])
        if not personas:
            break
        for p in personas:
            pid = p.get("id")
            if pid in seen:          # offset puede solapar si entran registros nuevos
                continue
            seen.add(pid)
            rows.append({c: p.get(c) for c in campos})
        offset += PAGE
        sys.stdout.write(f"\r  {len(rows)}/{total}")
        sys.stdout.flush()
    print()

    with open(out, "w", newline="", encoding="utf-8", errors="replace") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(rows)
    print(f"Escrito: {out}  ({len(rows)} registros)")


if __name__ == "__main__":
    main()
