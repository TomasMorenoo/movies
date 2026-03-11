from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, Response
from models import db, Movie, User
from tmdb_helper import search_movie, get_movie_details
import os
import csv
from io import StringIO
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = 'super_secreto_para_cookies'
# Lee la URL de la base de datos desde tu archivo .env (PostgreSQL)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Crea las tablas (User y Movie) automáticamente si no existen
with app.app_context():
    db.create_all()

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
        writer.writerow(['ID', 'Titulo', 'Estado', 'Fecha Vista', 'Plataforma', 'Puntaje', 'Opinion', 'Director', 'Generos'])
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)
        
        for p in peliculas:
            estado = 'Watchlist' if p.is_watchlist else ('Abandonada' if p.abandoned else 'Colección')
            writer.writerow([
                p.tmdb_id, p.title, estado, p.date_watched or 'N/A', 
                p.platform or 'N/A', p.rating or 'N/A', 
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
        crew = details.get('credits', {}).get('crew', []) if details else []
        director = next((c['name'] for c in crew if c['job'] == 'Director'), 'Desconocido')
        cast = details.get('credits', {}).get('cast', []) if details else []
        actores = ", ".join([a['name'] for a in cast[:3]])
        generos_list = details.get('genres', []) if details else []
        generos = ", ".join([g['name'] for g in generos_list])

        nueva_peli = Movie(
            user_id=session['user_id'], # Asocia la peli al usuario creador
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
        
        db.session.commit()
        return redirect(url_for('index'))
        
    return render_template('edit.html', peli=pelicula)

if __name__ == '__main__':
    app.run(debug=True)