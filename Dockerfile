FROM python:3.12-slim

# AVEC_CAO=1 installe la bibliothèque qui produit les fichiers STEP des pièces.
# Si cette installation échoue sur votre machine : docker build --build-arg AVEC_CAO=0 .
# La plateforme fonctionne alors sans les fichiers CAO.
ARG AVEC_CAO=1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    YAME_DONNEES=/donnees \
    YAME_EXIGER_MOT_DE_PASSE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /application
COPY pyproject.toml README.md ./
COPY plateforme ./plateforme
RUN pip install --no-cache-dir . \
    && if [ "$AVEC_CAO" = "1" ]; then pip install --no-cache-dir "cadquery>=2.4"; fi

RUN useradd --create-home --uid 10001 yame \
    && mkdir -p /donnees \
    && chown yame:yame /donnees
USER yame
VOLUME /donnees
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/sante', timeout=4)"

CMD ["uvicorn", "plateforme.web.app:creer_application", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
