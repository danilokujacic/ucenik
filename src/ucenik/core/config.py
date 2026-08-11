from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": this app and the LLM proxy (llm_proxy/config.py's
    # ProxySettings, which already sets the same thing) intentionally share
    # one .env file - each only declares the fields it cares about. Without
    # this, any non-empty proxy-only value (GROQ_API_KEY, and even
    # .env.example's own non-empty GROQ_MODEL/GROQ_BASE_URL defaults) makes
    # pydantic-settings' default extra="forbid" reject the whole file at
    # import time - a real crash anyone copying .env.example to .env would
    # hit immediately, found by actually loading Settings() against a real
    # filled-in .env rather than assuming the template was safe.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # "development" or "production" - gates Swagger/ReDoc (see main.py:
    # roadmap §17, "protect/disable /docs"). Defaults to "production" (docs
    # disabled) on purpose - fail closed, not open: an env someone forgot to
    # set should hide docs, not expose them. Local dev sets this explicitly
    # in .env (see .env.example).
    environment: str = "production"

    jwt_secret: str
    jwt_access_token_expire_minutes: int = 10
    jwt_refresh_token_expire_days: int = 7
    max_quota: int  # LLM tokens per user per UTC day - see core/quota.py
    redis_url: str

    mongodb_url: str
    mongodb_db_name: str = "ucenik"

    # CORS - the origin(s) the browser frontend is served from. Comma-
    # separated for multiple (e.g. local dev + a deployed preview URL).
    # No CORS middleware without this - see core/config.py usage in main.py.
    frontend_url: str = "http://localhost:3000"

    @property
    def cors_allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_url.split(",") if origin.strip()]

    @property
    def docs_enabled(self) -> bool:
        return self.environment != "production"

    # The self-hosted LLM proxy - a real service now (src/ucenik/llm_proxy/,
    # Groq-backed), not a placeholder. OpenAI-compatible contract (POST
    # {llm_proxy_url}/chat/completions, Bearer auth) - see llm/proxy_client.py.
    # llm_proxy_model is advisory only: the proxy always overrides it with
    # its own configured model, never trusts what a caller sends.
    llm_proxy_url: str = "http://localhost:4000"
    llm_proxy_api_key: str = ""
    llm_proxy_model: str = "gpt-4o-mini"
    llm_proxy_timeout_seconds: float = 30.0

    # MinIO (S3-compatible), local via docker-compose
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "documents"
    s3_region: str = "us-east-1"  # required by the S3 API shape; MinIO ignores the actual value

    # Chroma
    chroma_host: str = "localhost"
    chroma_port: int = 8000

    # Embedding - BGE-M3 (multilingual). Switched from Arctic Embed v2: that
    # model's custom code crashed (RoPE indexing bug) on this stack even
    # after working around its trust_remote_code and xformers requirements -
    # a real upstream incompatibility, not a config issue. BGE-M3 is a
    # standard transformers architecture, no custom code needed at all.
    #
    # embedding_model here is only for rag/chunker.py's tokenizer (sizing
    # chunks in tokens) - a lightweight artifact, not the full model with
    # weights. The full model itself is loaded exactly once, by the
    # self-hosted embedding service (src/ucenik/embedding_service/), not by
    # this app or the Celery worker directly - see rag/embedder.py, which
    # is an HTTP client to that service now, same shape as llm/proxy_client.py
    # relates to llm_proxy. Loading BGE-M3 (~2.3GB, CPU-only inference) in
    # both `app` and `worker` independently - two separate OS processes,
    # each with its own model singleton - would double that cost for zero
    # benefit; the embedding service exists specifically to avoid that.
    embedding_model: str = "BAAI/bge-m3"
    embedding_max_tokens: int = 8192  # confirmed from the loaded model
    embedding_service_url: str = "http://localhost:4001"
    embedding_service_api_key: str = ""
    embedding_service_timeout_seconds: float = 60.0  # CPU-only inference - generous vs. an LLM call's timeout

    # Chunking - sized in tokens using the embedding model's own tokenizer
    # (token-accurate, not a char-count approximation - matters across
    # languages/scripts). Deliberately much smaller than embedding_max_tokens:
    # chunk size is chosen for retrieval-quality reasons (one coherent idea
    # per chunk), not because of a tight token ceiling - there's now plenty
    # of headroom under embedding_max_tokens for the contextual-retrieval
    # blurb that gets prepended before embedding.
    chunk_size: int = 400
    chunk_overlap: int = 50

    # Rate limiting (core/rate_limit.py) - disabled in tests (see
    # tests/conftest.py) since a global per-IP limit would otherwise trip
    # against the test suite's own rapid-fire requests from one IP.
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 120
    rate_limit_login_requests_per_minute: int = 10


settings = Settings()
