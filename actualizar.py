from app import app
from models import db, Movie
from sqlalchemy import text
from tmdb_helper import get_movie_details, get_imdb_rating
import time

with app.app_context():
    print("Iniciando protocolo de actualización de base de datos...")
    
    # 1. Intentar agregar la columna (si no existe)
    try:
        db.session.execute(text("ALTER TABLE movie ADD COLUMN imdb_score VARCHAR(10)"))
        db.session.commit()
        print("✅ Columna 'imdb_score' agregada a la base de datos.")
    except Exception as e:
        db.session.rollback()
        print("ℹ️ La columna 'imdb_score' ya existía o tu motor de base de datos requiere otro formato (ignorando este paso).")

    # 2. Buscar todas las películas
    peliculas = Movie.query.all()
    actualizadas = 0

    print(f"\n🔍 Escaneando {len(peliculas)} películas en tu bóveda...\n")

    for peli in peliculas:
        # Solo buscamos si la película todavía no tiene puntaje
        if not peli.imdb_score:
            print(f"🎬 Buscando IMDb para: {peli.title}...")
            
            # Paso A: Ir a TMDB para conseguir el código 'tt...' de IMDb
            details = get_movie_details(peli.tmdb_id)
            if details and details.get('imdb_id'):
                imdb_id = details['imdb_id']
                
                # Paso B: Ir a OMDb con ese código para traer el puntaje
                score = get_imdb_rating(imdb_id)
                if score:
                    peli.imdb_score = score
                    actualizadas += 1
                    print(f"   ⭐ Puntaje encontrado: {score}")
                else:
                    print("   ❌ No se encontró puntaje en OMDb.")
            else:
                print("   ❌ No se encontró ID de IMDb en TMDB.")
            
            # Una pausa de medio segundo para no saturar las APIs gratuitas y que no nos bloqueen
            time.sleep(0.5)
        else:
            print(f"⏭️  Saltando '{peli.title}' (Ya tiene puntaje: {peli.imdb_score})")

    # 3. Guardar todos los cambios
    db.session.commit()
    print(f"\n🎉 ¡Proceso terminado! Se actualizaron {actualizadas} películas.")