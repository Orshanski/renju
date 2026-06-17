# Renju

Self-hosted web app for playing [renju](https://en.wikipedia.org/wiki/Renju) (professional 5-in-a-row) against an AI engine. Runs on your own server, playable in the browser and installable as a PWA on iPad or iPhone. Powered by [Rapfi](https://github.com/dhbloo/rapfi).

## Why

Renju has asymmetric rules: black is subject to forbidden moves (double-three, double-four, overline), which makes it harder to learn than plain gomoku. A good engine both plays strong and highlights forbidden squares, so you can relearn the rules by feel rather than by reading them.

The hard part — AI and rule enforcement — comes free with [Rapfi](https://github.com/dhbloo/rapfi) (GomoCup champion). This project wraps it as a network backend with auth, persistence, and a web UI.

## Features

**Play**
- 15×15 board, renju rules (RULE 4), forbidden-move highlighting for black
- RIF opening: black opens at center, white replies in 3×3, black replies in 5×5
- Multiple AI strength levels (adjustable through admin settings)
- Resume any game from any device — the board state syncs in real time via SSE

**App**
- Installable as a PWA (iPad, iPhone, desktop)
- JWT auth with HTTP-only cookies; users are created by an admin, no open registration
- Admin panel: user management, role assignment, password reset
- Single-binary backend — no external databases, no message brokers; SQLite file on disk

## Stack

| Layer | Technology |
|---|---|
| AI engine | [Rapfi](https://github.com/dhbloo/rapfi) (C++, NNUE eval, GomoCup champion) |
| Backend | Python 3.13, FastAPI, SQLAlchemy, Alembic, SQLite, uv |
| Frontend | React 19, TypeScript, Vite |
| Server | nginx (TLS termination, static assets), systemd, Cloudflare |

## Self-hosting

### Requirements

- Linux server (x86-64 or ARM64)
- Python 3.13
- Node.js 20+
- C++ build toolchain (to compile Rapfi)
- nginx

### First deploy

```bash
# 1. Clone
git clone https://github.com/Orshanski/renju /opt/renju
cd /opt/renju

# 2. Build Rapfi engine (CPU-specific binary, must be built on the target machine)
bash engine/build.sh

# 3. Backend dependencies
cd backend && uv sync --no-dev

# 4. Database
uv run alembic upgrade head

# 5. Frontend
cd ../frontend && npm ci && npx vite build
```

Create `/etc/systemd/system/renju.service`:

```ini
[Unit]
Description=Renju
After=network.target

[Service]
User=alexey
WorkingDirectory=/opt/renju/backend
ExecStart=/opt/renju/backend/.venv/bin/uvicorn app.app_factory:create_app \
    --factory --host 127.0.0.1 --port 8001
Restart=always
RestartSec=3
Environment="RENJU_SECURE_COOKIE=true"

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now renju
```

nginx vhost (assumes a wildcard Cloudflare origin certificate):

```nginx
server {
    listen 443 ssl;
    server_name renju.example.com;

    ssl_certificate     /etc/ssl/cloudflare/example.com.pem;
    ssl_certificate_key /etc/ssl/cloudflare/example.com.key;

    location /assets/ {
        alias /opt/renju/frontend/dist/assets/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name renju.example.com;
    return 301 https://$host$request_uri;
}
```

### Environment variables

All settings use the `RENJU_` prefix (e.g. via systemd drop-in or `.env` file in `backend/`).

| Variable | Default | Description |
|---|---|---|
| `RENJU_RAPFI_BIN` | auto-detected | Path to the `pbrain-rapfi` binary |
| `RENJU_DATA_DIR` | `<repo>/data` | Directory for SQLite DB and secret key file |
| `RENJU_SECRET_KEY` | auto-generated | JWT signing key (auto-saved to `data/.secret_key`) |
| `RENJU_SECURE_COOKIE` | `false` | Set to `true` in production (HTTPS only) |

### Creating the first admin user

```bash
cd /opt/renju/backend
uv run python -m scripts.create_admin admin changeme
```

## Development

```bash
# Backend (from backend/)
uv sync
uv run pytest -q            # unit + integration tests (sequential — shared Rapfi process)
uv run ruff check app tests

# Frontend (from frontend/)
npm install
npm test
npx vite build
```

Run locally (with Rapfi built):

```bash
cd backend && uv run python run.py
# or with HTTPS (Tailscale dev cert):
uv run python run.py --ssl --dev
```

## Engine notes

Rapfi is an external GPL project and is excluded from this repository (see `.gitignore`). The binary is CPU-specific and **must be compiled on the deployment machine** — do not copy a binary between machines with different CPU architectures (it will crash with SIGILL).

See `engine/RUNBOOK.md` for build instructions and `engine/config.toml` for engine configuration (NNUE weights, rule settings).
