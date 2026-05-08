from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, Response, jsonify
from models import db, Movie, User, OracleBlacklist
from tmdb_helper import search_movie, get_movie_details, get_imdb_rating, get_movie_keywords
import os
import csv
from io import StringIO
from dotenv import load_dotenv
import json
import requests

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'fallback_dev_key_cambiar_en_prod')
# Lee la URL de la base de datos desde tu archivo .env (PostgreSQL)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Crea las tablas (User y Movie) automáticamente si no existen
with app.app_context():
    try:
        db.create_all()
    except Exception:
        pass

# --- RUTAS PWA ---
@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def sw():
    return send_from_directory('static', 'sw.js')

# --- AUTENTICACIÓN Y REGISTRO ---
@app.route('/', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('index'))
    
    error = None
    if request.method == 'POST':
        # 1. Agarramos lo que escribió (solo le sacamos los espacios, dejamos las mayúsculas)
        username_input = request.form.get('username').strip()
        password = request.form.get('password')
        
        # 2. Magia pura: Convertimos temporalmente la base y el texto a minúsculas solo para comparar
        user = User.query.filter(db.func.lower(User.username) == username_input.lower()).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            # 3. Guardamos en la sesión el nombre original tal cual está en la base de datos
            session['username'] = user.username
            session.permanent = True
            return redirect(url_for('index'))
        else:
            error = "Usuario o contraseña incorrectos"
            
    return render_template('login.html', error=error, mode='login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('user_id'):
        return redirect(url_for('index'))
    
    error = None
    if request.method == 'POST':
        # Agarramos el texto original
        username_input = request.form.get('username').strip()
        password = request.form.get('password')
        
        # Verificamos si existe alguien con ese nombre (ignorando mayúsculas)
        existe = User.query.filter(db.func.lower(User.username) == username_input.lower()).first()
        
        if existe:
            error = "El usuario ya existe. Elegí otro."
        else:
            # Guardamos el usuario con el formato EXACTO que escribió
            nuevo_usuario = User(username=username_input)
            nuevo_usuario.set_password(password)
            db.session.add(nuevo_usuario)
            db.session.commit()
            
            session['user_id'] = nuevo_usuario.id
            session['username'] = nuevo_usuario.username
            return redirect(url_for('index'))
            
    return render_template('login.html', error=error, mode='register')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- BACKUP ---
@app.route('/dashboard/export')
def export_csv():
    if not session.get('user_id'):
        return redirect(url_for('login'))
        
    # Solo exporta las películas del usuario logueado
    peliculas = Movie.query.filter_by(user_id=session['user_id']).all()
    
    def generate():
        data = StringIO()
        writer = csv.writer(data)
        writer.writerow(['ID', 'Titulo', 'Estado', 'Fecha Vista', 'Plataforma', 'Puntaje Vault', 'Puntaje IMDb', 'Opinion', 'Director', 'Generos'])
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)
        
        for p in peliculas:
            estado = 'Watchlist' if p.is_watchlist else ('Abandonada' if p.abandoned else 'Colección')
            writer.writerow([
                p.tmdb_id, p.title, estado, p.date_watched or 'N/A', 
                p.platform or 'N/A', p.rating or 'N/A', p.imdb_score or 'N/A',
                p.opinion or '', p.director, p.genres
            ])
            yield data.getvalue()
            data.seek(0)
            data.truncate(0)
            
    # El archivo ahora tiene el nombre del usuario para no mezclar backups
    filename = f"mobatai_vault_{session['username']}_backup.csv"
    return Response(generate(), mimetype='text/csv', headers={"Content-Disposition": f"attachment; filename={filename}"})

