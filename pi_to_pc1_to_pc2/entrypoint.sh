#!/bin/bash

# Τρέχει το πρώτο script (receiver)
echo "--- Starting Receiver ---"
python -u receiver.py

# Μόλις τερματίσει ο receiver, ξεκινάει το δεύτερο script
echo "--- Receiver finished. Sending data to server ---"
python -u send_to_server.py