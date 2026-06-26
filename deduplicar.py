"""
Deduplicar reportes de personas desaparecidas
Fuente de datos: CSV de reportes (registro comunitario humanitario)

Qué hace:
  1. Carga el CSV con pandas (campos con comas/saltos de línea dentro de comillas).
  2. Normaliza nombre, cédula, teléfonos y ubicación EN COLUMNAS NUEVAS
     (las 25 columnas originales nunca se tocan: cero pérdida de datos).
  3. Bloqueo (cédula / teléfono / prefijo de nombre) para no comparar 6300² pares.
  4. Puntúa cada par candidato 0–100 (cédula igual = 100; si no, nombre fuzzy
     + teléfono + ubicación + edad/género/foto).
  5. Agrupa con union-find → cluster_id por persona.
  6. Confianza por reporte = fuerza del enlace que lo une a su grupo.
  7. Estado resuelto: si algún reporte del grupo está "Encontrado"/"A salvo",
     el grupo se marca resuelto.

Salidas (en --output-dir):
  - reportes_dedup.csv   todas las filas + columnas nuevas (nada se pierde)
  - personas_unicas.csv  1 fila por persona, con TODOS los enlaces de reporte
                         y de fotos conservados (base para futuro comparador
                         de imágenes)
  - pares_revisar.csv    pares de confianza media (80–92) para revisión humana

Uso:
  python deduplicar.py
  python deduplicar.py --input "venezolanos_desaparecidos copy.csv"
  python deduplicar.py --output-dir ./salida
  python deduplicar.py --umbral-auto 92 --umbral-revisar 80

Dependencias:
  pandas (instalado), rapidfuzz  ->  pip install rapidfuzz
"""

import argparse
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

import pandas as pd

try:
    from rapidfuzz import fuzz
except ImportError:
    sys.exit("Falta rapidfuzz. Instala con:  pip install rapidfuzz")


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #

TEL_COLS = [
    "contacto_persona",
    "contacto_emergencia1",
    "contacto_emergencia2",
    "contacto_emergencia3",
    "contacto_reporter",
]

# Estados que indican que la persona ya apareció.
ESTADOS_RESUELTOS = {"encontrado", "a salvo"}
ESTADOS_VALIDOS = {"se busca", "encontrado", "a salvo"}

MAX_NO_CEDULA = 97.0  # solo una cédula igual llega a 100% de confianza

# Una ubicación compartida por <= este nº de reportes se considera "específica"
# (un hospital, una dirección puntual) y sirve para corroborar. Una ciudad
# genérica como "La Guaira" (miles de reportes) NO distingue personas.
UMBRAL_UBIC_ESPECIFICA = 40


# --------------------------------------------------------------------------- #
# Normalización  (todo va a columnas nuevas; nada destruye el original)
# --------------------------------------------------------------------------- #

def quitar_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def norm_nombre(valor: str) -> str:
    """minúsculas, sin acentos, solo letras/números/espacios, espacios colapsados."""
    if not valor:
        return ""
    t = quitar_acentos(valor.lower())
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def norm_cedula(valor: str) -> str:
    """Solo dígitos. Válida si quedan 6–9 dígitos; si no, cadena vacía."""
    if not valor:
        return ""
    digitos = re.sub(r"\D", "", valor)
    return digitos if 6 <= len(digitos) <= 9 else ""


def norm_un_tel(valor: str) -> str:
    """Dígitos; si hay 10+ toma los últimos 10 (descarta +58 / 0 inicial)."""
    if not valor:
        return ""
    d = re.sub(r"\D", "", valor)
    if len(d) < 7:
        return ""
    return d[-10:] if len(d) >= 10 else d


def norm_tels(fila) -> frozenset:
    tels = set()
    for col in TEL_COLS:
        t = norm_un_tel(fila.get(col, ""))
        if t:
            tels.add(t)
    return frozenset(tels)


def norm_ubic(valor: str) -> str:
    if not valor:
        return ""
    t = quitar_acentos(valor.lower())
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def norm_genero(valor: str) -> str:
    t = quitar_acentos((valor or "").lower()).strip()
    if t.startswith("masc") or t == "m":
        return "m"
    if t.startswith("fem") or t == "f":
        return "f"
    return ""


