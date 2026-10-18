"""The data drop (#190): squares uploaded to the server by the mappers whose
ground they are. ``app`` is the HTTP API, ``store`` the two copies of the
squares it changes, ``sources`` who a token is and whose ground a square is.
Run by gunicorn from danu-server's ``danu-drop.service``."""
