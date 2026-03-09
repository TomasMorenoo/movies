from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, Response
from models import db, Movie
from tmdb_helper import search_movie, get_movie_details
import os
import csv
from io import StringIO
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = 'super_secreto_para_cookies'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///movies.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
PIN_SECRETO = os.getenv('APP_PIN', '0000')

with app.app_context():
    db.create_all()

# --- RUTAS PWA ---
@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def sw():
    return send_from_directory('static', 'sw.js')

# --- AUTENTICACIÓN ---
@app.route('/', methods=['GET', 'POST'])
def login():
    if session.get('autorizado'):
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        if request.form.get('pin') == PIN_SECRETO:
            session['autorizado'] = True
            session.permanent = True
            return redirect(url_for('index'))
        else:
            return "PIN Incorrecto", 401
            
    return '''
        <div style="display:flex; justify-content:center; align-items:center; height:100vh; font-family:sans-serif; background-color:#121212; color:white;">
            <form method="post" style="text-align:center;">
                <h2>Mobatai<span>Vault</span></h2>
                <input type="password" name="pin" placeholder="Ingresa tu PIN" style="padding:10px; font-size:16px; margin-top:10px; border-radius: 5px; border: none;">
                <button type="submit" style="padding:10px 20px; font-size:16px; background-color: #00E5FF; color: black; border: none; border-radius: 5px; font-weight: bold; cursor: pointer;">Entrar</button>
            </form>
        </div>
    '''

@app.route('/logout')
def logout():
    session.pop('autorizado', None)
    return redirect(url_for('login'))

# --- BACKUP ---
@app.route('/dashboard/export')
def export_csv():
    if not session.get('autorizado'):
        return redirect(url_for('login'))
        
    peliculas = Movie.query.all()
    
    def generate():
        data = StringIO()
        writer = csv.writer(data)
        writer.writerow(['ID', 'Titulo', 'Estado', 'Fecha Vista', 'Plataforma', 'Puntaje', 'Opinion', 'Director', 'Generos'])
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)
        
        for p in peliculas:
            # Determinamos el estado real para el Excel
            estado = 'Watchlist' if p.is_watchlist else ('Abandonada' if p.abandoned else 'Colección')
            writer.writerow([
                p.tmdb_id, p.title, estado, p.date_watched or 'N/A', 
                p.platform or 'N/A', p.rating or 'N/A', 
                p.opinion or '', p.director, p.genres
            ])
            yield data.getvalue()
            data.seek(0)
            data.truncate(0)
            
    return Response(generate(), mimetype='text/csv', headers={"Content-Disposition": "attachment; filename=mobatai_vault_backup.csv"})

# --- RUTAS PRINCIPALES ---
@app.route('/dashboard/index')
def index():
    if not session.get('autorizado'):
        return redirect(url_for('login'))
        
    todas_las_pelis = Movie.query.all()
    
    # Separar Colección de Watchlist
    vistas = [p for p in todas_las_pelis if not p.is_watchlist]
    pendientes = [p for p in todas_las_pelis if p.is_watchlist]
    
    vistas.sort(key=lambda x: x.date_watched or '0000-00-00', reverse=True)
    pendientes.sort(key=lambda x: x.id, reverse=True)
    
    # El promedio ignora los nulos y las abandonadas
    ratings = [p.rating for p in vistas if p.rating is not None and not p.abandoned]
    promedio = round(sum(ratings) / len(ratings)) if ratings else 0
    
    plataformas = {}
    for p in vistas:
        if p.platform:
            plataformas[p.platform] = plataformas.get(p.platform, 0) + 1
    plataforma_fav = max(plataformas, key=plataformas.get) if plataformas else "N/A"
    
    stats = {'total': len(vistas), 'promedio': promedio, 'plataforma': plataforma_fav}
    
    return render_template('index.html', peliculas=vistas, pendientes=pendientes, stats=stats)

@app.route('/dashboard/form', methods=['GET', 'POST'])
def form():
    if not session.get('autorizado'):
        return redirect(url_for('login'))
        
    resultados = []
    if request.method == 'POST':
        query = request.form.get('query')
        resultados = search_movie(query)
        
    return render_template('form.html', resultados=resultados)

@app.route('/dashboard/save', methods=['POST'])
def save_movie():
    if not session.get('autorizado'):
        return redirect(url_for('login'))
        
    tmdb_id = request.form.get('tmdb_id')
    title = request.form.get('title')
    poster_path = request.form.get('poster_path')
    
    # Detectamos a dónde va y si la abandonó
    is_watchlist = request.form.get('action') == 'watchlist'
    abandoned = request.form.get('abandoned') == 'on'
    
    rating_str = request.form.get('rating')
    rating = int(rating_str) if rating_str and rating_str.strip() != "" else None
    date_str = request.form.get('date_watched')
    date_watched = date_str if date_str and date_str.strip() != "" else None
    platform = request.form.get('platform')
    opinion = request.form.get('opinion')
    
    existe = Movie.query.filter_by(tmdb_id=tmdb_id).first()
    
    if not existe:
        details = get_movie_details(tmdb_id)
        crew = details.get('credits', {}).get('crew', []) if details else []
        director = next((c['name'] for c in crew if c['job'] == 'Director'), 'Desconocido')
        cast = details.get('credits', {}).get('cast', []) if details else []
        actores = ", ".join([a['name'] for a in cast[:3]])
        generos_list = details.get('genres', []) if details else []
        generos = ", ".join([g['name'] for g in generos_list])

        nueva_peli = Movie(
            tmdb_id=tmdb_id, title=title, poster_path=poster_path,
            rating=rating, platform=platform, opinion=opinion, date_watched=date_watched,
            director=director, genres=generos, cast=actores,
            is_watchlist=is_watchlist,
            abandoned=abandoned
        )
        db.session.add(nueva_peli)
        db.session.commit()
        
    return redirect(url_for('index'))

@app.route('/dashboard/delete/<int:id>', methods=['POST'])
def delete_movie(id):
    if not session.get('autorizado'):
        return redirect(url_for('login'))
        
    pelicula = Movie.query.get_or_404(id)
    db.session.delete(pelicula)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/dashboard/edit/<int:id>', methods=['GET', 'POST'])
def edit_movie(id):
    if not session.get('autorizado'):
        return redirect(url_for('login'))
        
    pelicula = Movie.query.get_or_404(id)
    
    if request.method == 'POST':
        date_str = request.form.get('date_watched')
        pelicula.date_watched = date_str if date_str and date_str.strip() != "" else None
        
        pelicula.platform = request.form.get('platform')
        
        rating_str = request.form.get('rating')
        pelicula.rating = int(rating_str) if rating_str and rating_str.strip() != "" else None
        
        pelicula.opinion = request.form.get('opinion')
        
        # Actualizamos estado de watchlist y abandonada
        pelicula.abandoned = request.form.get('abandoned') == 'on'
        pelicula.is_watchlist = False 
        
        db.session.commit()
        return redirect(url_for('index'))
        
    return render_template('edit.html', peli=pelicula)

if __name__ == '__main__':
    app.run(debug=True)