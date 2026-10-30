# Putting Paper Trader on Google Cloud (for your phone)

## What you get

A private web address like `https://paper-trader-xxxxx.a.run.app` that works on your phone and
laptop, behind a password. Add it to your phone's home screen and it opens like an app.

## How it's built

| Piece | Google service | Why |
| --- | --- | --- |
| The app | **Cloud Run** (Mumbai, `asia-south1`), max 1 instance | Runs the same Python as your Mac; scales to zero when unused |
| Your account, settings, Upstox keys | A private **Cloud Storage** bucket mounted at `/data` | Cloud Run's own disk is wiped on every restart |
| App password, timer token | **Secret Manager** | Never written in the code or the image |
| Stop-loss / target checks while your phone is locked | **Cloud Scheduler**, every minute, Mon–Fri 9:00–15:59 IST | Cloud Run sleeps between requests, so a timer wakes it to check exits |

Why max 1 instance: the account is a JSON file in the bucket, and Cloud Storage has no file
locking ("last write wins"). One instance means one writer.

## Cost (estimate; check your billing page after the first week)

Cloud Run's free tier is per billing account each month: 180,000 vCPU-seconds, 360,000 GiB-seconds
and 2 million requests, and it applies in Mumbai. The scheduler sends about 8,000 requests a month,
each a fraction of a second. Cloud Scheduler gives 3 jobs free; this uses 1. Expect **₹0 to a few
tens of rupees a month** for one person. Set a budget alert at ₹200 so nothing surprises you.

## Deploy (about 15 minutes, first time)

1. Install the gcloud CLI: https://cloud.google.com/sdk/docs/install, then `gcloud auth login`.
2. Pick or create a project with billing on. Note its project ID.
3. From the `paper-trader` folder:
   ```bash
   bash deploy/deploy.sh YOUR_PROJECT_ID
   ```
   It asks you to choose an app password (12+ characters) and prints your web address.
4. Upstox: on https://account.upstox.com/developer/apps, set your app's redirect URL to
   `https://YOUR-ADDRESS/upstox/callback` (the script prints it). Then open the app > Settings >
   Upstox and log in. If you also want the Mac version to log in, create a second Upstox app for it,
   since each app has one redirect URL.
5. On your phone: open the address, log in, then Share > **Add to Home Screen**.

To update after a change: run the same command again. Your trades stay in the bucket.

## Safety notes

- The password screen is the only lock on the app. Use a long, unique password.
- Your Upstox key and secret live in the private bucket. Anyone with access to your Google Cloud
  project can read them, so don't share the project.
- The app only reads prices from Upstox. It cannot place, change or cancel real orders.
