#!/usr/bin/env python3
"""Background worker for processing scraper jobs from Redis queue"""

import os
import json
import time
import sys
from datetime import datetime
import redis
import psycopg2
from psycopg2.extras import RealDictCursor
import subprocess

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DB_URL = os.getenv("DATABASE_URL")
SCRAPER_BASE_PATH = os.getenv("SCRAPER_BASE_PATH", "/opt/scrapers")

redis_client = redis.from_url(REDIS_URL)

def get_db():
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)

def update_job_status(job_id: str, status: str, **kwargs):
    """Update job status in both Redis and PostgreSQL"""
    # Update Redis for real-time status
    status_data = {
        "job_id": job_id,
        "status": status,
        "updated_at": datetime.utcnow().isoformat(),
        **kwargs
    }
    
    target = kwargs.get("target", "unknown")
    redis_client.setex(
        f"scraper:status:{target}",
        3600,  # 1 hour TTL
        json.dumps(status_data)
    )
    
    # Update PostgreSQL for persistence
    conn = get_db()
    cur = conn.cursor()
    
    update_fields = ["status = %s"]
    update_values = [status]
    
    if status == "running" and "started_at" not in kwargs:
        update_fields.append("started_at = NOW()")
    if status in ["completed", "failed"]:
        update_fields.append("completed_at = NOW()")
    if "error_message" in kwargs:
        update_fields.append("error_message = %s")
        update_values.append(kwargs["error_message"])
    if "result" in kwargs:
        update_fields.append("result = %s")
        update_values.append(json.dumps(kwargs["result"]))
    
    update_values.append(job_id)
    
    cur.execute(
        f"UPDATE scraper_jobs SET {', '.join(update_fields)} WHERE job_id = %s",
        update_values
    )
    conn.commit()
    cur.close()
    conn.close()

def execute_scraper(target: str, job_id: str) -> dict:
    """Execute scraper for given target"""
    scraper_script = os.path.join(SCRAPER_BASE_PATH, f"{target}.py")
    
    if not os.path.exists(scraper_script):
        raise FileNotFoundError(f"Scraper script not found: {scraper_script}")
    
    # Execute scraper with timeout
    result = subprocess.run(
        ["python3", scraper_script, "--job-id", job_id],
        capture_output=True,
        text=True,
        timeout=3600  # 1 hour max
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"Scraper failed: {result.stderr}")
    
    # Parse output as JSON (assume scraper returns JSON)
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        output = {"raw_output": result.stdout}
    
    return output

def process_job(job_data: dict):
    """Process a single scraper job"""
    job_id = job_data["job_id"]
    target = job_data["target"]
    
    print(f"[{datetime.utcnow().isoformat()}] Processing job {job_id} for target {target}")
    
    try:
        update_job_status(job_id, "running", target=target)
        
        result = execute_scraper(target, job_id)
        
        update_job_status(
            job_id,
            "completed",
            target=target,
            result=result
        )
        
        print(f"[{datetime.utcnow().isoformat()}] Job {job_id} completed successfully")
        
    except Exception as e:
        print(f"[{datetime.utcnow().isoformat()}] Job {job_id} failed: {e}")
        update_job_status(
            job_id,
            "failed",
            target=target,
            error_message=str(e)
        )

def main():
    """Main worker loop"""
    print(f"[{datetime.utcnow().isoformat()}] Scraper worker started")
    
    while True:
        try:
            # Blocking pop from Redis queue (5 second timeout)
            job_data = redis_client.blpop("queue:scrapers", timeout=5)
            
            if job_data:
                _, job_json = job_data
                job = json.loads(job_json)
                process_job(job)
            
        except KeyboardInterrupt:
            print("\nWorker stopped by user")
            break
        except Exception as e:
            print(f"[{datetime.utcnow().isoformat()}] Worker error: {e}")
            time.sleep(5)  # Wait before retrying

if __name__ == "__main__":
    main()