def parse_edad(valor: str):
    if not valor:
        return None
    m = re.search(r"\d{1,3}", valor)
    if not m:
        return None
    n = int(m.group())
    return n if 0 <= n <= 120 else None


def clave_nombre_bloque(nombre_norm: str) -> str:
    """Primeros 4 caracteres del nombre sin espacios -> clave de bloqueo."""
    return nombre_norm.replace(" ", "")[:4]


# --------------------------------------------------------------------------- #
# Union-Find
# --------------------------------------------------------------------------- #

class UnionFind:
    def __init__(self, n):
        self.padre = list(range(n))

    def find(self, x):
        while self.padre[x] != x:
            self.padre[x] = self.padre[self.padre[x]]
            x = self.padre[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.padre[rb] = ra


# --------------------------------------------------------------------------- #
# Puntuación de un par
# --------------------------------------------------------------------------- #

def puntuar(a, b, ubic_freq):
    """
    Devuelve (score 0-100, motivo str).

    Filosofía: para personas desaparecidas, fusionar de más (juntar personas
    DISTINTAS) es peor que dejar duplicados. Por eso:
      - Cédulas válidas distintas -> 0 (son personas distintas; bloqueo duro).
      - Nombre igual con edad o género INCOMPATIBLE -> 0.
      - Nombre solo (sin cédula ni teléfono) NO basta para fusionar: exige
        corroboración por edad y/o género. Si no hay con qué confirmar, queda
        como dudoso (no se fusiona; candidato a revisión/comparador de imágenes).
    """
    ca, cb = a["cedula_norm"], b["cedula_norm"]
    if ca and cb:
        return (100.0, "cedula igual") if ca == cb else (0.0, "cedula distinta")

    ns = fuzz.token_sort_ratio(a["nombre_norm"], b["nombre_norm"])
    ga, gb = a["genero_norm"], b["genero_norm"]
    ea, eb = a["edad"], b["edad"]
    genero_conflicto = bool(ga and gb and ga != gb)
    edad_conflicto = ea is not None and eb is not None and abs(ea - eb) > 3

    # Teléfono compartido: señal casi única.
    if a["tels"] & b["tels"]:
        if ns < 50:
            return 70.0, f"tel compartido, nombre {ns:.0f} (revisar)"
        if genero_conflicto or edad_conflicto:
            return 70.0, "tel+nombre, pero edad/genero en conflicto (revisar)"
        return min(96.0, max(ns, 90.0) + 4.0), "tel + nombre"

    # Sin cédula compartida ni teléfono: todo depende del nombre.
    if ns < 90:
        return 0.0, f"nombre {ns:.0f} (insuficiente)"
    if genero_conflicto or edad_conflicto:
        return 0.0, "mismo nombre pero edad/genero distinto (personas distintas)"

    # Nombre casi idéntico (>=90). ¿Hay corroboración (edad / género / lugar específico)?
    corrob = 0
    if ea is not None and eb is not None and abs(ea - eb) <= 1:
        corrob += 1
    if ga and gb and ga == gb:
        corrob += 1
    ubic_match = bool(a["ubic_norm"] and b["ubic_norm"]
                      and fuzz.token_set_ratio(a["ubic_norm"], b["ubic_norm"]) >= 70)
    ubic_especifica = ubic_match and min(ubic_freq.get(a["ubic_norm"], 0),
                                         ubic_freq.get(b["ubic_norm"], 0)) <= UMBRAL_UBIC_ESPECIFICA
    if ubic_especifica:
        corrob += 1

    if corrob >= 1:
        s = float(ns) + (2.0 if ubic_match else 0.0)
        return min(MAX_NO_CEDULA, s), "nombre fuerte + corroboracion (edad/genero/lugar)"

    # Nombre idéntico pero sin nada que confirme (ni edad, ni género, ni lugar
    # específico): no se puede asegurar. No fusionar; dejar como dudoso
    # (revisión humana / futuro comparador de imágenes).
    return 78.0, "solo nombre, sin corroboracion"


# --------------------------------------------------------------------------- #
# Proceso principal
# --------------------------------------------------------------------------- #

def construir_bloques(reg):
    """Devuelve lista de listas de índices que comparten algún bloque."""
    por_cedula = defaultdict(list)
    por_tel = defaultdict(list)
    por_nombre = defaultdict(list)

    for i, r in enumerate(reg):
        if r["cedula_norm"]:
            por_cedula[r["cedula_norm"]].append(i)
        for t in r["tels"]:
            por_tel[t].append(i)
        if r["nombre_norm"]:
            por_nombre[clave_nombre_bloque(r["nombre_norm"])].append(i)

    bloques = []
    for d in (por_cedula, por_tel, por_nombre):
        for idxs in d.values():
            if len(idxs) > 1:
                bloques.append(idxs)
    return bloques


def generar_pares(bloques):
    # No se memoriza el conjunto de pares vistos: a 73k explotaría la RAM
    # (decenas de millones de tuplas). Un par puede salir en >1 bloque, pero
    # volver a puntuarlo es idempotente (union-find + max_score), y
    # pares_revisar se deduplica al escribir.
    for idxs in bloques:
        m = len(idxs)
        for x in range(m):
            ax = idxs[x]
            for y in range(x + 1, m):
                yield ax, idxs[y]


def canonico_mas_completo(valores):
    """Valor no vacío más frecuente; desempate por el más largo."""
    nv = [v for v in valores if v and v.strip()]
    if not nv:
        return ""
    cnt = Counter(nv)
    maxf = max(cnt.values())
    candidatos = [v for v, c in cnt.items() if c == maxf]
    return max(candidatos, key=len)


def main():
    ap = argparse.ArgumentParser(description="Deduplica reportes de personas desaparecidas.")
    ap.add_argument("--input", default="data/raw/venezolanos_desaparecidos.csv")
    ap.add_argument("--output-dir", default="data/processed")
    ap.add_argument("--umbral-auto", type=float, default=92.0,
                    help="score >= esto => enlace de alta confianza")
    ap.add_argument("--umbral-revisar", type=float, default=80.0,
                    help="score en [revisar, auto) => enlace marcado para revisión")
    ap.add_argument("--incremental", action="store_true",
                    help="reutiliza el reportes_dedup.csv previo (en --output-dir) y "
                         "solo procesa reportes nuevos; conserva los cluster_id existentes")
    ap.add_argument("--state", default=None,
                    help="ruta del reportes_dedup.csv previo (por defecto, dentro de --output-dir)")
    args = ap.parse_args()

    print(f"Cargando {args.input} ...")
    df = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    n = len(df)
    print(f"  {n} filas, {len(df.columns)} columnas originales")

    # --- Normalización (columnas nuevas) ---
    df["nombre_norm"] = df["nombre"].map(norm_nombre)
    df["cedula_norm"] = df["cedula"].map(norm_cedula)
    df["ubic_norm"] = df["ubicacion"].map(norm_ubic)
    df["tels_norm"] = df.apply(lambda r: " ".join(sorted(norm_tels(r))), axis=1)

    # Registros ligeros para el motor de matching.
    reg = []
    for _, r in df.iterrows():
        reg.append({
            "nombre_norm": r["nombre_norm"],
            "cedula_norm": r["cedula_norm"],
            "ubic_norm": r["ubic_norm"],
            "tels": frozenset(r["tels_norm"].split()) if r["tels_norm"] else frozenset(),
            "genero_norm": norm_genero(r["genero"]),
            "edad": parse_edad(r["edad"]),
            "foto_url": r["foto_url"].strip(),
        })

    uuids = list(df["uuid"])
    ubic_freq = Counter(r["ubic_norm"] for r in reg if r["ubic_norm"])

    # --- Estado previo (modo incremental) ---
    # Si se reutiliza una corrida anterior, los reportes ya vistos conservan su
    # cluster_id y NO se vuelven a comparar entre sí: solo lo nuevo se procesa.
    prior_cid, prior_conf = {}, {}
    state_path = args.state or os.path.join(args.output_dir, "reportes_dedup.csv")
    usar_incremental = args.incremental and os.path.exists(state_path)
    if args.incremental and not usar_incremental:
        print(f"  (incremental pedido, pero no existe {state_path}: corro completo)")
    if usar_incremental:
        prev = pd.read_csv(state_path, dtype=str, keep_default_na=False)
        for _, r in prev.iterrows():
            prior_cid[r["uuid"]] = r.get("cluster_id", "")
            try:
                prior_conf[r["uuid"]] = float(r.get("confianza_pct") or 0)
            except ValueError:
                prior_conf[r["uuid"]] = 0.0

    es_nuevo = [(not usar_incremental) or (u not in prior_cid) for u in uuids]
    n_nuevos = sum(es_nuevo)
    if usar_incremental:
        print(f"  incremental: {n_nuevos} reportes nuevos, {n - n_nuevos} ya conocidos")

    # --- Bloqueo + puntuación ---
    bloques = construir_bloques(reg)
    print(f"  {len(bloques)} bloques generados")

    uf = UnionFind(n)
    max_score = [0.0] * n          # mejor enlace incidente a cada nodo
    pares_revisar = []             # (a, b, score, motivo)
    n_pares = n_enlaces = 0

    # Pre-unión: respeta los grupos ya formados en la corrida anterior y
    # siembra su confianza, para no recalcularlos.
    if usar_incremental:
        grupos_prev = defaultdict(list)
        for i, u in enumerate(uuids):
            c = prior_cid.get(u, "")
            if c:
                grupos_prev[c].append(i)
        for idxs in grupos_prev.values():
            for j in idxs[1:]:
                uf.union(idxs[0], j)
        for i, u in enumerate(uuids):
            if not es_nuevo[i]:
                max_score[i] = prior_conf.get(u, 0.0)

    for a, b in generar_pares(bloques):
        # En incremental, dos reportes viejos ya están resueltos: se saltan.
        if usar_incremental and not es_nuevo[a] and not es_nuevo[b]:
            continue
        n_pares += 1
        score, motivo = puntuar(reg[a], reg[b], ubic_freq)
        if score >= args.umbral_revisar:
            uf.union(a, b)
            n_enlaces += 1
            max_score[a] = max(max_score[a], score)
            max_score[b] = max(max_score[b], score)
            if score < args.umbral_auto:
                pares_revisar.append((a, b, round(score, 1), motivo))

    print(f"  {n_pares} pares comparados, {n_enlaces} enlaces")

    # --- Clustering ---
    raiz_a_miembros = defaultdict(list)
    for i in range(n):
        raiz_a_miembros[uf.find(i)].append(i)

    # Salvaguarda anti-contaminación: una persona NO puede tener dos cédulas
    # válidas distintas. Si un componente quedó "puenteado" por registros sin
    # cédula y mezcla varias cédulas, se separa por cédula; los registros sin
    # cédula de ese componente quedan como individuos (no se adivina a quién
    # pertenecen).
    componentes = []
    n_split = 0
    for miembros in raiz_a_miembros.values():
        ceds = {reg[i]["cedula_norm"] for i in miembros if reg[i]["cedula_norm"]}
        if len(ceds) <= 1:
            componentes.append(miembros)
        else:
            n_split += 1
            por_ced = defaultdict(list)
            sin_ced = []
            for i in miembros:
                c = reg[i]["cedula_norm"]
                if c:
                    por_ced[c].append(i)
                else:
                    sin_ced.append(i)
            componentes.extend(por_ced.values())
            componentes.extend([i] for i in sin_ced)
    if n_split:
        print(f"  {n_split} componentes contaminados separados por cédula")

    # Asigna cluster_id. Estable: un grupo que ya tenía id en la corrida
    # anterior lo conserva (el menor si dos grupos se fusionaron); los grupos
    # nuevos reciben un id correlativo a partir del máximo existente.
    nums_prev = [int(m.group(1)) for c in prior_cid.values()
                 for m in [re.match(r"PER-(\d+)$", c)] if m]
    contador = (max(nums_prev) + 1) if nums_prev else 1

    comps = sorted(componentes, key=lambda m: min(uuids[i] for i in m))
    cluster_id = [""] * n
    miembros_de = {}
    usados = set()
    nuevos_comps = []
    for miembros in comps:
        ids_prev = sorted({prior_cid.get(uuids[i], "") for i in miembros} - {""})
        if ids_prev:
            cid = ids_prev[0]
            miembros_de[cid] = miembros
            usados.add(cid)
            for i in miembros:
                cluster_id[i] = cid
        else:
            nuevos_comps.append(miembros)
    for miembros in nuevos_comps:
        cid = f"PER-{contador:06d}"
        while cid in usados:
            contador += 1
            cid = f"PER-{contador:06d}"
        contador += 1
        miembros_de[cid] = miembros
        for i in miembros:
            cluster_id[i] = cid

    # --- Columnas nuevas en la salida A ---
    df["cluster_id"] = cluster_id
    df["n_reportes_cluster"] = [len(miembros_de[cid]) for cid in cluster_id]
    df["es_duplicado"] = [len(miembros_de[cid]) > 1 for cid in cluster_id]

    confianza_pct = []
    for i in range(n):
        if len(miembros_de[cluster_id[i]]) == 1:
            confianza_pct.append(100.0)          # único: sin riesgo de fusión
        else:
            confianza_pct.append(round(max_score[i], 1))
    df["confianza_pct"] = confianza_pct

    def nivel(p):
        return "ALTA" if p >= args.umbral_auto else ("MEDIA" if p >= args.umbral_revisar else "BAJA")
    df["confianza_nivel"] = [nivel(p) for p in confianza_pct]

    # revisar_manual a nivel grupo: algún miembro por debajo del umbral auto.
    conf_min_grupo = {}
    for cid, miembros in miembros_de.items():
        conf_min_grupo[cid] = min(confianza_pct[i] for i in miembros)
    df["revisar_manual"] = [
        len(miembros_de[cid]) > 1 and conf_min_grupo[cid] < args.umbral_auto
        for cid in cluster_id
    ]

    # estado_resuelto por grupo
    def es_resuelto_txt(estado):
        return quitar_acentos((estado or "").lower()).strip() in ESTADOS_RESUELTOS
    estado_grupo = {}
    for cid, miembros in miembros_de.items():
        resuelto = any(es_resuelto_txt(df.iloc[i]["estado"]) for i in miembros)
        estado_grupo[cid] = "Resuelto" if resuelto else "Se busca"
    df["estado_resuelto"] = [estado_grupo[cid] for cid in cluster_id]

    # --- Salida A ---
    os.makedirs(args.output_dir, exist_ok=True)
    ruta_a = os.path.join(args.output_dir, "reportes_dedup.csv")
    df.to_csv(ruta_a, index=False)
    print(f"Escrito: {ruta_a}")

    # --- Salida B: personas_unicas (1 fila por grupo, conserva TODOS los enlaces) ---
    filas_b = []
    for cid, miembros in miembros_de.items():
        sub = df.iloc[miembros]
        fechas = [f for f in sub["fecha_reporte"] if f]
        filas_b.append({
            "cluster_id": cid,
            "nombre": canonico_mas_completo(list(sub["nombre"])),
            "cedula": canonico_mas_completo(list(sub["cedula"])),
            "edad": canonico_mas_completo(list(sub["edad"])),
            "genero": canonico_mas_completo(list(sub["genero"])),
            "ubicacion": canonico_mas_completo(list(sub["ubicacion"])),
            "n_reportes": len(miembros),
            "estados_todos": " | ".join(sorted({e for e in sub["estado"] if e})),
            "estado_resuelto": estado_grupo[cid],
            "fecha_primer_reporte": min(fechas) if fechas else "",
            "fecha_ultimo_reporte": max(fechas) if fechas else "",
            "confianza_min": round(conf_min_grupo[cid], 1),
            "revisar_manual": len(miembros) > 1 and conf_min_grupo[cid] < args.umbral_auto,
            "telefonos": " ".join(sorted({t for tl in sub["tels_norm"] for t in tl.split()})),
            # Enlaces conservados completos (base para comparador de imágenes futuro)
            "uuids_miembros": " | ".join(sub["uuid"]),
            "urls_reporte": " | ".join(u for u in sub["url_reporte"] if u),
            "fotos_urls": " | ".join(u for u in sub["foto_url"] if u),
        })
    df_b = pd.DataFrame(filas_b).sort_values("cluster_id")
    ruta_b = os.path.join(args.output_dir, "personas_unicas.csv")
    df_b.to_csv(ruta_b, index=False)
    print(f"Escrito: {ruta_b}")

    # --- Salida C: pares para revisión (deduplicados, mayor score gana) ---
    if pares_revisar:
        mejores = {}
        for a, b, sc, mo in pares_revisar:
            key = (a, b) if a < b else (b, a)
            if key not in mejores or sc > mejores[key][0]:
                mejores[key] = (sc, mo)
        filas_c = [{
            "uuid_a": df.iloc[a]["uuid"], "nombre_a": df.iloc[a]["nombre"],
            "uuid_b": df.iloc[b]["uuid"], "nombre_b": df.iloc[b]["nombre"],
            "score": sc, "motivo": mo,
        } for (a, b), (sc, mo) in sorted(mejores.items(), key=lambda kv: -kv[1][0])]
        ruta_c = os.path.join(args.output_dir, "pares_revisar.csv")
        pd.DataFrame(filas_c).to_csv(ruta_c, index=False)
        print(f"Escrito: {ruta_c}  ({len(filas_c)} pares)")

    # --- Resumen ---
    n_personas = len(miembros_de)
    n_dup_grupos = sum(1 for m in miembros_de.values() if len(m) > 1)
    n_colapsados = n - n_personas
    print("\n===== RESUMEN =====")
    print(f"Reportes totales : {n}")
    print(f"Personas únicas  : {n_personas}")
    print(f"Grupos con dups  : {n_dup_grupos}")
    print(f"Reportes colapsados (duplicados): {n_colapsados}")
    print(f"Marcados revisar_manual (grupos): "
          f"{sum(1 for cid in miembros_de if conf_min_grupo[cid] < args.umbral_auto and len(miembros_de[cid]) > 1)}")
    print("Estado resuelto por persona:")
    print(f"  Resuelto : {sum(1 for v in estado_grupo.values() if v == 'Resuelto')}")
    print(f"  Se busca : {sum(1 for v in estado_grupo.values() if v == 'Se busca')}")

    _validar(df)


# --------------------------------------------------------------------------- #
# Validación: casos de duplicado confirmados a mano deben quedar agrupados
# --------------------------------------------------------------------------- #

def _validar(df):
    print("\n===== VALIDACIÓN (invariantes, sin datos personales) =====")
    # Invariante clave: nadie puede tener dos cédulas válidas distintas.
    contam = df.groupby("cluster_id")["cedula_norm"].apply(lambda s: s[s != ""].nunique())
    n_contam = int((contam > 1).sum())
    print(f"  Clusters con >1 cédula distinta: {n_contam}  "
          f"[{'OK' if n_contam == 0 else 'FALLA'}]")
    tam = df.groupby("cluster_id").size()
    print(f"  Tamaño de cluster -> máx {tam.max()}, media {tam.mean():.2f}")

    # Casos de prueba con nombres reales: OPCIONALES y PRIVADOS. Para no exponer
    # datos personales en el repositorio, viven en casos_prueba.json (gitignored).
    # Formato: {"deben_agrupar": ["nombre normalizado", ...],
    #           "no_forzar":     ["nombre normalizado", ...]}
    ok = n_contam == 0
    if os.path.exists("casos_prueba.json"):
        import json
        casos = json.load(open("casos_prueba.json", encoding="utf-8"))
        for nombre in casos.get("deben_agrupar", []):
            sel = df[df["nombre_norm"] == nombre]
            bien = len(sel) > 1 and sel["cluster_id"].nunique() == 1
            ok = ok and bien
            print(f"  [debe agrupar] {nombre!r}: {len(sel)} reportes -> "
                  f"{sel['cluster_id'].nunique()} grupo(s)  [{'OK' if bien else 'REVISAR'}]")
        for nombre in casos.get("no_forzar", []):
            sel = df[df["nombre_norm"] == nombre]
            print(f"  [solo nombre, no se fuerza] {nombre!r}: {len(sel)} reportes -> "
                  f"{sel['cluster_id'].nunique()} grupo(s)")
    print("  Resultado:", "OK" if ok else "FALLA")


if __name__ == "__main__":
    main()
