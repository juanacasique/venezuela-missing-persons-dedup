"""
Genera docs/infografia_api.html (trilingüe ES/EN/FR) desde los datos de la API
abierta de Venezuela Reporta (ya de-duplicados en origen).

Sigue la ESTRUCTURA de la infografía anterior (infografia_gen.py): langbar, banda
SDG, hero con logo OLDS, procedencia, método, KPIs, estado (dona), sexo, edad
(rangos OCHA), pirámides y ubicaciones; mismo toggle de idioma y mismas cifras
localizadas. Diferencias pedidas:
  - Fuente API (no scraping); datos de-duplicados en origen.
  - Enfoque en IMPACTOS (no en comparar metodologías).
  - TRES pirámides OCHA (aún buscadas · encontradas/a salvo · ingresos a hospitales),
    estilo nuevo: azul (hombres) / ámbar (mujeres), con cifras y % en cada barra,
    fila independiente para "sin dato de edad", y nota con totales de sexo sin dato.
  - Sin la sección de "calidad de ubicaciones para un mapa".

Entrada: data/processed/api_personas_inferido.csv  + api_ingresos_inferido.csv
Uso:     python3 infografia_api_gen.py
"""

import base64
import json
import re
import unicodedata
from datetime import datetime, timezone, timedelta

import pandas as pd

PERS = "data/processed/api_personas_inferido.csv"
ING = "data/processed/api_ingresos_inferido.csv"
LOGO = "assets/olds_logo.png"
OUTDIR = "docs"   # nombre del archivo: infografia_<AAAA-MM-DD>.html (fecha de generación)
SNAPSHOTS = "docs/api_snapshots.json"  # cifras agregadas por fecha (sin PII) — base de la tendencia
LANGS = ["es", "en", "fr"]

CIUDADES = ["catia la mar", "la guaira", "caraballeda", "naiguata", "tanaguarena",
            "carayaca", "maiquetia", "macuto", "caracas", "carmen de uria",
            "los caracas", "chichiriviche", "el junko", "camuri", "anare",
            "la sabana", "todasana", "osma", "oricao", "playa grande", "caribe"]
MES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]
MES_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]
MON_EN = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


