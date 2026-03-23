# 🚁 Drone Thermal AI Recognition Pipeline

An end-to-end, multi-stage processing pipeline for drone-captured video streams. This project utilizes a distributed architecture to capture, encode, and analyze thermal/visual data using **YOLOv8** and **Docker**.

---

## 🏗 System Architecture

The project is split into three main nodes to distribute processing power efficiently:

1.  **Drone (Raspberry Pi):** Captures raw frames and streams them over the network.
2.  **Base Station (PC 1 - Laptop):** * Receives raw frame data via Socket.
    * Encodes frames into compressed **MP4** files using OpenCV.
    * Automatically forwards completed video segments to the AI Server.
3.  **AI Inference Server (PC 2):**
    * Receives MP4 files.
    * Runs **YOLOv8 (Ultralytics)** object detection.
    * Logs detections (Object class, Confidence, Timestamp) into a **MySQL** database.
    * Provides a web interface via **phpMyAdmin** for data visualization.

---

## 🚀 Tech Stack

* **Language:** Python 3.9+
* **AI Model:** YOLOv8 (Ultralytics)
* **Containerization:** Docker & Docker Compose
* **Database:** MySQL 8.0
* **Image Processing:** OpenCV (Headless)
* **Networking:** TCP Sockets

---

## 🛠 Setup & Installation

### Prerequisites
* Docker & Docker Compose installed on both machines.
* Python 3.x (for local testing).

### Deployment

**1. Start the AI Server (PC 2):**
cd pc2-ai-server
docker-compose up -d --build
Access the Database via http://localhost:8080 (phpMyAdmin).

2. Start the Base Station (PC 1 - Laptop):
   cd pc1-laptop
docker-compose up -d --build



📊 Features
[x] Real-time frame-to-video encoding.

[x] Automated file transfer between distributed nodes.

[x] High-performance AI inference using YOLOv8.

[x] Persistent storage of detections in a relational database.

[x] Headless Docker environment for easy deployment.

## 📝 License
**Private / Personal Project.** All rights reserved. This code is for personal use only.

