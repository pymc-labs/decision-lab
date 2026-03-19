FROM continuumio/miniconda3:latest

WORKDIR /workspace

COPY environment.yml /tmp/environment.yml
RUN conda env create -f /tmp/environment.yml -n dlab-modal-example && \
    conda clean -afy
SHELL ["conda", "run", "-n", "dlab-modal-example", "/bin/bash", "-c"]

COPY modal_app/ /opt/modal_app/
ENV PYTHONPATH="/opt"

CMD ["conda", "run", "-n", "dlab-modal-example", "/bin/bash"]
