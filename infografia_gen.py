"""
Genera docs/infografia.html (trilingüe: ES/EN/FR) desde la base de-duplicada.

Lee data/processed/{personas_unicas,reportes_dedup}.csv, calcula las cifras,
incrusta el logo de OLDS (assets/olds_logo.png) como data-URI y estampa la
fecha/hora de actualización en hora de Venezuela (UTC−4). El toggle de idioma
intercambia el texto vía JS (con fallback en español si no hay JS). Las cifras
se localizan por idioma (separadores de miles y decimales).

Uso:
  python infografia_gen.py
"""

import base64
import json
import re
import unicodedata
from datetime import datetime, timezone, timedelta

import pandas as pd

PU = "data/processed/personas_unicas.csv"
RD = "data/processed/reportes_dedup.csv"
LOGO = "assets/olds_logo.png"
OUT = "docs/infografia.html"
LANGS = ["es", "en", "fr"]

CIUDADES = ["catia la mar", "la guaira", "caraballeda", "naiguata", "tanaguarena",
            "carayaca", "maiquetia", "macuto", "caracas", "carmen de uria",
            "los caracas", "chichiriviche", "el junko", "camuri", "anare",
            "la sabana", "todasana", "osma", "oricao"]
MES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]
MES_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]
MON_EN = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
MARK = re.compile(r"\b(calle|av|avenida|edif|edificio|sector|urb|urbanizacion|callejon|"
                  r"carrera|manzana|casa|quinta|hospital|colegio|liceo|escuela|plaza|"
                  r"terminal|aeropuerto|estacion|km|playa|muelle|puerto|hotel|posada|"
                  r"iglesia|residencia|conjunto|barrio|parroquia|kilometro|entrada|club)\b")


