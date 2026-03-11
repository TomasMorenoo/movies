import csv
from app import app, db
from models import Movie

with app.app_context():
    # Abrimos el CSV que preparaste con el user_id
    with open('movie.csv', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 1. Convertir los "0" y "1" viejos a booleanos reales de Python
            is_watchlist = str(row.get('is_watchlist', '0')).lower() in ['1', 'true']
            abandoned = str(row.get('abandoned', '0')).lower() in ['1', 'true']

            # 2. Reemplazar celdas vacías por None
            for k in row.keys():
                if row[k] == '':
                    row[k] = None

            # 3. Armar la película con todos los datos
            pelicula = Movie(
                id=int(row['id']),
                user_id=int(row.get('user_id', 1)),
                tmdb_id=int(row['tmdb_id']),
                title=row['title'],
                poster_path=row.get('poster_path'),
                is_watchlist=is_watchlist,
                abandoned=abandoned,
                rating=int(row['rating']) if row.get('rating') else None,
                platform=row.get('platform'),
                opinion=row.get('opinion'),
                date_watched=row.get('date_watched'),
                director=row.get('director'),
                genres=row.get('genres'),
                cast=row.get('cast')
            )
            # Usamos merge para que inserte forzando el ID histórico
            db.session.merge(pelicula) 
        
        # Guardamos los cambios en el archivo SQLite
        db.session.commit()
        
        print("¡Inyección exitosa! Tu SQLite local ya tiene todas tus películas.")