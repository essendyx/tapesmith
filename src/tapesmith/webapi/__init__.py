"""Lokale HTTP-API (FastAPI) des Druckdienstes p12d für die Web-Oberfläche.

Qt-frei. Läuft im Dienstprozess in einem eigenen Thread (`webapi.server.WebServer`), bindet nur
127.0.0.1 und schützt sich über Host-, Origin- und Token-Prüfung (`webapi.security`).
"""
