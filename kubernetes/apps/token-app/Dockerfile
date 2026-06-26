FROM python:3.11-slim

# Install dependencies
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Expose port
EXPOSE 5000

# Set Python to run in unbuffered mode (good for docker logging)
ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"]
