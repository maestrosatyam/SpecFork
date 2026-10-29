#!/usr/bin/env bash
# Deploy SpecFork to Google Cloud Run from source (Cloud Build builds the Dockerfile; no local Docker needed).
# Prereqs: gcloud auth login; gcloud config set project <PROJECT>; NEBIUS_API_KEY in .env
# Usage: scripts/deploy_cloudrun.sh [service-name] [region]
set -euo pipefail
cd "$(dirname "$0")/.."
SERVICE="${1:-specfork}"
REGION="${2:-us-central1}"
GCLOUD="${GCLOUD:-gcloud}"
command -v "$GCLOUD" >/dev/null || GCLOUD="$HOME/google-cloud-sdk/bin/gcloud"
KEY="$(grep -E '^NEBIUS_API_KEY=' .env | head -1 | cut -d= -f2- | tr -d '"'"'"'')"
[ -n "$KEY" ] || { echo "NEBIUS_API_KEY missing in .env" >&2; exit 1; }
"$GCLOUD" services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --quiet
ENVFILE="$(mktemp)"; trap 'rm -f "$ENVFILE"' EXIT; chmod 600 "$ENVFILE"
cat > "$ENVFILE" <<YAML
NEBIUS_API_KEY: "$KEY"
MODEL_FAST: "${MODEL_FAST:-nvidia/Nemotron-3_5-Lightning}"
MODEL_DEEP: "${MODEL_DEEP:-nvidia/Nemotron-3-Ultra-550b-a55b}"
DAILY_BUDGET_USD: "${DAILY_BUDGET_USD:-5}"
RATE_LIMIT_RUNS: "${RATE_LIMIT_RUNS:-6}"
YAML
# --no-cpu-throttling: runs continue in background tasks after the POST returns
# --max-instances 1: in-memory run store + rate limiter, bounded cost
"$GCLOUD" run deploy "$SERVICE" --source . --region "$REGION" --allow-unauthenticated \
  --env-vars-file "$ENVFILE" --cpu 2 --memory 2Gi --concurrency 80 --timeout 900 \
  --min-instances 0 --max-instances 1 --no-cpu-throttling --execution-environment gen2 --quiet
URL="$("$GCLOUD" run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)')"
echo "Deployed: $URL"
curl -fsS "$URL/api/health" && echo
