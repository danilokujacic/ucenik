from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    jwt_secret: str
    jwt_access_token_expire_minutes: int = 10
    jwt_refresh_token_expire_days: int = 7
    max_quota: int
    redis_url: str

    mongodb_url: str
    mongodb_db_name: str = "ucenik"

    # TODO: placeholder values - the self-hosted proxy isn't built/running yet.
    # Assumed OpenAI-compatible contract (POST {llm_proxy_url}/chat/completions,
    # Bearer auth). Fill in real values once it exists; see llm/proxy_client.py.
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
    embedding_model: str = "BAAI/bge-m3"
    embedding_max_tokens: int = 8192  # confirmed from the loaded model

    # Chunking - sized in tokens using the embedding model's own tokenizer
    # (token-accurate, not a char-count approximation - matters across
    # languages/scripts). Deliberately much smaller than embedding_max_tokens:
    # chunk size is chosen for retrieval-quality reasons (one coherent idea
    # per chunk), not because of a tight token ceiling - there's now plenty
    # of headroom under embedding_max_tokens for the contextual-retrieval
    # blurb that gets prepended before embedding.
    chunk_size: int = 400
    chunk_overlap: int = 50


settings = Settings()
