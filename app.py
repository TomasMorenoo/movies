from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, Response, jsonify
from models import db, Movie, User, OracleBlacklist, OracleShown
from tmdb_helper import search_movie, get_movie_details, get_imdb_rating, get_movie_keywords
import oracle_helper
import os
import csv
from io import StringIO
from dotenv import load_dotenv
import json
import requests
from datetime import datetime

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY']
if len(app.secret_key) < 32 or app.secret_key == 'fallback_dev_key_cambiar_en_prod':
    raise RuntimeError('SECRET_KEY debe tener al menos 32 caracteres aleatorios')
from security import configure_security
configure_security(app)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

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
        username_input = request.form.get('username', '').strip()
        password = request.form.get('password')

        user = User.query.filter(db.func.lower(User.username) == username_input.lower()).first()

        if user and user.check_password(password):
            session.clear()
            session['user_id'] = user.id
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
        username_input = request.form.get('username', '').strip()
        password = request.form.get('password')

        existe = User.query.filter(db.func.lower(User.username) == username_input.lower()).first()

        if existe:
            error = "El usuario ya existe. Elegí otro."
        else:
            nuevo_usuario = User(username=username_input)
            nuevo_usuario.set_password(password)
            db.session.add(nuevo_usuario)
            db.session.commit()

            session.clear()
            session['user_id'] = nuevo_usuario.id
            session['username'] = nuevo_usuario.username
            return redirect(url_for('index'))

    return render_template('login.html', error=error, mode='register')

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- BACKUP ---
@app.route('/dashboard/export')
def export_csv():
    if not session.get('user_id'):
        return redirect(url_for('login'))

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
            row = [
                p.tmdb_id, p.title, estado, p.date_watched or 'N/A',
                p.platform or 'N/A', p.rating or 'N/A', p.imdb_score or 'N/A',
                p.opinion or '', p.director, p.genres
            ]
            writer.writerow(["'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v for v in row])
            yield data.getvalue()
            data.seek(0)
            data.truncate(0)

    filename = f"mobatai_vault_{session['user_id']}_backup.csv"
    return Response(generate(), mimetype='text/csv', headers={"Content-Disposition": f"attachment; filename={filename}"})

# --- RUTAS PRINCIPALES ---
@app.route('/dashboard/index')
def index():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    todas_las_pelis = Movie.query.filter_by(user_id=session['user_id']).all()

    vistas = [p for p in todas_las_pelis if not p.is_watchlist]
    pendientes = [p for p in todas_las_pelis if p.is_watchlist]

    vistas.sort(key=lambda x: (x.date_watched or '0000-00-00', x.created_at or datetime.min, x.id), reverse=True)
    pendientes.sort(key=lambda x: (x.created_at or datetime.min, x.id), reverse=True)

    ratings = [p.rating for p in vistas if p.rating is not None and not p.abandoned]
    promedio = round(sum(ratings) / len(ratings)) if ratings else 0

    plataformas = {}
    for p in vistas:
        if p.platform:
            plataformas[p.platform] = plataformas.get(p.platform, 0) + 1
    plataforma_fav = max(plataformas, key=plataformas.get) if plataformas else "N/A"

    efectivas = [p for p in vistas if p.rating is not None and not p.abandoned]
    stats = {'total': len(efectivas), 'promedio': promedio, 'plataforma': plataforma_fav}

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

    promedio = round(sum(p.rating for p in calificadas) / len(calificadas)) if calificadas else 0

    rangos = {'0-34': 0, '35-54': 0, '55-74': 0, '75-89': 0, '90-99': 0, '100': 0}
    for p in calificadas:
        r = p.rating
        if r == 100: rangos['100'] += 1
        elif r >= 90: rangos['90-99'] += 1
        elif r >= 75: rangos['75-89'] += 1
        elif r >= 55: rangos['55-74'] += 1
        elif r >= 35: rangos['35-54'] += 1
        else: rangos['0-34'] += 1

    from collections import defaultdict
    por_mes = defaultdict(int)
    for p in vistas:
        if p.date_watched and len(p.date_watched) >= 7:
            mes_key = p.date_watched[:7]
            por_mes[mes_key] += 1
    meses_sorted = sorted(por_mes.items())

    plataformas = defaultdict(int)
    for p in vistas:
        if p.platform:
            plataformas[p.platform] += 1
    top_plataformas = sorted(plataformas.items(), key=lambda x: x[1], reverse=True)[:6]

    combos_count = defaultdict(int)
    for p in vistas:
        if not p.genres:
            continue
        gs = [g.strip() for g in p.genres.split(',') if g.strip()]
        combo = " / ".join(sorted(gs[:2])) if len(gs) >= 2 else gs[0]
        combos_count[combo] += 1
    top_generos = sorted(combos_count.items(), key=lambda x: x[1], reverse=True)[:6]

    directores_count = defaultdict(int)
    for p in calificadas:
        if p.director and p.director != 'Desconocido':
            directores_count[p.director] += 1
    top_directores = sorted(directores_count.items(), key=lambda x: x[1], reverse=True)[:5]

    mejor = max(calificadas, key=lambda x: x.rating) if calificadas else None
    peor = min(calificadas, key=lambda x: x.rating) if calificadas else None

    con_fecha = [p for p in vistas if p.date_watched]
    con_fecha_sorted = sorted(con_fecha, key=lambda x: x.date_watched)
    primera = con_fecha_sorted[0] if con_fecha_sorted else None
    ultima = con_fecha_sorted[-1] if con_fecha_sorted else None

    total_minutos = sum(p.runtime for p in calificadas if p.runtime)

    top_perfil, kw_evita = oracle_helper.build_taste_profile(calificadas)

    stats_data = {
        'total_vistas': len(calificadas),
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

    existe = Movie.query.filter_by(tmdb_id=tmdb_id, user_id=session['user_id']).first()

    if not existe:
        details = get_movie_details(tmdb_id)
        director = 'Desconocido'
        actores = ''
        generos = ''
        imdb_score = None
        runtime = None
        keywords_str = None

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

    pelicula = Movie.query.filter_by(id=id, user_id=session['user_id']).first_or_404()
    db.session.delete(pelicula)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/dashboard/edit/<int:id>', methods=['GET', 'POST'])
def edit_movie(id):
    if not session.get('user_id'):
        return redirect(url_for('login'))

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

    blacklist = OracleBlacklist.query.filter_by(user_id=session['user_id']).all()
    shown = OracleShown.query.filter_by(user_id=session['user_id']).all()

    calificadas = [p for p in mis_pelis if p.rating is not None and not p.is_watchlist and not p.abandoned]
    top_perfil, kw_evita = oracle_helper.build_taste_profile(calificadas)

    historial_str = oracle_helper.build_historial(mis_pelis, blacklist, shown)
    perfil_str = oracle_helper._perfil_str(top_perfil, kw_evita)

    excluir_str = ""
    if ya_mostradas:
        excluir_str = f"\n\nPelículas que YA recomendé en ESTA misma consulta (NO repetir ninguna, ni siquiera el bonus): {', '.join(ya_mostradas)}."

    prompt = oracle_helper.build_json_prompt(historial_str, perfil_str, excluir_str, cantidad)

    try:
        groq_key = os.getenv('GROQ_API_KEY')
        resp = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {groq_key}', 'Content-Type': 'application/json'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.9,
                'top_p': 0.9,
                'response_format': {'type': 'json_object'}
            },
            timeout=30
        )
        if resp.status_code == 429:
            return jsonify({'error': "El Oráculo está saturado (límite de la IA gratuita). Esperá unos segundos y volvé a intentar."})
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

        existing_tmdb_ids = {str(p.tmdb_id) for p in mis_pelis if p.tmdb_id}
        blacklist_ids = {str(b.tmdb_id) for b in blacklist if b.tmdb_id}
        shown_ids = {str(s.tmdb_id) for s in shown if s.tmdb_id}
        excluir_ids = existing_tmdb_ids | blacklist_ids | shown_ids | ya_mostradas_ids

        resultados_finales = []

        for rec in todos:
            peli = oracle_helper.buscar_en_tmdb(rec['titulo'], rec['anio'])

            poster_fallback = '/static/mbvault-512.png'
            es_bonus = rec.get('bonus', False)

            if peli:
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

        regulares = [r for r in resultados_finales if not r['bonus']][:cantidad]
        bonus = [r for r in resultados_finales if r['bonus']][:1]
        finales = regulares + bonus

        if not regulares:
            return jsonify({'error': "El Oráculo no encontró nada nuevo esta vez (probablemente repitió algo que ya viste o descartaste). Probá de nuevo."})

        ya_guardados = {s.tmdb_id for s in shown}
        for r in finales:
            if r['tmdb_id'] and r['tmdb_id'] not in ya_guardados:
                db.session.add(OracleShown(user_id=session['user_id'], tmdb_id=r['tmdb_id'], title=r['titulo']))
                ya_guardados.add(r['tmdb_id'])
        db.session.commit()

        return jsonify({'success': True, 'peliculas': finales})

    except Exception as e:
        app.logger.error('Oracle failure: %s', type(e).__name__)
        return jsonify({'error': 'No se pudieron obtener recomendaciones. Intentá nuevamente.'}), 502

@app.route('/dashboard/oracle/prompt')
def oracle_prompt():
    if not session.get('user_id'):
        return jsonify({'error': 'Sesión expirada'})
    mis_pelis = Movie.query.filter_by(user_id=session['user_id']).all()
    blacklist = OracleBlacklist.query.filter_by(user_id=session['user_id']).all()
    shown = OracleShown.query.filter_by(user_id=session['user_id']).all()

    calificadas = [p for p in mis_pelis if p.rating is not None and not p.is_watchlist and not p.abandoned]
    top_perfil, kw_evita = oracle_helper.build_taste_profile(calificadas)

    historial_str = oracle_helper.build_historial(mis_pelis, blacklist, shown)
    perfil_str = oracle_helper._perfil_str(top_perfil, kw_evita)

    prompt = oracle_helper.build_manual_prompt(historial_str, perfil_str)
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

    existe = Movie.query.filter_by(user_id=session['user_id'], tmdb_id=tmdb_id).first()
    if existe:
        return jsonify({'success': False, 'error': 'Ya está en tu colección'})

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
        db.session.rollback()
        app.logger.error('Watchlist failure: %s', type(e).__name__)
        return jsonify({'success': False, 'error': 'No se pudo guardar la película.'}), 500

app.extensions['apply_security_limits']()

if __name__ == '__main__':
    app.run()