def qa(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def fmt_int(n, lang):
    s = f"{int(round(n)):,}"
    if lang == "es":
        return s.replace(",", ".")
    if lang == "fr":
        return s.replace(",", " ")
    return s

def fmt_pct(x, lang):       # x en 0..100, 1 decimal
    s = f"{x:.1f}"
    if lang == "en":
        return s + "%"
    s = s.replace(".", ",")
    return s + (" %" if lang == "fr" else "%")

def fmt_pcti(x, lang):      # porcentaje entero
    return f"{int(round(x))}" + (" %" if lang == "fr" else "%")

def ciudad(s):
    t = qa(s.lower())
    for c in CIUDADES:
        if c in t:
            return c.title()
    return "__OTRAS__"

def short_date(iso, lang):
    """'2026-06-28' → '28 jun' (es/fr) / 'Jun 28' (en)."""
    try:
        _, m, d = (int(x) for x in iso.split("-"))
    except (ValueError, AttributeError):
        return iso
    mes = {"es": MES_ES, "fr": MES_FR, "en": MON_EN}[lang][m-1][:3]
    return f"{mes} {d}" if lang == "en" else f"{d} {mes}"


# --------------------------------------------------------------------------- #
# Cadenas traducibles
# --------------------------------------------------------------------------- #
S = {
 "lang_label": {"es": "Idioma", "en": "Language", "fr": "Langue"},
 "eyebrow": {"es": "Terremoto de Venezuela · 2026 · Estado La Guaira",
             "en": "Venezuela earthquake · 2026 · La Guaira State",
             "fr": "Séisme au Venezuela · 2026 · État de La Guaira"},
 "h1": {"es": "Personas reportadas tras el terremoto",
        "en": "People reported after the earthquake",
        "fr": "Personnes signalées après le séisme"},
 "stand": {
  "es": 'Quiénes son las personas afectadas tras el terremoto: <b style="color:#fff">sexo y edad</b> de quienes aún se buscan, de quienes fueron encontradas y de quienes ingresaron a hospitales. A partir de datos ciudadanos abiertos de Venezuela Reporta, <b style="color:#fff">sin verificar</b>; información indicativa.',
  "en": 'Who the people affected by the earthquake are: <b style="color:#fff">sex and age</b> of those still missing, those found, and those admitted to hospitals. Based on open, citizen-sourced data from Venezuela Reporta, <b style="color:#fff">unverified</b>; indicative information.',
  "fr": 'Qui sont les personnes affectées par le séisme : <b style="color:#fff">sexe et âge</b> de celles toujours recherchées, retrouvées, ou admises à l’hôpital. À partir de données citoyennes ouvertes de Venezuela Reporta, <b style="color:#fff">non vérifiées</b> ; information indicative.'},
 "updated": {"es": "Actualizado:", "en": "Updated:", "fr": "Mis à jour :"},
 "prov_api": {"es": "API abierta", "en": "open API", "fr": "API ouverte"},
 "prov_dedup": {"es": "de-duplicada en origen", "en": "de-duplicated at source", "fr": "dédoublonnée à la source"},
 "prov_people": {"es": "personas", "en": "people", "fr": "personnes"},
 "prov_hosp": {"es": "ingresos a hospitales", "en": "hospital admissions", "fr": "admissions à l’hôpital"},
 "src_tag": {"es": "Fuentes en expansión", "en": "Sources expanding", "fr": "Sources en expansion"},
 "src_body": {
  "es": "Por ahora los datos provienen <b>únicamente de Venezuela Reporta</b> (su API abierta). Se integrarán otras bases; las cifras crecerán al sumar nuevas fuentes.",
  "en": "For now the data comes <b>solely from Venezuela Reporta</b> (its open API). Other databases will be integrated; the figures will grow as new sources are added.",
  "fr": "Pour l’instant, les données proviennent <b>uniquement de Venezuela Reporta</b> (son API ouverte). D’autres bases seront intégrées ; les chiffres augmenteront avec de nouvelles sources."},
 "method": {
  "es": '<b>Cómo se obtiene e infiere.</b> La API entrega las fichas <b>ya de-duplicadas</b> (una por persona). Cuando la persona reporta su <b>sexo o edad</b> se usan tal cual; si no, el <b>sexo se infiere por el nombre</b> y la <b>edad por la descripción</b>, 100% offline y sin inventar (vacío si no hay señal). La inferencia de sexo se validó: <b>coincide en 98,7%</b> con el sexo que la API sí reporta.',
  "en": '<b>How data is obtained and inferred.</b> The API returns records <b>already de-duplicated</b> (one per person). When a person reports their <b>sex or age</b> we use it as-is; otherwise <b>sex is inferred from the name</b> and <b>age from the description</b>, 100% offline and never fabricated (blank when there is no signal). The sex inference was validated: it <b>matches 98.7%</b> of the time against the sex the API does report.',
  "fr": '<b>Obtention et inférence.</b> L’API renvoie des fiches <b>déjà dédoublonnées</b> (une par personne). Quand la personne déclare son <b>sexe ou âge</b>, on les utilise tels quels ; sinon, le <b>sexe est déduit du nom</b> et l’<b>âge de la description</b>, 100% hors ligne et jamais inventés (vide sans signal). L’inférence du sexe a été validée : elle <b>coïncide à 98,7%</b> avec le sexe que l’API déclare.'},
 "kpi_total": {"es": "Personas (registro)", "en": "People (registry)", "fr": "Personnes (registre)"},
 "kpi_total_d": {"es": "buscadas + encontradas", "en": "missing + found", "fr": "recherchées + retrouvées"},
 "kpi_busca": {"es": "Aún en búsqueda", "en": "Still missing", "fr": "Toujours recherchées"},
 "kpi_busca_d": {"es": "{p} del registro", "en": "{p} of the registry", "fr": "{p} du registre"},
 "kpi_res": {"es": "Encontradas o a salvo", "en": "Found or safe", "fr": "Retrouvées ou en sécurité"},
 "kpi_res_d": {"es": "{p} del registro", "en": "{p} of the registry", "fr": "{p} du registre"},
 "kpi_hosp": {"es": "Ingresos a hospitales", "en": "Hospital admissions", "fr": "Admissions à l’hôpital"},
 "kpi_hosp_d": {"es": "listas comunitarias", "en": "community lists", "fr": "listes communautaires"},
 "estado_h2": {"es": "Estado de la búsqueda", "en": "Search status", "fr": "Statut des recherches"},
 "estado_sub": {
  "es": "Una persona se cuenta como resuelta si <em>cualquiera</em> de sus reportes la marca encontrada o a salvo.",
  "en": "A person counts as resolved if <em>any</em> of their reports marks them found or safe.",
  "fr": "Une personne est résolue si <em>l’un</em> de ses signalements l’indique retrouvée ou en sécurité."},
 "leg_busca": {"es": "Aún en búsqueda", "en": "Still missing", "fr": "Toujours recherchées"},
 "leg_res": {"es": "Encontradas / a salvo", "en": "Found / safe", "fr": "Retrouvées / en sécurité"},
 "sexo_h2": {"es": "Sexo (registro)", "en": "Sex (registry)", "fr": "Sexe (registre)"},
 "sexo_sub": {
  "es": "Inferido por persona (reportado → nombre → descripción). Cobertura {cov}; inferencia validada en 98,7%.",
  "en": "Inferred per person (reported → name → description). Coverage {cov}; inference validated at 98.7%.",
  "fr": "Déduit par personne (déclaré → nom → description). Couverture {cov} ; inférence validée à 98,7%."},
 "male": {"es": "Masculino", "en": "Male", "fr": "Homme"},
 "female": {"es": "Femenino", "en": "Female", "fr": "Femme"},
 "unknown": {"es": "Desconocido", "en": "Unknown", "fr": "Inconnu"},
 "other": {"es": "Otro", "en": "Other", "fr": "Autre"},
 "sex_unknown": {"es": "Sexo sin dato", "en": "Sex unknown", "fr": "Sexe inconnu"},
 "edad_h2": {"es": "Rango de edad (registro)", "en": "Age range (registry)", "fr": "Tranche d’âge (registre)"},
 "edad_sub": {
  "es": "Grupos de edad estándar usados en respuesta humanitaria. Inferido por persona; grupo de edad asignado al {cov}.",
  "en": "Standard age groups used in humanitarian response. Inferred per person; age group assigned for {cov}.",
  "fr": "Tranches d’âge standard utilisées en réponse humanitaire. Déduit par personne ; tranche d’âge attribuée pour {cov}."},
 "age_04": {"es": "0–4 (primera infancia)", "en": "0–4 (early childhood)", "fr": "0–4 (petite enfance)"},
 "age_517": {"es": "5–17 (NNA)", "en": "5–17 (children & adolescents)", "fr": "5–17 (enfants & adolescents)"},
 "age_1859": {"es": "18–59 (adultos)", "en": "18–59 (adults)", "fr": "18–59 (adultes)"},
 "age_60": {"es": "60+ (adultos mayores)", "en": "60+ (older adults)", "fr": "60+ (personnes âgées)"},
 "age_nd": {"es": "Sin dato", "en": "No data", "fr": "Sans donnée"},
 "pyr_intro_h2": {"es": "Pirámides poblacionales por sexo y edad",
                  "en": "Population pyramids by sex and age",
                  "fr": "Pyramides des âges par sexe"},
 "pyr_intro_sub": {
  "es": "Rangos de edad estándar de respuesta humanitaria. Cada pirámide cuenta a TODAS las personas: la fila inferior agrupa a quienes <b>no tienen edad conocida</b>, y la <b>franja gris central</b> en cada fila representa personas <b>sin dato de sexo</b> (escala propia, no compara con las barras laterales). La incertidumbre se muestra, no se oculta.",
  "en": "Standard humanitarian age ranges. Each pyramid counts ALL people: the bottom row groups those with <b>no known age</b>, and the <b>central grey stripe</b> in each row represents people with <b>unknown sex</b> (own scale, not comparable to the side bars). Uncertainty is shown, not hidden.",
  "fr": "Tranches d’âge standard de la réponse humanitaire. Chaque pyramide compte TOUTES les personnes : la rangée du bas regroupe celles <b>sans âge connu</b>, et la <b>bande grise centrale</b> de chaque ligne représente les personnes <b>sans sexe connu</b> (échelle propre, non comparable aux barres latérales). L’incertitude est montrée, pas masquée."},
 "pyr_busc_h": {"es": "Aún buscadas", "en": "Still missing", "fr": "Toujours recherchées"},
 "pyr_busc_s": {"es": "Las {n} personas todavía reportadas como desaparecidas.",
                "en": "The {n} people still reported as missing.",
                "fr": "Les {n} personnes toujours portées disparues."},
 "pyr_enc_h": {"es": "Encontradas o a salvo", "en": "Found or safe", "fr": "Retrouvées ou en sécurité"},
 "pyr_enc_s": {"es": "Las {n} personas con reporte de encontradas o a salvo.",
               "en": "The {n} people reported as found or safe.",
               "fr": "Les {n} personnes signalées retrouvées ou en sécurité."},
 "pyr_hosp_h": {"es": "Ingresos a hospitales y refugios", "en": "Hospital & shelter admissions", "fr": "Admissions hôpitaux & refuges"},
 "pyr_hosp_s": {
  "es": "{n} ingresos de listas comunitarias. ⚠ La API <b>no trae el sexo</b> aquí (inferido por nombre) y la edad solo en parte: cobertura menor, leer con cautela. Aparecer en una lista <b>no confirma</b> que la persona esté a salvo.",
  "en": "{n} admissions from community lists. ⚠ The API <b>does not provide sex</b> here (inferred from name) and age only partly: lower coverage, read with caution. Appearing on a list <b>does not confirm</b> the person is safe.",
  "fr": "{n} admissions de listes communautaires. ⚠ L’API <b>ne fournit pas le sexe</b> ici (déduit du nom) et l’âge en partie : couverture moindre, à lire avec prudence. Figurer sur une liste <b>ne confirme pas</b> que la personne est en sécurité."},
 "pyr_nd": {"es": "Edad<br>sin dato", "en": "Age<br>unknown", "fr": "Âge<br>inconnu"},
 "pyr_note": {
  "es": "Población: <b>{tot}</b>. Hombres {m} ({mp}) · Mujeres {f} ({fp}) · sexo sin dato {u} ({up}).",
  "en": "Population: <b>{tot}</b>. Male {m} ({mp}) · Female {f} ({fp}) · sex unknown {u} ({up}).",
  "fr": "Population : <b>{tot}</b>. Hommes {m} ({mp}) · Femmes {f} ({fp}) · sexe inconnu {u} ({up})."},
 "ubic_h2": {"es": "Dónde están reportadas", "en": "Where they are reported", "fr": "Où elles sont signalées"},
 "ubic_sub": {
  "es": "Personas del registro por localidad. El terremoto golpeó la franja costera del estado La Guaira.",
  "en": "Registry people by locality. The earthquake struck the coastal strip of La Guaira State.",
  "fr": "Personnes du registre par localité. Le séisme a frappé la bande côtière de l’État de La Guaira."},
 "otras": {"es": "Otras / sin indicar", "en": "Other / unspecified", "fr": "Autres / non précisé"},
 "credit": {
  "es": 'Elaborado por <b>Juana Casique</b>, desarrolladora y analista de datos — <b>Kognis OÜ</b>, Tallin (Estonia) · <a href="mailto:jcasique@kognis.org">jcasique@kognis.org</a>. Con el apoyo del <b><a href="https://www.olds2030.org/">Observatorio Latinoamericano de Desarrollo Sostenible</a></b> y la red <b>Todos con Venezuela</b>. Datos ciudadanos compartidos en abierto sin verificar; la información es <b>indicativa</b> y debe contrastarse con otras fuentes.',
  "en": 'Produced by <b>Juana Casique</b>, developer and data analyst — <b>Kognis OÜ</b>, Tallinn (Estonia) · <a href="mailto:jcasique@kognis.org">jcasique@kognis.org</a>. With the support of the <b><a href="https://www.olds2030.org/">Latin American Observatory for Sustainable Development</a></b> and the <b>Todos con Venezuela</b> network. Open, citizen-sourced, unverified data; the information is <b>indicative</b> and must be cross-checked.',
  "fr": 'Réalisé par <b>Juana Casique</b>, développeuse et analyste de données — <b>Kognis OÜ</b>, Tallinn (Estonie) · <a href="mailto:jcasique@kognis.org">jcasique@kognis.org</a>. Avec le soutien de l’<b><a href="https://www.olds2030.org/">Observatoire latino-américain du développement durable</a></b> et du réseau <b>Todos con Venezuela</b>. Données citoyennes ouvertes et non vérifiées ; l’information est <b>indicative</b> et doit être recoupée.'},
 "source": {
  "es": '<b>Fuente de datos (en expansión):</b> por ahora únicamente Venezuela Reporta — API abierta <code>/api/v1/personas</code> y <code>/ingresos</code>, datos de-duplicados en origen, sin verificar (<a href="https://venezuelareporta.org/api-abierta">venezuelareporta.org</a>). Cifras por persona: {tot} personas en el registro + {ing} ingresos a hospitales.',
  "en": '<b>Data source (expanding):</b> for now only Venezuela Reporta — open API <code>/api/v1/personas</code> and <code>/ingresos</code>, de-duplicated at source, unverified (<a href="https://venezuelareporta.org/api-abierta">venezuelareporta.org</a>). Per-person figures: {tot} registry people + {ing} hospital admissions.',
  "fr": '<b>Source des données (en expansion) :</b> pour l’instant uniquement Venezuela Reporta — API ouverte <code>/api/v1/personas</code> et <code>/ingresos</code>, dédoublonnées à la source, non vérifiées (<a href="https://venezuelareporta.org/api-abierta">venezuelareporta.org</a>). Chiffres par personne : {tot} personnes du registre + {ing} admissions à l’hôpital.'},
 "repo": {
  "es": '<b>Metodología y código abierto:</b> <a href="https://github.com/juanacasique/venezuela-missing-persons-dedup">github.com/juanacasique/venezuela-missing-persons-dedup</a> — método de obtención e inferencia, abierto a revisión y contribución.',
  "en": '<b>Methodology & open source:</b> <a href="https://github.com/juanacasique/venezuela-missing-persons-dedup">github.com/juanacasique/venezuela-missing-persons-dedup</a> — data and inference method, open to review and contribution.',
  "fr": '<b>Méthodologie et code ouvert :</b> <a href="https://github.com/juanacasique/venezuela-missing-persons-dedup">github.com/juanacasique/venezuela-missing-persons-dedup</a> — méthode d’obtention et d’inférence, ouverte à révision.'},
 "method_foot": {
  "es": '<b>Método:</b> datos de-duplicados en origen por la API. Sexo y edad inferidos 100% offline cuando no se reportan, nunca inventados (vacío sin señal); la inferencia de sexo coincide 98,7% con el dato reportado. En hospitales el sexo no viene en la API y se infiere por nombre.',
  "en": '<b>Method:</b> data de-duplicated at source by the API. Sex and age inferred 100% offline when not reported, never fabricated (blank without signal); sex inference matches 98.7% of reported data. For hospitals the API gives no sex, so it is inferred from the name.',
  "fr": '<b>Méthode :</b> données dédoublonnées à la source par l’API. Sexe et âge déduits 100% hors ligne s’ils ne sont pas déclarés, jamais inventés (vide sans signal) ; l’inférence du sexe coïncide à 98,7% avec le déclaré. Pour les hôpitaux, l’API ne donne pas le sexe : déduit du nom.'},
 "use": {
  "es": '<b>Uso responsable:</b> contiene datos personales sensibles de población vulnerable. Usar solo para apoyar su localización; no redistribuir contactos fuera de ese fin.',
  "en": '<b>Responsible use:</b> contains sensitive personal data of vulnerable people. Use only to support locating them; do not redistribute contacts beyond that purpose.',
  "fr": '<b>Usage responsable :</b> contient des données personnelles sensibles de personnes vulnérables. À utiliser uniquement pour aider à les localiser ; ne pas rediffuser les contacts.'},
 "authors": {
  "es": 'Infografía y análisis: <b><a href="https://github.com/juanacasique">Juana Casique</a></b>. Bifurcado del trabajo original de <a href="https://github.com/alcastaro">Alberto Castillo Aroca</a>.',
  "en": 'Infographic and analysis: <b><a href="https://github.com/juanacasique">Juana Casique</a></b>. Forked from the original work by <a href="https://github.com/alcastaro">Alberto Castillo Aroca</a>.',
  "fr": 'Infographie et analyse : <b><a href="https://github.com/juanacasique">Juana Casique</a></b>. Bifurqué du travail original d’<a href="https://github.com/alcastaro">Alberto Castillo Aroca</a>.'},

 # --- Panorama / análisis (para periodistas, arriba, estilo humanitario) ---
 "analysis_h2": {"es": "El panorama", "en": "The situation", "fr": "La situation"},
 "analysis_body": {
  "es": 'Tras el terremoto, <b>{busca} personas</b> siguen reportadas como desaparecidas —el <b>{buscap}</b> del registro—, mientras <b>{res}</b> ya fueron encontradas o están a salvo. De quienes aún se buscan, el <b>{femp} son mujeres</b>, frente a un <b>{mascp} de hombres</b>; del <b>{descp}</b> restante no se conoce el sexo, así que ninguna cifra debe leerse como "el resto". Entre las personas buscadas hay <b>{ninos} niñas, niños y adolescentes</b> y <b>{mayores} personas mayores de 60 años</b> — los grupos que suelen requerir atención prioritaria. Los reportes se concentran en <b>{ciudad}</b>. Por separado, <b>{ing} personas</b> figuran en listas de ingreso a hospitales y refugios.',
  "en": 'After the earthquake, <b>{busca} people</b> are still reported missing —<b>{buscap}</b> of the registry— while <b>{res}</b> have been found or are safe. Of those still missing, <b>{femp} are women</b>, compared with <b>{mascp} men</b>; for the remaining <b>{descp}</b> the sex is unknown, so no figure should be read as "the rest". Among those missing are <b>{ninos} children and adolescents</b> and <b>{mayores} people over 60</b> — the groups that usually require priority attention. Reports concentrate in <b>{ciudad}</b>. Separately, <b>{ing} people</b> appear on hospital and shelter admission lists.',
  "fr": 'Après le séisme, <b>{busca} personnes</b> sont toujours portées disparues —<b>{buscap}</b> du registre— tandis que <b>{res}</b> ont été retrouvées ou sont en sécurité. Parmi les personnes recherchées, <b>{femp} sont des femmes</b>, contre <b>{mascp} d’hommes</b> ; pour les <b>{descp}</b> restants, le sexe est inconnu — aucun chiffre ne doit donc se lire comme « le reste ». Parmi elles, <b>{ninos} enfants et adolescents</b> et <b>{mayores} personnes de plus de 60 ans</b> — les groupes qui requièrent souvent une attention prioritaire. Les signalements se concentrent à <b>{ciudad}</b>. Par ailleurs, <b>{ing} personnes</b> figurent sur les listes d’admission aux hôpitaux et refuges.'},
 # --- Encabezado de la sección técnica (al final) ---
 "tech_h2": {"es": "Metodología, fuentes y calidad del dato",
             "en": "Methodology, sources and data quality",
             "fr": "Méthodologie, sources et qualité des données"},
 "tech_sub": {
  "es": "Cómo se obtienen, deduplican e infieren estos datos, y qué tan completos son. Para lectores que quieran auditar el método.",
  "en": "How this data is obtained, de-duplicated and inferred, and how complete it is. For readers who want to audit the method.",
  "fr": "Comment ces données sont obtenues, dédoublonnées et déduites, et leur degré de complétude. Pour les lecteurs qui veulent auditer la méthode."},

 # --- Cifras clave (#1) ---
 "cifras_h2": {"es": "Cifras clave", "en": "Key figures", "fr": "Chiffres clés"},
 "cifras_sub": {
  "es": "Lo esencial sobre quienes <b>aún se buscan</b>, para orientar la respuesta.",
  "en": "The essentials about those <b>still being searched for</b>, to guide the response.",
  "fr": "L’essentiel sur les personnes <b>toujours recherchées</b>, pour orienter la réponse."},
 "cc_04": {"es": "<b>menores de 5 años</b> aún sin localizar",
           "en": "<b>children under 5</b> still unlocated",
           "fr": "<b>enfants de moins de 5 ans</b> non localisés"},
 "cc_517": {"es": "<b>niñas, niños y adolescentes</b> (5–17) en búsqueda",
            "en": "<b>children & adolescents</b> (5–17) still missing",
            "fr": "<b>enfants et adolescents</b> (5–17) recherchés"},
 "cc_60": {"es": "<b>personas mayores de 60</b> aún sin localizar",
           "en": "<b>older adults (60+)</b> still unlocated",
           "fr": "<b>personnes de plus de 60 ans</b> non localisées"},
 "cc_fem": {"es": "de las aún buscadas <b>son mujeres</b>, frente a {mp} de hombres; del {up} no se conoce el sexo",
            "en": "of those still missing <b>are women</b>, vs. {mp} men; sex unknown for {up}",
            "fr": "des personnes recherchées <b>sont des femmes</b>, contre {mp} d’hommes ; sexe inconnu pour {up}"},

 # --- Qué implican estos datos (#lectura humanitaria) ---
 "implic_h2": {"es": "Qué implican estos datos",
               "en": "What these figures imply",
               "fr": "Ce que ces chiffres impliquent"},
 "implic_sub": {
  "es": "Lectura humanitaria de la composición por sexo y edad de quienes aún se buscan. Interpretación indicativa sobre datos sin verificar.",
  "en": "A humanitarian reading of the sex and age composition of those still missing. Indicative interpretation of unverified data.",
  "fr": "Lecture humanitaire de la composition par sexe et âge des personnes recherchées. Interprétation indicative de données non vérifiées."},
 "implic_1": {
  "es": '<b>Mujeres, leve mayoría — y un {descp} es incógnita.</b> El {femp} de quienes se buscan son mujeres y el {mascp} hombres. El resto no tiene sexo conocido: cada porcentaje es un piso, no un techo, y la respuesta no debería asumir que las personas sin dato son hombres.',
  "en": '<b>Women are a slight majority — and {descp} is unknown.</b> {femp} of those missing are women and {mascp} men. The rest have no known sex: each share is a floor, not a ceiling, and the response should not assume the unknowns are men.',
  "fr": '<b>Les femmes, légère majorité — et {descp} d’inconnues.</b> {femp} des personnes recherchées sont des femmes et {mascp} des hommes. Le reste n’a pas de sexe connu : chaque part est un plancher, pas un plafond, et la réponse ne doit pas supposer que les inconnus sont des hommes.'},
 "implic_2": {
  "es": '<b>Mujeres adultas, las más sobrerrepresentadas.</b> Entre 35 y 54 años se buscan <b>{f3554} mujeres</b> frente a <b>{m3554} hombres</b> ({extra} más). El colapso golpeó sobre todo edificios residenciales de la franja costera, y estas edades concentran a quienes sostienen hogares — un indicio de familias enteras afectadas y de separación familiar.',
  "en": '<b>Adult women are the most overrepresented.</b> Between ages 35 and 54, <b>{f3554} women</b> are missing versus <b>{m3554} men</b> ({extra} more). The collapse mainly hit residential buildings along the coastal strip, and these ages concentrate those sustaining households — a sign of entire families affected and of family separation.',
  "fr": '<b>Les femmes adultes, les plus surreprésentées.</b> Entre 35 et 54 ans, <b>{f3554} femmes</b> sont recherchées contre <b>{m3554} hommes</b> ({extra} de plus). L’effondrement a surtout touché des immeubles résidentiels du littoral, et ces âges concentrent les personnes qui soutiennent les foyers — signe de familles entières affectées et de séparations familiales.'},
 "implic_3": {
  "es": '<b>Implicaciones para la respuesta.</b> Con mayoría femenina y <b>{ninos} NNA</b> y <b>{mayores} personas 60+</b> aún buscadas, los estándares humanitarios (Esfera, guías de género IASC) priorizan: salud materna y obstétrica, kits de dignidad e higiene menstrual, saneamiento seguro e iluminado en refugios, prevención de la violencia de género, reunificación familiar y protección de niñez y personas mayores.',
  "en": '<b>Implications for the response.</b> With a female majority and <b>{ninos} children</b> and <b>{mayores} people 60+</b> still missing, humanitarian standards (Sphere, IASC gender guidance) prioritise: maternal and obstetric health, dignity and menstrual hygiene kits, safe and well-lit sanitation in shelters, gender-based violence prevention, family reunification and protection of children and older people.',
  "fr": '<b>Implications pour la réponse.</b> Avec une majorité féminine et <b>{ninos} enfants</b> et <b>{mayores} personnes 60+</b> toujours recherchés, les standards humanitaires (Sphère, directives genre IASC) priorisent : santé maternelle et obstétricale, kits de dignité et d’hygiène menstruelle, assainissement sûr et éclairé dans les refuges, prévention des violences de genre, réunification familiale et protection des enfants et des aînés.'},

 # --- Semáforo de confiabilidad ---
 "conf_lbl": {"es": "Confiabilidad del dato", "en": "Data reliability", "fr": "Fiabilité des données"},
 "conf_val": {"es": "Media-baja", "en": "Medium-low", "fr": "Moyenne-faible"},
 "conf_note": {
  "es": "Datos ciudadanos sin verificar · fuente única · sexo y edad en parte inferidos. No apto para uso oficial sin contrastar.",
  "en": "Unverified citizen data · single source · sex and age partly inferred. Not for official use without cross-checking.",
  "fr": "Données citoyennes non vérifiées · source unique · sexe et âge en partie déduits. Pas pour un usage officiel sans recoupement."},

 # --- Tendencia (#4) ---
 "trend_h2": {"es": "Tendencia", "en": "Trend", "fr": "Tendance"},
 "trend_sub": {"es": "Cambio respecto al corte anterior.", "en": "Change since the previous snapshot.", "fr": "Évolution depuis le relevé précédent."},
 "trend_none": {
  "es": "Primera medición registrada. La tendencia aparecerá cuando exista un corte anterior con el que comparar.",
  "en": "First snapshot recorded. The trend will appear once there is a previous snapshot to compare against.",
  "fr": "Premier relevé enregistré. La tendance apparaîtra dès qu’un relevé antérieur sera disponible."},
 "trend_busca": {"es": "aún buscadas", "en": "still missing", "fr": "toujours recherchées"},
 "trend_res": {"es": "encontradas o a salvo", "en": "found or safe", "fr": "retrouvées ou en sécurité"},
 "trend_reg": {"es": "registro total", "en": "total registry", "fr": "registre total"},
 "trend_since": {"es": "vs. {date}", "en": "vs. {date}", "fr": "vs. {date}"},
 "trend_same": {"es": "sin cambio", "en": "no change", "fr": "sans changement"},

 # --- Completitud del dato (#5) ---
 "compl_h2": {"es": "Completitud del dato", "en": "Data completeness", "fr": "Complétude des données"},
 "compl_sub": {
  "es": "Qué proporción del registro trae cada atributo (reportado o inferido). Los huecos se muestran, no se rellenan.",
  "en": "What share of the registry carries each attribute (reported or inferred). Gaps are shown, not filled.",
  "fr": "Quelle part du registre porte chaque attribut (déclaré ou déduit). Les manques sont montrés, pas comblés."},
 "compl_sexo": {"es": "Sexo", "en": "Sex", "fr": "Sexe"},
 "compl_edad": {"es": "Edad", "en": "Age", "fr": "Âge"},
 "compl_ubic": {"es": "Ubicación", "en": "Location", "fr": "Localisation"},

 # --- Caja de caveats (#7) ---
 "caveat_h2": {"es": "Qué dice y qué no dice este dato", "en": "What this data does and doesn’t say", "fr": "Ce que ces données disent et ne disent pas"},
 "caveat_yes_h": {"es": "Qué SÍ dice", "en": "What it DOES say", "fr": "Ce qu’elles disent"},
 "caveat_no_h": {"es": "Qué NO dice", "en": "What it does NOT say", "fr": "Ce qu’elles ne disent pas"},
 "caveat_yes": {
  "es": "<li>Cuántas personas fueron <b>reportadas</b> y su estado declarado (buscada / encontrada / a salvo).</li><li>La <b>composición por sexo y edad</b> de cada grupo, con la incertidumbre visible.</li><li>En qué <b>localidades</b> se concentran los reportes.</li>",
  "en": "<li>How many people were <b>reported</b> and their declared status (missing / found / safe).</li><li>The <b>sex and age composition</b> of each group, with uncertainty shown.</li><li>Which <b>localities</b> concentrate the reports.</li>",
  "fr": "<li>Combien de personnes ont été <b>signalées</b> et leur statut déclaré (recherchée / retrouvée / en sécurité).</li><li>La <b>composition par sexe et âge</b> de chaque groupe, incertitude visible.</li><li>Dans quelles <b>localités</b> se concentrent les signalements.</li>"},
 "caveat_no": {
  "es": "<li>No es un <b>censo de víctimas</b> ni una cifra oficial: son reportes ciudadanos sin verificar.</li><li>Aparecer en una <b>lista de hospital o refugio no confirma</b> que la persona esté a salvo.</li><li>El sexo y la edad <b>inferidos</b> pueden fallar en casos individuales; úsense en el agregado.</li>",
  "en": "<li>It is <b>not a casualty census</b> nor an official figure: these are unverified citizen reports.</li><li>Being on a <b>hospital or shelter list does not confirm</b> the person is safe.</li><li><b>Inferred</b> sex and age may be wrong in individual cases; use them in aggregate.</li>",
  "fr": "<li>Ce n’est <b>pas un recensement des victimes</b> ni un chiffre officiel : signalements citoyens non vérifiés.</li><li>Figurer sur une <b>liste d’hôpital ou de refuge ne confirme pas</b> que la personne est en sécurité.</li><li>Le sexe et l’âge <b>déduits</b> peuvent être erronés au cas par cas ; à utiliser en agrégé.</li>"},
}

OCHA = ["0-4", "5-17", "18-59", "60+"]
BAND_LBL = {"0-4": "0–4", "5-17": "5–17", "18-59": "18–59", "60+": "60+"}


def bar(name, cnt, total, width, lang, color=None, muted=False):
    col = f";background:{color}" if color else ""
    nm = ' style="color:var(--muted)"' if muted else ""
    return (f'<div class="bar"><span class="name"{nm}>{name}</span>'
            f'<span class="track"><span class="fill" style="--w:{width:.1f}%{col}"></span></span>'
            f'<span class="val">{fmt_int(cnt,lang)}<small>{fmt_pct(100*cnt/total,lang)}</small></span></div>')


def pop_stats(df):
    """Devuelve dict numérico para una subpoblación: celdas OCHA x sexo, totales, maxcell."""
    g = df["grupo_edad"].replace("", "Sin dato")
    ct = pd.crosstab(g, df["sexo_inferido"])
    for c in ["Masculino", "Femenino", "Desconocido", "Otro"]:
        if c not in ct.columns:
            ct[c] = 0

    def cell(b):
        if b not in ct.index:
            return 0, 0, 0
        return (int(ct.loc[b, "Masculino"]), int(ct.loc[b, "Femenino"]),
                int(ct.loc[b, "Desconocido"]) + int(ct.loc[b, "Otro"]))

    bands = [(b, *cell(b)) for b in ["60+", "18-59", "5-17", "0-4"]]
    sd = cell("Sin dato")
    N = len(df)
    M = int((df["sexo_inferido"] == "Masculino").sum())
    F = int((df["sexo_inferido"] == "Femenino").sum())
    U = N - M - F
    maxcell = max([max(b[1], b[2]) for b in bands] + [max(sd[0], sd[1]), 1])
    return {"bands": bands, "sd": sd, "N": N, "M": M, "F": F, "U": U, "maxcell": maxcell}


def main():
    p = pd.read_csv(PERS, dtype=str, keep_default_na=False)
    ing = pd.read_csv(ING, dtype=str, keep_default_na=False)
    N = len(p)
    busca_df = p[p["status"] == "buscando"]
    enc_df = p[p["status"].isin(["encontrado", "a_salvo"])]
    se_busca = len(busca_df)
    resuelto = len(enc_df)
    n_ing = len(ing)
    p_busca = 100 * se_busca / N

    # sexo (registro)
    sx = p["sexo_inferido"].value_counts().to_dict()
    F, M = sx.get("Femenino", 0), sx.get("Masculino", 0)
    DESC, OTRO = sx.get("Desconocido", 0), sx.get("Otro", 0)
    cov_sexo = 100 * (F + M + OTRO) / N
    maxsx = max(F, M, DESC, OTRO, 1)

    # edad OCHA (registro)
    ge = p["grupo_edad"].replace("", "Sin dato")
    ec = ge.value_counts().to_dict()
    e = {k: ec.get(k, 0) for k in OCHA + ["Sin dato"]}
    maxe = max(e.values())
    edad_cov = 100 * (N - e["Sin dato"]) / N

    # pirámides
    POPS = [("busc", pop_stats(busca_df)), ("enc", pop_stats(enc_df)), ("hosp", pop_stats(ing))]

    # ciudades (registro)
    cc = p["ciudad"].map(ciudad).value_counts()
    nombradas = [(k, int(v)) for k, v in cc.items() if k != "__OTRAS__"][:8]
    otras = int(cc.get("__OTRAS__", 0) or 0)
    maxc = nombradas[0][1] if nombradas else 1

    # cifras clave (#1): sobre la población AÚN BUSCADA (prioridad operativa)
    busc = dict(POPS)["busc"]

    def band_total(st, b):
        for lbl, m, f, u in st["bands"]:
            if lbl == b:
                return m + f + u
        return 0

    cc_04 = band_total(busc, "0-4")
    cc_517 = band_total(busc, "5-17")
    cc_60 = band_total(busc, "60+")
    busc_fpct = 100 * busc["F"] / busc["N"] if busc["N"] else 0
    busc_mpct = 100 * busc["M"] / busc["N"] if busc["N"] else 0
    busc_upct = 100 * busc["U"] / busc["N"] if busc["N"] else 0

    # sobre-representación de mujeres adultas (35–54) entre las aún buscadas
    edad_b = pd.to_numeric(busca_df["edad_estimada"], errors="coerce")
    f3554 = int(((busca_df["sexo_inferido"] == "Femenino") & edad_b.between(35, 54)).sum())
    m3554 = int(((busca_df["sexo_inferido"] == "Masculino") & edad_b.between(35, 54)).sum())
    extra3554 = 100 * (f3554 - m3554) / m3554 if m3554 else 0

    # completitud del dato (#5): proporción del registro con cada atributo.
    # Ubicación = % con localidad RECONOCIDA (no vacía y no "otras/sin indicar"),
    # consistente con el gráfico de ubicaciones; el campo bruto está casi siempre lleno
    # pero ~22% no identifica una localidad usable.
    ubic_cov = 100 * (N - otras) / N

    logo = "data:image/png;base64," + base64.b64encode(open(LOGO, "rb").read()).decode()
    now = datetime.now(timezone(timedelta(hours=-4)))
    hm = now.strftime("%H:%M")
    OUT = f"{OUTDIR}/infografia_{now.strftime('%Y-%m-%d')}.html"
    TS = {"es": f"{now.day} de {MES_ES[now.month-1]} de {now.year}, {hm} (hora de Venezuela, UTC−4)",
          "en": f"{MON_EN[now.month-1]} {now.day}, {now.year}, {hm} (Venezuela time, UTC−4)",
          "fr": f"{now.day} {MES_FR[now.month-1]} {now.year}, {hm} (heure du Venezuela, UTC−4)"}

    # tendencia (#4): snapshot agregado (sin PII) por fecha → docs/api_snapshots.json
    today = now.strftime("%Y-%m-%d")
    snap = {"date": today, "reg": N, "buscadas": se_busca, "resueltas": resuelto, "ingresos": n_ing}
    try:
        with open(SNAPSHOTS, encoding="utf-8") as fh:
            hist = json.load(fh)
        if not isinstance(hist, list):
            hist = []
    except (FileNotFoundError, json.JSONDecodeError):
        hist = []
    prev = next((s for s in reversed(hist) if s.get("date") != today), None)
    hist = [s for s in hist if s.get("date") != today]
    hist.append(snap)
    hist.sort(key=lambda s: s.get("date", ""))
    with open(SNAPSHOTS, "w", encoding="utf-8") as fh:
        json.dump(hist, fh, ensure_ascii=False, indent=2)

    def kpi(cls, n, lbl, delta):
        c = f" {cls}" if cls else ""
        return f'<div class="kpi{c}"><div class="n">{n}</div><div class="lbl">{lbl}</div><div class="delta">{delta}</div></div>'

    def leg(color, n, pc, t):
        return (f'<div class="leg"><span class="dot" style="background:{color}"></span>'
                f'<div><div class="v">{n} <small>· {pc}</small></div><div class="t">{t}</div></div></div>')

    def pyr_row(label, m, f, u, Npop, maxcell, max_u, lang, nodata=False):
        wm, wf = 100*m/maxcell, 100*f/maxcell
        wuc = 100*u/max_u if max_u > 0 else 0
        cls = "pyr-row nodata" if nodata else "pyr-row"
        stripe = f'<span class="u-stripe" style="--wuc:{wuc:.1f}%"></span>' if u > 0 else ''
        return (f'<div class="{cls}">'
                f'<div class="pyr-side left">'
                f'<span class="v">{fmt_int(m,lang)}<small>{fmt_pct(100*m/Npop,lang)}</small></span>'
                f'<span class="bar m" style="--w:{wm:.1f}%"></span></div>'
                f'<div class="pyr-label">{stripe}{label}</div>'
                f'<div class="pyr-side right">'
                f'<span class="bar f" style="--w:{wf:.1f}%"></span>'
                f'<span class="v">{fmt_int(f,lang)}<small>{fmt_pct(100*f/Npop,lang)}</small></span></div></div>')

    def pyramid_block(key, st, lang, L):
        head = (f'<div class="pyr-head"><span class="l">◀ {L("male")}</span><span></span>'
                f'<span class="r">{L("female")} ▶</span></div>')
        max_u = max((u for _, _, _, u in st["bands"]), default=0)
        max_u = max(max_u, st["sd"][2])
        rows = "".join(pyr_row(BAND_LBL[b], m, f, u, st["N"], st["maxcell"], max_u, lang)
                       for b, m, f, u in st["bands"])
        sdm, sdf, sdu = st["sd"]
        rows += pyr_row(L("pyr_nd"), sdm, sdf, sdu, st["N"], st["maxcell"], max_u, lang, nodata=True)
        note = L("pyr_note").format(
            tot=fmt_int(st["N"], lang),
            m=fmt_int(st["M"], lang), mp=fmt_pct(100*st["M"]/st["N"], lang),
            f=fmt_int(st["F"], lang), fp=fmt_pct(100*st["F"]/st["N"], lang),
            u=fmt_int(st["U"], lang), up=fmt_pct(100*st["U"]/st["N"], lang))
        legend = (
            f'<span class="leg"><span class="dot" style="background:var(--blue-deep)"></span>{L("male")}</span>'
            f'<span class="leg"><span class="dot" style="background:var(--amber)"></span>{L("female")}</span>'
            f'<span class="leg"><span class="dot" style="background:var(--slate);opacity:.7"></span>{L("sex_unknown")}</span>')
        title = L(f"pyr_{key}_h")
        sub = L(f"pyr_{key}_s").format(n=fmt_int(st["N"], lang))
        return (f'<section class="pyrsec"><h3 class="pyr-title">{title}</h3>'
                f'<p class="sub">{sub}</p>'
                f'<div class="pyr">{head}{rows}</div>'
                f'<p class="pyr-note">{note}</p>'
                f'<div class="pyr-legend">{legend}</div></section>')

    def build(lang):
        L = lambda k: S[k][lang]
        d = {}
        for k in ["lang_label", "eyebrow", "h1", "stand", "estado_h2", "estado_sub",
                  "sexo_h2", "edad_h2", "method", "credit", "repo", "method_foot",
                  "use", "authors", "ubic_h2", "ubic_sub", "pyr_intro_h2", "pyr_intro_sub",
                  "cifras_h2", "cifras_sub", "implic_h2", "implic_sub",
                  "conf_lbl", "conf_val", "conf_note",
                  "trend_h2", "trend_sub", "compl_h2", "compl_sub",
                  "caveat_h2", "caveat_yes_h", "caveat_no_h", "caveat_yes", "caveat_no",
                  "analysis_h2", "tech_h2", "tech_sub"]:
            d[k] = L(k)
        d["updated"] = f'{L("updated")} <b>{TS[lang]}</b>'
        d["provenance"] = (
            f'<span class="flow"><b>{L("prov_api")}</b></span>'
            f'<span class="flow"><span class="arrow">→</span> {L("prov_dedup")}</span>'
            f'<span class="flow"><span class="arrow">→</span> <b>{fmt_int(N,lang)}</b>&nbsp;{L("prov_people")}</span>'
            f'<span style="color:var(--muted)">+ {fmt_int(n_ing,lang)} {L("prov_hosp")}</span>')
        d["srcnote"] = f'<span class="tag">{L("src_tag")}</span><span>{L("src_body")}</span>'
        d["kpis"] = (
            kpi("", fmt_int(N, lang), L("kpi_total"), L("kpi_total_d"))
            + kpi("amber", fmt_int(se_busca, lang), L("kpi_busca"), L("kpi_busca_d").format(p=fmt_pct(p_busca, lang)))
            + kpi("green", fmt_int(resuelto, lang), L("kpi_res"), L("kpi_res_d").format(p=fmt_pct(100*resuelto/N, lang)))
            + kpi("slate", fmt_int(n_ing, lang), L("kpi_hosp"), L("kpi_hosp_d")))
        d["estado_legend"] = (
            leg("var(--blue)", fmt_int(se_busca, lang), fmt_pct(p_busca, lang), L("leg_busca"))
            + leg("var(--green)", fmt_int(resuelto, lang), fmt_pct(100*resuelto/N, lang), L("leg_res")))
        d["sexo_sub"] = L("sexo_sub").format(cov=fmt_pcti(cov_sexo, lang))
        d["sexo_bars"] = "".join([
            bar(L("female"), F, N, 100*F/maxsx, lang, "var(--amber)"),
            bar(L("male"), M, N, 100*M/maxsx, lang, "var(--blue-deep)"),
            bar(L("unknown"), DESC, N, 100*DESC/maxsx, lang, "var(--slate)"),
            bar(L("other"), OTRO, N, 100*OTRO/maxsx, lang, "var(--blue-soft)")])
        d["edad_sub"] = L("edad_sub").format(cov=fmt_pcti(edad_cov, lang))
        d["edad_bars"] = "".join([
            bar(L("age_04"), e["0-4"], N, 100*e["0-4"]/maxe, lang, "var(--blue-soft)"),
            bar(L("age_517"), e["5-17"], N, 100*e["5-17"]/maxe, lang, "#7ec0e8"),
            bar(L("age_1859"), e["18-59"], N, 100*e["18-59"]/maxe, lang, "var(--blue)"),
            bar(L("age_60"), e["60+"], N, 100*e["60+"]/maxe, lang, "var(--blue-deep)"),
            bar(L("age_nd"), e["Sin dato"], N, 100*e["Sin dato"]/maxe, lang, "var(--slate)")])
        d["pyramids"] = "".join(pyramid_block(key, st, lang, L) for key, st in POPS)
        d["city_bars"] = ("".join(bar(k, v, N, 100*v/maxc, lang, "var(--blue)") for k, v in nombradas)
                          + bar(L("otras"), otras, N, 100*otras/maxc, lang, "var(--slate)", muted=True))
        d["source"] = L("source").format(tot=fmt_int(N, lang), ing=fmt_int(n_ing, lang))

        # Panorama / análisis narrativo (arriba, para periodistas)
        d["analysis_body"] = L("analysis_body").format(
            busca=fmt_int(se_busca, lang), buscap=fmt_pct(p_busca, lang),
            res=fmt_int(resuelto, lang), femp=fmt_pcti(busc_fpct, lang),
            mascp=fmt_pcti(busc_mpct, lang), descp=fmt_pcti(busc_upct, lang),
            ninos=fmt_int(cc_04 + cc_517, lang), mayores=fmt_int(cc_60, lang),
            ciudad=(nombradas[0][0] if nombradas else "—"), ing=fmt_int(n_ing, lang))

        # Qué implican estos datos (lectura humanitaria)
        d["implicaciones"] = "".join(
            f'<div class="imp">{txt}</div>' for txt in [
                L("implic_1").format(femp=fmt_pcti(busc_fpct, lang),
                                     mascp=fmt_pcti(busc_mpct, lang),
                                     descp=fmt_pcti(busc_upct, lang)),
                L("implic_2").format(f3554=fmt_int(f3554, lang), m3554=fmt_int(m3554, lang),
                                     extra=fmt_pcti(extra3554, lang)),
                L("implic_3").format(ninos=fmt_int(cc_04 + cc_517, lang),
                                     mayores=fmt_int(cc_60, lang))])

        # Cifras clave (#1)
        def cc_item(n, txt):
            return f'<div class="cc"><div class="cc-n">{n}</div><div class="cc-t">{txt}</div></div>'
        d["cifras"] = "".join([
            cc_item(fmt_int(cc_04, lang), L("cc_04")),
            cc_item(fmt_int(cc_517, lang), L("cc_517")),
            cc_item(fmt_int(cc_60, lang), L("cc_60")),
            cc_item(fmt_pcti(busc_fpct, lang),
                    L("cc_fem").format(mp=fmt_pcti(busc_mpct, lang),
                                       up=fmt_pcti(busc_upct, lang)))])

        # Completitud del dato (#5)
        def cbar(lbl, pct):
            return (f'<div class="cbar"><span class="cbar-l">{lbl}</span>'
                    f'<span class="cbar-track"><span class="cbar-fill" style="--w:{pct:.0f}%"></span></span>'
                    f'<span class="cbar-v">{fmt_pcti(pct, lang)}</span></div>')
        d["completeness"] = (cbar(L("compl_sexo"), cov_sexo)
                             + cbar(L("compl_edad"), edad_cov)
                             + cbar(L("compl_ubic"), ubic_cov))

        # Tendencia (#4). polarity: -1 = bajar es bueno, +1 = subir es bueno, 0 = neutral.
        if prev:
            def chip(cur, was, lbl, polarity):
                diff = cur - was
                arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "▬")
                if diff == 0 or polarity == 0:
                    cls = "flat"
                else:
                    good = (diff < 0) if polarity < 0 else (diff > 0)
                    cls = "good" if good else "bad"
                val = L("trend_same") if diff == 0 else f'{arrow} {fmt_int(abs(diff), lang)}'
                return f'<span class="trend-chip {cls}"><b>{val}</b> {lbl}</span>'
            since = L("trend_since").format(date=short_date(prev["date"], lang))
            d["trend"] = (f'<div class="trend-since">{since}</div><div class="trend-chips">'
                          + chip(se_busca, prev.get("buscadas", se_busca), L("trend_busca"), -1)
                          + chip(resuelto, prev.get("resueltas", resuelto), L("trend_res"), +1)
                          + chip(N, prev.get("reg", N), L("trend_reg"), 0)
                          + '</div>')
        else:
            d["trend"] = f'<p class="trend-none">{L("trend_none")}</p>'
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
    left = set(re.findall(r"@@[a-z_]+@@", html))
    print(f"Escrito: {OUT}  ({len(html)} bytes)  tokens pendientes: {left or 'ninguno'}")
    print(f"  registro={fmt_int(N,'es')} buscadas={fmt_int(se_busca,'es')} encontradas={fmt_int(resuelto,'es')} ingresos={fmt_int(n_ing,'es')}")
    for key, st in POPS:
        print(f"  pir {key}: N={st['N']} M={st['M']} F={st['F']} U={st['U']} maxcell={st['maxcell']}")
    print(f"  actualizado: {TS['es']}")


