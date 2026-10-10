import os
import re
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

os.environ['SECRET_KEY'] = 'test-only-key-' + 'a' * 40
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['COOKIE_SECURE'] = 'false'

from app import app
from models import db, Movie


class SecurityTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        for limiter in app.extensions['limiter']:
            limiter.reset()
        with app.app_context():
            db.drop_all()
            db.create_all()
        self.client = app.test_client()

    def token(self, path='/'):
        page = self.client.get(path)
        return re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]

    def register(self):
        return self.client.post('/register', data={'csrf_token': self.token('/register'),
                                'username': 'tester', 'password': 'long-password-123'})

    def test_csrf_and_validation(self):
        self.assertEqual(self.client.post('/').status_code, 400)
        self.assertEqual(self.client.post('/', data={'csrf_token': self.token()}).status_code, 400)
        self.assertEqual(self.register().status_code, 302)
        token = self.token('/dashboard/form')
        self.assertEqual(self.client.post('/dashboard/save', data={'csrf_token': token, 'tmdb_id': '1', 'title': 'Movie', 'rating': '101'}).status_code, 400)
        self.assertEqual(self.client.post('/dashboard/oracle', json=[], headers={'X-CSRFToken': token}).status_code, 400)

    def test_crud_and_ownership(self):
        self.register()
        token = self.token('/dashboard/form')
        with patch('app.get_movie_details', return_value=None):
            self.assertEqual(self.client.post('/dashboard/save', data={'csrf_token': token, 'tmdb_id': '1', 'title': 'Movie', 'rating': '80'}).status_code, 302)
        with app.app_context():
            movie_id = Movie.query.first().id
        self.assertEqual(self.client.get(f'/dashboard/edit/{movie_id}').status_code, 200)
        self.assertEqual(self.client.post(f'/dashboard/edit/{movie_id}', data={'csrf_token': token, 'rating': '90'}).status_code, 302)
        for path in ('/dashboard/index', '/dashboard/stats', '/dashboard/top10', '/dashboard/oracle', '/dashboard/export'):
            self.assertEqual(self.client.get(path).status_code, 200)
        with self.client.session_transaction() as sess:
            sess['user_id'] = 999
        self.assertEqual(self.client.post(f'/dashboard/delete/{movie_id}', data={'csrf_token': token}).status_code, 404)
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
        self.assertEqual(self.client.post(f'/dashboard/delete/{movie_id}', data={'csrf_token': token}).status_code, 302)
        self.assertEqual(self.client.get('/logout').status_code, 405)
        self.assertEqual(self.client.post('/logout', data={'csrf_token': token}).status_code, 302)
        self.assertEqual(self.client.post('/', data={'csrf_token': self.token(), 'username': 'tester', 'password': 'long-password-123'}).status_code, 302)

    def test_rate_limit_and_headers(self):
        token = self.token()
        codes = [self.client.post('/', data={'csrf_token': token, 'username': 'nobody', 'password': 'wrong'}).status_code for _ in range(11)]
        self.assertEqual(codes[-1], 429)
        self.assertEqual(self.client.get('/').headers['Cache-Control'], 'no-store')

    def test_oracle_escapes_untrusted_content(self):
        source = Path('templates/oracle.html').read_text(encoding='utf-8')
        functions = source[source.index('    function escapeHtml'):source.index('    function getPageWidth')]
        script = "const document = {getElementById: () => ({addEventListener: () => {}})};\n" + functions
        script += "\nconst html = buildCardHtml({titulo: '<img src=x onerror=alert(1)>', poster: '\" onload=alert(1)', justificacion: '<script>alert(1)</script>', tmdb_id: 1}); if(html.includes('<script>') || html.includes('<img src=x') || html.includes('onclick=')) throw Error('Unsafe HTML');"
        subprocess.run(['node', '-e', script], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
