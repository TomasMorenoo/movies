from app import app
from models import db, Movie
from sqlalchemy import text
from tmdb_helper import get_movie_details, get_imdb_rating
import time

with app.app_context():
    print("Iniciando protocolo de actualización de base de datos...")

    for col_sql, col_name in [
        ("ALTER TABLE movie ADD COLUMN imdb_score VARCHAR(10)", "imdb_score"),
        ("ALTER TABLE movie ADD COLUMN runtime INTEGER", "runtime"),
    ]:
        try:
            db.session.execute(text(col_sql))
            db.session.commit()
            print(f"✅ Columna '{col_name}' agregada.")
        except Exception:
            db.session.rollback()
            print(f"ℹ️ Columna '{col_name}' ya existía (ignorando).")

    peliculas = Movie.query.all()
    actualizadas = 0
    print(f"\n🔍 Escaneando {len(peliculas)} películas...\n")

    for peli in peliculas:
        if peli.imdb_score and peli.runtime:
            print(f"⏭️  Saltando '{peli.title}'")
            continue

        print(f"🎬 Actualizando: {peli.title}...")
        details = get_movie_details(peli.tmdb_id)

        if details:
            if not peli.runtime:
                rt = details.get('runtime')
                if rt:
                    peli.runtime = rt
                    print(f"   🕐 Runtime: {rt} min")

            if not peli.imdb_score and details.get('imdb_id'):
                score = get_imdb_rating(details['imdb_id'])
                if score:
                    peli.imdb_score = score
                    actualizadas += 1
                    print(f"   ⭐ IMDb: {score}")

        time.sleep(0.5)

    db.session.commit()
    print(f"\n🎉 ¡Listo! Se actualizaron {actualizadas} películas.")
