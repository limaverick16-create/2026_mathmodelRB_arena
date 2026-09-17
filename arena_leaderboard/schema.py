"""Compatibility imports for the encrypted leaderboard schema.

Schema v1 plaintext submissions are intentionally unsupported.
"""

from .schema_v2 import (
    SubmissionError,
    account_hash,
    build_encrypted_submission,
    canonical_json,
    category_for,
    prepare_submission,
    validate_decrypted_submission,
    validate_public_submission,
    write_submission,
)

validate_submission = validate_public_submission

__all__ = [
    "SubmissionError",
    "account_hash",
    "build_encrypted_submission",
    "canonical_json",
    "category_for",
    "prepare_submission",
    "validate_decrypted_submission",
    "validate_public_submission",
    "validate_submission",
    "write_submission",
]
