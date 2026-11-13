# 🚀 Production Server Deployment Guide: ShareM F&O Analyzer
### Full-Stack Python (FastAPI) Backend + React.js Frontend

To take both the **Python FastAPI Backend** and **React.js Frontend** live on a production server (such as an **Ubuntu VPS** on AWS EC2, DigitalOcean Droplet, Hetzner, Hostinger, or Linode), you have two standard production approaches:

* **Method 1 (Recommended & Fastest): Docker Compose** — Runs Backend, Frontend, and Database in isolated containers with 1 command.
* **Method 2: Traditional Systemd + Nginx Service** — Runs Python as a background Linux system service and serves the built React static bundle via Nginx with reverse proxy and free SSL.

---

## 🏗️ Architecture Overview

```text
                      Internet User (Browser / Mobile)
                                    │
                                    ▼ (HTTPS :443 / HTTP :80)
                       ┌─────────────────────────┐
                       │      Nginx Server       │
                       └────────────┬────────────┘
                                    │
             ┌──────────────────────┴──────────────────────┐
             ▼                                             ▼
       location /                                    location /api/
  ┌──────────────────────┐                     ┌────────────────────────┐
  │   React Production   │                     │  Python FastAPI Backend│
  │    (Built HTML/JS)   │                     │   (Uvicorn :8000/8001) │
  └──────────────────────┘                     └───────────┬────────────┘
                                                           │
                                                           ▼
                                                ┌───────────────────────┐
                                                │ SQLite / PostgreSQL   │
                                                │ & Angel One SmartAPI  │
                                                └───────────────────────┘
```

---

## 📋 Pre-Requisites (Server Setup)

Connect to your Ubuntu server via SSH:
```bash
ssh root@YOUR_SERVER_IP
```

### 1. Update Server Packages & Configure Firewall
Copy and paste this block into your server terminal:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl wget ufw htop

# Configure Firewall
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable -y
```

### 2. Clone the Latest Branch (`angelone_v11`)
```bash
# Create web directory and navigate
sudo mkdir -p /var/www
cd /var/www

# Clone Backend and Frontend
git clone -b angelone_v11 https://github.com/prashantshende16/ShareM_Back.git backend
git clone -b angelone_v11 https://github.com/prashantshende16/ShareM_Front.git frontend
```

### 3. Setup Backend Environment Variables (`.env`)
```bash
cd /var/www/backend
cat << 'EOF' > .env
PROJECT_NAME="ShareM F&O Analyzer"
API_V1_PREFIX="/api/v1"
DATABASE_URL="sqlite:///./fo_analyzer.db"
UPLOAD_DIR="uploads"

# AI Vision Provider
AI_PROVIDER="mock"
GEMINI_API_KEY=""

# Angel One SmartAPI Live Data & Option Chain
MARKET_DATA_PROVIDER="angel_one"
DATA_SOURCE_PREFERENCE="angel_one"
ANGEL_ONE_API_KEY="YOUR_ANGEL_ONE_API_KEY"
ANGEL_ONE_CLIENT_CODE="YOUR_ANGEL_CLIENT_CODE"
ANGEL_ONE_PIN="YOUR_ANGEL_PIN"
ANGEL_ONE_TOTP_KEY="YOUR_TOTP_SECRET_KEY"

# CORS
CORS_ORIGINS=["*"]
EOF
```
> *(Replace the Angel One credentials above with your actual API details using `nano /var/www/backend/.env`)*.

---

## 🐳 Method 1: Docker Compose Deployment (Fastest)

If you prefer running everything in self-contained Docker containers:

### Step 1: Install Docker & Docker Compose
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo apt install -y docker-compose-plugin
```

### Step 2: Start the Stack with 1 Command
```bash
cd /var/www
docker compose up -d --build
```

### Step 3: Check Status
```bash
docker compose ps
docker compose logs -f backend
```
* **Frontend Web:** `http://YOUR_SERVER_IP:3000` (or `http://YOUR_SERVER_IP`)
* **Backend API Docs:** `http://YOUR_SERVER_IP:8000/docs`

---

