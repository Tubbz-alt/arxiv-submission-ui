"""Helpers for working with Flask globals."""

import os
from typing import Union
from flask import g, Flask
from flask import current_app as flask_app
import werkzeug


def get_application_config(app: Flask=None) -> Union[dict, os._Environ]:
    """
    Get a configuration from the current app, or fall back to env.

    Parameters
    ----------
    app : :class:`flask.Flask`

    Returns
    -------
    dict-like
        This is either the current Flask application configuration, or
        ``os.environ``. Either of these should support the ``get()`` method.
    """
    if app is not None:
        if isinstance(app, Flask):
            return app.config
    if flask_app:    # Proxy object; falsey if there is no application context.
        return flask_app.config
    return os.environ


def get_application_global() -> werkzeug.local.LocalProxy:
    """
    Get the current application global proxy object.

    Returns
    -------
    proxy or None
    """
    if g:
        return g
    return None
