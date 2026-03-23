# Χρησιμοποιούμε το επίσημο image της Ultralytics (έκδοση για CPU)
# Αυτό το image έχει ΗΔΗ μέσα OpenCV, YOLO και όλες τις βιβλιοθήκες συστήματος
FROM ultralytics/ultralytics:latest-cpu

WORKDIR /app

# Εγκαθιστούμε ΜΟΝΟ τον connector της MySQL (αυτό γίνεται μέσω pip και συνήθως περνάει)
RUN pip install --no-cache-dir mysql-connector-python

# Αντιγραφή του κώδικα AI
COPY server_ai.py .

# Εκκίνηση του server
CMD ["python", "-u", "server_ai.py"]