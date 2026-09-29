"""Test-side import path for the synthetic tender pack; the generator lives in app/intake/sample_pack.py
so the dev stack can write it out for the real-backend Playwright spec."""

from app.intake.sample_pack import (  # noqa: F401
    ARCHIVE,
    CLASSIFIABLE,
    DUPLICATE,
    REJECTED,
    PackFile,
    build_pack,
    build_zip_member_files,
    ground_truth,
)


def __getattr__(name: str):
    if name == "GROUND_TRUTH":
        return ground_truth()
    raise AttributeError(name)
