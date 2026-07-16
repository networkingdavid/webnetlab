FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer-cached)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent source
COPY . .

# SNMP uses UDP port 161
EXPOSE 161/udp

CMD ["python", "agent.py"]
