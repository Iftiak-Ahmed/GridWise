FROM python:3.11-slim

# CBC solver binary used by PuLP for the LP optimizer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends coinor-cbc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# No secrets are baked into the image; GROQ_API_KEY is injected at `docker run` time.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
