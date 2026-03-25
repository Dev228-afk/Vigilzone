FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Collect static files (including Django admin CSS/JS)
RUN python manage.py collectstatic --noinput

# Run migrations on startup, then start ASGI server (Daphne for WebSocket support)
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && daphne -b 0.0.0.0 -p 8000 server.asgi:application"]
