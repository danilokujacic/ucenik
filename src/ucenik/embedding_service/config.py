from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbeddingServiceSettings(BaseSettings):
    """Own settings object, deliberately separate from ucenik.core.config's
    Settings - same reasoning as llm_proxy/config.py's ProxySettings: this
    is a standalone process (own container, own port) with its own narrow
    set of concerns. Reads the same .env file the main app does, so shared
    values (EMBEDDING_MODEL) stay in sync without duplicating them.
    """

    # extra="ignore": same reasoning as llm_proxy/config.py's ProxySettings
    # - this service's .env is the same file the main app reads, this
    # settings object only cares about its own few fields.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Which model to actually load - same default as ucenik.core.config's
    # embedding_model (that setting stays there too, unrelated purpose:
    # rag/chunker.py needs this model's *tokenizer* to size chunks, which
    # is a separate, much lighter thing than this service loading the full
    # model with weights).
    embedding_model: str = "BAAI/bge-m3"

    # Shared secret this service requires from callers - same pattern as
    # llm_proxy/config.py's llm_proxy_api_key (and llm/proxy_client.py's
    # matching behavior): empty disables auth entirely, fine for local dev.
    # This service has no `ports:` in docker-compose.prod.yaml either way -
    # never reachable from outside the docker network there.
    embedding_service_api_key: str = ""


embedding_service_settings = EmbeddingServiceSettings()
