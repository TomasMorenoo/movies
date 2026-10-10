import os
from datetime import date, timedelta

from flask import abort, jsonify, request, session
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def configure_security(app):
    app.config.update(
        MAX_CONTENT_LENGTH=64 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'true').lower() == 'true',
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    )
    CSRFProtect(app)
    limiter = Limiter(
        get_remote_address, app=app, default_limits=['300 per minute'],
        storage_uri=os.getenv('RATELIMIT_STORAGE_URI', 'memory://'),
    )

    @app.before_request
    def validate_input():
        if request.method != 'POST':
            return
        data = request.get_json() if request.is_json else request.form
        if not hasattr(data, 'get'):
            abort(400)
        limits = {'username': 50, 'password': 256, 'title': 200, 'titulo': 200,
                  'poster_path': 200, 'poster': 500, 'platform': 50,
                  'opinion': 10000, 'query': 200, 'imdb_score': 10, 'date_watched': 10}
        for key, length in limits.items():
            value = data.get(key)
            if value is not None and (not isinstance(value, str) or len(value) > length or '\x00' in value):
                abort(400)
        if request.endpoint in ('login', 'register'):
            if not data.get('username', '').strip() or not data.get('password'):
                abort(400)
            if request.endpoint == 'register' and len(data['password']) < 12:
                abort(400, description='La contraseña debe tener al menos 12 caracteres.')
        if request.endpoint in ('save_movie', 'oracle_discard', 'oracle_add_watchlist'):
            try:
                if not 0 < int(data.get('tmdb_id', 0)) <= 2147483647:
                    abort(400)
            except (TypeError, ValueError):
                abort(400)
            if not (data.get('title') or data.get('titulo') or '').strip():
                abort(400)
            if request.endpoint == 'oracle_add_watchlist' and not isinstance(data.get('poster'), str):
                abort(400)
        if data.get('rating') not in (None, ''):
            try:
                if not 0 <= int(data['rating']) <= 100:
                    abort(400)
            except (ValueError, TypeError):
                abort(400)
        if data.get('date_watched'):
            try:
                date.fromisoformat(data['date_watched'])
            except ValueError:
                abort(400)
        if request.endpoint == 'oracle':
            try:
                if not 1 <= int(data.get('cantidad', 3)) <= 5:
                    abort(400)
            except (ValueError, TypeError):
                abort(400)
            for key in ('ya_mostradas', 'ya_mostradas_ids'):
                values = data.get(key, [])
                if not isinstance(values, list) or len(values) > 100 or any(not isinstance(v, (str, int)) or len(str(v)) > 200 for v in values):
                    abort(400)

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy'] = "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        if not request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(500)
    def server_error(error):
        return jsonify(error='Error interno. Intentá nuevamente.'), 500

    def apply_limits():
        for endpoint in ('login', 'register'):
            app.view_functions[endpoint] = limiter.limit('10 per minute', methods=['POST'])(app.view_functions[endpoint])
        app.view_functions['oracle'] = limiter.limit(
            '5 per minute', methods=['POST'],
            key_func=lambda: str(session.get('user_id') or get_remote_address()),
        )(app.view_functions['oracle'])
    app.extensions['apply_security_limits'] = apply_limits
