"""
server.py — Flask entry point.

Security:  webhook_security.verify_webhook() — HMAC, replay, rate limit
Threading: thread_pool.dispatch()           — bounded pool, queue cap
Health:    /ping (public), /health (auth-gated detail)
"""

import logging
import os
import time
import traceback
from dotenv import load_dotenv
load_dotenv()


from flask import Flask, jsonify, render_template, request

from app.core.idempotency  import is_duplicate, make_fingerprint
from app.core.metrics      import metrics
from app.core.redis_client import is_redis_available
from app.core.thread_pool  import dispatch, pool_stats
from app.core.webhook_security import verify_webhook, startup_check

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("server")

app = Flask(__name__,
            template_folder='app/templates',
            static_folder='app/static')

METRICS_TOKEN = os.environ.get("METRICS_AUTH_TOKEN", "")
START_TIME    = time.time()
VERSION       = "4.2.0"


# ── Routes ─────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", version=VERSION)


@app.route("/dashboard", methods=["GET"])
def dashboard():
    return render_template("dashboard.html", version=VERSION)


@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    """Public dashboard data endpoint — safe to call without auth."""
    import time as _time

    try:
        from app.core.health_check import get_system_health
        health = get_system_health()
    except Exception:
        health = _mock_health()

    try:
        metrics_data = metrics.snapshot()
    except Exception:
        metrics_data = _mock_metrics()

    try:
        from app.core.thread_pool import pool_stats
        pool = pool_stats()
    except Exception:
        pool = {"max_workers": 6, "pending_tasks": 0, "queue_capacity": 50, "saturation_pct": 0.0}

    try:
        from app.github.rate_limit import get_status as _gh_rl
        gh_rate = _gh_rl()
    except Exception:
        gh_rate = {"remaining": 5000, "resets_in": 3600, "low": False}

    try:
        from app.github.auth import APP_ID
        app_id = str(APP_ID) if APP_ID else "not configured"
    except Exception:
        app_id = os.environ.get("GITHUB_APP_ID", "not configured")

    total  = metrics_data.get("events.total", 0)
    errors = metrics_data.get("events.error", 0)
    success_rate = round((total - errors) / max(total, 1) * 100, 1)

    event_types = {
        et: {
            "queued":  metrics_data.get(f"events.{et}.queued", 0),
            "success": metrics_data.get(f"events.{et}.success", 0),
            "error":   metrics_data.get(f"events.{et}.error", 0),
        }
        for et in ("pull_request", "issues", "issue_comment", "push", "check_run")
    }

    return jsonify({
        "status":         health.get("status", "ok"),
        "is_degraded":    health.get("is_degraded", False),
        "version":        VERSION,
        "uptime_seconds": metrics_data.get("uptime_seconds", int(_time.time() - START_TIME)),
        "uptime_human":   metrics_data.get("uptime_human", "—"),
        "github_app_id":  app_id,
        "providers":      health.get("providers", {}),
        "github_api":     health.get("github_api", gh_rate),
        "redis":          health.get("redis", {"connected": is_redis_available()}),
        "thread_pool":    pool,
        "metrics": {
            "events_total":       total,
            "events_error":       errors,
            "success_rate_pct":   success_rate,
            "webhook_received":   metrics_data.get("webhook.received", 0),
            "webhook_duplicates": metrics_data.get("webhook.duplicate_skipped", 0),
            "events_dropped":     metrics_data.get("events.dropped", 0),
        },
        "event_types":    event_types,
        "generated_at":   int(_time.time()),
    })


@app.route("/api/events/recent", methods=["GET"])
def api_events_recent():
    """Returns last 20 webhook events stored in Redis."""
    try:
        import json as _json
        from app.core.redis_client import get_redis
        r = get_redis()
        raw = r.lrange("webhook:events:recent", 0, 19)
        events = []
        for item in raw:
            try:
                events.append(_json.loads(item))
            except Exception:
                pass
        return jsonify({"events": events, "count": len(events)})
    except Exception:
        return jsonify({"events": _mock_events(), "count": 4})


# ── Mock data helpers (used when env vars not configured) ──────────────────

