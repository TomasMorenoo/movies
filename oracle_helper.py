from collections import defaultdict
import requests
from tmdb_helper import TMDB_API_KEY, BASE_URL

# Keywords de tono/estilo/atmosfera que sirven para perfilar gustos.
# (compartido entre /dashboard/stats y el Oraculo para que ambos usen la misma señal)
KW_UTILES = {
    # Géneros y subgéneros
    'psychological thriller', 'psychological horror', 'psychological drama',
    'crime thriller', 'crime horror', 'conspiracy thriller', 'suspense mystery',
    'neo-noir', 'dark fairy tale', 'magic realism', 'urban gothic', 'steampunk',
    'supernatural thriller', 'supernatural horror', 'spy thriller', 'space adventure',
    # Recursos narrativos
    'twist', 'time-manipulation', 'time travel', 'time paradox', 'non-linear narrative',
    'high concept', 'allegory', 'symbolism', 'ambiguity', 'surrealism',
    'parallel universe', 'whodunit', 'story within the story',
    # Temas y atmósfera
    'obsession', 'manipulation', 'revenge', 'guilt', 'redemption', 'suppressed past',
    'identity', 'melancholy', 'dystopia', 'investigation', 'vigilante',
    'rivalry', 'betrayal', 'deception', 'cowardice', 'ambivalent',
    # Figuras
    'serial killer', 'detective', 'psychopath', 'cannibal', 'spy',
    'heist', 'dream world', 'subconscious', 'memory', 'intellectual',
    # Ciencia ficción temática
    'wormhole', 'black hole', 'quantum mechanics', 'artificial intelligence (a.i.)',
    'space travel', 'alien contact', 'first contact', 'extraterrestrial technology',
    'determinism', 'communication',
    # Tono emocional útil
    'psychological profiling', 'cat and mouse', 'mind-blowing', 'bittersweet',
    'moral manipulation', 'ideological clash', 'psychological predator',
}


def kw_relevantes(raw_keywords, limit=None):
    if not raw_keywords:
        return []
    kws = [k.strip() for k in raw_keywords.split(',') if k.strip().lower() in KW_UTILES]
    return kws[:limit] if limit else kws


def build_taste_profile(calificadas):
    """A partir de películas calificadas, arma (keywords que le gustan, keywords que evita)."""
    kw_alto = defaultdict(int)
    kw_bajo = defaultdict(int)

    for p in calificadas:
        kws = kw_relevantes(p.keywords)
        bucket = kw_alto if p.rating >= 75 else kw_bajo
        for kw in kws:
            bucket[kw] += 1

    top_perfil = sorted(kw_alto.items(), key=lambda x: -x[1])[:18]
    kw_evita = sorted(
        [(kw, cnt) for kw, cnt in kw_bajo.items() if kw not in kw_alto],
        key=lambda x: -x[1]
    )[:8]
    return top_perfil, kw_evita


def _perfil_str(top_perfil, kw_evita):
    if not top_perfil and not kw_evita:
        return ""
    partes = []
    if top_perfil:
        partes.append("Rasgos que MAS le gustan (por frecuencia en pelis bien puntuadas): " +
                       ", ".join(kw for kw, _ in top_perfil))
    if kw_evita:
        partes.append("Rasgos presentes en peliculas que NO le gustaron: " +
                       ", ".join(kw for kw, _ in kw_evita))
    return "\n\nPERFIL DE GUSTOS (calculado de su historial real):\n" + "\n".join(partes)


def _movie_line(p):
    """Una linea de historial enriquecida con director/generos/keywords (no solo el titulo)."""
    detalle = []
    if p.director and p.director != 'Desconocido':
        detalle.append(f"Dir. {p.director}")
    if p.genres:
        detalle.append(p.genres)
    kws = kw_relevantes(p.keywords, limit=6)
    if kws:
        detalle.append("tags: " + ", ".join(kws))
    extra = f" [{' | '.join(detalle)}]" if detalle else ""

    if p.is_watchlist and not p.rating and not p.abandoned:
        return f"- {p.title}{extra} — EN WATCHLIST, NO RECOMENDAR"
    elif p.abandoned:
        return f"- {p.title}{extra} — ABANDONADA, NO RECOMENDAR NUNCA"
    elif p.rating:
        return f"- {p.title}{extra} — Puntaje: {p.rating}/100"
    else:
        return f"- {p.title}{extra} — Vista, sin puntaje"


