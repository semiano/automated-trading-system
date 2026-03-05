# DigitalOcean Deployment Checklist

## 1) Local prerequisites

- Docker Desktop running
- Repository pushed (branch: `feature/docker-digitalocean-migration`)
- `doctl` installed

Installed `doctl` path on this machine:

`C:\Users\Steve\AppData\Local\Microsoft\WinGet\Packages\DigitalOcean.Doctl_Microsoft.Winget.Source_8wekyb3d8bbwe\doctl.exe`

If `doctl` is not recognized in a terminal, open a new terminal session.

## 2) Login to DigitalOcean CLI

1. In DigitalOcean web portal, create a Personal Access Token:
   - API -> Tokens/Keys -> Generate New Token
   - Scopes: read + write for droplets, registry, apps, databases (as needed)
2. Login in terminal:

```powershell
& "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\DigitalOcean.Doctl_Microsoft.Winget.Source_8wekyb3d8bbwe\doctl.exe" auth init
```

3. Validate:

```powershell
& "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\DigitalOcean.Doctl_Microsoft.Winget.Source_8wekyb3d8bbwe\doctl.exe" account get
```

## 3) Secrets and env vars to prepare (portal)

Use these values in DigitalOcean App settings or on your Droplet `.env.docker`:

- `POSTGRES_USER=mdtas`
- `POSTGRES_PASSWORD=mdtas` (change for production)
- `POSTGRES_DB=mdtas`
- `POSTGRES_PORT=5432`
- `DATABASE_URL=postgresql+psycopg://mdtas:<PASSWORD>@<DB_HOST>:5432/mdtas`
- `MDTAS_LOG_LEVEL=INFO`
- `MDTAS_CONFIG_PATH=/app/config.yaml`
- `VITE_API_BASE_URL=https://<your-api-domain>/api/v1`

Optional exchange auth (only if using authenticated endpoints):

- `EXCHANGE_API_KEY`
- `EXCHANGE_API_SECRET`

## 4) Config profile recommendation for first deployment

For low-resource environments, use:

- `config.minimal.yaml`
- `MDTAS_CONFIG_FILE=./config.minimal.yaml`

## 5) Deployment target options

### Option A: Droplet + Docker Compose (fastest with current repo)

1. Create Ubuntu Droplet (>= 2 GB recommended for smoother operation).
2. Install Docker + Docker Compose on Droplet.
3. Clone repo and copy `.env.docker`.
4. Set production values/secrets in `.env.docker`.
5. Start stack:

```bash
docker compose --env-file .env.docker up --build -d
```

6. Verify:

```bash
docker compose --env-file .env.docker ps
curl http://localhost:8000/api/v1/health
```

### Option B: App Platform

- Split into services (`api`, `ingestion`, `trader`, `web`) with env/secrets above.
- Use managed PostgreSQL and inject `DATABASE_URL` into backend services.

## 6) Post-deploy smoke test

Run from host where stack is reachable:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test_compose.ps1
```
