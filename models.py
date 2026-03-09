from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tmdb_id = db.Column(db.Integer, unique=True, nullable=False)
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

    def __repr__(self):
        return f'<Movie {self.title}>'