# --- RUTAS PRINCIPALES ---
@app.route('/dashboard/index')
def index():
    if not session.get('user_id'):
        return redirect(url_for('login'))
        
    # Trae SOLO las películas del dueño de la cuenta
    todas_las_pelis = Movie.query.filter_by(user_id=session['user_id']).all()
    
    vistas = [p for p in todas_las_pelis if not p.is_watchlist]
    pendientes = [p for p in todas_las_pelis if p.is_watchlist]
    
    vistas.sort(key=lambda x: x.date_watched or '0000-00-00', reverse=True)
    pendientes.sort(key=lambda x: x.id, reverse=True)
    
    ratings = [p.rating for p in vistas if p.rating is not None and not p.abandoned]
    promedio = round(sum(ratings) / len(ratings)) if ratings else 0
    
    plataformas = {}
    for p in vistas:
        if p.platform:
            plataformas[p.platform] = plataformas.get(p.platform, 0) + 1
    plataforma_fav = max(plataformas, key=plataformas.get) if plataformas else "N/A"
    
    stats = {'total': len(vistas), 'promedio': promedio, 'plataforma': plataforma_fav}
    
    return render_template('index.html', peliculas=vistas, pendientes=pendientes, stats=stats)

@app.route('/dashboard/top10')
def top10():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    peliculas = Movie.query.filter_by(user_id=session['user_id'])\
        .filter(Movie.rating.isnot(None), Movie.is_watchlist == False, Movie.abandoned == False)\
        .order_by(Movie.rating.desc()).limit(10).all()
    return render_template('top10.html', peliculas=peliculas, username=session.get('username'))

@app.route('/dashboard/stats')
def stats():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    todas = Movie.query.filter_by(user_id=session['user_id']).all()
    vistas = [p for p in todas if not p.is_watchlist and not p.abandoned]
    abandonadas = [p for p in todas if p.abandoned]
    pendientes = [p for p in todas if p.is_watchlist]
    volver_a_ver = [p for p in vistas if p.rating is None]
    calificadas = [p for p in vistas if p.rating is not None]

    # Promedio general
    promedio = round(sum(p.rating for p in calificadas) / len(calificadas)) if calificadas else 0

    # Distribución de puntuaciones
    rangos = {'0-34': 0, '35-54': 0, '55-74': 0, '75-89': 0, '90-99': 0, '100': 0}
    for p in calificadas:
        r = p.rating
        if r == 100: rangos['100'] += 1
        elif r >= 90: rangos['90-99'] += 1
        elif r >= 75: rangos['75-89'] += 1
        elif r >= 55: rangos['55-74'] += 1
        elif r >= 35: rangos['35-54'] += 1
        else: rangos['0-34'] += 1

    # Películas por mes — todos los meses con actividad, ordenados cronológicamente
    from collections import defaultdict
    por_mes = defaultdict(int)
    for p in vistas:
        if p.date_watched and len(p.date_watched) >= 7:
            mes_key = p.date_watched[:7]  # "YYYY-MM"
            por_mes[mes_key] += 1
    meses_sorted = sorted(por_mes.items())  # todos, orden cronológico

    # Top plataformas
    plataformas = defaultdict(int)
    for p in vistas:
        if p.platform:
            plataformas[p.platform] += 1
    top_plataformas = sorted(plataformas.items(), key=lambda x: x[1], reverse=True)[:6]

    # Top combos de géneros — un combo por película (primeros 2 géneros)
    combos_count = defaultdict(int)
    for p in vistas:
        if not p.genres:
            continue
        gs = [g.strip() for g in p.genres.split(',') if g.strip()]
        combo = " / ".join(sorted(gs[:2])) if len(gs) >= 2 else gs[0]
        combos_count[combo] += 1
    top_generos = sorted(combos_count.items(), key=lambda x: x[1], reverse=True)[:6]

    # Top directores
    directores_count = defaultdict(int)
    for p in calificadas:
        if p.director and p.director != 'Desconocido':
            directores_count[p.director] += 1
    top_directores = sorted(directores_count.items(), key=lambda x: x[1], reverse=True)[:5]

    # Mejor y peor película
    mejor = max(calificadas, key=lambda x: x.rating) if calificadas else None
    peor = min(calificadas, key=lambda x: x.rating) if calificadas else None

    # Película más reciente y más antigua con fecha
    con_fecha = [p for p in vistas if p.date_watched]
    con_fecha_sorted = sorted(con_fecha, key=lambda x: x.date_watched)
    primera = con_fecha_sorted[0] if con_fecha_sorted else None
    ultima = con_fecha_sorted[-1] if con_fecha_sorted else None

    total_minutos = sum(p.runtime for p in vistas if p.runtime)

    # Perfil cinéfilo — solo keywords de tono/estilo/atmósfera
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

    kw_alto = defaultdict(int)
    kw_bajo = defaultdict(int)

    for p in calificadas:
        if not p.keywords:
            continue
        kws = [k.strip() for k in p.keywords.split(',') if k.strip().lower() in KW_UTILES]
        bucket = kw_alto if p.rating >= 75 else kw_bajo
        for kw in kws:
            bucket[kw] += 1

    top_perfil = sorted(kw_alto.items(), key=lambda x: -x[1])[:18]

    kw_evita = sorted(
        [(kw, cnt) for kw, cnt in kw_bajo.items() if kw not in kw_alto],
        key=lambda x: -x[1]
    )[:8]

    stats_data = {
        'total_vistas': len(vistas),
        'total_minutos': total_minutos,
        'total_calificadas': len(calificadas),
        'total_abandonadas': len(abandonadas),
        'total_pendientes': len(pendientes),
        'total_volver': len(volver_a_ver),
        'promedio': promedio,
        'rangos': rangos,
        'meses': meses_sorted,
        'top_plataformas': top_plataformas,
        'top_generos': top_generos,
        'top_directores': top_directores,
        'mejor': mejor,
        'peor': peor,
        'primera': primera,
        'ultima': ultima,
        'perfil_keywords': top_perfil,
        'perfil_evita': kw_evita,
    }

    return render_template('stats.html', stats=stats_data)

