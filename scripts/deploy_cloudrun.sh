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
"$GCLOUD" services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com iam.googleapis.com --quiet
# Least privilege: the service runs as a dedicated service account with NO IAM roles, so code that escaped
# the sandbox could not use the metadata server's token for anything.
PROJECT="$("$GCLOUD" config get-value project 2>/dev/null)"
SA="specfork-runtime@${PROJECT}.iam.gserviceaccount.com"
"$GCLOUD" iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  "$GCLOUD" iam service-accounts create specfork-runtime --display-name "SpecFork runtime (no roles)" --quiet
ENVFILE="$(mktemp)"; trap 'rm -f "$ENVFILE"' EXIT; chmod 600 "$ENVFILE"
cat > "$ENVFILE" <<YAML
NEBIUS_API_KEY: "$KEY"
MODEL_FAST: "${MODEL_FAST:-nvidia/Nemotron-3_5-Lightning}"
MODEL_DEEP: "${MODEL_DEEP:-nvidia/Nemotron-3-Ultra-550b-a55b}"
DAILY_BUDGET_USD: "${DAILY_BUDGET_USD:-5}"
RATE_LIMIT_RUNS: "${RATE_LIMIT_RUNS:-6}"
SANDBOX_CONCURRENCY: "2"
LLM_CONCURRENCY: "16"
YAML
# --no-cpu-throttling: runs continue in background tasks after the POST returns
# --max-instances 1: in-memory run store + rate limiter, bounded cost
"$GCLOUD" run deploy "$SERVICE" --source . --region "$REGION" --allow-unauthenticated \
  --env-vars-file "$ENVFILE" --cpu 2 --memory 2Gi --concurrency 80 --timeout 900 \
  --min-instances 0 --max-instances 1 --no-cpu-throttling --execution-environment gen2 \
  --service-account "$SA" --quiet
URL="$("$GCLOUD" run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)')"
echo "Deployed: $URL"
curl -fsS "$URL/api/health" && echo
