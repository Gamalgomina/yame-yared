# Image complète : la plateforme et tous les logiciels de calcul embarqués.
#
# Elle reprend la distribution sur laquelle ces logiciels ont été installés et
# essayés (Ubuntu 24.04). L'image elle-même n'a pas pu être construite dans
# l'environnement de développement : la première construction est un essai.
#
# Pour une image plus légère et plus rapide à construire :
#   docker build --build-arg LOGICIELS_LOURDS=0 --build-arg SIMULATEUR=0 .
# La plateforme signale alors ces logiciels comme « non installés » et
# fonctionne sans eux.

# ---------------------------------------------------------------------------
# Étape 1 : compiler le simulateur ArduPilot (ArduPlane, cible SITL)
# ---------------------------------------------------------------------------
FROM ubuntu:24.04 AS simulateur
ARG SIMULATEUR=1
ARG ARDUPILOT_VERSION=master
ENV DEBIAN_FRONTEND=noninteractive
RUN mkdir -p /sitl/defauts
RUN if [ "$SIMULATEUR" = "1" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends git ca-certificates build-essential python3 python3-pip python3-dev \
        && pip install --break-system-packages --no-cache-dir empy==3.3.4 pexpect future pymavlink \
        && git clone --depth 1 --branch "$ARDUPILOT_VERSION" https://github.com/ArduPilot/ardupilot.git /ardupilot \
        && cd /ardupilot \
        && git submodule update --init --recursive --depth 1 \
        && ./waf configure --board sitl \
        && ./waf plane \
        && cp build/sitl/bin/arduplane /sitl/arduplane \
        && cp Tools/autotest/default_params/plane.parm Tools/autotest/default_params/quadplane.parm /sitl/defauts/ ; \
    fi

# ---------------------------------------------------------------------------
# Étape 2 : la plateforme
# ---------------------------------------------------------------------------
FROM ubuntu:24.04
ARG LOGICIELS_LOURDS=1
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    YAME_DONNEES=/donnees \
    YAME_EXIGER_MOT_DE_PASSE=1 \
    YAME_SITL=/opt/sitl/arduplane \
    YAME_SITL_DEFAUTS=/opt/sitl/defauts \
    WM_PROJECT_DIR=/usr/share/openfoam

# Python, CalculiX (structure), GetDP (électromagnétisme) et les bibliothèques
# graphiques dont CadQuery et gmsh ont besoin.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-venv ca-certificates \
        calculix-ccx getdp \
        libgl1 libglu1-mesa libglib2.0-0 libxrender1 libxext6 libxcursor1 libxinerama1 libxft2 libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# OpenFOAM (mécanique des fluides) et KiCad (cartes électroniques) : plusieurs Go.
RUN if [ "$LOGICIELS_LOURDS" = "1" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends openfoam kicad \
        && rm -rf /var/lib/apt/lists/* ; \
    fi

RUN python3 -m venv /opt/venv
WORKDIR /application
COPY pyproject.toml README.md ./
COPY plateforme ./plateforme
RUN pip install --no-cache-dir ".[cao,calcul]"

COPY --from=simulateur /sitl /opt/sitl

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
