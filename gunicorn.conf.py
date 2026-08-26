# Gunicorn configuration for Render (free tier has limited memory).
# Recycle workers periodically to avoid memory leaks / OOM kills, and allow
# slow first requests after idle sleep.

import os

# One worker on the free tier to stay within memory limits.
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
threads = int(os.environ.get("WEB_THREADS", "1"))

# Recycle each worker after N requests to release leaked memory.
max_requests = 200
max_requests_jitter = 50

# Generous timeout so slow AI/email calls don't kill workers.
timeout = 120
graceful_timeout = 30

# Forward proxy headers (Render sits behind a proxy).
forwarded_allow_ips = "*"
