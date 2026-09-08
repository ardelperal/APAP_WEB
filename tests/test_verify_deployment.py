"""Tests for the post-deployment revision verifier."""

from __future__ import annotations

import httpx
import pytest

from scripts.verify_deployment import wait_for_revision


def test_wait_for_revision_retries_until_expected_build_is_live() -> None:
    revisions = iter(["old", "wanted"])
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "ok", "revision": next(revisions)},
        )

    body = wait_for_revision(
        "https://example.test/healthz",
        "wanted",
        attempts=2,
        interval_seconds=0.25,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )

    assert body["revision"] == "wanted"
    assert sleeps == [0.25]


def test_wait_for_revision_fails_closed_after_retry_budget() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"status": "ok", "revision": "old"})
    )

    with pytest.raises(RuntimeError, match="expected 'wanted'"):
        wait_for_revision(
            "https://example.test/healthz",
            "wanted",
            attempts=2,
            interval_seconds=0,
            transport=transport,
            sleep=lambda _: None,
        )
