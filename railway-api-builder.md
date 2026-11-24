---
name: railway-api-builder-and-repair
description: Autonomous agent skill to scaffold, locally test, self-repair, and deploy a production-ready WebP & 360 Panorama Optimizer API onto Railway, plus generate RapidAPI monetization configs.
---

# Mission
You are an autonomous DevOps and Backend Engineering Agent operating inside the user's Ubuntu CLI environment. Your objective is to build, verify, self-repair, and deploy a commercial-grade **Ultra-Fast WebP & 360° Panorama Optimizer API** ready for Railway hosting and RapidAPI monetization, requiring zero manual code edits from the user.

# Target Tech Stack & Constraints
- **Framework:** Python 3.11 + FastAPI + Uvicorn (optimized for low memory footprint).
- **Image Engine:** Pillow (`PIL`) with `libwebp` support, handling high-resolution 360° equirectangular panoramas safely without OOM (Out-Of-Memory) crashes.
- **Container & Hosting:** Alpine Linux `Dockerfile` + `railway.toml` configured for dynamic `$PORT` binding.
- **Monetization Ready:** Header-based API Key verification (`X-RapidAPI-Proxy-Secret` or `X-API-Key`) with a toggleable `DISABLE_AUTH` env var for initial smoke testing.

# Execution Pipeline (Strict Order)

## Phase 1: Scaffold Production Files
Create the following files in the current working directory (`~/railway-webp-saas`):

1. `main.py`:
   - `GET /` -> Health check returning `{"status": "live", "engine": "WebP-360-Optimizer", "version": "1.0.0"}`.
   - `POST /optimize` -> Accepts JSON payload: `{"image_url": "<url>", "quality": 80, "max_width": 4096, "strip_metadata": true}`.
   - Must validate URL, enforce a 25MB download cap (streaming check) to prevent Railway container OOM crashes, convert RGBA/P modes to RGB cleanly, resize proportionally if width > `max_width` using `Image.Resampling.LANCZOS`, compress to `WEBP` (`method=6`), and return JSON containing `original_kb`, `optimized_kb`, `savings_percent`, `dimensions`, and `webp_base64`.
   - Include clean exception handling returning HTTP 400/422 with clear JSON error messages (never expose raw stack traces).

2. `requirements.txt`:
   - Pin stable versions: `fastapi==0.115.0`, `uvicorn[standard]==0.30.6`, `pillow==10.4.0`, `requests==2.32.3`, `pydantic==2.9.2`.

3. `Dockerfile`:
   - Base image: `python:3.11-alpine`.
   - Install system build/runtime deps: `gcc musl-dev zlib-dev jpeg-dev libwebp-dev`.
   - Expose port `8080` and launch via shell form so Railway's `$PORT` injects properly: `CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]`.

4. `railway.toml`:
   - Configure `[build]` using `DOCKERFILE` and `[deploy]` with `healthcheckPath = "/"`, `healthcheckTimeout = 30`, and `restartPolicyType = "ON_FAILURE"`.

5. `.dockerignore` & `.gitignore`:
   - Exclude `__pycache__`, `.venv`, `.env`, `*.log`.

## Phase 2: Local Verification & Self-Repair Loop
Before touching Railway, run an automated verification cycle:
1. Build the Docker image locally (`docker build -t webp-saas-test .`) OR test inside an isolated Python venv if Docker daemon is inactive.
2. Start the container/server on port `8080` in detached/background mode.
3. Run `curl -s http://localhost:8080/` and verify HTTP 200.
4. Run a live `POST /optimize` test using a public sample image URL (`https://httpbin.org/image/jpeg`).
5. **SELF-REPAIR RULE:** If the build fails, dependencies conflict, Pillow lacks WebP support, or the `POST` test fails:
   - Read the exact stderr/logs.
   - Patch `Dockerfile`, `requirements.txt`, or `main.py` automatically.
   - Re-run the test loop (up to 3 attempts) until both `GET /` and `POST /optimize` pass 100%.
6. Stop and clean up the local test container once verified.

## Phase 3: Railway Deployment & Monetization Pack
1. Check if `railway` CLI is installed and authenticated (`railway whoami`).
   - If authenticated: Initialize/link the project (`railway init` or `railway up --detach`), set `DISABLE_AUTH=true` initially, and fetch the generated public domain (`railway domain`).
   - If not logged in: Output the exact 2-line login + deploy command for the user without failing.
2. Generate `RAPIDAPI_SETUP.md` containing:
   - Exact OpenAPI/cURL payload examples.
   - Ready-to-copy SEO title, short description, and long description for RapidAPI marketplace.
   - Suggested pricing tiers: Basic ($0/mo - 50 reqs), Pro ($9.99/mo - 5,000 reqs), Ultra ($29.99/mo - 25,000 reqs).
