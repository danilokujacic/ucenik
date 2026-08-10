from pydantic_settings import BaseSettings, SettingsConfigDict


class ProxySettings(BaseSettings):
    """Own settings object, deliberately separate from ucenik.core.config's
    Settings - this service is a standalone process (own container, own
    port) with its own concerns (the real Groq credentials) that the main
    app must never see. Reads the same .env file the main app does (both
    get the same env_file in docker-compose.prod.yaml), so shared values
    (LLM_PROXY_API_KEY) stay in sync without duplicating them.
    """

    # extra="ignore": this service's .env is the same file the main app
    # reads (MONGODB_URL, JWT_SECRET, ...) - this settings object only
    # cares about its own few fields, so pydantic-settings' default
    # extra="forbid" would otherwise reject the file outright.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # The one secret only the user can provide - see .env.example.
    groq_api_key: str = ""

    # Fallback upstream - only tried if the Hugging Face request fails
    # (network error or non-2xx status), see main.py's _upstreams(). Unlike
    # hf_api_key, there's no "disabled" state for this one - groq_api_key is
    # assumed always configured, so Groq is always the last resort. Groq's
    # model lineup moves fast; verify against
    # https://console.groq.com/docs/models before relying on this in
    # production rather than trusting this default indefinitely.
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Primary upstream - tried first, see main.py's _upstreams(). Optional:
    # an empty hf_api_key skips it entirely, falling back to Groq-only
    # behavior (same as before this existed). Uses Hugging Face's
    # OpenAI-compatible Inference Providers router
    # (https://huggingface.co/docs/inference-providers) - verify the model's
    # still routed there before relying on the default.
    hf_api_key: str = ""
    hf_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    hf_base_url: str = "https://router.huggingface.co/v1"

    # Shared secret this service requires from callers - same env var name
    # and same value as the main app's LLM_PROXY_API_KEY (core/config.py),
    # both read from one .env. Empty = auth disabled, matching
    # llm/proxy_client.py's own behavior of omitting the Authorization
    # header entirely when its LLM_PROXY_API_KEY is empty - fine for local
    # dev, set a real value for anything reachable beyond localhost.
    llm_proxy_api_key: str = ""


proxy_settings = ProxySettings()
