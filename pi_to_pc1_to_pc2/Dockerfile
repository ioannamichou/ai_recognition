FROM python:3.9-slim

# Εγκατάσταση απαραίτητων βιβλιοθηκών για το OpenCV
RUN apt-get update && apt-get install -y \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Εγκατάσταση βιβλιοθηκών Python
RUN pip install --no-cache-dir opencv-python-headless numpy

# Αντιγραφή των scripts και του entrypoint
COPY receiver.py .
COPY send_to_server.py .
COPY entrypoint.sh .

# Δίνουμε δικαιώματα εκτέλεσης στο entrypoint script
RUN chmod +x entrypoint.sh

# Ορίζουμε το entrypoint (αφαιρούμε το CMD)
ENTRYPOINT ["./entrypoint.sh"]