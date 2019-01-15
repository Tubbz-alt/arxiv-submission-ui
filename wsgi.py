"""Web Server Gateway Interface entry-point."""

from submit.factory import create_ui_web_app
import os


def application(environ, start_response):
    """WSGI application factory."""
    for key, value in environ.items():
        os.environ[key] = str(value)
    app = create_ui_web_app()
    return app(environ, start_response)
