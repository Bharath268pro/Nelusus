"""Configuration management for NexusMCP Gateway - Production Grade"""

from pydantic_settings import BaseSettings
from typing import Optional
import logging


class Settings(BaseSettings):
    """NexusMCP Gateway application settings loaded from environment variables."""

    # ========== Application Core ==========
    environment: str = "development"
    debug: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    service_name: str = "nexusmcp-gateway"
    service_version: str = "1.0.0"

    # ========== JWT/RS256 Authentication ==========
    jwt_algorithm: str = "RS256"
    jwks_uri: str  # URL to fetch public keys
    jwks_cache_ttl_seconds: int = 3600
    jwt_issuer: str  # Expected issuer claim
    jwt_audience: str  # Expected audience claim
    jwt_leeway_seconds: int = 30  # Clock skew tolerance

    # ========== OAuth2/Authlib ==========
    oauth2_client_id: str
    oauth2_client_secret: str
    oauth2_provider_url: str
    oauth2_token_endpoint: str
    oauth2_authorize_endpoint: str
    oauth2_jwks_endpoint: str

    # ========== Redis Cache Layer ==========
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    redis_ssl: bool = False
    redis_max_connections: int = 50
    redis_timeout_seconds: int = 5

    # Redis cache TTLs by type (seconds)
    redis_jwks_ttl: int = 3600  # 1 hour
    redis_token_ttl: int = 1800  # 30 minutes
    redis_tool_schema_ttl: int = 7200  # 2 hours
    redis_rls_policy_ttl: int = 3600  # 1 hour
    redis_scope_mapping_ttl: int = 7200  # 2 hours

    # ========== DynamoDB Configuration ==========
    dynamodb_region: str = "us-east-1"
    dynamodb_endpoint_url: Optional[str] = None  # For local dev
    dynamodb_table_tools: str = "nexusmcp-tools"
    dynamodb_table_rls_policies: str = "nexusmcp-rls-policies"
    dynamodb_table_scope_mappings: str = "nexusmcp-scope-mappings"
    dynamodb_table_audit_logs: str = "nexusmcp-audit-logs"

    # ========== Connector Registry ==========
    tool_registry_cache_enabled: bool = True
    tool_registry_refresh_interval_seconds: int = 300  # 5 minutes
    tool_namespace_pattern: str = r"^[a-z_]+\.[a-z_]+$"  # e.g., salesforce.query_opportunities

    # ========== JWT Token Validation ==========
    required_scopes_prefix: str = "nexusmcp"
    scope_separator: str = ":"

    # ========== RLS (Row-Level Security) ==========
    rls_cache_enabled: bool = True
    rls_policy_evaluation_timeout_ms: int = 1000
    rls_deny_by_default: bool = True

    # ========== Observability - OpenTelemetry ==========
    otel_enabled: bool = True
    otel_service_name: str = "nexusmcp-gateway"
    otel_environment: str = "production"
    otel_exporter_type: str = "xray"  # xray, otlp, jaeger
    otel_exporter_otlp_endpoint: Optional[str] = None
    otel_sampler_rate: float = 1.0  # 100% for now
    otel_trace_propagation_format: str = "tracecontext"  # W3C standard

    # X-Ray specific
    xray_enabled: bool = True
    xray_sdk_enabled: bool = True
    xray_context_missing: str = "LOG_ERROR"
    xray_daemon_address: str = "127.0.0.1:2000"

    # ========== Structured Logging ==========
    log_level: str = "INFO"
    log_format: str = "json"  # json or text
    log_include_request_body: bool = False
    log_include_response_body: bool = False

    # ========== Request ID & Correlation ==========
    request_id_header: str = "X-Request-ID"
    trace_id_header: str = "X-Trace-ID"
    correlation_id_header: str = "X-Correlation-ID"

    # ========== Security - TLS/mTLS ==========
    tls_enabled: bool = False
    tls_cert_path: Optional[str] = None
    tls_key_path: Optional[str] = None
    tls_ca_bundle_path: Optional[str] = None
    mtls_enabled: bool = False
    mtls_client_cert_required: bool = False

    # ========== CORS Configuration ==========
    cors_enabled: bool = True
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8080"]
    cors_credentials: bool = True
    cors_allow_methods: list[str] = ["GET", "POST", "OPTIONS"]
    cors_allow_headers: list[str] = ["*"]
    cors_expose_headers: list[str] = ["X-Request-ID", "X-Trace-ID"]

    # ========== Rate Limiting & Throttling ==========
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 1000
    rate_limit_burst_size: int = 100

    # ========== Salesforce Connector (Phase 2+) ==========
    salesforce_client_id: str = ""
    salesforce_client_secret: str = ""
    salesforce_instance_url: str = ""
    salesforce_oauth_endpoint: str = ""

    # ========== Database (for future phases) ==========
    database_url: str = "postgresql://user:password@localhost:5432/nexusmcp"
    database_pool_size: int = 20
    database_pool_pre_ping: bool = True

    # ========== AWS Secrets Manager (future) ==========
    aws_secrets_manager_enabled: bool = False
    aws_region: str = "us-east-1"
    aws_secret_arn: str = ""

    # ========== Timeouts & Connection Pools ==========
    http_client_timeout_seconds: int = 30
    http_pool_connections: int = 100
    http_pool_maxsize: int = 100

    # ========== JSON-RPC Configuration ==========
    jsonrpc_batch_request_max_size: int = 100
    jsonrpc_request_timeout_seconds: int = 30
    jsonrpc_max_request_body_size: int = 1048576  # 1MB

    # ========== SSE (Server-Sent Events) Configuration ==========
    sse_enabled: bool = True
    sse_heartbeat_interval_seconds: int = 30
    sse_max_connections: int = 1000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings singleton
settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create the global settings instance."""
    global settings
    if settings is None:
        settings = Settings()
    return settings


def configure_logging(cfg: Settings) -> logging.Logger:
    """Configure structured logging with the chosen format."""
    log_level = getattr(logging, cfg.log_level.upper(), logging.INFO)
    
    if cfg.log_format == "json":
        import json
        import logging.handlers
        
        class JSONFormatter(logging.Formatter):
            def format(self, record):
                log_obj = {
                    "timestamp": self.formatTime(record),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                    "service": cfg.service_name,
                }
                if record.exc_info:
                    log_obj["exception"] = self.formatException(record.exc_info)
                return json.dumps(log_obj)
        
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
    else:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
    
    logger = logging.getLogger(cfg.service_name)
    logger.setLevel(log_level)
    logger.addHandler(handler)
    return logger


# Global settings instance
settings = Settings()