def build_historial(movies, blacklist, shown=None):
    """Arma el historial completo: peliculas del usuario + descartadas + ya recomendadas antes."""
    lineas = [_movie_line(p) for p in movies]

    for b in blacklist:
        lineas.append(f"- {b.title} — DESCARTADA POR EL USUARIO, NO RECOMENDAR NUNCA")

    if shown:
        for s in shown:
            lineas.append(f"- {s.title} — YA RECOMENDADA EN UNA CONSULTA ANTERIOR, NO REPETIR")

    return "\n".join(lineas)


CRITERIOS_ANALISIS = """Tu objetivo NO es recomendar peliculas populares ni prestigiosas.
Tu objetivo es detectar con la mayor precision posible que tipo de experiencia cinematografica disfruta esta persona y recomendar peliculas compatibles con esa sensibilidad.

ANALISIS OBLIGATORIO (hacelo antes de recomendar, no lo muestres en la respuesta):
- Identifica patrones reales en las puntuaciones.
- Detecta que peliculas parecen gustarle por su narrativa y cuales por su carga emocional.
- Detecta falsos positivos y falsos negativos (peliculas bien puntuadas que no encajan con el resto del patron, o mal puntuadas que si encajan).
- Detecta que elementos aparecen repetidamente en sus peliculas favoritas y en las peor valoradas.
- Detecta contradicciones aparentes.
- Determina que caracteristicas tienen mas peso en sus gustos.

No analices solo generos o popularidad. Deteca especificamente:
- tipo de complejidad narrativa que disfruta,
- nivel de ambiguedad tolerado,
- equilibrio entre emocion e intelectualidad,
- ritmo preferido,
- tolerancia al simbolismo abstracto,
- tipo de finales que mas valora,
- nivel de oscuridad emocional preferido,
- tipo de tension que funciona mejor para el,
- y si prefiere peliculas contemplativas o de tension constante.

NO confundas:
- complejidad emocional y narrativa accesible
con
- surrealismo abstracto, simbolismo excesivo, cine deliberadamente criptico, o peliculas donde el significado depende de interpretacion libre.

Para inferir gustos NO asumas que le gusta una pelicula solo por compartir genero, director, actor, tematica o prestigio critico.
Busca similitudes reales en: estructura narrativa, sensacion emocional, forma de generar tension, conflicto moral, atmosfera, accesibilidad narrativa, recompensa emocional, recompensa intelectual y experiencia global del espectador.

PESOS DE EVALUACION:
- Las peliculas con 90+ son la fuente principal para inferir gustos.
- Las de 85+ tienen muchisimo peso.
- Las abandonadas pesan mas negativo que una puntuada con 60.
- Las vistas completas pesan mas que las vistas sin puntuar.
- Las de 65 a 75 tienen poco peso comparativo.

DETECCION DE ANTI-GUSTOS:
Deteca explicitamente que NO le gusta. Las recomendaciones deben evitar esos rasgos incluso si pertenecen a generos que normalmente disfruta.
Presta especial atencion a: simbolismo excesivamente abierto, surrealismo interpretativo, narrativas que priorizan metafora sobre conflicto, peliculas que esconden demasiado el significado, o donde el espectador debe construir casi toda la interpretacion.

REGLA DE COMPATIBILIDAD:
Si una pelicula tiene alta compatibilidad emocional y narrativa pero menor prestigio o fama, preferila sobre una obra maestra universal que encaje solo parcialmente.
No recomiendes peliculas unicamente porque son consideradas obras maestras, son importantes para la historia del cine, o aparecen frecuentemente en listas de mejores peliculas.
Prioriza compatibilidad real con la sensibilidad cinematografica de la persona.

VARIEDAD:
Cada vez que te consulten, explora un angulo distinto de sus gustos. Evita repetir siempre los mismos directores o subgeneros dominantes, y evita que las recomendaciones sean todas clones del mismo estilo (ej. solo clones de Nolan, Fincher o Villeneuve) si eso ya predomina en su historial."""

REGLA_FUNDAMENTAL = """REGLA FUNDAMENTAL:
No recomiendes ninguna pelicula que aparezca en el historial. Esto incluye: vistas, abandonadas, watchlist, recomendadas anteriormente y descartadas.
Los titulos pueden estar en español o ingles, con o sin año.
Si el titulo es parecido Y comparte director o elenco principal, asumi que es la misma pelicula y NO la recomiendes."""


