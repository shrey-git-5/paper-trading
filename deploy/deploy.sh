#!/bin/bash
# Deploys Paper Trader to Google Cloud Run in Mumbai, with its data in a private Cloud Storage bucket
# and a Cloud Scheduler job that checks stop-losses and targets every minute of market hours.
#
#   bash deploy/deploy.sh YOUR_PROJECT_ID
#
# Needs: the gcloud CLI, logged in (gcloud auth login), and billing enabled on the project.
# Asks you for an app password; the app shows a login screen with it. Run again to update the app.
set -euo pipefail

PROJECT="${1:?usage: bash deploy/deploy.sh YOUR_PROJECT_ID}"
REGION="asia-south1"                       # Mumbai
SERVICE="paper-trader"
BUCKET="${PROJECT}-paper-trader-data"
cd "$(dirname "$0")/.."

gcloud config set project "$PROJECT" >/dev/null
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com secretmanager.googleapis.com storage.googleapis.com

# 1. A private bucket for your account, settings and broker keys (not public; only the app's identity can read it).
if ! gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access --public-access-prevention
fi

# 2. Two secrets: the password you type to open the app, and the token Cloud Scheduler uses.
if ! gcloud secrets describe pt-app-password >/dev/null 2>&1; then
  read -r -s -p "Choose an app password (at least 12 characters): " PW; echo
  [ ${#PW} -ge 12 ] || { echo "Too short."; exit 1; }
  printf "%s" "$PW" | gcloud secrets create pt-app-password --data-file=-
fi
if ! gcloud secrets describe pt-tick-token >/dev/null 2>&1; then
  python3 -c "import secrets; print(secrets.token_urlsafe(32), end='')" | gcloud secrets create pt-tick-token --data-file=-
fi
NUM=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
SA="${NUM}-compute@developer.gserviceaccount.com"
for s in pt-app-password pt-tick-token; do
  gcloud secrets add-iam-policy-binding "$s" --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor >/dev/null
done
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA" --role=roles/storage.objectAdmin >/dev/null

# 3. Build and deploy. max-instances=1: one copy of the app, so two copies never overwrite each other's files.
gcloud run deploy "$SERVICE" --source . --region "$REGION" --allow-unauthenticated \
  --max-instances 1 --min-instances 0 --memory 512Mi --cpu 1 --timeout 300 \
  --execution-environment gen2 \
  --add-volume name=data,type=cloud-storage,bucket="$BUCKET" --add-volume-mount volume=data,mount-path=/data \
  --set-secrets APP_PASSWORD=pt-app-password:latest,TICK_TOKEN=pt-tick-token:latest

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')

# 4. Every minute, Monday to Friday, 9 AM to 3:59 PM India time: run the stop-loss / target / 3:20 PM checks.
TOKEN=$(gcloud secrets versions access latest --secret=pt-tick-token)
if gcloud scheduler jobs describe pt-tick --location "$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http pt-tick --location "$REGION" --schedule="* 9-15 * * 1-5" --time-zone="Asia/Kolkata" \
    --uri="$URL/api/tick" --http-method=POST --update-headers="X-Tick-Token=$TOKEN"
else
  gcloud scheduler jobs create http pt-tick --location "$REGION" --schedule="* 9-15 * * 1-5" --time-zone="Asia/Kolkata" \
    --uri="$URL/api/tick" --http-method=POST --headers="X-Tick-Token=$TOKEN"
fi

echo ""
echo "Deployed: $URL"
echo "Open it on your phone, log in with your app password, then 'Add to Home Screen'."
echo "In your Upstox app on account.upstox.com/developer/apps, set the redirect URL to: $URL/upstox/callback"
