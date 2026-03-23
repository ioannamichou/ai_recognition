FROM python:3.9-slim

RUN apt-get update && apt-get install -y \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Εγκατάσταση του OpenCV
RUN pip install --no-cache-dir opencv-python-headless

COPY sender.py .

CMD ["python", "sender.py"]