def build_json_prompt(historial_str, perfil_str, excluir_str, cantidad):
    return f"""Actua como un critico y curador cinefilo con criterio moderno y personalidad propia.

IMPORTANTE:
Responde EXCLUSIVAMENTE en JSON valido.
NO agregues texto fuera del JSON.
NO uses markdown.
NO uses ```json.
NO expliques el formato.
NO agregues introducciones ni cierres.

{CRITERIOS_ANALISIS}

Peliculas:
{historial_str}{perfil_str}{excluir_str}

{REGLA_FUNDAMENTAL}

La respuesta DEBE seguir EXACTAMENTE este esquema JSON:
{{
  "analysis": {{
    "main_tastes": [],
    "narrative_preferences": [],
    "emotional_profile": [],
    "preferred_pacing": "",
    "ambiguity_tolerance": "",
    "symbolism_tolerance": "",
    "complexity_type": "",
    "what_the_user_avoids": []
  }},
  "recommendations": [
    {{
      "title": "",
      "original_title": "",
      "year": "",
      "director": "",
      "why_it_fits": "",
      "feeling_after_watching": ""
    }}
  ],
  "bonus": {{
    "title": "",
    "original_title": "",
    "year": "",
    "director": "",
    "why_it_is_essential": "",
    "feeling_after_watching": ""
  }}
}}

REGLAS IMPORTANTES:
- recommendations debe tener EXACTAMENTE {cantidad + 3} peliculas.
- bonus debe tener EXACTAMENTE 1 pelicula.
- NO repitas peliculas del historial.
- NO recomiendes peliculas de la watchlist.
- NO recomiendes peliculas abandonadas.
- NO uses placeholders.
- NO dejes campos vacios.
- Las recomendaciones deben sentirse personalizadas y especificas para el usuario.
- El bonus debe ser una pelicula enorme, influyente o mundialmente considerada imprescindible, incluso si sale un poco de los gustos habituales del usuario."""


