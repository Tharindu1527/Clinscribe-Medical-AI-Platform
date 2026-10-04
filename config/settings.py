"""Typed settings for every ClinScribe service, loaded from `.env`.

Secrets are `SecretStr`, so they never appear in `repr`, logs or JSON dumps.
Every field must have a matching key in `.env.example` (enforced by tests/unit/test_settings.py).
URLs are host-side defaults; docker-compose overrides them with in-network service names.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # LLM providers (free tiers), reached only through the gateway
    gemini_api_key: SecretStr = SecretStr("")
    groq_api_key: SecretStr = SecretStr("")
    openrouter_api_key: SecretStr = SecretStr("")
    ollama_api_base: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.2:3b"

    # Gateway
    litellm_master_key: SecretStr = SecretStr("")
    litellm_salt_key: SecretStr = SecretStr("")
    litellm_app_key: SecretStr = SecretStr("")
    gateway_url: str = "http://localhost:4000"

    # Postgres (databases: clinscribe, litellm, hapi)
    postgres_user: str = "clinscribe"
    postgres_password: SecretStr = SecretStr("")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    app_db_password: SecretStr = SecretStr("")
    litellm_db_password: SecretStr = SecretStr("")
    hapi_db_password: SecretStr = SecretStr("")

    # FHIR
    fhir_base_url: str = "http://localhost:8080/fhir"
    synthea_population: int = 50
    synthea_seed: int = 42

    # Privacy and audit
    deid_url: str = "http://localhost:8001"
    deid_mapping_key: SecretStr = SecretStr("")
    audit_chain_key: SecretStr = SecretStr("")

    # Observability
    langfuse_public_key: SecretStr = SecretStr("")
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_host: str = "https://cloud.langfuse.com"
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"

    # Chaos switches
    chaos_primary_down: bool = False


def get_settings() -> Settings:
    return Settings()
