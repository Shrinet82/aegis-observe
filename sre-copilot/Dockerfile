FROM python:3.11-slim

# Install system dependencies (curl, git, kubectl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ca-certificates \
    && curl -LO https://dl.k8s.io/release/v1.30.0/bin/linux/amd64/kubectl \
    && chmod +x kubectl \
    && mv kubectl /usr/local/bin/ \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY agent.py /app/agent.py

# Run agent
CMD ["python", "-u", "/app/agent.py"]
