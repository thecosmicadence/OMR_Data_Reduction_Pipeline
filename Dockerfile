# ──────────────────────────────────────────────────────────────────────────────
# Dockerfile — VBO OMR Spectroscopic Pipeline
#
# Base: Ubuntu 22.04 LTS (x86_64)
# Python: 3.11 stable (via deadsnakes PPA — added manually without gpg-agent)
# IRAF: installed via apt (iraf package, v2.17)
# DS9:  installed via apt (saods9) — required for pyds9
# GUI:  Tkinter + PyQt5, forwarded via X11
#
# BUILD:
#   docker build -t omr-pipeline .
#
# RUN (Linux host):
#   xhost +local:docker
#   docker run --rm -it \
#     -e DISPLAY=$DISPLAY \
#     -v /tmp/.X11-unix:/tmp/.X11-unix \
#     -v /path/to/your/data:/data \
#     --network host \
#     omr-pipeline
# ──────────────────────────────────────────────────────────────────────────────

FROM ubuntu:22.04

# Prevent interactive prompts during apt installs
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# ── 1. Base tools + deadsnakes PPA (added manually — add-apt-repository ───────
#    fails in containers because it needs gpg-agent / D-Bus)
#    We also enable the multiverse repo which contains iraf-noao.
RUN sed -i 's/ main$/ main multiverse/' /etc/apt/sources.list \
    && sed -i 's/ universe$/ universe multiverse/' /etc/apt/sources.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    gnupg \
    curl \
    wget \
    git \
    ca-certificates \
    && mkdir -p /usr/share/keyrings \
    && curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xF23C5A6CF475977595C89F51BA6932366A755776" \
       | gpg --batch --yes --dearmor -o /usr/share/keyrings/deadsnakes.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/deadsnakes.gpg] https://ppa.launchpadcontent.net/deadsnakes/ppa/ubuntu jammy main" \
       > /etc/apt/sources.list.d/deadsnakes.list \
    && apt-get update

# ── 2. System packages ────────────────────────────────────────────────────────
RUN apt-get install -y --no-install-recommends \
    # IRAF (v2.17 from Ubuntu repos) and NOAO (from multiverse)
    iraf \
    iraf-noao \
    # SAOImage DS9 + XPA tools (required for pyds9)
    saods9 \
    xpa-tools \
    # Stable Python 3.11 from deadsnakes PPA
    python3.11 \
    python3.11-dev \
    python3.11-tk \
    # X11 / display libraries (for Tkinter + DS9 GUI over X11 forwarding)
    libx11-6 \
    libx11-dev \
    libxt-dev \
    libxext-dev \
    libxrender1 \
    libxtst6 \
    libxi6 \
    libxext6 \
    libxcb1 \
    libxcb-util1 \
    # Qt5 dependencies (for PyQt5)
    libqt5widgets5 \
    libqt5gui5 \
    libqt5core5a \
    libqt5x11extras5 \
    libgl1-mesa-glx \
    # Build tools (needed for some pip packages compiled from source)
    gcc \
    g++ \
    make \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── 3. Make python3.11 the default python3 ───────────────────────────────────
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --set python3 /usr/bin/python3.11

# ── 4. Install pip for python3.11 ────────────────────────────────────────────
#    Ubuntu 22.04 ships pip tied to python3.10; install fresh for python3.11
RUN curl -fsSL https://bootstrap.pypa.io/get-pip.py | python3.11

# ── 5. Set IRAF environment variables ────────────────────────────────────────
#    The Ubuntu 'iraf' package installs to /usr/lib/iraf
ENV iraf=/usr/lib/iraf/
ENV IRAFARCH=linux64
ENV DISPLAY=:0
#    Matplotlib config: use /tmp so it works with --userns=keep-id (any UID)
ENV MPLCONFIGDIR=/tmp/matplotlib

# ── 5a. Fix IRAF binary path mismatch ────────────────────────────────────────
#    Ubuntu's iraf packages put binaries in bin/ (no arch suffix), but PyRAF
#    with IRAFARCH=linux64 looks for bin.linux64/. Symlinks bridge the gap.
RUN ln -s /usr/lib/iraf/bin /usr/lib/iraf/bin.linux64 \
    && ln -s /usr/lib/iraf/noao/bin /usr/lib/iraf/noao/bin.linux64

# ── 6. Working directory ──────────────────────────────────────────────────────
WORKDIR /app

# ── 7. Install Python dependencies ───────────────────────────────────────────
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# ── 8. Copy pipeline source code ─────────────────────────────────────────────
COPY . .

# ── 9. Create a writable pyraf cache dir ─────────────────────────────────────
#    PyRAF writes its cache (clcache.sqlite3, uparm, etc.) here
RUN mkdir -p /app/pyraf && chmod 777 /app/pyraf

# ── 10. Default entry point ───────────────────────────────────────────────────
CMD ["python3", "main.py"]
