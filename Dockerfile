# Python runtime
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create necessary directories
RUN mkdir -p output data logs

# Expose port
EXPOSE 18903

# Start web server
CMD ["python", "-m", "src.main", "web"]