## ⚙️ Method 2: Traditional Systemd + Nginx (Industry Standard)

This method provides optimal raw performance, direct hardware access, native logging, and seamless SSL integration.

### Part A: Python FastAPI Backend Service

#### 1. Install Python 3 & Dependencies
```bash
sudo apt install -y python3-pip python3-venv python3-dev build-essential libpq-dev
cd /var/www/backend

# Create Virtual Environment
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install uvicorn gunicorn httpx
```

#### 2. Create Systemd Service (Auto-Start & Restart on Failure)
```bash
sudo cat << 'EOF' > /etc/systemd/system/sharem-backend.service
[Unit]
Description=ShareM Python FastAPI Backend Service
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/backend
Environment="PATH=/var/www/backend/venv/bin"
ExecStart=/var/www/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5
EnvironmentFile=/var/www/backend/.env

[Install]
WantedBy=multi-user.target
EOF
```

#### 3. Enable and Start Backend Service
```bash
sudo systemctl daemon-reload
sudo systemctl enable sharem-backend
sudo systemctl start sharem-backend
sudo systemctl status sharem-backend
```

Test backend health:
```bash
curl -I http://127.0.0.1:8000/api/v1/health
```

---

### Part B: React.js Frontend Production Build

#### 1. Install Node.js 20 LTS
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

#### 2. Build the React Bundle
```bash
cd /var/www/frontend
npm install
npm run build
```
*(The production files will be compiled into `/var/www/frontend/dist`)*.

---

### Part C: Configure Nginx Web Server

#### 1. Install Nginx
```bash
sudo apt install -y nginx
```

#### 2. Create Nginx Site Configuration
```bash
sudo cat << 'EOF' > /etc/nginx/sites-available/sharem
server {
    listen 80;
    server_name YOUR_DOMAIN_OR_SERVER_IP;

    # Maximum upload size for screenshots/charts
    client_max_body_size 25M;

    # 1. React Production Single Page Application (SPA)
    location / {
        root /var/www/frontend/dist;
        index index.html index.htm;
        try_files $uri $uri/ /index.html;
    }

    # 2. Reverse Proxy to FastAPI Backend
    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    # 3. Static Uploads (Screenshots, trade logs)
    location /uploads/ {
        proxy_pass http://127.0.0.1:8000/uploads/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF
```
> *(Replace `YOUR_DOMAIN_OR_SERVER_IP` with your actual domain or IP using `sudo nano /etc/nginx/sites-available/sharem`)*.

#### 3. Enable Site & Restart Nginx
```bash
sudo ln -s /etc/nginx/sites-available/sharem /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

---

### Part D: Setup Free SSL (HTTPS) with Let's Encrypt

If you have a domain pointed to your server IP (e.g. `sharem.yourdomain.com`):
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```
* Follow the on-screen prompts.
* Certbot will automatically configure HTTPS redirect and set up auto-renewal certificates.

---

## 🔄 How to Deploy Updates in the Future

Whenever you push new features or bug fixes to GitHub branch `angelone_v11`:

```bash
# ------------------------------
# 1. Pull & Restart Backend
# ------------------------------
cd /var/www/backend
git pull origin angelone_v11
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart sharem-backend

# ------------------------------
# 2. Pull & Re-build Frontend
# ------------------------------
cd /var/www/frontend
git pull origin angelone_v11
npm install
npm run build
sudo systemctl restart nginx

echo "✅ ShareM Successfully Updated & Live!"
```

---

## 🛠️ Handy Monitoring & Debugging Commands

* **Check Backend Live Logs:**
  ```bash
  sudo journalctl -u sharem-backend -f -n 50
  ```
* **Restart Backend:**
  ```bash
  sudo systemctl restart sharem-backend
  ```
* **Check Nginx Access & Error Logs:**
  ```bash
  sudo tail -f /var/log/nginx/error.log
  sudo tail -f /var/log/nginx/access.log
  ```
* **Test Option Search API directly on server:**
  ```bash
  curl -s "http://127.0.0.1:8000/api/v1/trades/search-options?query=56000"
  ```
