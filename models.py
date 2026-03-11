from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    
    # Relación: Un usuario tiene muchas películas
    movies = db.relationship('Movie', backref='owner', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    
    # ID del usuario dueño de esta película
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    tmdb_id = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    poster_path = db.Column(db.String(200))
    
    is_watchlist = db.Column(db.Boolean, default=False)
    abandoned = db.Column(db.Boolean, default=False)
    
    rating = db.Column(db.Integer, nullable=True) 
    platform = db.Column(db.String(50), nullable=True)
    opinion = db.Column(db.Text, nullable=True)
    date_watched = db.Column(db.String(20), nullable=True) 
    
    director = db.Column(db.String(100), nullable=True)
    genres = db.Column(db.String(200), nullable=True)
    cast = db.Column(db.String(300), nullable=True)
    
    # NUEVO: Puntaje de IMDb
    imdb_score = db.Column(db.String(10), nullable=True)

    def __repr__(self):
        return f'<Movie {self.title}>'