def _mock_health() -> dict:
    return {
        "status": "ok",
        "is_degraded": False,
        "providers": {
            "groq_70b":   {"state": "closed",    "is_degraded": False, "avg_latency_ms": 1100, "error_rate": 0.0},
            "groq_8b":    {"state": "closed",    "is_degraded": False, "avg_latency_ms": 450,  "error_rate": 0.0},
            "gemini":     {"state": "closed",    "is_degraded": False, "avg_latency_ms": 800,  "error_rate": 0.0},
            "openrouter": {"state": "half_open", "is_degraded": True,  "avg_latency_ms": 2200, "error_rate": 0.1},
        },
        "github_api": {"remaining": 4823, "resets_in": 2340, "is_healthy": True},
        "redis": {"connected": False},
        "checked_at": int(time.time()),
    }


def _mock_metrics() -> dict:
    return {
        "uptime_seconds": int(time.time() - START_TIME),
        "uptime_human": _format_uptime(int(time.time() - START_TIME)),
        "webhook.received": 42,
        "events.total": 38,
        "events.pull_request.queued": 14, "events.pull_request.success": 13, "events.pull_request.error": 1,
        "events.issues.queued": 11, "events.issues.success": 11, "events.issues.error": 0,
        "events.push.queued": 9, "events.push.success": 9, "events.push.error": 0,
        "events.issue_comment.queued": 4, "events.issue_comment.success": 4, "events.issue_comment.error": 0,
        "events.check_run.queued": 0, "events.check_run.success": 0, "events.check_run.error": 0,
        "webhook.duplicate_skipped": 3,
        "events.error": 1,
        "events.dropped": 0,
    }


def _mock_events() -> list:
    now = int(time.time())
    return [
        {"event": "pull_request",  "repo": "acme/webapp",  "delivery_id": "a1b2c3d4", "timestamp": now - 120,  "status": "accepted"},
        {"event": "issues",        "repo": "acme/api",     "delivery_id": "e5f6g7h8", "timestamp": now - 340,  "status": "accepted"},
        {"event": "push",          "repo": "acme/webapp",  "delivery_id": "i9j0k1l2", "timestamp": now - 600,  "status": "accepted"},
        {"event": "issue_comment", "repo": "acme/docs",    "delivery_id": "m3n4o5p6", "timestamp": now - 900,  "status": "accepted"},
    ]


def _format_uptime(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}h {m}m {s}s"


@app.route("/ping", methods=["GET"])
def ping():
    """Public liveness probe. Returns minimal response — no internal info."""
    return jsonify({"status": "ok", "version": VERSION}), 200


@app.route("/health", methods=["GET"])
def health():
    """
    Detailed health. Auth-gated when METRICS_AUTH_TOKEN is set.
    Use /ping for Render health checks (no auth needed).
    """
    if METRICS_TOKEN:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {METRICS_TOKEN}":
            return jsonify({"error": "Unauthorized"}), 401

    from app.ai.circuit_breaker import status_all
    from app.github.rate_limit  import get_status as gh_rl_status

    redis_ok       = is_redis_available()
    gh_ok          = gh_rl_status().get("remaining", 5000) > 50
    breaker_status = status_all()
    any_llm_ok     = any(s["state"] == "closed" for s in breaker_status.values())
    overall        = "ok" if (gh_ok and any_llm_ok) else "degraded"

    return jsonify({
        "status":         overall,
        "version":        VERSION,
        "uptime_seconds": int(time.time() - START_TIME),
        "checks": {
            "redis":         "ok" if redis_ok else "unavailable",
            "github_api":    "ok" if gh_ok    else "rate_limited",
            "llm_providers": breaker_status,
        },
        "thread_pool": pool_stats(),
        "metrics": {
            "events_total": metrics.get("events.total", 0),
            "errors_total": metrics.get("events.error", 0),
        },
    }), 200 if overall == "ok" else 207


@app.route("/metrics", methods=["GET"])
def get_metrics():
    if METRICS_TOKEN:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {METRICS_TOKEN}":
            return jsonify({"error": "Unauthorized"}), 401
    return jsonify(metrics.snapshot())


@app.route("/test-discord", methods=["POST"])
def test_discord():
    if os.environ.get("FLASK_ENV") == "production":
        return jsonify({"error": "Not available in production"}), 403
    from app.github.notifications import test_discord as _test
    success, message = _test()
    return jsonify({"success": success, "message": message}), 200 if success else 500




@app.route("/mcp", methods=["POST"])
def mcp_endpoint():
    """MCP (Model Context Protocol) endpoint for IDE integrations."""
    from app.mcp.mcp_server import handle_mcp_request

    auth  = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""

    try:
        body = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": {"code": -32700, "message": "Parse error"}}), 400

    resp, status = handle_mcp_request(
        body.get("method", ""), body.get("params", {}), token
    )
    return jsonify(resp), status


