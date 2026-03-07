#!/usr/bin/env python3
"""Infra Control API - VPS listener for orchestrating scrapers, MCP tools, and dual LLM routing"""

import os
import json
import subprocess
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from functools import wraps

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import redis
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
CORS(app, origins=os.getenv("ALLOWED_ORIGINS", "*").split(","))

# Config
CONTROL_TOKEN = os.getenv("CONTROL_TOKEN")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DB_URL = os.getenv("DATABASE_URL")
QWEN_LOCAL_URL = os.getenv("QWEN_LOCAL_URL", "http://localhost:8080/v1")
QWEN_CLOUD_URL = os.getenv("QWEN_CLOUD_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
QWEN_API_KEY = os.getenv("QWEN_API_KEY")

# Redis client for job queue
redis_client = redis.from_url(REDIS_URL)

def get_db():
    """Get PostgreSQL connection"""
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)

def require_auth(f):
    """Auth decorator"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if token != CONTROL_TOKEN:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

def log_event(event_type: str, data: Dict[str, Any]):
    """Log event to DB and Redis"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO events (event_type, data, created_at) 
               VALUES (%s, %s, %s)""",
            (event_type, json.dumps(data), datetime.utcnow())
        )
        conn.commit()
        cur.close()
        conn.close()
        
        # Also push to Redis for real-time monitoring
        redis_client.lpush("events:recent", json.dumps({
            "type": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }))
        redis_client.ltrim("events:recent", 0, 99)  # Keep last 100
    except Exception as e:
        app.logger.error(f"Failed to log event: {e}")

# ============================================================================
# DUAL LLM ROUTING LOGIC
# ============================================================================

def route_llm_request(prompt: str, preference: str = "auto", max_tokens: int = 4096) -> Dict[str, Any]:
    """Route LLM request to Qwen (local/cloud) or Gemini based on load and preference"""
    
    # Check local Qwen availability and load
    local_available = False
    local_load = 100.0
    try:
        health_resp = subprocess.run(
            ["curl", "-s", f"{QWEN_LOCAL_URL}/health"],
            capture_output=True, text=True, timeout=2
        )
        if health_resp.returncode == 0:
            local_available = True
            # Parse load from health endpoint (assume it returns {"load": 0.45})
            health_data = json.loads(health_resp.stdout)
            local_load = health_data.get("load", 0.5)
    except:
        pass
    
    # Routing decision
    if preference == "qwen-local" and local_available:
        return _call_qwen_local(prompt, max_tokens)
    elif preference == "qwen-cloud":
        return _call_qwen_cloud(prompt, max_tokens)
    elif preference == "gemini":
        return _call_gemini(prompt, max_tokens)
    else:  # auto
        # Route to local if load < 70%, otherwise cloud
        if local_available and local_load < 0.7:
            return _call_qwen_local(prompt, max_tokens)
        else:
            return _call_qwen_cloud(prompt, max_tokens)

def _call_qwen_local(prompt: str, max_tokens: int) -> Dict[str, Any]:
    """Call local Qwen instance via llama.cpp server"""
    import requests
    resp = requests.post(
        f"{QWEN_LOCAL_URL}/chat/completions",
        json={
            "model": "qwen",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.7
        },
        timeout=120
    )
    resp.raise_for_status()
    result = resp.json()
    return {
        "provider": "qwen-local",
        "content": result["choices"][0]["message"]["content"],
        "usage": result.get("usage", {}),
        "cost": 0.0  # Local is free
    }

def _call_qwen_cloud(prompt: str, max_tokens: int) -> Dict[str, Any]:
    """Call Qwen cloud API"""
    import requests
    resp = requests.post(
        f"{QWEN_CLOUD_URL}/chat/completions",
        headers={"Authorization": f"Bearer {QWEN_API_KEY}"},
        json={
            "model": "qwen-max",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens
        },
        timeout=120
    )
    resp.raise_for_status()
    result = resp.json()
    usage = result.get("usage", {})
    # Rough cost estimate (example pricing)
    cost = (usage.get("prompt_tokens", 0) * 0.000002) + (usage.get("completion_tokens", 0) * 0.000006)
    return {
        "provider": "qwen-cloud",
        "content": result["choices"][0]["message"]["content"],
        "usage": usage,
        "cost": cost
    }

def _call_gemini(prompt: str, max_tokens: int) -> Dict[str, Any]:
    """Call Gemini API"""
    import requests
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_API_KEY}",
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens}
        },
        timeout=120
    )
    resp.raise_for_status()
    result = resp.json()
    content = result["candidates"][0]["content"]["parts"][0]["text"]
    usage = result.get("usageMetadata", {})
    cost = (usage.get("promptTokenCount", 0) * 0.000001) + (usage.get("candidatesTokenCount", 0) * 0.000003)
    return {
        "provider": "gemini",
        "content": content,
        "usage": usage,
        "cost": cost
    }

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.route("/health", methods=["GET"])
def health():
    """Health check"""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "redis": redis_client.ping(),
            "db": bool(get_db())
        }
    })

@app.route("/run-scraper", methods=["POST"])
@require_auth
def run_scraper():
    """Trigger scraper job"""
    data = request.json
    target = data.get("target", "all")
    priority = data.get("priority", 5)
    
    job_id = f"scraper:{target}:{int(time.time())}"
    
    # Queue job in Redis
    redis_client.rpush("queue:scrapers", json.dumps({
        "job_id": job_id,
        "target": target,
        "priority": priority,
        "queued_at": datetime.utcnow().isoformat()
    }))
    
    log_event("scraper_queued", {"job_id": job_id, "target": target})
    
    return jsonify({
        "status": "queued",
        "job_id": job_id,
        "target": target,
        "position": redis_client.llen("queue:scrapers")
    })

@app.route("/scraper-status/<target>", methods=["GET"])
@require_auth
def scraper_status(target):
    """Get scraper status"""
    status_key = f"scraper:status:{target}"
    status_data = redis_client.get(status_key)
    
    if not status_data:
        return jsonify({"status": "unknown", "target": target}), 404
    
    return jsonify(json.loads(status_data))

@app.route("/query-state", methods=["POST"])
@require_auth
def query_state():
    """Get current system state"""
    # Get recent jobs from Redis
    recent_events = redis_client.lrange("events:recent", 0, 19)
    events = [json.loads(e) for e in recent_events]
    
    # Get active scrapers
    active_scrapers = []
    for key in redis_client.scan_iter("scraper:status:*"):
        data = json.loads(redis_client.get(key))
        if data.get("status") == "running":
            active_scrapers.append(data)
    
    # Get queue depth
    queue_depth = redis_client.llen("queue:scrapers")
    
    return jsonify({
        "timestamp": datetime.utcnow().isoformat(),
        "active_scrapers": active_scrapers,
        "queue_depth": queue_depth,
        "recent_events": events
    })

@app.route("/execute-mcp", methods=["POST"])
@require_auth
def execute_mcp():
    """Execute MCP tool with dual LLM routing"""
    data = request.json
    tool_name = data.get("tool")
    arguments = data.get("arguments", {})
    llm_preference = data.get("llm_preference", "auto")
    
    if not tool_name:
        return jsonify({"error": "tool name required"}), 400
    
    # Build prompt for LLM to execute tool
    prompt = f"""Execute the MCP tool '{tool_name}' with these arguments:
{json.dumps(arguments, indent=2)}

Return a JSON response with the tool execution result."""
    
    try:
        llm_result = route_llm_request(prompt, llm_preference, max_tokens=8192)
        
        log_event("mcp_executed", {
            "tool": tool_name,
            "provider": llm_result["provider"],
            "cost": llm_result["cost"]
        })
        
        return jsonify({
            "status": "success",
            "tool": tool_name,
            "result": llm_result["content"],
            "provider": llm_result["provider"],
            "usage": llm_result["usage"],
            "cost": llm_result["cost"]
        })
    except Exception as e:
        log_event("mcp_failed", {"tool": tool_name, "error": str(e)})
        return jsonify({
            "status": "error",
            "tool": tool_name,
            "error": str(e)
        }), 500

@app.route("/admin/restart", methods=["POST"])
@require_auth
def admin_restart():
    """Restart the service (via systemd)"""
    try:
        subprocess.run(["sudo", "systemctl", "restart", "infra-control-api"], check=True)
        return jsonify({"status": "restarting"})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Only listen on Tailscale interface
    tailscale_ip = os.getenv("TAILSCALE_IP", "127.0.0.1")
    app.run(host=tailscale_ip, port=5000, debug=False)
