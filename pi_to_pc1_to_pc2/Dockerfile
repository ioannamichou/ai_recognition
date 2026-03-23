FROM python:3.9-slim

# Εγκατάσταση απαραίτητων βιβλιοθηκών για το OpenCV
RUN apt-get update && apt-get install -y \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Εγκατάσταση βιβλιοθηκών Python
RUN pip install --no-cache-dir opencv-python-headless numpy

# ΑΝΤΙΓΡΑΦΗ των αρχείων που πραγματικά χρησιμοποιούμε
COPY receiver.py .
COPY send_to_server.py .

# Εκτέλεση του receiver (το -u βοηθάει να βλέπεις τα logs σε πραγματικό χρόνο)
CMD ["python", "-u", "receiver.py"]