from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    trusted_proxy_hops: int = Field(default=1, alias="TRUSTED_PROXY_HOPS")

    # --- database ---
    # APP_DATABASE_URL: the app/workers connect as the non-owner RLS-bound role.
    # MIGRATOR_DATABASE_URL: alembic connects as the schema-owning role.
    app_database_url: str = Field(alias="APP_DATABASE_URL")
    migrator_database_url: str = Field(alias="MIGRATOR_DATABASE_URL")

    # --- redis / celery ---
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://localhost:6379/1", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(
        default="redis://localhost:6379/2", alias="CELERY_RESULT_BACKEND"
    )

    # --- object storage ---
    s3_endpoint: str = Field(alias="S3_ENDPOINT")
    # Browser-facing host for presigned URLs (drawing downloads) -- same
    # internal/public split as keycloak_base_url/keycloak_public_url above.
    # `s3_endpoint` (e.g. "http://seaweedfs:8333") only resolves inside the
    # compose network; a presigned URL handed to a real browser must be
    # signed against a host it can actually reach. Found while building
    # Phase 8b's PDF viewer -- see docs/module-frontend-phase8b-plan.md.
    s3_public_endpoint: str = Field(default="http://localhost:8333", alias="S3_PUBLIC_ENDPOINT")
    s3_access_key: str = Field(default="", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="", alias="S3_SECRET_KEY")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_bucket_drawings: str = Field(default="installtec-drawings", alias="S3_BUCKET_DRAWINGS")
    s3_force_path_style: bool = Field(default=True, alias="S3_FORCE_PATH_STYLE")

    # --- ai ---
    vllm_api_base: str = Field(alias="VLLM_API_BASE")
    vllm_model: str = Field(default="Qwen/Qwen2.5-VL-7B-Instruct", alias="VLLM_MODEL")
    vllm_api_key: str = Field(default="not-needed", alias="VLLM_API_KEY")
    vllm_timeout_s: float = Field(default=120, alias="VLLM_TIMEOUT_S")
    embedding_backend: str = Field(default="onnx", alias="EMBEDDING_BACKEND")
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=384, alias="EMBEDDING_DIM")
    onnx_model_dir: str = Field(default="/models", alias="ONNX_MODEL_DIR")

    # --- identity ---
    keycloak_base_url: str = Field(default="http://keycloak:8080", alias="KEYCLOAK_BASE_URL")
    keycloak_public_url: str = Field(
        default="http://localhost:8080", alias="KEYCLOAK_PUBLIC_URL"
    )
    keycloak_realm: str = Field(default="installtec", alias="KEYCLOAK_REALM")
    keycloak_client_id: str = Field(default="installtec-backend", alias="KEYCLOAK_CLIENT_ID")
    keycloak_client_secret: str = Field(default="", alias="KEYCLOAK_CLIENT_SECRET")
    keycloak_audience: str = Field(default="installtec-backend", alias="KEYCLOAK_AUDIENCE")
    jwks_cache_ttl_s: int = Field(default=600, alias="JWKS_CACHE_TTL_S")
    jwt_leeway_s: int = Field(default=30, alias="LEEWAY_S")
    required_acr_for_approval: str = Field(default="silver", alias="REQUIRED_ACR_FOR_APPROVAL")
    # A still-valid session/token can carry acr=silver long after the OTP
    # entry that earned it -- Keycloak's own realm-installtec.json Level 2
    # flow subflow (fix/keycloak-step-up) re-checks its own loa-max-age=300
    # before letting a NEW authentication reach silver, but a refresh_token
    # grant on an EXISTING silver session just re-mints an access token that
    # still says acr=silver, auth_time unchanged, no matter how old that
    # auth_time gets. app/security/deps.py::has_recent_step_up re-checks
    # auth_time against this independently for exactly that reason. Matches
    # Keycloak's own loa-max-age for the same acr level by default.
    step_up_max_age_s: int = Field(default=300, alias="STEP_UP_MAX_AGE_S")

    # --- session / cookies ---
    session_secret: str = Field(default="", alias="SESSION_SECRET")
    cookie_secure: bool = Field(default=True, alias="COOKIE_SECURE")
    cookie_domain: str = Field(default="localhost", alias="COOKIE_DOMAIN")
    session_ttl_s: int = Field(default=28800, alias="SESSION_TTL_S")
    csrf_header: str = Field(default="X-CSRF-Token", alias="CSRF_HEADER")

    # --- audit ---
    audit_all_reads: bool = Field(default=False, alias="AUDIT_ALL_READS")
    audit_checkpoint_hmac_key: str = Field(default="", alias="AUDIT_CHECKPOINT_HMAC_KEY")

    # --- tenancy ---
    demo_tenant_id: str = Field(
        default="8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00", alias="DEMO_TENANT_ID"
    )

    # --- takeoff ---
    takeoff_persist_geometry: bool = Field(default=False, alias="TAKEOFF_PERSIST_GEOMETRY")
    max_upload_size_bytes: int = Field(default=50 * 1024 * 1024, alias="MAX_UPLOAD_SIZE_BYTES")

    # --- procurement (Module C1: RFQ generation & dispatch) ---
    s3_bucket_procurement: str = Field(default="installtec-procurement", alias="S3_BUCKET_PROCUREMENT")
    smtp_host: str = Field(default="localhost", alias="SMTP_HOST")
    smtp_port: int = Field(default=1025, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_use_tls: bool = Field(default=False, alias="SMTP_USE_TLS")
    smtp_from_address: str = Field(default="procurement@installtec.local", alias="SMTP_FROM_ADDRESS")
    # Reply-To uses plus-addressing (`{local}+{rfq_token}@{domain}`) so a
    # reply lands in one shared mailbox that C2's IMAP poller can match back
    # to the originating Rfq row deterministically, without depending on
    # In-Reply-To/References survivng every vendor's mail client/forward.
    email_reply_to_local_part: str = Field(default="rfq", alias="EMAIL_REPLY_TO_LOCAL_PART")
    email_reply_to_domain: str = Field(default="installtec.local", alias="EMAIL_REPLY_TO_DOMAIN")
    # Safety net (not just a Mailpit default): whenever app_env != "production",
    # every outbound RFQ email is sent to this single address instead of the
    # vendor's real one, regardless of what SMTP_HOST points at -- see
    # app/procurement/mailer.py::resolve_recipient. Required (fails closed)
    # in every non-production environment; ignored in production.
    email_redirect_all_to: str = Field(default="", alias="EMAIL_REDIRECT_ALL_TO")

    # --- procurement (Module C2: inbound quotation ingestion) ---
    # IMAP mailbox polled for vendor replies (see
    # app/workers/tasks/quotation_ingestion.py::poll_inbound_mailbox). The
    # tenant a message belongs to is identified from the plus-addressed
    # recipient embedded in the message's own To: header
    # (app/procurement/inbound_address.py), not from which literal mailbox
    # it landed in -- this one shared mailbox receives replies for every
    # tenant, mirroring a real provider (Gmail/Office365/Postfix with
    # recipient_delimiter=+) that folds `local+ext@domain` into `local@domain`
    # before final delivery.
    imap_host: str = Field(default="localhost", alias="IMAP_HOST")
    imap_port: int = Field(default=993, alias="IMAP_PORT")
    imap_use_ssl: bool = Field(default=True, alias="IMAP_USE_SSL")
    imap_user: str = Field(default="", alias="IMAP_USER")
    imap_password: str = Field(default="", alias="IMAP_PASSWORD")
    imap_mailbox: str = Field(default="INBOX", alias="IMAP_MAILBOX")
    # Safety net symmetric to email_redirect_all_to/resolve_recipient, but for
    # the inbound direction: whenever app_env != "production", IMAP_HOST must
    # equal this value or the poller refuses to start (see
    # app/workers/tasks/quotation_ingestion.py::_assert_dev_imap_host_is_safe).
    # Better to refuse to poll than risk a dev/test worker draining a real
    # mailbox. Default points at the GreenMail dev/test IMAP server (Mailpit
    # has no IMAP server -- verified; see docs/procurement-quotation-ingestion.md).
    imap_dev_allowed_host: str = Field(default="greenmail", alias="IMAP_DEV_ALLOWED_HOST")
    quotation_max_attachment_size_bytes: int = Field(
        default=15 * 1024 * 1024, alias="QUOTATION_MAX_ATTACHMENT_SIZE_BYTES"
    )
    quotation_max_pdf_pages: int = Field(default=60, alias="QUOTATION_MAX_PDF_PAGES")

    @field_validator("vllm_api_base")
    @classmethod
    def _assert_vllm_is_private(cls, v: str) -> str:
        """Zero-external-cloud-dependency guardrail (SRS §1.1): refuse to boot
        against a public internet host for the AI inference base URL."""
        host = urlparse(v).hostname or ""
        public_giveaways = ("openai.com", "anthropic.com", "googleapis.com", "azure.com")
        if any(host.endswith(suffix) for suffix in public_giveaways):
            raise ValueError(
                f"VLLM_API_BASE host '{host}' looks like a commercial external AI API; "
                "this platform must only call a self-hosted vLLM instance."
            )
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
