FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md LICENSE ./
COPY contextguard ./contextguard
COPY app.py ./
COPY examples ./examples
COPY changes ./changes
COPY .streamlit ./.streamlit

RUN pip install --no-cache-dir -e .

ENV CONTEXTGUARD_DEMO=true
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
