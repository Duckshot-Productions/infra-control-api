-- Events table for logging all system events
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    data JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_created_at ON events(created_at DESC);
CREATE INDEX idx_events_data ON events USING GIN(data);

-- Scraper jobs table
CREATE TABLE IF NOT EXISTS scraper_jobs (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(255) UNIQUE NOT NULL,
    target VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'queued',
    priority INTEGER DEFAULT 5,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    result JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_scraper_jobs_status ON scraper_jobs(status);
CREATE INDEX idx_scraper_jobs_target ON scraper_jobs(target);
CREATE INDEX idx_scraper_jobs_created_at ON scraper_jobs(created_at DESC);

-- MCP tool executions table
CREATE TABLE IF NOT EXISTS mcp_executions (
    id SERIAL PRIMARY KEY,
    tool_name VARCHAR(200) NOT NULL,
    arguments JSONB NOT NULL,
    llm_provider VARCHAR(50) NOT NULL,
    result JSONB,
    usage JSONB,
    cost DECIMAL(10, 6) DEFAULT 0,
    duration_ms INTEGER,
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_mcp_executions_tool ON mcp_executions(tool_name);
CREATE INDEX idx_mcp_executions_provider ON mcp_executions(llm_provider);
CREATE INDEX idx_mcp_executions_created_at ON mcp_executions(created_at DESC);

-- LLM usage tracking for cost analysis
CREATE TABLE IF NOT EXISTS llm_usage (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(50) NOT NULL,
    model VARCHAR(100),
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    cost DECIMAL(10, 6) DEFAULT 0,
    context VARCHAR(200),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_llm_usage_provider ON llm_usage(provider);
CREATE INDEX idx_llm_usage_created_at ON llm_usage(created_at DESC);

-- Create view for daily cost rollup
CREATE OR REPLACE VIEW daily_llm_costs AS
SELECT 
    DATE(created_at) as date,
    provider,
    COUNT(*) as request_count,
    SUM(total_tokens) as total_tokens,
    SUM(cost) as total_cost
FROM llm_usage
GROUP BY DATE(created_at), provider
ORDER BY date DESC, provider;
