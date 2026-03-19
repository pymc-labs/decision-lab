FROM continuumio/miniconda3:latest

WORKDIR /workspace

RUN pip install --no-cache-dir modal

COPY modal_app/ /opt/modal_app/
ENV PYTHONPATH="/opt"

CMD ["/bin/bash"]