@app.route('/dashboard/form', methods=['GET', 'POST'])
def form():
    if not session.get('user_id'):
        return redirect(url_for('login'))
        
    resultados = []
    if request.method == 'POST':
        query = request.form.get('query')
        resultados = search_movie(query)
        
    return render_template('form.html', resultados=resultados)

@app.route('/dashboard/save', methods=['POST'])
def save_movie():
    if not session.get('user_id'):
        return redirect(url_for('login'))
        
    tmdb_id = request.form.get('tmdb_id')
    title = request.form.get('title')
    poster_path = request.form.get('poster_path')
    
    is_watchlist = request.form.get('action') == 'watchlist'
    abandoned = request.form.get('abandoned') == 'on'
    
    rating_str = request.form.get('rating')
    rating = int(rating_str) if rating_str and rating_str.strip() != "" else None
    date_str = request.form.get('date_watched')
    date_watched = date_str if date_str and date_str.strip() != "" else None
    platform = request.form.get('platform')
    opinion = request.form.get('opinion')
    
    # Comprueba que el usuario logueado no tenga ya esta película
    existe = Movie.query.filter_by(tmdb_id=tmdb_id, user_id=session['user_id']).first()
    
    if not existe:
        details = get_movie_details(tmdb_id)
        director = 'Desconocido'
        actores = ''
        generos = ''
        imdb_score = None
        runtime = None
        
        if details:
            crew = details.get('credits', {}).get('crew', [])
            director = next((c['name'] for c in crew if c['job'] == 'Director'), 'Desconocido')
            
            cast = details.get('credits', {}).get('cast', [])
            actores = ", ".join([a['name'] for a in cast[:3]])
            
            generos_list = details.get('genres', [])
            generos = ", ".join([g['name'] for g in generos_list])
            
            # MAGIA IMDB: Traemos el código de IMDb y buscamos el puntaje
            imdb_id = details.get('imdb_id')
            if imdb_id:
                imdb_score = get_imdb_rating(imdb_id)
            runtime = details.get('runtime') or None

            kw_list = get_movie_keywords(tmdb_id)
            keywords_str = ", ".join(kw_list) if kw_list else None

        nueva_peli = Movie(
            user_id=session['user_id'],
            tmdb_id=tmdb_id, title=title, poster_path=poster_path,
            rating=rating, platform=platform, opinion=opinion, date_watched=date_watched,
            director=director, genres=generos, cast=actores, imdb_score=imdb_score,
            is_watchlist=is_watchlist, abandoned=abandoned, runtime=runtime,
            keywords=keywords_str
        )
        db.session.add(nueva_peli)
        db.session.commit()
        
    return redirect(url_for('index'))

