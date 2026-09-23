# Laya System One decisions (Convai Innovations, Apache-2.0) for system_one.provider=laya.
# CPU only: torch comes from the PyTorch CPU index, so no CUDA libraries are installed.
# Weights are not baked in; they download once into HF_HOME (the laya_hf_cache volume).
FROM python:3.12.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/var/lib/laya/hf

COPY requirements.txt /tmp/requirements.txt
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# The cache directory exists (owned by the service user) before a named volume is first
# mounted on it, so the new volume inherits that ownership and the process never runs as root.
RUN useradd --system --uid 10001 --user-group --home-dir /var/lib/laya --create-home laya \
    && mkdir -p /var/lib/laya/hf \
    && chown -R laya:laya /var/lib/laya

COPY ragweld_laya_serve.py /opt/laya/ragweld_laya_serve.py

USER laya
WORKDIR /var/lib/laya
EXPOSE 8000
CMD ["python", "/opt/laya/ragweld_laya_serve.py"]
