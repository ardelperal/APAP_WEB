"""Strict-TDD contract atoms for operator-proven PR4a storage evidence."""

from __future__ import annotations

import json
from pathlib import Path

from migration.storage_spike import (
    PINNED_DOWNLOAD_STRATEGY_ENDPOINT,
    build_pinned_operator_evidence_result,
    write_discovery_document,
)


def test_pinned_download_contract_distinguishes_strategy_auth_from_presigned_url() -> None:
    """Strategy requires bearer auth; returned presigned URL authenticates itself."""
    evidence = build_pinned_operator_evidence_result().to_machine_dict()

    assert evidence["pr4b_gate"] == "PASS"
    assert evidence["status"] == "supported"
    assert evidence["canonical_endpoint"] == PINNED_DOWNLOAD_STRATEGY_ENDPOINT
    assert evidence["strategy_status_code"] == 200
    assert evidence["strategy_without_auth_status_code"] == 401
    assert evidence["strategy_body_shape"] == {
        "expiresAt": "str",
        "method": "str",
        "url": "url",
    }
    assert evidence["strategy_without_auth_body_shape"] == {
        "error": "str",
        "message": "str",
        "nextActions": "list",
        "statusCode": "int",
    }
    assert evidence["required_auth_header"] == "Authorization: Bearer <service_key>"
    assert evidence["download_method"] == "presigned"
    assert evidence["returned_url"] == "<redacted-url>"
    assert evidence["returned_url_auth"] == "self-authenticating"
    assert evidence["returned_url_exposure"] == "server-stream-only"
    assert evidence["object_head"] == {
        "with_auth_status": 200,
        "without_auth_status": 200,
    }


def test_pinned_upload_contract_is_three_step_s3_with_required_confirmation() -> None:
    """PR4b must implement strategy → transfer-by-fields → confirmation."""
    evidence = build_pinned_operator_evidence_result().to_machine_dict()

    assert evidence["upload_contract"] == {
        "protocol": "s3-compatible",
        "strategy_fields_present": True,
        "confirm_required": True,
        "transfer_method_rule": "POST when fields present; PUT when fields absent",
        "confirm_status_code": 201,
        "steps": [
            "request_upload_strategy",
            "transfer_object",
            "confirm_upload",
        ],
    }


def test_pinned_cleanup_contract_restores_empty_private_bucket() -> None:
    """Operator evidence proves reversible sentinel cleanup with no leftovers."""
    evidence = build_pinned_operator_evidence_result().to_machine_dict()

    assert evidence["bucket"] == {
        "bucket_name": "apap-photos",
        "is_public": False,
    }
    assert evidence["cleanup"] == {
        "sentinel_delete_status_code": 200,
        "post_list_object_count": 0,
        "post_list_total": 0,
        "success": True,
        "leftovers": False,
    }


def test_pinned_evidence_is_deterministic_redacted_and_renders_pass_doc(
    tmp_path: Path,
) -> None:
    """Only shapes/categories/hash are persisted; no presigned URL or body values."""
    first = build_pinned_operator_evidence_result()
    second = build_pinned_operator_evidence_result()
    output = tmp_path / "storage-contract-2026-Q3.md"

    write_discovery_document(first, output)

    evidence = first.to_machine_dict()
    serialized = json.dumps(evidence, sort_keys=True)
    text = output.read_text(encoding="utf-8")
    assert first.evidence_hash == second.evidence_hash
    assert first.to_machine_dict() == second.to_machine_dict()
    assert len(first.evidence_hash) == 64
    assert "Verdict: PASS" in text
    assert "PR4b gate: PASS" in text
    assert f"Canonical endpoint: `{PINNED_DOWNLOAD_STRATEGY_ENDPOINT}`" in text
    assert "Authorization: Bearer <service_key>" in text
    assert "Agent-side probe remains GET/HEAD-only" in text
    assert "Operator-supplied reversible sentinel evidence" in text
    assert "S3-compatible three-step upload" in text
    assert "confirmRequired=true" in text
    assert "confirm status 201" in text
    assert "cleanup restored object_count=0 and total=0" in text
    assert "expiresIn=3600" not in text
    assert "server-stream-only" in text
    assert "MUST NOT be exposed to browser/client" in text
    assert first.evidence_hash in text
    assert "https://" not in serialized
    assert "https://" not in text
    assert "presigned-secret" not in serialized
    assert "presigned-secret" not in text
