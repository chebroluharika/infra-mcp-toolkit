# VM Deployment Guide

Complete guide for deploying the QE Agentic Dashboard to a Virtual Machine (VM).

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [VM Requirements](#2-vm-requirements)
3. [Build Docker Images (Local Machine)](#3-build-docker-images-local-machine)
4. [Transfer Files to VM](#4-transfer-files-to-vm)
5. [VM Setup](#5-vm-setup)
6. [Configuration](#6-configuration)
7. [Deploy and Start](#7-deploy-and-start)
8. [Verification](#8-verification)
9. [Maintenance & Operations](#9-maintenance--operations)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Prerequisites

### On Your Local Machine (for building)

| Software | Version | Purpose |
|----------|---------|---------|
| **Docker Desktop** | Latest | Building container images |
| **Git** | Any | Source code management |

### On the VM

| Software | Version | Purpose |
|----------|---------|---------|
| **Docker** | 20.10+ | Container runtime |
| **Docker Compose** | 2.0+ | Multi-container orchestration |
| **Ollama** | Latest | Local LLM inference |

---

## 2. VM Requirements

### Hardware Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| **CPU** | 2 cores | 4+ cores |
| **RAM** | 4 GB | 8+ GB |
| **Disk** | 20 GB | 50+ GB |
| **OS** | Ubuntu 20.04+ | Ubuntu 22.04 LTS |

### Network Ports

| Port | Service | Description |
|------|---------|-------------|
| **8080** | Frontend (Nginx) | React dashboard |
| **8000** | Backend (FastAPI) | API server |
| **8501** | Streamlit | AI Assistant |
| **11434** | Ollama | LLM inference (localhost only) |

### Firewall Rules

```bash
# Allow required ports (Ubuntu with ufw)
sudo ufw allow 8080/tcp   # Frontend
sudo ufw allow 8000/tcp   # Backend API
```

---

## 3. Build Docker Images (Local Machine)

### Step 1: Navigate to Docker Directory

```bash
cd custom-monitoring-dashboard/docker
```

### Step 2: Build Images for Linux (amd64)

```bash
# Build for amd64 architecture and export as tar.gz
./docker-build.sh -p amd64 -e v1.0.1
```

This creates the following files in `docker-exports/`:
```
docker-exports/
├── qe-dashboard-backend-v1.0.1-amd64.tar.gz
├── qe-dashboard-frontend-v1.0.1-amd64.tar.gz
└── qe-dashboard-streamlit-v1.0.1-amd64.tar.gz
```

### Build Script Options

| Option | Description |
|--------|-------------|
| `-p amd64` | Build for Linux amd64 architecture |
| `-e` | Export images as tar.gz files |
| `-t` | Run container health tests after build |
| `-s` | Skip Docker cache (clean build) |

---

## 4. Transfer Files to VM

### Files to Transfer

| File/Directory | Purpose |
|----------------|---------|
| `docker-exports/*.tar.gz` | Docker images |
| `docker/docker-compose.yml` | Container orchestration |
| `env_template.txt` | Environment variable template |

> **Note:** You don't need to copy data files. The backend container automatically initializes the `data/` directory with defaults (release_calendar.pdf, etc.) on first run.

### Transfer Commands

```bash
# Create directory on VM
ssh user@VM_IP "mkdir -p ~/qe-dashboard"

# Transfer Docker images
scp docker-exports/qe-dashboard-*-v1.0.1-amd64.tar.gz user@VM_IP:~/qe-dashboard/

# Transfer docker-compose.yml
scp docker/docker-compose.yml user@VM_IP:~/qe-dashboard/

# Transfer environment template
scp env_template.txt user@VM_IP:~/qe-dashboard/
```

---

## 5. VM Setup

### Step 1: Install Docker

```bash
# Update packages
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# Add Docker's GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add your user to docker group
sudo usermod -aG docker $USER

# Logout and login again for group changes to take effect
# Then verify installation
docker --version
docker compose version
```

### Step 2: Install Ollama

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama service
sudo systemctl start ollama
sudo systemctl enable ollama

# Pull required models
ollama pull gemma2:9b      # Main chat model
ollama pull llama3.2       # Alternative model

# Verify installation
ollama list
```

### Step 3: Load Docker Images

```bash
cd ~/qe-dashboard

# Load images from tar.gz files
gunzip -c qe-dashboard-backend-v1.0.1-amd64.tar.gz | docker load
gunzip -c qe-dashboard-frontend-v1.0.1-amd64.tar.gz | docker load
gunzip -c qe-dashboard-streamlit-v1.0.1-amd64.tar.gz | docker load

# Verify images are loaded
docker images | grep qe-dashboard
```

Expected output:
```
qe-dashboard-backend    v1.0.1   abc123...   ...
qe-dashboard-frontend   v1.0.1   def456...   ...
qe-dashboard-streamlit  v1.0.1   ghi789...   ...
```

---

## 6. Configuration

### How Frontend Communicates with Backend

The current setup works for **any VM IP without code changes**. Here's why:

```
Browser (User's machine)
    │
    │  http://VM_IP:8080
    ▼
┌─────────────────────────────────┐
│  Frontend Container (Nginx)     │
│  - Serves React app on :8080    │
│  - Proxies /api/* to backend    │
└─────────────────────────────────┘
    │
    │  proxy_pass http://localhost:8000
    ▼
┌─────────────────────────────────┐
│  Backend Container (FastAPI)    │
│  - Runs on :8000                │
└─────────────────────────────────┘
```

**Key points:**
- React app uses **relative URLs** (`/api/*` not `http://host:8000/api/*`)
- `nginx.conf` proxies `/api` requests to `http://localhost:8000`
- `docker-compose.yml` uses `network_mode: host` so all containers share the VM's network
- No need to change `nginx.conf`, `config.js`, or any code for different VM IPs

**Files involved (no changes needed):**

| File | Setting | Purpose |
|------|---------|---------|
| `src/config.js` | `API_BASE_URL = ''` | Empty = relative URLs |
| `nginx.conf` | `proxy_pass http://localhost:8000` | Proxies API to backend |
| `docker-compose.yml` | `network_mode: host` | Containers use VM's network |

### Step 1: Create Environment File

```bash
cd ~/qe-dashboard

# Create .env from template
cp env_template.txt .env

# Edit with your values
nano .env
```

### Step 2: Configure Environment Variables

Update the following variables in `.env`:

```bash
# =============================================================================
# RELEASE CONFIGURATION
# =============================================================================
CURRENT_RELEASE=R135

# =============================================================================
# APPLICATION
# =============================================================================
APP_ENV=production
DEBUG=false
CORS_ORIGINS=*

# =============================================================================
# TESTRAIL
# =============================================================================
TESTRAIL_URL=https://your-instance.testrail.io
TESTRAIL_USERNAME=your-email@company.com
TESTRAIL_API_KEY=your-api-key
TESTRAIL_PROJECT_ID=38

# =============================================================================
# JIRA
# =============================================================================
JIRA_URL=https://your-company.atlassian.net
JIRA_USERNAME=your-email@company.com
JIRA_API_TOKEN=your-api-token
JIRA_PROJECT_KEY=YOUR_PRODUCT
JIRA_FIX_VERSION=R 135.0.0.0

# =============================================================================
# JENKINS
# =============================================================================
JENKINS_URL=http://jenkins.your-company.com:8080
JENKINS_USER=your-username
JENKINS_TOKEN=your-token
JENKINS_VIEW=Your-Product
JENKINS_JOBS=job1,job2,job3
JENKINS_GOLDEN_REGRESSION_URL=http://jenkins.../job/Golden%20Regression%20Suite

# =============================================================================
# GITHUB
# =============================================================================
GITHUB_TOKEN=ghp_your_token_here

# =============================================================================
# SLACK NOTIFICATIONS
# =============================================================================
SLACK_BOT_TOKEN=xoxb-your-token
SLACK_CHANNEL=YOUR_SLACK_CHANNEL_ID
SLACK_NOTIFICATIONS_ENABLED=true

# =============================================================================
# AI CONFIGURATION
# =============================================================================
ADK_LLM_PROVIDER=ollama
ADK_LLM_MODEL=gemma2:9b
ADK_OLLAMA_BASE_URL=http://localhost:11434
```

### Step 3: Update docker-compose.yml Image Tags (if needed)

Ensure the image tags match your version:

```bash
nano docker-compose.yml
```

```yaml
services:
  backend:
    image: qe-dashboard-backend:v1.0.1
  frontend:
    image: qe-dashboard-frontend:v1.0.1
  streamlit:
    image: qe-dashboard-streamlit:v1.0.1
```

---

## 7. Deploy and Start

### Start All Services

```bash
cd ~/qe-dashboard

# Start containers
docker compose up -d
```

### Check Service Status

```bash
docker compose ps
```

Expected output:
```
NAME                      STATUS    PORTS
qe-dashboard-backend      Up        
qe-dashboard-frontend     Up        
qe-dashboard-streamlit    Up        
```

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f streamlit
```

---

## 8. Verification

### Check Health Endpoints

```bash
# Backend health
curl http://localhost:8000/api/health

# Frontend (nginx)
curl -s http://localhost:8080 | head -5

# Streamlit health
curl http://localhost:8501/_stcore/health

# Ollama
ollama list
```

### Access the Dashboard

Open in browser:

| Service | URL |
|---------|-----|
| **Dashboard** | `http://VM_IP:8080` |
| **API Docs** | `http://VM_IP:8000/docs` |
| **AI Assistant** | `http://VM_IP:8080/streamlit/` |

### Verify Data Connections

```bash
# Test API endpoints
curl http://localhost:8000/api/releases
curl http://localhost:8000/api/jira/health
curl http://localhost:8000/api/jenkins/pipelines
```

---

## 9. Maintenance & Operations

### Common Commands

| Task | Command |
|------|---------|
| Start all services | `docker compose up -d` |
| Stop all services | `docker compose down` |
| Restart all services | `docker compose restart` |
| View logs | `docker compose logs -f` |
| Check status | `docker compose ps` |
| Shell into backend | `docker compose exec backend bash` |
| Shell into frontend | `docker compose exec frontend sh` |

### Updating to New Version

```bash
# 1. Transfer new images to VM
scp docker-exports/qe-dashboard-*-v1.0.2-amd64.tar.gz user@VM_IP:~/qe-dashboard/

# 2. On VM: Stop current services
cd ~/qe-dashboard
docker compose down

# 3. Load new images
gunzip -c qe-dashboard-backend-v1.0.2-amd64.tar.gz | docker load
gunzip -c qe-dashboard-frontend-v1.0.2-amd64.tar.gz | docker load
gunzip -c qe-dashboard-streamlit-v1.0.2-amd64.tar.gz | docker load

# 4. Update docker-compose.yml with new version tags
nano docker-compose.yml
# Change v1.0.1 to v1.0.2

# 5. Start services
docker compose up -d

# 6. Verify
docker compose ps
curl http://localhost:8000/api/health
```

### Backup Data

```bash
# Backup persistent data
cd ~/qe-dashboard
tar -czvf backup-$(date +%Y%m%d).tar.gz data/
```

### Cleanup Old Images

```bash
# Remove old version images
docker rmi qe-dashboard-backend:v1.0.0
docker rmi qe-dashboard-frontend:v1.0.0
docker rmi qe-dashboard-streamlit:v1.0.0

# Remove unused images
docker image prune -f
```

---

## 10. Troubleshooting

### Container Won't Start

```bash
# Check container logs
docker compose logs backend

# Check if ports are in use
sudo netstat -tlnp | grep -E '8000|8080|8501'

# Kill process using port (if needed)
sudo kill $(sudo lsof -t -i:8000)
```

### Backend Can't Connect to External Services

```bash
# Check .env file is loaded
docker compose exec backend env | grep JIRA

# Test connectivity from container
docker compose exec backend curl -v https://your-jira.atlassian.net
```

### Frontend Shows "API Not Available"

```bash
# Check backend is running
curl http://localhost:8000/api/health

# Check nginx logs
docker compose logs frontend
```

### Ollama Not Working

```bash
# Check Ollama service
sudo systemctl status ollama

# Restart Ollama
sudo systemctl restart ollama

# Check models are available
ollama list

# Re-pull models if needed
ollama pull gemma2:9b
```

### Permission Issues with Data Directory

```bash
# Fix data directory permissions
sudo chown -R 1001:1001 ~/qe-dashboard/data/
```

### Memory Issues

```bash
# Check memory usage
free -h
docker stats

# If Ollama uses too much memory, use smaller model
ollama pull llama3.2  # Smaller than gemma2:9b
```

---

## Quick Reference

### Directory Structure on VM

```
~/qe-dashboard/
├── docker-compose.yml          # Container orchestration
├── .env                        # Environment configuration
├── data/                       # Persistent data (auto-created on first run)
└── qe-dashboard-*.tar.gz       # Docker images (can delete after loading)
```

### Service URLs

| Service | URL |
|---------|-----|
| Dashboard | `http://VM_IP:8080` |
| API | `http://VM_IP:8000` |
| API Docs | `http://VM_IP:8000/docs` |
| AI Assistant | `http://VM_IP:8080/streamlit/` |

---
