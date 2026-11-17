FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
USER nobody
EXPOSE 8000
# Una sola imagen para las dos piezas: la API usa este CMD y el worker lo cambia en compose.yaml.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
