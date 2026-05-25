# =============================================================================
# netforensics Dockerfile
# =============================================================================
# CPU-only torch + torch-geometric for portability. The dpack is designed to
# run on a laptop without GPUs; demo dataset (Elliptic, ~200k nodes) trains
# in minutes on CPU.

FROM python:3.11-slim

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir \
        torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir \
        torch-geometric==2.6.1

COPY netforensics_lib /opt/netforensics_lib
ENV PYTHONPATH="/opt"

RUN python -c "import netforensics_lib; print('netforensics_lib import OK')"
RUN python -c "import torch; import torch_geometric; print(f'torch {torch.__version__}, PyG {torch_geometric.__version__}')"
RUN python -c "import xgboost; import networkx; import sklearn; print('xgboost / networkx / sklearn OK')"

CMD ["/bin/bash"]
