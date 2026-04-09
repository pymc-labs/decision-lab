FROM python:3.11-slim

WORKDIR /workspace

RUN pip install --no-cache-dir \
    PyMuPDF==1.25.3 \
    pdfplumber==0.11.4 \
    httpx==0.28.1

COPY peer_review_lib /opt/peer_review_lib

ENV PYTHONPATH="/opt"

RUN python -c "import peer_review_lib; print('peer_review_lib import OK')"
RUN python -c "import fitz; print('PyMuPDF import OK')"

CMD ["/bin/bash"]
