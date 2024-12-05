FROM python:3.12-slim

WORKDIR /app

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

RUN python3 --version
RUN python3 -m venv /opt/venv

RUN apt-get update && \
    apt-get install -y git pkg-config curl gcc g++ && \
    rm -rf /var/lib/apt/lists/*

RUN pip install litellm websockets

COPY . .

ENV GUARDRAILS_TOKEN="123" 
ENV CONTROL_PLANE_URL=""

CMD ["python", "example.py"]