def qa(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def fmt_int(n, lang):
    s = f"{int(round(n)):,}"
    if lang == "es":
        return s.replace(",", ".")
    if lang == "fr":
        return s.replace(",", " ")
    return s

def fmt_pct(x, lang):       # x en 0..100, 1 decimal
    s = f"{x:.1f}"
    if lang == "en":
        return s + "%"
    s = s.replace(".", ",")
    return s + (" %" if lang == "fr" else "%")

def fmt_pcti(x, lang):      # porcentaje entero
    s = f"{int(round(x))}"
    return s + (" %" if lang == "fr" else "%")

def ciudad(s):
    t = qa(s.lower())
    for c in CIUDADES:
        if c in t:
            return c.title()
    return "__OTRAS__"

def nivel_ubic(s):
    t = qa(s.lower()).strip()
    if not t:
        return "vacio"
    toks = len(t.split())
    comma = "," in s
    if MARK.search(t) or (comma and toks >= 4):
        return "dir"
    if comma or toks >= 3:
        return "barrio"
    return "ciudad"


# --------------------------------------------------------------------------- #
# Cadenas traducibles
# --------------------------------------------------------------------------- #
S = {
 "lang_label": {"es": "Idioma", "en": "Language", "fr": "Langue"},
 "eyebrow": {"es": "Terremoto de Venezuela · 2026 · Estado La Guaira",
             "en": "Venezuela earthquake · 2026 · La Guaira State",
             "fr": "Séisme au Venezuela · 2026 · État de La Guaira"},
 "h1": {"es": "Personas reportadas desaparecidas",
        "en": "People reported missing",
        "fr": "Personnes portées disparues"},
 "stand": {
  "es": 'Retrato de la base <b style="color:#fff">de-duplicada</b>: una fila por persona, no por reporte. Datos ciudadanos en abierto, <b style="color:#fff">sin verificar</b>; información indicativa para apoyar la localización.',
  "en": 'A snapshot of the <b style="color:#fff">de-duplicated</b> dataset: one row per person, not per report. Open, citizen-sourced and <b style="color:#fff">unverified</b> data; indicative information to help locate people.',
  "fr": 'Un aperçu de la base <b style="color:#fff">dédoublonnée</b> : une ligne par personne, et non par signalement. Données citoyennes ouvertes et <b style="color:#fff">non vérifiées</b> ; information indicative pour aider à localiser les personnes.'},
 "updated": {"es": "Actualizado:", "en": "Updated:", "fr": "Mis à jour :"},
 "prov_raw": {"es": "reportes crudos", "en": "raw reports", "fr": "signalements bruts"},
 "prov_dedup": {"es": "deduplicación conservadora", "en": "conservative deduplication", "fr": "déduplication prudente"},
 "prov_unique": {"es": "personas únicas", "en": "unique people", "fr": "personnes uniques"},
 "prov_dups": {"es": "reportes repetidos descartados", "en": "duplicate reports removed", "fr": "signalements en double retirés"},
 "src_tag": {"es": "Fuentes en expansión", "en": "Sources expanding", "fr": "Sources en expansion"},
 "src_body": {
  "es": "Por ahora los datos provienen <b>únicamente de Venezuela Reporta</b>. Se están integrando otras bases de datos para ampliar la cobertura; las cifras crecerán al sumar nuevas fuentes.",
  "en": "For now the data comes <b>solely from Venezuela Reporta</b>. Other databases are being integrated to expand coverage; the figures will grow as new sources are added.",
  "fr": "Pour l’instant, les données proviennent <b>uniquement de Venezuela Reporta</b>. D’autres bases de données sont en cours d’intégration pour élargir la couverture ; les chiffres augmenteront avec l’ajout de nouvelles sources."},
 "method": {
  "es": '<b>Cómo se de-duplicó.</b> Los reportes se agrupan en personas con reglas + coincidencia aproximada de texto: la <b>misma cédula</b> identifica a la misma persona; cuando no hay cédula, se exige que el <b>nombre</b> coincida y que además lo respalde la <b>edad, el sexo o una ubicación específica</b>. Cédulas distintas nunca se unen. El criterio es deliberadamente <b>conservador</b>: ante la duda no fusiona —es preferible un duplicado de más que juntar por error a dos personas distintas—.',
  "en": '<b>How de-duplication works.</b> Reports are grouped into people using rules + approximate text matching: the <b>same ID number</b> identifies the same person; when there is no ID, the <b>name</b> must match and be backed by <b>age, sex or a specific location</b>. Different ID numbers are never merged. The approach is deliberately <b>conservative</b>: when in doubt it does not merge —better an extra duplicate than wrongly merging two different people—.',
  "fr": '<b>Comment fonctionne le dédoublonnage.</b> Les signalements sont regroupés par personne via des règles + correspondance approximative de texte : un <b>même numéro de pièce d’identité</b> désigne la même personne ; à défaut, le <b>nom</b> doit correspondre et être confirmé par <b>l’âge, le sexe ou un lieu précis</b>. Des numéros différents ne sont jamais fusionnés. L’approche est délibérément <b>prudente</b> : en cas de doute, pas de fusion —mieux vaut un doublon de trop que fusionner par erreur deux personnes différentes—.'},
 "kpi_total": {"es": "Personas únicas", "en": "Unique people", "fr": "Personnes uniques"},
 "kpi_total_d": {"es": "de {rep} reportes", "en": "from {rep} reports", "fr": "sur {rep} signalements"},
 "kpi_busca": {"es": "Aún en búsqueda", "en": "Still missing", "fr": "Toujours recherchées"},
 "kpi_busca_d": {"es": "{p} de las personas", "en": "{p} of people", "fr": "{p} des personnes"},
 "kpi_res": {"es": "Encontradas o a salvo", "en": "Found or safe", "fr": "Retrouvées ou en sécurité"},
 "kpi_res_d": {"es": "{p} de las personas", "en": "{p} of people", "fr": "{p} des personnes"},
 "kpi_dup": {"es": "Reportes duplicados", "en": "Duplicate reports", "fr": "Signalements en double"},
 "kpi_dup_d": {"es": "misma persona, varias veces", "en": "same person, multiple times", "fr": "même personne, plusieurs fois"},
 "estado_h2": {"es": "Estado de la búsqueda", "en": "Search status", "fr": "Statut des recherches"},
 "estado_sub": {
  "es": "Una persona se cuenta como resuelta si <em>cualquiera</em> de sus reportes la marca encontrada o a salvo.",
  "en": "A person counts as resolved if <em>any</em> of their reports marks them found or safe.",
  "fr": "Une personne est comptée comme résolue si <em>l’un</em> de ses signalements l’indique retrouvée ou en sécurité."},
 "leg_busca": {"es": "Aún en búsqueda", "en": "Still missing", "fr": "Toujours recherchées"},
 "leg_res": {"es": "Encontradas / a salvo", "en": "Found / safe", "fr": "Retrouvées / en sécurité"},
 "sexo_h2": {"es": "Sexo", "en": "Sex", "fr": "Sexe"},
 "sexo_sub": {
  "es": "Inferido por persona (reportado → nombre → descripción). Cobertura {cov}.",
  "en": "Inferred per person (reported → name → description). Coverage {cov}.",
  "fr": "Déduit par personne (déclaré → nom → description). Couverture {cov}."},
 "male": {"es": "Masculino", "en": "Male", "fr": "Homme"},
 "female": {"es": "Femenino", "en": "Female", "fr": "Femme"},
 "unknown": {"es": "Desconocido", "en": "Unknown", "fr": "Inconnu"},
 "other": {"es": "Otro", "en": "Other", "fr": "Autre"},
 "sex_unknown": {"es": "Sexo sin dato", "en": "Sex unknown", "fr": "Sexe inconnu"},
 "edad_h2": {"es": "Rango de edad", "en": "Age range", "fr": "Tranche d’âge"},
 "edad_sub": {
  "es": "Grupos de vulnerabilidad estándar (UN OCHA). Inferido por persona; grupo de edad asignado al {cov}.",
  "en": "Standard vulnerability groups (UN OCHA). Inferred per person; age group assigned for {cov}.",
  "fr": "Groupes de vulnérabilité standard (UN OCHA). Déduit par personne ; tranche d’âge attribuée pour {cov}."},
 "age_04": {"es": "0–4 (primera infancia)", "en": "0–4 (early childhood)", "fr": "0–4 (petite enfance)"},
 "age_517": {"es": "5–17 (NNA)", "en": "5–17 (children & adolescents)", "fr": "5–17 (enfants & adolescents)"},
 "age_1859": {"es": "18–59 (adultos)", "en": "18–59 (adults)", "fr": "18–59 (adultes)"},
 "age_60": {"es": "60+ (adultos mayores)", "en": "60+ (older adults)", "fr": "60+ (personnes âgées)"},
 "age_nd": {"es": "Sin dato", "en": "No data", "fr": "Sans donnée"},
 "pyr_h2": {"es": "Pirámide poblacional", "en": "Population pyramid", "fr": "Pyramide des âges"},
 "pyr_sub": {
  "es": "Personas por sexo y grupo de edad (UN OCHA). El gris al centro = sin sexo determinado; la franja inferior = sin edad conocida. La incertidumbre del dato se muestra, no se oculta.",
  "en": "People by sex and age group (UN OCHA). Grey in the centre = sex not determined; the bottom band = age unknown. Data uncertainty is shown, not hidden.",
  "fr": "Personnes par sexe et tranche d’âge (UN OCHA). Le gris au centre = sexe non déterminé ; la bande du bas = âge inconnu. L’incertitude des données est montrée, pas masquée."},
 "pyr_nd": {"es": "Edad<br>sin dato", "en": "Age<br>unknown", "fr": "Âge<br>inconnu"},
 "pyr_note": {
  "es": "Porcentajes sobre el total de personas ({tot}). Masculino + Femenino = {mf}; el {ss} restante es <b>sexo sin dato</b> (gris al centro).",
  "en": "Percentages of all people ({tot}). Male + Female = {mf}; the remaining {ss} is <b>sex unknown</b> (grey, centre).",
  "fr": "Pourcentages sur l’ensemble des personnes ({tot}). Homme + Femme = {mf} ; les {ss} restants sont <b>sexe inconnu</b> (gris, au centre)."},
 "ubic_h2": {"es": "Ubicaciones, a grandes rasgos", "en": "Locations, broadly", "fr": "Localisations, en gros"},
 "ubic_sub": {
  "es": "Personas por localidad (clasificadas por palabra clave sobre el texto de ubicación). El terremoto golpeó la franja costera de La Guaira.",
  "en": "People by locality (classified by keyword over the location text). The earthquake struck the La Guaira coastal strip.",
  "fr": "Personnes par localité (classées par mot-clé sur le texte de localisation). Le séisme a frappé la bande côtière de La Guaira."},
 "otras": {"es": "Otras / sin clasificar", "en": "Other / unclassified", "fr": "Autres / non classé"},
 "cal_h2": {"es": "¿Qué tan bien sirven estas ubicaciones para un mapa?",
            "en": "How usable are these locations for a map?",
            "fr": "Ces localisations sont-elles exploitables pour une carte ?"},
 "cal_sub": {
  "es": "Toda persona tiene una ubicación (cobertura 100%), pero la precisión varía. Clasificación por nivel de detalle geográfico del texto.",
  "en": "Everyone has a location (100% coverage), but precision varies. Classified by the geographic detail level of the text.",
  "fr": "Chaque personne a une localisation (couverture 100 %), mais la précision varie. Classement selon le niveau de détail géographique du texte."},
 "q_ciudad_t": {"es": "Solo ciudad / municipio", "en": "City / municipality only", "fr": "Ville / municipalité seulement"},
 "q_ciudad_b": {"es": "{n} personas. Geocodifica al centro de la localidad, no a un punto.",
                "en": "{n} people. Geocodes to the locality centre, not a point.",
                "fr": "{n} personnes. Géocode au centre de la localité, pas à un point."},
 "q_barrio_t": {"es": "Barrio o sector", "en": "Neighbourhood or sector", "fr": "Quartier ou secteur"},
 "q_barrio_b": {"es": "{n} personas. Acerca a una zona, sin dirección exacta.",
                "en": "{n} people. Narrows to an area, no exact address.",
                "fr": "{n} personnes. Cible une zone, sans adresse exacte."},
 "q_dir_t": {"es": "Dirección o lugar específico", "en": "Address or specific place", "fr": "Adresse ou lieu précis"},
 "q_dir_b": {"es": "{n} personas. Calle, edificio, hospital, playa… geocodificable a un punto.",
             "en": "{n} people. Street, building, hospital, beach… geocodable to a point.",
             "fr": "{n} personnes. Rue, bâtiment, hôpital, plage… géocodable à un point."},
 "cal_note": {
  "es": "<b>Hallazgo para el mapa:</b> los campos estructurados de dirección vienen casi vacíos —<b>dirección precisa {dir}</b>, última ubicación {ult}, zona/barrio {zona}—. Todo el detalle geográfico está embebido en el texto libre de <code>ubicacion</code>. Un mapa exigirá <b>geocodificación con NLP</b> sobre ese texto.",
  "en": "<b>Finding for the map:</b> the structured address fields are almost empty —<b>precise address {dir}</b>, last location {ult}, zone/neighbourhood {zona}—. All geographic detail is embedded in the free text of <code>ubicacion</code>. A map will require <b>NLP geocoding</b> over that text.",
  "fr": "<b>Constat pour la carte :</b> les champs d’adresse structurés sont presque vides —<b>adresse précise {dir}</b>, dernière localisation {ult}, zone/quartier {zona}—. Tout le détail géographique est intégré dans le texte libre de <code>ubicacion</code>. Une carte nécessitera un <b>géocodage par NLP</b> sur ce texte."},
 "credit": {
  "es": 'Elaborado por el <b><a href="https://www.olds2030.org/">Observatorio Latinoamericano de Desarrollo Sostenible</a></b> con datos ciudadanos compartidos en abierto sin verificar. La información es <b>indicativa</b> y debe utilizarse con cuidado y contrastar con otras fuentes.',
  "en": 'Produced by the <b><a href="https://www.olds2030.org/">Latin American Observatory for Sustainable Development</a></b> with open, citizen-sourced, unverified data. The information is <b>indicative</b> and must be used with care and cross-checked against other sources.',
  "fr": 'Réalisé par l’<b><a href="https://www.olds2030.org/">Observatoire latino-américain du développement durable</a></b> à partir de données citoyennes ouvertes et non vérifiées. L’information est <b>indicative</b> et doit être utilisée avec prudence et recoupée avec d’autres sources.'},
 "source": {
  "es": '<b>Fuente de datos (en expansión):</b> por ahora únicamente Venezuela Reporta — registro comunitario humanitario, sin verificar (<a href="https://venezuelareporta.org/buscar">venezuelareporta.org</a>). Se están integrando otras bases de datos. Cifras por persona sobre la base de-duplicada ({tot} personas de {rep} reportes).',
  "en": '<b>Data source (expanding):</b> for now only Venezuela Reporta — a humanitarian community registry, unverified (<a href="https://venezuelareporta.org/buscar">venezuelareporta.org</a>). Other databases are being integrated. Figures are per person over the de-duplicated dataset ({tot} people from {rep} reports).',
  "fr": '<b>Source des données (en expansion) :</b> pour l’instant uniquement Venezuela Reporta — registre communautaire humanitaire, non vérifié (<a href="https://venezuelareporta.org/buscar">venezuelareporta.org</a>). D’autres bases de données sont en cours d’intégration. Chiffres par personne sur la base dédoublonnée ({tot} personnes sur {rep} signalements).'},
 "repo": {
  "es": '<b>Metodología y código abierto:</b> <a href="https://github.com/alcastaro/venezuela-missing-persons-dedup">github.com/alcastaro/venezuela-missing-persons-dedup</a> — ahí se puede revisar el método de deduplicación y contribuir.',
  "en": '<b>Methodology & open source:</b> <a href="https://github.com/alcastaro/venezuela-missing-persons-dedup">github.com/alcastaro/venezuela-missing-persons-dedup</a> — review the deduplication method and contribute.',
  "fr": '<b>Méthodologie et code ouvert :</b> <a href="https://github.com/alcastaro/venezuela-missing-persons-dedup">github.com/alcastaro/venezuela-missing-persons-dedup</a> — pour consulter la méthode de déduplication et contribuer.'},
 "method_foot": {
  "es": '<b>Método:</b> deduplicación conservadora (cédulas distintas no se fusionan; el nombre solo no basta sin corroboración por edad, sexo o lugar específico). Sexo y edad inferidos 100% offline, nunca inventados: vacío cuando no hay señal.',
  "en": '<b>Method:</b> conservative deduplication (different ID numbers are not merged; name alone is not enough without corroboration by age, sex or specific location). Sex and age inferred 100% offline, never fabricated: blank when there is no signal.',
  "fr": '<b>Méthode :</b> déduplication prudente (des numéros différents ne sont pas fusionnés ; le nom seul ne suffit pas sans confirmation par âge, sexe ou lieu précis). Sexe et âge déduits 100% hors ligne, jamais inventés : vide en l’absence de signal.'},
 "use": {
  "es": '<b>Uso responsable:</b> contiene datos personales sensibles de población vulnerable. Usar solo para apoyar su localización; no redistribuir contactos fuera de ese fin.',
  "en": '<b>Responsible use:</b> contains sensitive personal data of vulnerable people. Use only to support locating them; do not redistribute contacts beyond that purpose.',
  "fr": '<b>Usage responsable :</b> contient des données personnelles sensibles de personnes vulnérables. À utiliser uniquement pour aider à les localiser ; ne pas rediffuser les contacts au-delà de cette finalité.'},
 "authors": {
  "es": 'Autoría: <a href="https://www.olds2030.org/">OLDS2030</a> · desarrollo e infografía por <a href="https://github.com/juanacasique">Juana Casique</a> y <a href="https://github.com/alcastaro">Alcastaro</a>.',
  "en": 'Authorship: <a href="https://www.olds2030.org/">OLDS2030</a> · development and infographic by <a href="https://github.com/juanacasique">Juana Casique</a> and <a href="https://github.com/alcastaro">Alcastaro</a>.',
  "fr": 'Auteurs : <a href="https://www.olds2030.org/">OLDS2030</a> · développement et infographie par <a href="https://github.com/juanacasique">Juana Casique</a> et <a href="https://github.com/alcastaro">Alcastaro</a>.'},
}


def bar(name, cnt, total, width, lang, color=None, muted=False):
    col = f";background:{color}" if color else ""
    nm = ' style="color:var(--muted)"' if muted else ""
    return (f'<div class="bar"><span class="name"{nm}>{name}</span>'
            f'<span class="track"><span class="fill" style="--w:{width:.1f}%{col}"></span></span>'
            f'<span class="val">{fmt_int(cnt,lang)}<small>{fmt_pct(100*cnt/total,lang)}</small></span></div>')


def main():
    pu = pd.read_csv(PU, dtype=str, keep_default_na=False)
    rd = pd.read_csv(RD, dtype=str, keep_default_na=False)
    N = len(pu)
    reportes = len(rd)
    dup = reportes - N
    se_busca = int((pu["estado_resuelto"] == "Se busca").sum())
    resuelto = int((pu["estado_resuelto"] == "Resuelto").sum())
    p_busca = 100 * se_busca / N

    sx = pu["sexo_inferido"].value_counts().to_dict()
    F, M = sx.get("Femenino", 0), sx.get("Masculino", 0)
    DESC, OTRO = sx.get("Desconocido", 0), sx.get("Otro", 0)
    sin_sexo = DESC + OTRO
    cov_sexo = 100 * (F + M + OTRO) / N
    maxsx = max(F, M, DESC, OTRO)

    ge = pu["grupo_edad"].replace("", "Sin dato")
    ec = ge.value_counts().to_dict()
    e = {k: ec.get(k, 0) for k in ["0-4", "5-17", "18-59", "60+", "Sin dato"]}
    maxe = max(e.values())
    edad_cov = 100 * (N - e["Sin dato"]) / N

    pu["_ge"] = ge
    ct = pd.crosstab(pu["_ge"], pu["sexo_inferido"])
    for c in ["Masculino", "Femenino", "Desconocido", "Otro"]:
        if c not in ct.columns:
            ct[c] = 0
    def cell(b):
        if b not in ct.index:
            return 0, 0, 0
        return (int(ct.loc[b, "Masculino"]), int(ct.loc[b, "Femenino"]),
                int(ct.loc[b, "Desconocido"]) + int(ct.loc[b, "Otro"]))
    bands = [("60+", "60+"), ("18–59", "18-59"), ("5–17", "5-17"), ("0–4", "0-4")]
    band_data = [(lbl, *cell(key)) for lbl, key in bands]
    sdm, sdf, sdu = cell("Sin dato")
    maxcell = max([max(b[1], b[2]) for b in band_data] + [max(sdm, sdf)])

    cc = pu["ubicacion"].map(ciudad).value_counts()
    nombradas = [(k, int(v)) for k, v in cc.items() if k != "__OTRAS__"][:8]
    otras = int(cc.get("__OTRAS__", 0))
    maxc = nombradas[0][1] if nombradas else 1

    niv = pu["ubicacion"].map(nivel_ubic).value_counts().to_dict()
    n_ciudad = niv.get("ciudad", 0) + niv.get("vacio", 0)
    n_barrio = niv.get("barrio", 0)
    n_dir = niv.get("dir", 0)
    def cob(col):
        g = rd.groupby("cluster_id")[col].apply(lambda s: (s.str.strip() != "").any())
        return 100 * int(g.sum()) / N
    zona_p, dir_p, ult_p = cob("zona_barrio"), cob("direccion_precisa"), cob("ultima_ubicacion")

    logo = "data:image/png;base64," + base64.b64encode(open(LOGO, "rb").read()).decode()
    now = datetime.now(timezone(timedelta(hours=-4)))
    hm = now.strftime("%H:%M")
    TS = {"es": f"{now.day} de {MES_ES[now.month-1]} de {now.year}, {hm} (hora de Venezuela, UTC−4)",
          "en": f"{MON_EN[now.month-1]} {now.day}, {now.year}, {hm} (Venezuela time, UTC−4)",
          "fr": f"{now.day} {MES_FR[now.month-1]} {now.year}, {hm} (heure du Venezuela, UTC−4)"}

    def kpi(cls, n, lbl, delta):
        c = f" {cls}" if cls else ""
        return f'<div class="kpi{c}"><div class="n">{n}</div><div class="lbl">{lbl}</div><div class="delta">{delta}</div></div>'

    def leg(color, n, p, t):
        return (f'<div class="leg"><span class="dot" style="background:{color}"></span>'
                f'<div><div class="v">{n} <small>· {p}</small></div><div class="t">{t}</div></div></div>')

    def pyr_row(label, m, f, u, lang, nodata=False):
        wm, wf, wu = 100*m/maxcell, 100*f/maxcell, 100*(u/2)/maxcell
        cls = "pyr-row nodata" if nodata else "pyr-row"
        return (f'<div class="{cls}">'
                f'<div class="pyr-side left"><span class="v">{fmt_int(m,lang)}<small>{fmt_pct(100*m/N,lang)}</small></span>'
                f'<span class="bar m" style="--w:{wm:.1f}%"></span><span class="bar u" style="--w:{wu:.2f}%"></span></div>'
                f'<div class="pyr-label">{label}</div>'
                f'<div class="pyr-side right"><span class="bar u" style="--w:{wu:.2f}%"></span>'
                f'<span class="bar f" style="--w:{wf:.1f}%"></span>'
                f'<span class="v">{fmt_int(f,lang)}<small>{fmt_pct(100*f/N,lang)}</small></span></div></div>')

    def build(lang):
        L = lambda k: S[k][lang]
        d = {}
        d["lang_label"] = L("lang_label")
        d["eyebrow"] = L("eyebrow")
        d["h1"] = L("h1")
        d["stand"] = L("stand")
        d["updated"] = f'{L("updated")} <b>{TS[lang]}</b>'
        d["provenance"] = (
            f'<span class="flow"><b>{fmt_int(reportes,lang)}</b>&nbsp;{L("prov_raw")}</span>'
            f'<span class="flow"><span class="arrow">→</span> {L("prov_dedup")}</span>'
            f'<span class="flow"><span class="arrow">→</span> <b>{fmt_int(N,lang)}</b>&nbsp;{L("prov_unique")}</span>'
            f'<span style="color:var(--muted)">({fmt_int(dup,lang)} {L("prov_dups")}, {fmt_pcti(100*dup/reportes,lang)})</span>')
        d["srcnote"] = f'<span class="tag">{L("src_tag")}</span><span>{L("src_body")}</span>'
        d["method"] = L("method")
        d["kpis"] = (
            kpi("", fmt_int(N,lang), L("kpi_total"), L("kpi_total_d").format(rep=fmt_int(reportes,lang)))
            + kpi("amber", fmt_int(se_busca,lang), L("kpi_busca"), L("kpi_busca_d").format(p=fmt_pct(p_busca,lang)))
            + kpi("green", fmt_int(resuelto,lang), L("kpi_res"), L("kpi_res_d").format(p=fmt_pct(100*resuelto/N,lang)))
            + kpi("slate", fmt_pcti(100*dup/reportes,lang), L("kpi_dup"), L("kpi_dup_d")))
        d["estado_h2"] = L("estado_h2")
        d["estado_sub"] = L("estado_sub")
        d["estado_legend"] = (
            leg("var(--blue)", fmt_int(se_busca,lang), fmt_pct(p_busca,lang), L("leg_busca"))
            + leg("var(--green)", fmt_int(resuelto,lang), fmt_pct(100*resuelto/N,lang), L("leg_res")))
        d["sexo_h2"] = L("sexo_h2")
        d["sexo_sub"] = L("sexo_sub").format(cov=fmt_pcti(cov_sexo,lang))
        d["sexo_bars"] = "".join([
            bar(L("female"), F, N, 100*F/maxsx, lang, "var(--blue-bright)"),
            bar(L("male"), M, N, 100*M/maxsx, lang, "var(--blue-deep)"),
            bar(L("unknown"), DESC, N, 100*DESC/maxsx, lang, "var(--slate)"),
            bar(L("other"), OTRO, N, 100*OTRO/maxsx, lang, "var(--blue-soft)")])
        d["edad_h2"] = L("edad_h2")
        d["edad_sub"] = L("edad_sub").format(cov=fmt_pcti(edad_cov,lang))
        d["edad_bars"] = "".join([
            bar(L("age_04"), e["0-4"], N, 100*e["0-4"]/maxe, lang, "var(--blue-soft)"),
            bar(L("age_517"), e["5-17"], N, 100*e["5-17"]/maxe, lang, "#7ec0e8"),
            bar(L("age_1859"), e["18-59"], N, 100*e["18-59"]/maxe, lang, "var(--blue)"),
            bar(L("age_60"), e["60+"], N, 100*e["60+"]/maxe, lang, "var(--blue-deep)"),
            bar(L("age_nd"), e["Sin dato"], N, 100*e["Sin dato"]/maxe, lang, "var(--slate)")])
        head = (f'<div class="pyr-head"><span class="l">◀ {L("male")}</span><span></span>'
                f'<span class="r">{L("female")} ▶</span></div>')
        rows = "".join([pyr_row(lbl, m, f, u, lang) for lbl, m, f, u in band_data])
        rows += pyr_row(L("pyr_nd"), sdm, sdf, sdu, lang, nodata=True)
        d["pyramid"] = head + rows
        d["pyr_h2"] = L("pyr_h2")
        d["pyr_sub"] = L("pyr_sub")
        d["pyr_note"] = L("pyr_note").format(tot=fmt_int(N,lang), mf=fmt_pct(100*(M+F)/N,lang),
                                             ss=fmt_pct(100*sin_sexo/N,lang))
        d["pyr_legend"] = (
            f'<span class="leg"><span class="dot" style="background:var(--blue-deep)"></span>{L("male")} · {fmt_int(M,lang)} ({fmt_pct(100*M/N,lang)})</span>'
            f'<span class="leg"><span class="dot" style="background:var(--blue-bright)"></span>{L("female")} · {fmt_int(F,lang)} ({fmt_pct(100*F/N,lang)})</span>'
            f'<span class="leg"><span class="dot" style="background:var(--slate);opacity:.7"></span>{L("sex_unknown")} · {fmt_int(sin_sexo,lang)} ({fmt_pct(100*sin_sexo/N,lang)})</span>')
        d["ubic_h2"] = L("ubic_h2")
        d["ubic_sub"] = L("ubic_sub")
        d["city_bars"] = ("".join([bar(k, v, N, 100*v/maxc, lang, "var(--blue)") for k, v in nombradas])
                          + bar(L("otras"), otras, N, 100*otras/maxc, lang, "var(--slate)", muted=True))
        d["cal_h2"] = L("cal_h2")
        d["cal_sub"] = L("cal_sub")
        d["qcards"] = (
            f'<div class="qcard low"><div class="p" style="color:var(--muted)">{fmt_pct(100*n_ciudad/N,lang)}</div><div class="k"><b>{L("q_ciudad_t")}</b><br>{L("q_ciudad_b").format(n=fmt_int(n_ciudad,lang))}</div></div>'
            f'<div class="qcard mid"><div class="p" style="color:var(--blue)">{fmt_pct(100*n_barrio/N,lang)}</div><div class="k"><b>{L("q_barrio_t")}</b><br>{L("q_barrio_b").format(n=fmt_int(n_barrio,lang))}</div></div>'
            f'<div class="qcard good"><div class="p" style="color:var(--green)">{fmt_pct(100*n_dir/N,lang)}</div><div class="k"><b>{L("q_dir_t")}</b><br>{L("q_dir_b").format(n=fmt_int(n_dir,lang))}</div></div>')
        d["cal_note"] = L("cal_note").format(dir=fmt_pct(dir_p,lang), ult=fmt_pct(ult_p,lang), zona=fmt_pct(zona_p,lang))
        d["credit"] = L("credit")
        d["source"] = L("source").format(tot=fmt_int(N,lang), rep=fmt_int(reportes,lang))
        d["repo"] = L("repo")
        d["method_foot"] = L("method_foot")
        d["use"] = L("use")
        d["authors"] = L("authors")
        return d

    REG = {lang: build(lang) for lang in LANGS}
    es = REG["es"]
    i18n_json = json.dumps(REG, ensure_ascii=False).replace("</", "<\\/")

    html = TEMPLATE
    html = html.replace("__LOGO__", logo)
    html = html.replace("__DONUT_P__", f"{p_busca:.1f}")
    html = html.replace("__I18N_JSON__", i18n_json)
    for k, v in es.items():
        html = html.replace("@@" + k + "@@", v)
    open(OUT, "w", encoding="utf-8").write(html)
    left = re.findall(r"@@[a-z_]+@@", html)
    print(f"Escrito: {OUT}  ({len(html)} bytes)  tokens pendientes: {set(left) or 'ninguno'}")
    print(f"  personas={fmt_int(N,'es')} se_busca={fmt_int(se_busca,'es')} resuelto={fmt_int(resuelto,'es')}")
    print(f"  actualizado: {TS['es']}")


TEMPLATE = r"""<title>Personas desaparecidas · Venezuela 2026 — base de-duplicada</title>
<meta name="description" content="Retrato de la base de-duplicada de personas reportadas desaparecidas tras el terremoto de Venezuela 2026: sexo, edad, estado y calidad de las ubicaciones. Elaborado por OLDS2030.">
<style>
  :root{
    --paper:#eef3f8; --card:#ffffff; --ink:#13314a; --ink-soft:#4d6075; --muted:#8093a4;
    --line:#d6e1ec; --line-soft:#e9f0f6;
    --blue:#1f8fd0; --blue-deep:#0b4f7a; --navy:#0a3a5c; --blue-bright:#3aa6dd; --blue-soft:#bcdcf0;
    --green:#2f9c6a; --amber:#e0902f; --slate:#a9b9c8;
    --maxw:1060px;
  }
  *{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  body{margin:0; background:var(--paper); color:var(--ink);
    font:400 16px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    font-variant-numeric:tabular-nums;}
  .langbar{position:sticky; top:0; z-index:50; background:var(--navy); color:#fff;
    box-shadow:0 2px 10px rgba(10,58,92,.25);}
  .langbar-in{max-width:var(--maxw); margin:0 auto; padding:8px clamp(18px,4vw,40px);
    display:flex; align-items:center; gap:14px;}
  .langlbl{font-size:.72rem; letter-spacing:.14em; text-transform:uppercase; color:var(--blue-soft); font-weight:700; margin-right:auto;}
  .seg{display:inline-flex; background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.25); border-radius:999px; padding:3px;}
  .langbtn{appearance:none; border:0; background:transparent; color:#dbe9f5; font:inherit;
    font-weight:700; font-size:.85rem; padding:6px 16px; border-radius:999px; cursor:pointer; line-height:1; transition:background .15s,color .15s;}
  .langbtn[aria-pressed="true"]{background:#fff; color:var(--blue-deep);}
  .langbtn:hover{color:#fff;}
  .langbtn[aria-pressed="true"]:hover{color:var(--blue-deep);}
  .langbtn:focus-visible{outline:2px solid #fff; outline-offset:2px;}
  .sdg{height:5px; background:linear-gradient(90deg,
    #e5243b 0 11%,#fd9d24 11% 22%,#fcc30b 22% 33%,#4c9f38 33% 47%,
    #1f8fd0 47% 64%,#19486a 64% 80%,#dd1367 80% 100%);}
  .band{background:linear-gradient(135deg,var(--navy),var(--blue-deep)); color:#fff;}
  .bandwrap{display:flex; gap:22px; align-items:flex-start; justify-content:space-between;
    max-width:var(--maxw); margin:0 auto; padding:clamp(22px,4vw,40px) clamp(18px,4vw,40px);}
  .band .eyebrow{font-size:.72rem; letter-spacing:.18em; text-transform:uppercase; color:var(--blue-soft); font-weight:600;}
  .band h1{font-size:clamp(1.8rem,4.4vw,2.9rem); line-height:1.04; margin:.3em 0 .3em; font-weight:800; letter-spacing:-.01em; text-wrap:balance; max-width:18ch;}
  .band .stand{font-size:clamp(.98rem,1.5vw,1.12rem); color:#dbe9f5; max-width:62ch; text-wrap:pretty;}
  .band .updated{margin-top:14px; font-size:.82rem; color:var(--blue-soft); font-weight:600;}
  .band .updated b{color:#fff; font-weight:700;}
  .brandmark{display:flex; align-items:center; flex:0 0 auto; background:#fff; border-radius:10px; padding:12px 16px;}
  .olds-logo{display:inline-block; background:center/contain no-repeat url("__LOGO__");}
  .olds-logo--hd{width:152px; height:58px;}
  .olds-logo--ft{width:116px; height:45px;}
  .wrap{max-width:var(--maxw); margin:0 auto; padding:clamp(18px,3.5vw,34px) clamp(18px,4vw,40px) clamp(28px,4vw,48px);}
  .provenance{display:flex; flex-wrap:wrap; align-items:center; gap:10px 16px;
    padding:13px 18px; background:var(--card); border:1px solid var(--line); border-left:4px solid var(--blue);
    border-radius:10px; font-size:.95rem; color:var(--ink-soft); margin-top:clamp(-30px,-4vw,-22px); position:relative; box-shadow:0 6px 20px rgba(11,79,122,.07);}
  .provenance b{color:var(--ink); font-weight:700;}
  .flow{display:flex; align-items:center; gap:10px;}
  .flow .arrow{color:var(--blue); font-weight:800;}
  .method{background:#e7f1f9; border:1px solid #c7def0; border-left:4px solid var(--blue-deep);
    border-radius:10px; padding:15px 18px; margin-top:18px; font-size:.95rem; color:#234a64;}
  .method b{color:var(--blue-deep);}
  .srcnote{display:flex; gap:10px; align-items:baseline; margin-top:12px; padding:11px 16px;
    background:#fff; border:1px dashed var(--blue); border-radius:10px; font-size:.88rem; color:var(--ink-soft);}
  .srcnote .tag{flex:0 0 auto; font-size:.66rem; letter-spacing:.08em; text-transform:uppercase;
    font-weight:700; color:#fff; background:var(--blue); border-radius:5px; padding:3px 8px; translate:0 -1px;}
  .srcnote b{color:var(--blue-deep);}
  hr.rule{border:0; border-top:1px solid var(--line); margin:clamp(30px,4.5vw,46px) 0;}
  section{margin-top:clamp(28px,4vw,42px);}
  h2{font-size:1.08rem; letter-spacing:.01em; margin:0 0 4px; font-weight:700; color:var(--navy);}
  .sub{font-size:.9rem; color:var(--muted); margin:0 0 18px; max-width:74ch;}
  .kpis{display:grid; grid-template-columns:repeat(4,1fr); gap:14px;}
  .kpi{background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px; position:relative; overflow:hidden;}
  .kpi::before{content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--blue);}
  .kpi.amber::before{background:var(--amber);} .kpi.green::before{background:var(--green);} .kpi.slate::before{background:var(--muted);}
  .kpi .n{font-size:clamp(1.7rem,3.4vw,2.4rem); font-weight:800; line-height:1; color:var(--navy);}
  .kpi .lbl{margin-top:8px; font-size:.82rem; color:var(--ink-soft);}
  .kpi .delta{font-size:.76rem; color:var(--muted); margin-top:3px;}
  .cols{display:grid; grid-template-columns:1fr 1fr; gap:clamp(20px,3.5vw,40px); align-items:start;}
  .bars{display:flex; flex-direction:column; gap:11px;}
  .bar{display:grid; grid-template-columns:9rem 1fr auto; align-items:center; gap:12px; font-size:.92rem;}
  .bar .name{color:var(--ink); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
  .track{height:14px; background:var(--line-soft); border-radius:7px; overflow:hidden;}
  .fill{height:100%; width:var(--w); border-radius:7px; background:var(--blue);
        transform-origin:left; animation:grow .9s cubic-bezier(.22,.61,.36,1) both;}
  .bar .val{font-weight:700; color:var(--ink); white-space:nowrap;}
  .bar .val small{color:var(--muted); font-weight:400; margin-left:5px;}
  @keyframes grow{from{transform:scaleX(0)} to{transform:scaleX(1)}}
  @media(prefers-reduced-motion:reduce){.fill,.pyr-side .bar{animation:none}}
  .donut-wrap{display:flex; align-items:center; gap:26px; flex-wrap:wrap;}
  .donut{width:168px; height:168px; border-radius:50%; flex:0 0 auto;
    background:conic-gradient(var(--blue) 0 calc(var(--p)*1%), var(--green) 0);
    -webkit-mask:radial-gradient(circle 50px at center,transparent 98%,#000 100%);
            mask:radial-gradient(circle 50px at center,transparent 98%,#000 100%);}
  .legend{display:flex; flex-direction:column; gap:12px;}
  .leg{display:flex; gap:10px; align-items:baseline;}
  .dot{width:11px; height:11px; border-radius:3px; flex:0 0 auto; translate:0 1px;}
  .leg .v{font-weight:700;} .leg .v small{color:var(--muted); font-weight:400; margin-left:4px;}
  .leg .t{font-size:.9rem; color:var(--ink-soft);}
  .pyr{display:flex; flex-direction:column; gap:9px; margin-top:4px;}
  .pyr-head{display:grid; grid-template-columns:1fr 5.4rem 1fr; align-items:center;
    font-size:.74rem; letter-spacing:.1em; text-transform:uppercase; color:var(--muted);}
  .pyr-head .l{text-align:right; padding-right:10px; color:var(--blue-deep); font-weight:700;}
  .pyr-head .r{text-align:left; padding-left:10px; color:var(--blue-bright); font-weight:700;}
  .pyr-row{display:grid; grid-template-columns:1fr 5.4rem 1fr; align-items:center;}
  .pyr-side{display:flex; align-items:center; height:20px; overflow:hidden;}
  .pyr-side.left{justify-content:flex-end;}
  .pyr-side.right{justify-content:flex-start;}
  .pyr-side .bar{height:100%; width:var(--w); min-width:2px; animation:grow .9s cubic-bezier(.22,.61,.36,1) both;}
  .pyr-side.left .bar{transform-origin:right;}
  .pyr-side.right .bar{transform-origin:left;}
  .bar.m{background:var(--blue-deep);}
  .bar.f{background:var(--blue-bright);}
  .bar.u{background:var(--slate); opacity:.7;}
  .pyr-side .v{font-size:.8rem; font-weight:700; color:var(--ink-soft); white-space:nowrap;}
  .pyr-side .v small{font-weight:400; color:var(--muted); margin-left:4px;}
  .pyr-side.left .v{padding-right:8px;} .pyr-side.right .v{padding-left:8px;}
  .pyr-label{text-align:center; font-size:.86rem; color:var(--ink); white-space:nowrap;}
  .pyr-row.nodata{margin-top:6px; padding-top:9px; border-top:1px dashed var(--line);}
  .pyr-row.nodata .pyr-label{color:var(--muted);}
  .pyr-legend{display:flex; gap:20px; flex-wrap:wrap; margin-top:16px; font-size:.86rem; color:var(--ink-soft);}
  .pyr-legend .leg{display:flex; gap:8px; align-items:center;}
  .pyr-legend .dot{width:11px; height:11px; border-radius:3px;}
  .qgrid{display:grid; grid-template-columns:repeat(3,1fr); gap:14px;}
  .qcard{background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px;}
  .qcard .p{font-size:1.9rem; font-weight:800; line-height:1;}
  .qcard .k{font-size:.86rem; color:var(--ink-soft); margin-top:6px;}
  .qcard.good{border-top:4px solid var(--green);} .qcard.mid{border-top:4px solid var(--blue);} .qcard.low{border-top:4px solid var(--muted);}
  .note{background:#e7f1f9; border:1px solid #c7def0; border-left:4px solid var(--blue); border-radius:10px;
        padding:14px 16px; font-size:.92rem; color:#234a64; margin-top:18px;}
  .note b{color:var(--blue-deep);}
  footer{margin-top:clamp(34px,5vw,52px); padding-top:24px; border-top:1px solid var(--line); text-align:center;}
  .credit{display:inline-flex; align-items:center; gap:12px; justify-content:center; flex-wrap:wrap;
    background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 22px; margin:0 auto 16px;
    color:var(--ink-soft); font-size:.92rem; max-width:78ch; text-align:left;}
  .credit b{color:var(--ink);}
  footer p{margin:.55em auto; max-width:80ch; color:var(--muted); font-size:.82rem;}
  footer b{color:var(--ink-soft);}
  footer a{color:var(--blue-deep); font-weight:600; text-decoration:none; border-bottom:1px solid var(--blue-soft);}
  footer a:hover{border-bottom-color:var(--blue-deep);}
  a:focus-visible,.qcard:focus-visible{outline:2px solid var(--blue); outline-offset:2px;}
  @media(max-width:760px){
    .kpis{grid-template-columns:repeat(2,1fr);}
    .cols{grid-template-columns:1fr;}
    .qgrid{grid-template-columns:1fr;}
    .bar{grid-template-columns:7rem 1fr auto;}
    .bandwrap{flex-direction:column; gap:14px;}
    .langlbl{display:none;}
    .langbar-in{justify-content:center;}
  }
</style>

<div class="langbar"><div class="langbar-in">
  <span class="langlbl" data-i18n-html="lang_label">Idioma</span>
  <div class="seg" role="group" aria-label="Idioma / Language / Langue">
    <button type="button" class="langbtn" data-lang="es" aria-pressed="true">Español</button>
    <button type="button" class="langbtn" data-lang="en" aria-pressed="false">English</button>
    <button type="button" class="langbtn" data-lang="fr" aria-pressed="false">Français</button>
  </div>
</div></div>

<div class="sdg"></div>

<header class="band">
  <div class="bandwrap">
    <div>
      <div class="eyebrow" data-i18n-html="eyebrow">@@eyebrow@@</div>
      <h1 data-i18n-html="h1">@@h1@@</h1>
      <p class="stand" data-i18n-html="stand">@@stand@@</p>
      <div class="updated" data-i18n-html="updated">@@updated@@</div>
    </div>
    <div class="brandmark">
      <span class="olds-logo olds-logo--hd" role="img" aria-label="OLDS — Observatorio Latinoamericano de Desarrollo Sostenible"></span>
    </div>
  </div>
</header>

<div class="wrap">

  <div class="provenance" data-i18n-html="provenance">@@provenance@@</div>

  <div class="srcnote" data-i18n-html="srcnote">@@srcnote@@</div>

  <div class="method" data-i18n-html="method">@@method@@</div>

  <section aria-label="KPIs" style="margin-top:22px">
    <div class="kpis" data-i18n-html="kpis">@@kpis@@</div>
  </section>

  <hr class="rule">

  <div class="cols">
    <section style="margin-top:0">
      <h2 data-i18n-html="estado_h2">@@estado_h2@@</h2>
      <p class="sub" data-i18n-html="estado_sub">@@estado_sub@@</p>
      <div class="donut-wrap">
        <div class="donut" style="--p:__DONUT_P__" role="img" aria-label="estado"></div>
        <div class="legend" data-i18n-html="estado_legend">@@estado_legend@@</div>
      </div>
    </section>

    <section style="margin-top:0">
      <h2 data-i18n-html="sexo_h2">@@sexo_h2@@</h2>
      <p class="sub" data-i18n-html="sexo_sub">@@sexo_sub@@</p>
      <div class="bars" data-i18n-html="sexo_bars">@@sexo_bars@@</div>
    </section>
  </div>

  <hr class="rule">

  <section>
    <h2 data-i18n-html="edad_h2">@@edad_h2@@</h2>
    <p class="sub" data-i18n-html="edad_sub">@@edad_sub@@</p>
    <div class="bars" data-i18n-html="edad_bars">@@edad_bars@@</div>
  </section>

  <hr class="rule">

  <section>
    <h2 data-i18n-html="pyr_h2">@@pyr_h2@@</h2>
    <p class="sub" data-i18n-html="pyr_sub">@@pyr_sub@@</p>
    <div class="pyr" data-i18n-html="pyramid">@@pyramid@@</div>
    <p class="sub" style="margin-top:11px" data-i18n-html="pyr_note">@@pyr_note@@</p>
    <div class="pyr-legend" data-i18n-html="pyr_legend">@@pyr_legend@@</div>
  </section>

  <hr class="rule">

  <section>
    <h2 data-i18n-html="ubic_h2">@@ubic_h2@@</h2>
    <p class="sub" data-i18n-html="ubic_sub">@@ubic_sub@@</p>
    <div class="bars" data-i18n-html="city_bars">@@city_bars@@</div>
  </section>

  <hr class="rule">

  <section>
    <h2 data-i18n-html="cal_h2">@@cal_h2@@</h2>
    <p class="sub" data-i18n-html="cal_sub">@@cal_sub@@</p>
    <div class="qgrid" data-i18n-html="qcards">@@qcards@@</div>
    <div class="note" data-i18n-html="cal_note">@@cal_note@@</div>
  </section>

  <footer>
    <div class="credit">
      <span class="olds-logo olds-logo--ft" aria-hidden="true"></span>
      <span data-i18n-html="credit">@@credit@@</span>
    </div>
    <p data-i18n-html="authors">@@authors@@</p>
    <p data-i18n-html="source">@@source@@</p>
    <p data-i18n-html="repo">@@repo@@</p>
    <p data-i18n-html="method_foot">@@method_foot@@</p>
    <p data-i18n-html="use">@@use@@</p>
  </footer>

</div>

<script>
(function(){
  var I18N = __I18N_JSON__;
  function apply(lang){
    if(!I18N[lang]){ lang = "es"; }
    var d = I18N[lang];
    document.documentElement.setAttribute("lang", lang);
    document.querySelectorAll("[data-i18n-html]").forEach(function(el){
      var v = d[el.getAttribute("data-i18n-html")];
      if(v != null){ el.innerHTML = v; }
    });
    document.querySelectorAll(".langbtn").forEach(function(b){
      b.setAttribute("aria-pressed", b.getAttribute("data-lang") === lang ? "true" : "false");
    });
    try{ localStorage.setItem("infografia_lang", lang); }catch(e){}
  }
  document.addEventListener("DOMContentLoaded", function(){
    document.querySelectorAll(".langbtn").forEach(function(b){
      b.addEventListener("click", function(){ apply(b.getAttribute("data-lang")); });
    });
    var saved = null;
    try{ saved = localStorage.getItem("infografia_lang"); }catch(e){}
    apply(saved || "es");
  });
})();
</script>
"""


if __name__ == "__main__":
    main()