TEMPLATE = r"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Personas reportadas · Venezuela 2026 — sexo, edad y pirámides (API abierta)</title>
<meta name="description" content="Sexo, edad y pirámides poblacionales de las personas reportadas tras el terremoto de Venezuela 2026, desde la API abierta de Venezuela Reporta (deduplicada en origen): aún buscadas, encontradas e ingresos a hospitales. Enfoque en impactos. Por Juana Casique (Kognis).">
<style>
  :root{
    --paper:#eef3f8; --card:#ffffff; --ink:#13314a; --ink-soft:#4d6075; --muted:#8093a4;
    --line:#d6e1ec; --line-soft:#e9f0f6;
    --blue:#1f8fd0; --blue-deep:#0b4f7a; --navy:#0a3a5c; --blue-bright:#3aa6dd; --blue-soft:#bcdcf0;
    --amber:#e0902f; --amber-deep:#b56f16; --green:#2f9c6a; --slate:#a9b9c8;
    --maxw:1060px;
  }
  *{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  body{margin:0; background:var(--paper); color:var(--ink);
    font:400 16px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    font-variant-numeric:tabular-nums;}
  .langbar{position:sticky; top:0; z-index:50; background:var(--navy); color:#fff; box-shadow:0 2px 10px rgba(10,58,92,.25);}
  .langbar-in{max-width:var(--maxw); margin:0 auto; padding:8px clamp(18px,4vw,40px); display:flex; align-items:center; gap:14px;}
  .langlbl{font-size:.72rem; letter-spacing:.14em; text-transform:uppercase; color:var(--blue-soft); font-weight:700; margin-right:auto;}
  .seg{display:inline-flex; background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.25); border-radius:999px; padding:3px;}
  .langbtn{appearance:none; border:0; background:transparent; color:#dbe9f5; font:inherit;
    font-weight:700; font-size:.85rem; padding:6px 16px; border-radius:999px; cursor:pointer; line-height:1; transition:background .15s,color .15s;}
  .langbtn[aria-pressed="true"]{background:#fff; color:var(--blue-deep);}
  .langbtn:hover{color:#fff;} .langbtn[aria-pressed="true"]:hover{color:var(--blue-deep);}
  .langbtn:focus-visible{outline:2px solid #fff; outline-offset:2px;}
  .sdg{height:5px; background:linear-gradient(90deg,
    #e5243b 0 11%,#fd9d24 11% 22%,#fcc30b 22% 33%,#4c9f38 33% 47%,
    #1f8fd0 47% 64%,#19486a 64% 80%,#dd1367 80% 100%);}
  .band{background:linear-gradient(135deg,var(--navy),var(--blue-deep)); color:#fff;}
  .bandwrap{display:flex; gap:22px; align-items:flex-start; justify-content:space-between;
    max-width:var(--maxw); margin:0 auto; padding:clamp(22px,4vw,40px) clamp(18px,4vw,40px);}
  .band .eyebrow{font-size:.72rem; letter-spacing:.18em; text-transform:uppercase; color:var(--blue-soft); font-weight:600;}
  .band h1{font-size:clamp(1.8rem,4.4vw,2.9rem); line-height:1.04; margin:.3em 0 .3em; font-weight:800; letter-spacing:-.01em; text-wrap:balance; max-width:20ch;}
  .band .stand{font-size:clamp(.98rem,1.5vw,1.12rem); color:#dbe9f5; max-width:64ch; text-wrap:pretty;}
  .band .updated{margin-top:14px; font-size:.82rem; color:var(--blue-soft); font-weight:600;}
  .band .updated b{color:#fff; font-weight:700;}
  .brandmark{display:flex; align-items:center; flex:0 0 auto; background:#fff; border-radius:10px; padding:12px 16px;}
  .olds-logo{display:inline-block; background:center/contain no-repeat url("__LOGO__");}
  .olds-logo--hd{width:152px; height:58px;} .olds-logo--ft{width:116px; height:45px;}
  .wrap{max-width:var(--maxw); margin:0 auto; padding:clamp(18px,3.5vw,34px) clamp(18px,4vw,40px) clamp(28px,4vw,48px);}
  .provenance{display:flex; flex-wrap:wrap; align-items:center; gap:10px 16px;
    padding:13px 18px; background:var(--card); border:1px solid var(--line); border-left:4px solid var(--blue);
    border-radius:10px; font-size:.95rem; color:var(--ink-soft); margin-top:clamp(-30px,-4vw,-22px); position:relative; box-shadow:0 6px 20px rgba(11,79,122,.07);}
  .provenance b{color:var(--ink); font-weight:700;}
  .flow{display:flex; align-items:center; gap:10px;} .flow .arrow{color:var(--blue); font-weight:800;}
  .method{background:#e7f1f9; border:1px solid #c7def0; border-left:4px solid var(--blue-deep);
    border-radius:10px; padding:15px 18px; margin-top:18px; font-size:.95rem; color:#234a64;}
  .method b{color:var(--blue-deep);}
  .srcnote{display:flex; gap:10px; align-items:baseline; margin-top:12px; padding:11px 16px;
    background:#fff; border:1px dashed var(--blue); border-radius:10px; font-size:.88rem; color:var(--ink-soft);}
  .srcnote .tag{flex:0 0 auto; font-size:.66rem; letter-spacing:.08em; text-transform:uppercase;
    font-weight:700; color:#fff; background:var(--blue); border-radius:5px; padding:3px 8px; translate:0 -1px;}
  .srcnote b{color:var(--blue-deep);}
  code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.86em; background:#dce7f1; padding:.05em .35em; border-radius:4px; color:var(--blue-deep);}
  hr.rule{border:0; border-top:1px solid var(--line); margin:clamp(30px,4.5vw,46px) 0;}
  section{margin-top:clamp(28px,4vw,42px);}
  h2{font-size:1.08rem; letter-spacing:.01em; margin:0 0 4px; font-weight:700; color:var(--navy);}
  .sub{font-size:.9rem; color:var(--muted); margin:0 0 18px; max-width:78ch; text-wrap:pretty;}

  /* Panorama / análisis (lead para periodistas) */
  .analysis{margin-top:clamp(-30px,-4vw,-22px); position:relative;
    background:var(--card); border:1px solid var(--line); border-left:4px solid var(--blue-deep);
    border-radius:12px; padding:20px 24px; box-shadow:0 6px 20px rgba(11,79,122,.07);}
  .analysis h2{font-size:1.16rem; margin-bottom:8px;}
  .analysis-body{font-size:1.08rem; line-height:1.62; color:var(--ink); max-width:74ch; margin:0;}
  .analysis-body b{color:var(--navy); font-weight:700;}

  /* Sección técnica (al final) */
  .tech-sec h3{font-size:1rem; color:var(--navy); margin:22px 0 4px; font-weight:700;}
  .tech-sec .provenance{margin-top:16px;}
  .compl-block{margin-top:6px;}

  .kpis{display:grid; grid-template-columns:repeat(4,1fr); gap:14px;}
  .kpi{background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px; position:relative; overflow:hidden;}
  .kpi::before{content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--blue);}
  .kpi.amber::before{background:var(--amber);} .kpi.green::before{background:var(--green);} .kpi.slate::before{background:var(--muted);}
  .kpi .n{font-size:clamp(1.6rem,3.2vw,2.3rem); font-weight:800; line-height:1; color:var(--navy);}
  .kpi .lbl{margin-top:8px; font-size:.82rem; color:var(--ink-soft);}
  .kpi .delta{font-size:.76rem; color:var(--muted); margin-top:3px;}

  /* Confiabilidad del dato (semáforo) */
  .conf{display:flex; flex-wrap:wrap; align-items:center; gap:10px 14px; margin-top:14px;
    padding:11px 16px; background:#fff7ec; border:1px solid #f2d9ab; border-left:4px solid var(--amber);
    border-radius:10px; font-size:.86rem; color:#6b4e1e;}
  .conf-badge{display:inline-flex; align-items:center; gap:8px; flex:0 0 auto;}
  .conf-lbl{font-size:.66rem; letter-spacing:.08em; text-transform:uppercase; font-weight:700; color:var(--amber-deep);}
  .conf-val{font-weight:800; color:#fff; background:var(--amber); border-radius:6px; padding:3px 10px; font-size:.8rem;}
  .conf-note{color:#7a5c26;}

  /* Cifras clave */
  .cifras-sec{margin-top:clamp(24px,3.5vw,34px);}
  .cifras{display:grid; grid-template-columns:repeat(4,1fr); gap:14px;}
  .cc{background:linear-gradient(150deg,var(--navy),var(--blue-deep)); color:#fff; border-radius:12px;
    padding:18px 18px 16px; box-shadow:0 8px 22px rgba(11,79,122,.14);}
  .cc-n{font-size:clamp(1.9rem,4vw,2.6rem); font-weight:800; line-height:1; letter-spacing:-.01em;}
  .cc-t{margin-top:9px; font-size:.86rem; line-height:1.35; color:#dbe9f5;}
  .cc-t b{color:#fff; font-weight:700;}

  /* Qué implican estos datos */
  .implic-sec{margin-top:clamp(24px,3.5vw,34px);}
  .implic{display:grid; grid-template-columns:repeat(3,1fr); gap:14px;}
  .imp{background:var(--card); border:1px solid var(--line); border-left:4px solid var(--amber);
    border-radius:12px; padding:16px 18px; font-size:.92rem; line-height:1.5; color:var(--ink-soft);}
  .imp b{color:var(--navy);}

  /* Tendencia */
  .trend-sec{margin-top:clamp(22px,3vw,30px);}
  .trend-since{font-size:.78rem; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); font-weight:700; margin-bottom:9px;}
  .trend-chips{display:flex; flex-wrap:wrap; gap:10px;}
  .trend-chip{display:inline-flex; align-items:baseline; gap:7px; background:var(--card); border:1px solid var(--line);
    border-radius:999px; padding:7px 15px; font-size:.9rem; color:var(--ink-soft);}
  .trend-chip b{font-weight:800; font-variant-numeric:tabular-nums;}
  .trend-chip.good b{color:var(--green);} .trend-chip.bad b{color:#c2410c;} .trend-chip.flat b{color:var(--muted);}
  .trend-none{font-size:.9rem; color:var(--ink-soft); background:var(--card); border:1px dashed var(--line);
    border-radius:10px; padding:13px 16px; margin:0;}

  /* Completitud del dato */
  .cbars{display:flex; flex-direction:column; gap:12px; max-width:640px;}
  .cbar{display:grid; grid-template-columns:7rem 1fr 3.2rem; align-items:center; gap:12px; font-size:.92rem;}
  .cbar-l{color:var(--ink); font-weight:600;}
  .cbar-track{height:16px; background:var(--line-soft); border-radius:8px; overflow:hidden;}
  .cbar-fill{display:block; height:100%; width:var(--w); border-radius:8px;
    background:linear-gradient(90deg,var(--blue),var(--blue-deep)); transform-origin:left;
    animation:grow .9s cubic-bezier(.22,.61,.36,1) both;}
  .cbar-v{font-weight:800; color:var(--blue-deep); text-align:right;}

  /* Caja de caveats */
  .caveat{display:grid; grid-template-columns:1fr 1fr; gap:clamp(14px,2.5vw,26px);}
  .caveat-col{border-radius:12px; padding:16px 18px; border:1px solid var(--line);}
  .caveat-yes{background:#eef7f1; border-color:#c6e5d3;}
  .caveat-no{background:#fdf2ec; border-color:#f4d3bf;}
  .caveat-col h3{margin:0 0 8px; font-size:.72rem; letter-spacing:.09em; text-transform:uppercase; font-weight:800;}
  .caveat-yes h3{color:var(--green);} .caveat-no h3{color:#c2410c;}
  .caveat-col ul{margin:0; padding-left:1.15em; display:flex; flex-direction:column; gap:7px;}
  .caveat-col li{font-size:.9rem; line-height:1.4; color:var(--ink-soft);}
  .caveat-col li b{color:var(--ink); font-weight:700;}

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
  /* pirámides */
  .pyrsec{margin-top:clamp(22px,3vw,32px);}
  .pyr-title{font-size:1.02rem; font-weight:800; color:var(--navy); margin:0 0 2px;}
  .pyr{display:flex; flex-direction:column; gap:9px; margin-top:4px;}
  .pyr-head{display:grid; grid-template-columns:1fr 6.2rem 1fr; align-items:center;
    font-size:.74rem; letter-spacing:.1em; text-transform:uppercase; color:var(--muted);}
  .pyr-head .l{text-align:right; padding-right:10px; color:var(--blue-deep); font-weight:700;}
  .pyr-head .r{text-align:left; padding-left:10px; color:var(--amber-deep); font-weight:700;}
  .pyr-row{display:grid; grid-template-columns:1fr 6.2rem 1fr; align-items:center;}
  .pyr-side{display:flex; align-items:center; height:22px; overflow:hidden;}
  .pyr-side.left{justify-content:flex-end;} .pyr-side.right{justify-content:flex-start;}
  .pyr-side .bar{height:100%; width:var(--w); min-width:0; border-radius:3px; animation:grow .9s cubic-bezier(.22,.61,.36,1) both;}
  .pyr-side.left .bar{transform-origin:right;} .pyr-side.right .bar{transform-origin:left;}
  .bar.m{background:linear-gradient(90deg,var(--blue-soft),var(--blue));}
  .bar.f{background:linear-gradient(90deg,var(--amber),#f1c07a);}
  .pyr-side .v{font-size:.8rem; font-weight:700; color:var(--ink-soft); white-space:nowrap;}
  .pyr-side .v small{font-weight:400; color:var(--muted); margin-left:4px;}
  .pyr-side.left .v{padding-right:8px;} .pyr-side.right .v{padding-left:8px;}
  .pyr-label{text-align:center; font-size:.84rem; font-weight:700; color:var(--ink); white-space:nowrap; line-height:1.1;
    display:flex; flex-direction:column-reverse; align-items:center; gap:3px;}
  .u-stripe{height:5px; width:var(--wuc); background:var(--slate); opacity:.7; border-radius:2px; min-width:0; flex-shrink:0;}
  .pyr-row.nodata{margin-top:6px; padding-top:9px; border-top:1px dashed var(--line);}
  .pyr-row.nodata .pyr-label{color:var(--muted); font-weight:600;}
  .pyr-note{font-size:.84rem; color:var(--ink-soft); margin:12px 0 0; text-wrap:pretty;}
  .pyr-note b{color:var(--navy);}
  .pyr-legend{display:flex; gap:20px; flex-wrap:wrap; margin-top:10px; font-size:.86rem; color:var(--ink-soft);}
  .pyr-legend .leg{display:flex; gap:8px; align-items:center;}
  .pyr-legend .dot{width:11px; height:11px; border-radius:3px;}
  footer{margin-top:clamp(34px,5vw,52px); padding-top:24px; border-top:1px solid var(--line); text-align:center;}
  .credit{display:inline-flex; align-items:center; gap:12px; justify-content:center; flex-wrap:wrap;
    background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 22px; margin:0 auto 16px;
    color:var(--ink-soft); font-size:.92rem; max-width:78ch; text-align:left;}
  .credit b{color:var(--ink);}
  footer p{margin:.55em auto; max-width:80ch; color:var(--muted); font-size:.82rem;}
  .support-logo{margin-top:22px; display:flex; justify-content:center; opacity:.85;}
  footer b{color:var(--ink-soft);}
  footer a{color:var(--blue-deep); font-weight:600; text-decoration:none; border-bottom:1px solid var(--blue-soft);}
  footer a:hover{border-bottom-color:var(--blue-deep);}
  a:focus-visible{outline:2px solid var(--blue); outline-offset:2px;}
  @media(max-width:900px){
    .implic{grid-template-columns:1fr;}
  }
  @media(max-width:760px){
    .kpis{grid-template-columns:repeat(2,1fr);}
    .cifras{grid-template-columns:repeat(2,1fr);}
    .caveat{grid-template-columns:1fr;}
    .cols{grid-template-columns:1fr;}
    .bar{grid-template-columns:7rem 1fr auto;}
    .cbar{grid-template-columns:5.5rem 1fr 3rem;}
    .bandwrap{flex-direction:column; gap:14px;}
    .langlbl{display:none;} .langbar-in{justify-content:center;}
    .pyr-head, .pyr-row{grid-template-columns:1fr 4.4rem 1fr;}
    .pyr-side .v small{display:none;}
  }
  @media(max-width:430px){
    .cifras{grid-template-columns:1fr;}
    .bar{grid-template-columns:5.6rem 1fr auto; font-size:.86rem; gap:8px;}
    .bar .val small{display:none;}
    .trend-chips{flex-direction:column; align-items:flex-start;}
    .donut{width:132px; height:132px;}
    .pyr-head, .pyr-row{grid-template-columns:1fr 3.6rem 1fr;}
    .pyr-side .v{font-size:.72rem;}
    .credit{padding:14px 16px;}
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
  </div>
</header>

<div class="wrap">

  <!-- ─── PANORAMA / ANÁLISIS (arriba, para periodistas) ─── -->
  <section class="analysis" style="margin-top:0">
    <h2 data-i18n-html="analysis_h2">@@analysis_h2@@</h2>
    <p class="analysis-body" data-i18n-html="analysis_body">@@analysis_body@@</p>
    <div class="conf">
      <span class="conf-badge"><span class="conf-lbl" data-i18n-html="conf_lbl">@@conf_lbl@@</span>
        <span class="conf-val" data-i18n-html="conf_val">@@conf_val@@</span></span>
      <span class="conf-note" data-i18n-html="conf_note">@@conf_note@@</span>
    </div>
  </section>

  <section aria-label="KPIs" style="margin-top:22px">
    <div class="kpis" data-i18n-html="kpis">@@kpis@@</div>
  </section>

  <section class="cifras-sec">
    <h2 data-i18n-html="cifras_h2">@@cifras_h2@@</h2>
    <p class="sub" data-i18n-html="cifras_sub">@@cifras_sub@@</p>
    <div class="cifras" data-i18n-html="cifras">@@cifras@@</div>
  </section>

  <section class="implic-sec">
    <h2 data-i18n-html="implic_h2">@@implic_h2@@</h2>
    <p class="sub" data-i18n-html="implic_sub">@@implic_sub@@</p>
    <div class="implic" data-i18n-html="implicaciones">@@implicaciones@@</div>
  </section>

  <section class="trend-sec">
    <h2 data-i18n-html="trend_h2">@@trend_h2@@</h2>
    <p class="sub" data-i18n-html="trend_sub">@@trend_sub@@</p>
    <div class="trend" data-i18n-html="trend">@@trend@@</div>
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
    <h2 data-i18n-html="pyr_intro_h2">@@pyr_intro_h2@@</h2>
    <p class="sub" data-i18n-html="pyr_intro_sub">@@pyr_intro_sub@@</p>
    <div data-i18n-html="pyramids">@@pyramids@@</div>
  </section>

  <hr class="rule">

  <section>
    <h2 data-i18n-html="ubic_h2">@@ubic_h2@@</h2>
    <p class="sub" data-i18n-html="ubic_sub">@@ubic_sub@@</p>
    <div class="bars" data-i18n-html="city_bars">@@city_bars@@</div>
  </section>

  <hr class="rule">

  <section class="caveat-sec">
    <h2 data-i18n-html="caveat_h2">@@caveat_h2@@</h2>
    <div class="caveat">
      <div class="caveat-col caveat-yes">
        <h3 data-i18n-html="caveat_yes_h">@@caveat_yes_h@@</h3>
        <ul data-i18n-html="caveat_yes">@@caveat_yes@@</ul>
      </div>
      <div class="caveat-col caveat-no">
        <h3 data-i18n-html="caveat_no_h">@@caveat_no_h@@</h3>
        <ul data-i18n-html="caveat_no">@@caveat_no@@</ul>
      </div>
    </div>
  </section>

  <hr class="rule">

  <!-- ─── SECCIÓN TÉCNICA (al final, para quien quiera auditar el método) ─── -->
  <section class="tech-sec">
    <h2 data-i18n-html="tech_h2">@@tech_h2@@</h2>
    <p class="sub" data-i18n-html="tech_sub">@@tech_sub@@</p>
    <div class="provenance" data-i18n-html="provenance">@@provenance@@</div>
    <div class="srcnote" data-i18n-html="srcnote">@@srcnote@@</div>
    <div class="method" data-i18n-html="method">@@method@@</div>
    <div class="compl-block">
      <h3 data-i18n-html="compl_h2">@@compl_h2@@</h3>
      <p class="sub" data-i18n-html="compl_sub">@@compl_sub@@</p>
      <div class="cbars" data-i18n-html="completeness">@@completeness@@</div>
    </div>
  </section>

  <footer>
    <div class="credit">
      <span data-i18n-html="credit">@@credit@@</span>
    </div>
    <p data-i18n-html="authors">@@authors@@</p>
    <p data-i18n-html="source">@@source@@</p>
    <p data-i18n-html="repo">@@repo@@</p>
    <p data-i18n-html="method_foot">@@method_foot@@</p>
    <p data-i18n-html="use">@@use@@</p>
    <div class="support-logo">
      <span class="olds-logo olds-logo--ft" role="img" aria-label="Observatorio Latinoamericano de Desarrollo Sostenible"></span>
    </div>
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
