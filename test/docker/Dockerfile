FROM python:3.12-slim

WORKDIR /workspace

COPY environment.yml /tmp/environment.yml
RUN conda env update -n base -f /tmp/environment.yml && \
    conda clean -afy

COPY test_lib/ /opt/test_lib/
COPY modal_app/ /opt/modal_app/
ENV PYTHONPATH="/opt"

CMD ["/bin/bash"]
