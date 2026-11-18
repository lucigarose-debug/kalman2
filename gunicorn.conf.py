"""Configuración de Gunicorn para Render.

Render inyecta la variable PORT (por defecto 10000) y exige escuchar en 0.0.0.0.
"""
import multiprocessing
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"

# El plan gratuito tiene 512 MB y CPU compartida: 2 workers es un buen equilibrio.
workers = int(os.environ.get("WEB_CONCURRENCY", min(2, multiprocessing.cpu_count() * 2 + 1)))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
worker_class = "gthread"

# Rutas largas (cientos de miles de puntos) pueden tardar unos segundos.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
graceful_timeout = 30
keepalive = 5

# Recicla workers periódicamente para evitar crecimiento de memoria.
max_requests = 500
max_requests_jitter = 50

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
forwarded_allow_ips = "*"  # Render termina TLS en su proxy
