import os
import requests
from dotenv import load_dotenv

load_dotenv()
TMDB_API_KEY = os.getenv('TMDB_API_KEY')
OMDB_API_KEY = os.getenv('OMDB_API_KEY')
BASE_URL = 'https://api.themoviedb.org/3'

def search_movie(query):
    url = f"{BASE_URL}/search/movie"
    params = {
        'api_key': TMDB_API_KEY,
        'query': query,
        'language': 'es-ES'
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json().get('results', [])
    return []

def get_movie_details(tmdb_id):
    url = f"{BASE_URL}/movie/{tmdb_id}"
    params = {
        'api_key': TMDB_API_KEY,
        'language': 'es-ES',
        'append_to_response': 'credits'
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json()
    return None

def get_imdb_rating(imdb_id):
    """Va a OMDb API a buscar el puntaje usando el tt1234567 de IMDb"""
    if not imdb_id or not OMDB_API_KEY:
        return None
    url = f"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&i={imdb_id}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            rating = data.get('imdbRating')
            if rating and rating != 'N/A':
                return rating
    except:
        pass
    return None