def build_manual_prompt(historial_str, perfil_str):
    return f"""# Actúa como un crítico y curador cinéfilo con criterio moderno, personalidad propia y capacidad de análisis de gustos.

Tu objetivo NO es recomendar películas populares ni prestigiosas.

Tu objetivo es detectar con la mayor precisión posible qué tipo de experiencia cinematográfica disfruta esta persona y recomendar películas compatibles con esa sensibilidad.

## FASE 0 — ANÁLISIS OBLIGATORIO

Antes de recomendar cualquier película:

* Identificá patrones reales en las puntuaciones.
* Detectá qué películas parecen gustarle por su narrativa.
* Detectá cuáles parecen gustarle por su carga emocional.
* Detectá falsos positivos y falsos negativos.
* Explicá qué elementos aparecen repetidamente en sus películas favoritas.
* Explicá qué elementos aparecen repetidamente en sus películas peor valoradas.
* Detectá contradicciones aparentes y explicalas.
* Determiná qué características tienen más peso en sus gustos.

NO hagas recomendaciones hasta terminar este análisis.

---

## COSAS QUE DEBÉS DETECTAR

No analices solamente géneros.

Detectá específicamente:

* tipo de complejidad narrativa que disfruta,
* nivel de ambigüedad tolerado,
* equilibrio entre emoción e intelectualidad,
* ritmo preferido,
* tolerancia al simbolismo abstracto,
* tipo de finales que más valora,
* nivel de oscuridad emocional preferido,
* tipo de tensión que funciona mejor para él,
* y si prefiere películas contemplativas o de tensión constante.

---

## NO CONFUNDIR

NO confundas:

* complejidad emocional y narrativa accesible

con

* surrealismo abstracto,
* simbolismo excesivo,
* cine deliberadamente críptico,
* películas donde el significado principal depende de interpretación libre.

---

## CÓMO INFERIR GUSTOS

NO asumas que le gusta una película por compartir:

* género,
* director,
* actor,
* temática,
* prestigio crítico.

Buscá similitudes en:

* estructura narrativa,
* sensación emocional,
* forma de generar tensión,
* conflicto moral,
* atmósfera,
* accesibilidad narrativa,
* recompensa emocional,
* recompensa intelectual,
* experiencia global del espectador.

---

## PESOS DE EVALUACIÓN

Las películas calificadas con 90+ son la fuente principal para inferir gustos.

Las películas calificadas con 85+ tienen muchísimo peso.

Las películas abandonadas tienen más peso negativo que una película puntuada con 60.

Las películas vistas completas tienen más peso que las vistas sin puntuar.

Las películas calificadas entre 65 y 75 tienen poco peso comparativo.

---

## DETECCIÓN DE ANTI-GUSTOS

Detectá explícitamente qué NO le gusta.

Las recomendaciones deben evitar compartir esos rasgos incluso si pertenecen a géneros que normalmente disfruta.

Prestá especial atención a:

* simbolismo excesivamente abierto,
* surrealismo interpretativo,
* narrativas que priorizan metáfora sobre conflicto,
* películas que esconden demasiado el significado,
* películas donde el espectador debe construir casi toda la interpretación.

---

## REGLA DE COMPATIBILIDAD

Si una película tiene:

* alta compatibilidad emocional,
* alta compatibilidad narrativa,

pero menor prestigio o fama,

preferila sobre una obra maestra universal que encaje sólo parcialmente.

NO recomiendes películas únicamente porque:

* son consideradas obras maestras,
* son importantes para la historia del cine,
* aparecen frecuentemente en listas de mejores películas.

Priorizá compatibilidad real.

---

## VARIEDAD

Cada vez que recomiendes películas:

* explorá un ángulo distinto de mis gustos,
* evitá repetir siempre los mismos directores,
* evitá repetir siempre los mismos subgéneros,
* evitá recomendar clones de Nolan, Fincher o Villeneuve.

---

## HISTORIAL DE PELÍCULAS

{historial_str}{perfil_str}

---

## REGLA FUNDAMENTAL

NO recomiendes ninguna película que aparezca en el historial.

Esto incluye:

* vistas,
* abandonadas,
* watchlist,
* recomendadas anteriormente,
* descartadas.

Los títulos pueden aparecer en español o inglés.

Si el título es parecido y comparte director o elenco principal, asumí que es la misma película y NO la recomiendes.

---

# FORMATO DE RESPUESTA

## PARTE 1 — PERFIL CINEMATOGRÁFICO

Explicá primero:

* qué tipo de espectador parece ser,
* qué busca emocionalmente,
* qué busca intelectualmente,
* qué cosas lo hacen desconectarse de una película,
* qué patrones encontraste.

Máximo 400 palabras.

---

## PARTE 2 — RECOMENDACIONES PRINCIPALES

Recomendame exactamente 3 películas que NO estén en el historial.

Para cada una indicar:

* título original,
* año,
* director,
* por qué encaja específicamente conmigo,
* qué aspecto de mi perfil satisface,
* qué sensación deja después de verla.

NO hagas descripciones genéricas.

---

## PARTE 3 — BONUS SALVAJE

Recomendame UNA sola película fuera de mis gustos habituales.

Debe ser:

* una experiencia cinematográfica enorme,
* ampliamente reconocida,
* influyente,
* accesible para público general.

NO quiero:

* cine experimental,
* cine de nicho,
* cine extremadamente artístico,
* películas para entendidos.

Indicar:

* título original,
* año,
* director,
* por qué es considerada imprescindible,
* qué sensación deja después de verla.

---

Priorizá precisión, criterio y compatibilidad antes que popularidad."""


def buscar_en_tmdb(titulo, anio):
    """Busca una recomendacion en TMDB e intenta quedarse con el match correcto
    (no ciegamente el primer resultado): prioriza coincidencia de año y, si hay
    varios candidatos en esa ventana de año, el mas popular."""
    params = {'api_key': TMDB_API_KEY, 'query': titulo, 'language': 'es-ES'}
    if anio:
        params['year'] = anio
    resp = requests.get(f"{BASE_URL}/search/movie", params=params, timeout=10)
    results = resp.json().get('results', []) if resp.status_code == 200 else []

    if not results and anio:
        # El año exacto puede estar mal (el modelo se lo puede inventar); reintentamos sin filtrar por año
        params_sin_anio = {'api_key': TMDB_API_KEY, 'query': titulo, 'language': 'es-ES'}
        resp2 = requests.get(f"{BASE_URL}/search/movie", params=params_sin_anio, timeout=10)
        results = resp2.json().get('results', []) if resp2.status_code == 200 else []

    if not results:
        return None

    def year_of(r):
        rd = r.get('release_date', '')
        return int(rd[:4]) if rd[:4].isdigit() else None

    if anio:
        try:
            anio_int = int(anio)
            candidatos = [r for r in results if year_of(r) is not None and abs(year_of(r) - anio_int) <= 1]
            if candidatos:
                candidatos.sort(key=lambda r: r.get('popularity', 0), reverse=True)
                return candidatos[0]
        except ValueError:
            pass

    return sorted(results, key=lambda r: r.get('popularity', 0), reverse=True)[0]