@app.route('/dashboard/delete/<int:id>', methods=['POST'])
def delete_movie(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
        
    # Busca la película asegurándose de que pertenece a este usuario
    pelicula = Movie.query.filter_by(id=id, user_id=session['user_id']).first_or_404()
    db.session.delete(pelicula)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/dashboard/edit/<int:id>', methods=['GET', 'POST'])
def edit_movie(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
        
    # Busca la película asegurándose de que pertenece a este usuario
    pelicula = Movie.query.filter_by(id=id, user_id=session['user_id']).first_or_404()
    
    if request.method == 'POST':
        date_str = request.form.get('date_watched')
        pelicula.date_watched = date_str if date_str and date_str.strip() != "" else None
        
        pelicula.platform = request.form.get('platform')
        
        rating_str = request.form.get('rating')
        pelicula.rating = int(rating_str) if rating_str and rating_str.strip() != "" else None
        
        pelicula.opinion = request.form.get('opinion')
        
        pelicula.abandoned = request.form.get('abandoned') == 'on'
        pelicula.is_watchlist = False 
        
        pelicula.imdb_score = request.form.get('imdb_score')
        
        db.session.commit()
        return redirect(url_for('index'))
        
    return render_template('edit.html', peli=pelicula)

@app.route('/dashboard/oracle', methods=['GET', 'POST'])
def oracle():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    if request.method == 'GET':
        return render_template('oracle.html')

    # --- LOGICA DEL POST ---
    mis_pelis = Movie.query.filter_by(user_id=session['user_id']).all()

    if len(mis_pelis) < 3:
        return jsonify({'error': "El Oráculo necesita más datos. Agregá al menos 3 películas a tu bóveda."})

    cantidad = int(request.json.get('cantidad', 3)) if request.is_json else 3
    ya_mostradas = request.json.get('ya_mostradas', []) if request.is_json else []
    ya_mostradas_ids = {str(i) for i in request.json.get('ya_mostradas_ids', [])} if request.is_json else set()

    historial = []
    for p in mis_pelis:
        if p.is_watchlist and not p.rating and not p.abandoned:
            historial.append(f"- {p.title} (Watchlist — NO RECOMENDAR)")
        elif p.abandoned:
            historial.append(f"- {p.title} (Abandonada — NO RECOMENDAR)")
        elif p.rating:
            historial.append(f"- {p.title} (Puntaje: {p.rating}/100)")
        else:
            historial.append(f"- {p.title} (Vista)")

    blacklist = OracleBlacklist.query.filter_by(user_id=session['user_id']).all()
    for b in blacklist:
        historial.append(f"- {b.title} (Descartada — NO RECOMENDAR NUNCA)")

    reporte_peliculas = "\n".join(historial)

    excluir_str = ""
    if ya_mostradas:
        excluir_str = f"\n\nPelículas que YA recomendé antes (NO repetir ninguna, ni siquiera el bonus): {', '.join(ya_mostradas)}."

    prompt = f"""Actua como un critico y curador cinefilo con criterio moderno y personalidad propia.

IMPORTANTE:
Responde EXCLUSIVAMENTE en JSON valido.
NO agregues texto fuera del JSON.
NO uses markdown.
NO uses ```json.
NO expliques el formato.
NO agregues introducciones ni cierres.

No analices solo generos o popularidad.
Detecta especificamente:
- tipo de complejidad narrativa que disfruto,
- nivel de ambiguedad tolerado,
- equilibrio entre emocion e intelectualidad,
- ritmo preferido,
- tolerancia al simbolismo abstracto,
- y si prefiero peliculas contemplativas o de tension constante.

NO confundas:
- complejidad emocional y narrativa accesible
con
- surrealismo abstracto o cine excesivamente simbolico.

Dale MUCHISIMO mas peso a:
- peliculas con puntajes 85+,
- peliculas abandonadas,
- peliculas odiadas,
que a peliculas entre 65 y 75.

No recomiendes peliculas solo porque son consideradas obras maestras o cine importante.
Prioriza compatibilidad real con mi sensibilidad cinematografica.

Peliculas:
{reporte_peliculas}{excluir_str}

REGLA FUNDAMENTAL:
No recomiendes ninguna pelicula que aparezca en el historial.
Los titulos pueden estar en español o ingles, con o sin año.
Si el titulo es parecido Y comparte director o elenco, tratalos como la misma pelicula.

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

    try:
        groq_key = os.getenv('GROQ_API_KEY')
        resp = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {groq_key}', 'Content-Type': 'application/json'},
            json={'model': 'llama-3.3-70b-versatile', 'messages': [{'role': 'user', 'content': prompt}], 'temperature': 0.8},
            timeout=30
        )
        resp.raise_for_status()

        texto_limpio = resp.json()['choices'][0]['message']['content'].strip()
        if texto_limpio.startswith("```json"):
            texto_limpio = texto_limpio[7:-3].strip()
        elif texto_limpio.startswith("```"):
            texto_limpio = texto_limpio[3:-3].strip()

        parsed = json.loads(texto_limpio)

        todos = []
        for rec in parsed.get('recommendations', []):
            justif = f"Dir. {rec.get('director', '')}. {rec.get('why_it_fits', '')} {rec.get('feeling_after_watching', '')}".strip()
            todos.append({
                'titulo': rec.get('original_title') or rec.get('title', ''),
                'anio': rec.get('year', ''),
                'justificacion': justif,
                'bonus': False
            })
        bonus_raw = parsed.get('bonus')
        if bonus_raw:
            justif = f"Dir. {bonus_raw.get('director', '')}. {bonus_raw.get('why_it_is_essential', '')} {bonus_raw.get('feeling_after_watching', '')}".strip()
            todos.append({
                'titulo': bonus_raw.get('original_title') or bonus_raw.get('title', ''),
                'anio': bonus_raw.get('year', ''),
                'justificacion': justif,
                'bonus': True
            })

        # IDs y blacklist existentes para filtrar server-side
        existing_tmdb_ids = {str(p.tmdb_id) for p in mis_pelis if p.tmdb_id}
        blacklist_ids = {str(b.tmdb_id) for b in OracleBlacklist.query.filter_by(user_id=session['user_id']).all() if b.tmdb_id}
        excluir_ids = existing_tmdb_ids | blacklist_ids | ya_mostradas_ids

        # ENRIQUECER CON TMDB
        tmdb_api_key = os.getenv('TMDB_API_KEY')
        resultados_finales = []

        for rec in todos:
            search_url = f"https://api.themoviedb.org/3/search/movie?api_key={tmdb_api_key}&query={rec['titulo']}&year={rec['anio']}&language=es-ES"
            tmdb_res = requests.get(search_url).json()

            poster_fallback = '/static/mbvault-512.png'
            es_bonus = rec.get('bonus', False)

            if tmdb_res.get('results'):
                peli = tmdb_res['results'][0]
                details = get_movie_details(peli['id'])
                imdb_score = None
                if details and details.get('imdb_id'):
                    imdb_score = get_imdb_rating(details['imdb_id'])
                orig_lang = peli.get('original_language', '')
                if orig_lang in ('en', 'es'):
                    display_title = peli.get('original_title') or peli.get('title')
                else:
                    display_title = peli.get('title')
                if str(peli['id']) not in excluir_ids:
                    resultados_finales.append({
                        'titulo': display_title,
                        'original_title': rec['titulo'],
                        'poster': f"https://image.tmdb.org/t/p/w500{peli['poster_path']}" if peli.get('poster_path') else poster_fallback,
                        'sinopsis': peli.get('overview', 'Sin descripción disponible.'),
                        'fecha': peli.get('release_date', '').split('-')[0] if peli.get('release_date') else rec['anio'],
                        'justificacion': rec['justificacion'],
                        'tmdb_id': peli['id'],
                        'imdb_score': imdb_score,
                        'bonus': es_bonus
                    })
            else:
                resultados_finales.append({
                    'titulo': rec['titulo'],
                    'original_title': rec['titulo'],
                    'poster': poster_fallback,
                    'sinopsis': 'Detalles no encontrados en TMDB.',
                    'fecha': rec['anio'],
                    'justificacion': rec['justificacion'],
                    'tmdb_id': '',
                    'imdb_score': None,
                    'bonus': es_bonus
                })

        # Separar regulares y bonus, limitar regulares a cantidad solicitada
        regulares = [r for r in resultados_finales if not r['bonus']][:cantidad]
        bonus = [r for r in resultados_finales if r['bonus']][:1]
        return jsonify({'success': True, 'peliculas': regulares + bonus})

    except Exception as e:
        return jsonify({'error': f"Fallo en la conexión neural: {str(e)}"})

@app.route('/dashboard/oracle/prompt')
def oracle_prompt():
    if not session.get('user_id'):
        return jsonify({'error': 'Sesión expirada'})
    mis_pelis = Movie.query.filter_by(user_id=session['user_id']).all()
    historial = []
    for p in mis_pelis:
        if p.is_watchlist and not p.rating and not p.abandoned:
            historial.append(f"'{p.title}' (En mi Watchlist - NO RECOMENDAR)")
        elif p.abandoned:
            historial.append(f"'{p.title}' (Abandonada - Odio esto)")
        elif p.rating:
            historial.append(f"'{p.title}' (Puntaje: {p.rating}/100)")
        else:
            historial.append(f"'{p.title}' (Vista)")
    lineas = "\n".join(historial)
    prompt = f"""Actua como un critico y curador cinefilo con criterio moderno y personalidad propia.

No analices solo generos o popularidad.
Detecta especificamente:
- tipo de complejidad narrativa que disfruto,
- nivel de ambiguedad tolerado,
- equilibrio entre emocion e intelectualidad,
- ritmo preferido,
- tolerancia al simbolismo abstracto,
- y si prefiero peliculas contemplativas o de tension constante.

NO confundas:
- complejidad emocional y narrativa accesible
con
- surrealismo abstracto o cine excesivamente simbolico.

Dale MUCHISIMO mas peso a:
- peliculas con puntajes 85+,
- peliculas abandonadas,
- peliculas odiadas,
que a peliculas entre 65 y 75.

No recomiendes peliculas solo porque son consideradas obras maestras o cine importante.
Prioriza compatibilidad real con mi sensibilidad cinematografica.

Peliculas:
{lineas}

REGLA FUNDAMENTAL:
No recomiendes ninguna pelicula que aparezca en el historial.
Los titulos pueden estar en español o ingles, con o sin año.
Si el titulo es parecido Y comparte director o elenco, tratalos como la misma pelicula.

Tu respuesta tiene DOS partes:

PARTE 1:
Recomendame exactamente 3 peliculas que NO esten en la lista anterior y que encajen MUY bien con mis gustos.

Evita recomendaciones genericas.
Explica especificamente por que cada una conecta conmigo.

Prioriza:
- compatibilidad emocional,
- tono,
- tension,
- tipo de narrativa,
- atmosfera,
- y sensibilidad cinematografica.

NO priorices solamente:
- genero,
- popularidad,
- puntuacion critica,
- ni peliculas "complejas" porque si.

Para cada recomendacion indica:
- titulo original,
- año,
- director,
- por que la recomendas especificamente para mi,
- y que sensacion deja despues de verla.

PARTE 2 - BONUS SALVAJE:

Recomendame UNA sola pelicula fuera de mis gustos habituales, pero que sea considerada una experiencia cinematografica imprescindible y ampliamente reconocida.

NO quiero:
- cine experimental,
- peliculas de nicho,
- cine extremadamente artistico,
- ni recomendaciones "para entendidos".

Quiero una pelicula enorme, influyente o mundialmente considerada un peliculon.

Para la recomendacion bonus indica:
- titulo original,
- año,
- director,
- por que es considerada imprescindible,
- y que sensacion deja despues de verla.

No hagas listas genericas.
Prioriza personalidad, precision y criterio antes que popularidad."""
    return jsonify({'prompt': prompt})

@app.route('/dashboard/oracle/discard', methods=['POST'])
def oracle_discard():
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Sesión expirada'})
    data = request.json
    tmdb_id = data.get('tmdb_id')
    titulo = data.get('titulo')
    existe = OracleBlacklist.query.filter_by(user_id=session['user_id'], tmdb_id=tmdb_id).first()
    if not existe:
        db.session.add(OracleBlacklist(user_id=session['user_id'], tmdb_id=tmdb_id, title=titulo))
        db.session.commit()
    return jsonify({'success': True})

@app.route('/dashboard/oracle/add_watchlist', methods=['POST'])
def oracle_add_watchlist():
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Sesión expirada'})
        
    data = request.json
    tmdb_id = data.get('tmdb_id')
    titulo = data.get('titulo')
    poster = data.get('poster')
    
    # 1. Verificamos que no la tengas ya en la bóveda
    existe = Movie.query.filter_by(user_id=session['user_id'], tmdb_id=tmdb_id).first()
    if existe:
        return jsonify({'success': False, 'error': 'Ya está en tu colección'})
        
    # 2. Vamos a TMDB a buscar la data completa (Director, Cast, Géneros y ahora IMDb)
    try:
        details = get_movie_details(tmdb_id)
        director = 'Desconocido'
        actores = ''
        generos = ''
        imdb_score = None
        
        if details:
            crew = details.get('credits', {}).get('crew', [])
            director = next((c['name'] for c in crew if c['job'] == 'Director'), 'Desconocido')
            
            cast = details.get('credits', {}).get('cast', [])
            actores = ", ".join([a['name'] for a in cast[:3]])
            
            generos_list = details.get('genres', [])
            generos = ", ".join([g['name'] for g in generos_list])
            
            imdb_id = details.get('imdb_id')
            if imdb_id:
                imdb_score = get_imdb_rating(imdb_id)

        kw_list = get_movie_keywords(tmdb_id)
        keywords_str = ", ".join(kw_list) if kw_list else None

        # 3. La guardamos en la Watchlist con TODOS los datos
        nueva_peli = Movie(
            user_id=session['user_id'],
            tmdb_id=tmdb_id,
            title=titulo,
            poster_path=poster.replace('https://image.tmdb.org/t/p/w500', '') if 'tmdb.org' in poster else None,
            director=director,
            cast=actores,
            genres=generos,
            imdb_score=imdb_score,
            keywords=keywords_str,
            is_watchlist=True,
            abandoned=False
        )
        db.session.add(nueva_peli)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True)