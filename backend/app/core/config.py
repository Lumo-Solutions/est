from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
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
    # External AI provider layer (docs/ai-plan.md). TEMPORARY, knowing
    # reversal of SRS §1.1: unset AI_PROVIDER keeps the self-hosted vLLM
    # path above exactly as before. Switching back is config only.
    ai_provider: str = Field(default="local_vllm", alias="AI_PROVIDER")
    ai_model: str = Field(default="", alias="AI_MODEL")
    ai_model_classify: str = Field(default="", alias="AI_MODEL_CLASSIFY")
    ai_model_vision: str = Field(default="", alias="AI_MODEL_VISION")
    ai_model_reasoning: str = Field(default="", alias="AI_MODEL_REASONING")
    ai_api_key: SecretStr = Field(default=SecretStr(""), alias="AI_API_KEY")
    ai_base_url: str = Field(default="", alias="AI_BASE_URL")
    ai_timeout_s: float = Field(default=120, alias="AI_TIMEOUT_S")
    ai_max_retries: int = Field(default=3, alias="AI_MAX_RETRIES")
    ai_monthly_budget_usd: float | None = Field(default=None, alias="AI_MONTHLY_BUDGET_USD")
    ai_project_budget_usd: float | None = Field(default=None, alias="AI_PROJECT_BUDGET_USD")
    ai_rate_limit_per_min: int = Field(default=120, alias="AI_RATE_LIMIT_PER_MIN")
    # Celery worker hygiene (see app/workers/celery_app.py): recycle a child after this many tasks / this much memory (KiB).
    celery_max_tasks_per_child: int = Field(default=50, alias="CELERY_MAX_TASKS_PER_CHILD")
    celery_max_memory_per_child_kb: int = Field(default=700_000, alias="CELERY_MAX_MEMORY_PER_CHILD_KB")
    ai_stale_rate_months: int = Field(default=12, alias="AI_STALE_RATE_MONTHS")
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
    # DEV/TEST ONLY switch that turns MFA off: deploy/keycloak/bootstrap.sh
    # drops the login OTP, and app/security/deps.py::has_recent_step_up
    # passes without a step-up. Honoured only when APP_ENV is exactly "dev" or
    # "test" (see mfa_bypass_active); anywhere else, setting it true makes the
    # settings fail to load, so the backend and workers refuse to start
    # rather than silently running with MFA off.
    dev_disable_mfa: bool = Field(default=False, alias="DEV_DISABLE_MFA")

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
    # How long a drawing may sit in indexing/extracting/embedding with no
    # status change before app.workers.tasks.maintenance.reap_stuck_drawings
    # (celery-beat, hourly) treats it as abandoned (e.g. a worker crash mid-
    # chord) and resolves it to failed/partial itself -- see
    # docs/takeoff-pipeline.md. Independent of any single task's own
    # soft_time_limit/max_retries; this is the drawing-level backstop.
    drawing_stuck_timeout_s: int = Field(default=7200, alias="DRAWING_STUCK_TIMEOUT_S")

    # --- DWG conversion (ODA File Converter sandbox, docs/takeoff-pipeline.md) ---
    # Tri-state: unset/empty = auto (on when the converter container's
    # heartbeat is present), true = on (a missing converter still parks the
    # drawing in needs_conversion with a reason, never a 500), false = off.
    dwg_conversion_enabled: bool | None = Field(default=None, alias="DWG_CONVERSION_ENABLED")
    dwg_spool_dir: str = Field(default="/spool", alias="DWG_SPOOL_DIR")
    # Per-file wall-clock limit. Enforced inside the converter container
    # (process-group kill); the worker waits this + a grace period.
    dwg_convert_timeout_s: int = Field(default=120, alias="DWG_CONVERT_TIMEOUT_S")
    dwg_target_version: str = Field(default="ACAD2018", alias="DWG_TARGET_VERSION")
    dwg_heartbeat_max_age_s: int = Field(default=30, alias="DWG_HEARTBEAT_MAX_AGE_S")

    @field_validator("dwg_conversion_enabled", mode="before")
    @classmethod
    def _blank_dwg_flag_is_auto(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

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

    # --- tender document intake (docs/tender-intake-plan.md, docs/intake-scale/report.md) ---
    # Upload: a file larger than this is refused at registration. A file above `intake_max_process_bytes` is stored
    # but not read by the worker: it lands in "Needs your check: too large" for a person to classify.
    intake_max_file_size_bytes: int = Field(default=250 * 1024 * 1024, alias="INTAKE_MAX_FILE_SIZE_BYTES")
    intake_max_process_bytes: int = Field(default=40 * 1024 * 1024, alias="INTAKE_MAX_PROCESS_BYTES")
    # The legacy multipart endpoints (small packs, scripts) buffer their files; these keep that bounded.
    intake_max_request_bytes: int = Field(default=100 * 1024 * 1024, alias="INTAKE_MAX_REQUEST_BYTES")
    intake_max_files_per_request: int = Field(default=50, alias="INTAKE_MAX_FILES_PER_REQUEST")
    # A pack (one upload) may hold at most this many files; the registration says so clearly when it would not fit.
    intake_max_files_per_pack: int = Field(default=3_000, alias="INTAKE_MAX_FILES_PER_PACK")
    # Files per registration request of the resumable upload.
    intake_register_batch: int = Field(default=500, alias="INTAKE_REGISTER_BATCH")
    # The streaming upload buffers at most one part of this size per request (S3 multipart).
    intake_upload_part_bytes: int = Field(default=8 * 1024 * 1024, alias="INTAKE_UPLOAD_PART_BYTES")
    # A streamed upload that sends nothing for this long is abandoned (a closed tab or a dropped network leaves a
    # half-open connection that would otherwise hold a database connection and a transaction forever).
    intake_upload_idle_s: int = Field(default=60, alias="INTAKE_UPLOAD_IDLE_S")
    intake_max_pdf_pages: int = Field(default=800, alias="INTAKE_MAX_PDF_PAGES")
    intake_zip_max_entries: int = Field(default=1_000, alias="INTAKE_ZIP_MAX_ENTRIES")
    intake_zip_max_total_bytes: int = Field(default=250 * 1024 * 1024, alias="INTAKE_ZIP_MAX_TOTAL_BYTES")
    intake_zip_max_ratio: int = Field(default=100, alias="INTAKE_ZIP_MAX_RATIO")
    intake_zip_max_depth: int = Field(default=2, alias="INTAKE_ZIP_MAX_DEPTH")
    # Per-document processing budget inside the worker (checked between stages).
    intake_doc_timeout_s: int = Field(default=60, alias="INTAKE_DOC_TIMEOUT_S")
    # One Celery task per file: soft limit (the file is parked as "needs check") and hard limit (the child is killed).
    intake_task_soft_limit_s: int = Field(default=240, alias="INTAKE_TASK_SOFT_LIMIT_S")
    intake_task_hard_limit_s: int = Field(default=300, alias="INTAKE_TASK_HARD_LIMIT_S")
    # Stage 1 winner at or above this (and not conflicted) skips the model.
    intake_rules_confident: float = Field(default=0.85, alias="INTAKE_RULES_CONFIDENT")
    # Bulk-confirm only takes proposals at or above this.
    intake_bulk_confirm_min: float = Field(default=0.85, alias="INTAKE_BULK_CONFIRM_MIN")
    # Documents confirmed per request by a filter-based bulk confirm / reclassify (the UI repeats until done).
    intake_bulk_chunk: int = Field(default=100, alias="INTAKE_BULK_CHUNK")
    # AI calls: at most this many at a time inside one worker process; rate limiting itself is AI_RATE_LIMIT_PER_MIN.
    intake_ai_concurrency: int = Field(default=2, alias="INTAKE_AI_CONCURRENCY")
    # A rate-limited call waits for the next minute window and retries this many times before the file falls back to rules.
    intake_ai_rate_limit_retries: int = Field(default=6, alias="INTAKE_AI_RATE_LIMIT_RETRIES")
    # This many AI failures in a row (no success between) open the breaker for `intake_ai_breaker_s`: rules decide.
    intake_ai_max_consecutive_failures: int = Field(default=3, alias="INTAKE_AI_MAX_CONSECUTIVE_FAILURES")
    intake_ai_breaker_s: int = Field(default=120, alias="INTAKE_AI_BREAKER_S")
    # Dispatch: files are enqueued from the database, never more than this many queued or running at once.
    intake_dispatch_limit: int = Field(default=40, alias="INTAKE_DISPATCH_LIMIT")
    # A file queued this long ago without starting is enqueued again (the broker lost it).
    intake_requeue_after_s: int = Field(default=600, alias="INTAKE_REQUEUE_AFTER_S")
    # A file in `processing` this long without a heartbeat is treated as abandoned by a dead worker.
    intake_stuck_after_s: int = Field(default=360, alias="INTAKE_STUCK_AFTER_S")
    intake_max_attempts: int = Field(default=3, alias="INTAKE_MAX_ATTEMPTS")
    # The drawing pipeline's page index (one task per drawing): a PDF that takes longer than this is marked failed with a
    # reason ("split it"), and the child is killed at the hard limit, instead of starving the worker.
    drawing_index_soft_limit_s: int = Field(default=300, alias="DRAWING_INDEX_SOFT_LIMIT_S")
    drawing_index_hard_limit_s: int = Field(default=360, alias="DRAWING_INDEX_HARD_LIMIT_S")
    # PDF page images made for the drawing pipeline (VLM) are capped at this longest side, in pixels.
    pdf_render_max_px: int = Field(default=5000, alias="PDF_RENDER_MAX_PX")

    # Set (alongside a literal APP_ENV=production) only by
    # deploy/docker-compose.prod.yml, for backend/every worker/beat.
    # Deliberately a separate flag from app_env itself, not a check that
    # app_env == "production" unconditionally: everywhere else (a bare
    # `docker compose up`, a dev/test run, this Settings() class's own
    # default) app_env is allowed to be "dev"/unset/anything, so the check
    # below has to be conditioned on *intending* to run in production, or
    # it would either wrongly refuse every non-prod boot or be able to
    # verify nothing at all. Real defense-in-depth: catches e.g. someone
    # invoking `docker compose -f docker-compose.prod.yml run -e
    # APP_ENV=dev backend` for a one-off debug session against the prod
    # compose file and leaving it running -- production_mode still says
    # "this deployment must be real production", app_env says otherwise,
    # and the mismatch fails the whole Settings() construction closed
    # rather than silently booting a production deployment in dev mode
    # (weaker CORS/cookie/audit defaults elsewhere keyed off app_env).
    production_mode: bool = Field(default=False, alias="PRODUCTION_MODE")

    @model_validator(mode="after")
    def _refuse_production_mode_without_app_env_production(self) -> Settings:
        """Same fail-closed pattern as _refuse_mfa_bypass_outside_dev_test
        below: raising here makes Settings() itself refuse to construct, so
        the backend, every Celery worker and beat (all call get_settings()
        at import/startup) refuse to start rather than silently running a
        production deployment with a non-production APP_ENV."""
        if self.production_mode and self.app_env != "production":
            raise ValueError(
                f"PRODUCTION_MODE=true requires APP_ENV=production (APP_ENV={self.app_env!r}); "
                "refusing to start."
            )
        return self

    @model_validator(mode="after")
    def _refuse_mfa_bypass_outside_dev_test(self) -> Settings:
        """Fail closed: DEV_DISABLE_MFA=true is only legal when APP_ENV was
        explicitly set to exactly "dev" or "test". app_env's own default is
        "dev", so an unset APP_ENV is checked via model_fields_set rather
        than taken at face value."""
        if self.dev_disable_mfa and not _app_env_allows_mfa_bypass(self):
            raise ValueError(
                "DEV_DISABLE_MFA=true is only allowed with APP_ENV explicitly set to 'dev' or 'test' "
                f"(APP_ENV={self.app_env!r}, explicitly set: {'app_env' in self.model_fields_set}); "
                "refusing to start with MFA disabled."
            )
        return self

    @field_validator("ai_monthly_budget_usd", "ai_project_budget_usd", mode="before")
    @classmethod
    def _blank_budget_is_unlimited(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("ai_provider", mode="before")
    @classmethod
    def _blank_provider_is_local(cls, v: object) -> object:
        return "local_vllm" if isinstance(v, str) and not v.strip() else v

    @field_validator("ai_provider")
    @classmethod
    def _assert_known_ai_provider(cls, v: str) -> str:
        v = (v or "local_vllm").strip().lower()
        if v not in ("local_vllm", "anthropic", "openai_compatible", "mock"):
            raise ValueError(
                f"AI_PROVIDER={v!r} is not one of local_vllm, anthropic, openai_compatible, mock"
            )
        return v

    @field_validator("ai_base_url")
    @classmethod
    def _assert_ai_base_url_is_https(cls, v: str) -> str:
        """An external AI endpoint carries tenant data: refuse plain http
        except to a loopback/compose-internal host (mock servers in tests)."""
        v = (v or "").strip()
        if not v:
            return v
        parsed = urlparse(v)
        internal = (parsed.hostname or "") in ("localhost", "127.0.0.1", "host.docker.internal") or "." not in (
            parsed.hostname or ""
        )
        if parsed.scheme != "https" and not internal:
            raise ValueError("AI_BASE_URL must be https:// for a non-internal host")
        return v

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


def _app_env_allows_mfa_bypass(settings: Settings) -> bool:
    return "app_env" in settings.model_fields_set and settings.app_env in ("dev", "test")


def mfa_bypass_active(settings: Settings) -> bool:
    """True only when DEV_DISABLE_MFA=true AND APP_ENV is exactly dev/test.
    The single definition shared by has_recent_step_up, /auth/me (the
    frontend's "DEV: MFA disabled" banner) and the startup validator."""
    return settings.dev_disable_mfa and _app_env_allows_mfa_bypass(settings)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