@app.route("/mcp", methods=["GET"])
def mcp_info():
    """MCP server discovery endpoint."""
    return jsonify({
        "name":        "github-autopilot",
        "version":     VERSION,
        "protocol":    "mcp/2024-11-05",
        "tools":       8,
        "description": "AI-powered GitHub repository assistant",
        "auth":        "Bearer token via MCP_API_KEY env var",
        "docs":        "https://github.com/Shweta-Mishra-ai/github-autopilot/blob/main/docs/mcp-setup.md",
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    # Full security pipeline: size + IP rate limit + HMAC + replay
    ok, err = verify_webhook(request)
    if not ok:
        status = 429 if "Too many" in err else 413 if "large" in err else 401
        log.warning(f"webhook.rejected reason={err!r}")
        return jsonify({"error": err}), status

    # Parse JSON
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    webhook_event = request.headers.get("X-GitHub-Event", "")
    delivery_id   = request.headers.get("X-GitHub-Delivery", "")
    repo = payload.get("repository", {}).get("full_name", "unknown")

    # Bot loop prevention
    from app.core.webhook_security import is_bot_sender
    if is_bot_sender(payload):
        return jsonify({"status": "skipped — bot sender"}), 200

    log.info(
        f"webhook.received event={webhook_event} repo={repo} "
        f"delivery={delivery_id[:8] if delivery_id else 'none'}"
    )
    metrics.increment("webhook.received")

    # Idempotency — deduplicate retries
    fingerprint = make_fingerprint(delivery_id, webhook_event, payload)
    if is_duplicate(fingerprint):
        metrics.increment("webhook.duplicate_skipped")
        return jsonify({"status": "duplicate — skipped"}), 200

    # Dispatch to bounded pool — ACK immediately
    _dispatch(webhook_event, payload, repo)
    metrics.increment(f"events.{webhook_event}.queued")
    metrics.increment("events.total")

    # Store event summary for dashboard /api/events/recent
    try:
        import json as _json
        from app.core.redis_client import get_redis as _get_redis
        _r = _get_redis()
        _evt = _json.dumps({
            "event":       webhook_event,
            "repo":        repo,
            "delivery_id": delivery_id[:8] if delivery_id else "",
            "timestamp":   int(time.time()),
            "status":      "accepted",
        })
        _r.lpush("webhook:events:recent", _evt)
        _r.ltrim("webhook:events:recent", 0, 49)
        _r.expire("webhook:events:recent", 86400)
    except Exception:
        pass

    return jsonify({"status": "accepted"}), 202


# ── Dispatch ───────────────────────────────────────────────────────────────

def _run_handler(webhook_event: str, payload: dict, repo: str):
    """Runs inside the thread pool. All errors caught — never crashes pool."""
    try:
        log.info(f"dispatch.start event={webhook_event} repo={repo}")

        if webhook_event == "pull_request":
            from app.handlers.pull_request import handle
            handle(payload)

        elif webhook_event == "issues":
            from app.handlers.issues import handle
            handle(payload)

        elif webhook_event == "issue_comment":
            from app.handlers.comments import handle
            handle(payload)

        elif webhook_event == "push":
            from app.handlers.push import handle
            handle(payload)

        elif webhook_event == "check_run":
            try:
                from app.handlers.ci import handle
                handle(payload)
            except ImportError:
                log.debug("ci handler not available — skipping")

        else:
            log.debug(f"dispatch.unhandled event={webhook_event}")
            return

        metrics.increment(f"events.{webhook_event}.success")
        log.info(f"dispatch.done event={webhook_event}")

    except Exception as e:
        log.error(f"dispatch.error event={webhook_event} repo={repo}: {e}")
        log.error(traceback.format_exc())
        metrics.increment(f"events.{webhook_event}.error")


def _dispatch(webhook_event: str, payload: dict, repo: str):
    result = dispatch(_run_handler, webhook_event, payload, repo)
    if result is None:
        log.error(
            f"dispatch.dropped event={webhook_event} repo={repo} "
            "— pool saturated"
        )
        metrics.increment("events.dropped")


# ── Boot ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    startup_check()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
else:
    # Running via gunicorn — validate on import
    startup_check()
