"""Unit tests for product-agnostic licensing (Polar, Paddle, Offline, Sandbox)."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import urllib.error
from pathlib import Path

import memory_os.core.licensing as licensing_mod
from memory_os.core.licensing import (
    LicenseConfig,
    LicenseManager,
    OfflineTokenProvider,
    issue_offline_token,
)


def _cfg(tmp_path: Path, **kwargs) -> LicenseConfig:
    defaults = {
        "product_slug": "memory_os",
        "env_prefix": "TEST_MOS",
        "storage_path": tmp_path / "license.json",
    }
    defaults.update(kwargs)
    return LicenseConfig(**defaults)


def test_default_core_tier_without_key(tmp_path: Path):
    mgr = LicenseManager(_cfg(tmp_path))
    status = mgr.verify()

    assert status.valid is True
    assert status.tier == "core"
    assert status.has_feature("local_memory") is True
    assert status.has_feature("ci_pr_gate") is False


def test_sandbox_provider_activates_and_persists(tmp_path: Path):
    cfg = _cfg(tmp_path, sandbox=True)
    mgr = LicenseManager(cfg)

    status = mgr.activate("SANDBOX-TEAM-001")
    assert status.valid is True
    assert status.tier == "team"
    assert status.provider == "sandbox"
    assert status.has_feature("ci_pr_gate") is True
    assert status.has_feature("unlimited_seats") is True

    # Reload from persisted license.json
    reloaded = LicenseManager(cfg).verify()
    assert reloaded.valid is True
    assert reloaded.tier == "team"

    assert mgr.deactivate() is True
    assert LicenseManager(cfg).verify().tier == "core"


def test_sandbox_key_rejected_when_sandbox_disabled(tmp_path: Path):
    mgr = LicenseManager(_cfg(tmp_path, sandbox=False))
    status = mgr.verify(key="SANDBOX-PRO-123")
    assert status.valid is False
    assert status.tier == "core"


def test_offline_token_verification_and_product_isolation(tmp_path: Path):
    secret = "unit-test-signing-secret"
    token = issue_offline_token(
        product_slug="acme_cli",
        tier="enterprise",
        secret=secret,
        expires_at="2099-01-01T00:00:00Z",
    )

    # Valid for matching product_slug ("acme_cli")
    acme_mgr = LicenseManager(_cfg(tmp_path, product_slug="acme_cli", offline_signing_secret=secret))
    ok = acme_mgr.verify(key=token)
    assert ok.valid is True
    assert ok.tier == "enterprise"
    assert ok.has_feature("offline_airgap") is True

    # Rejected for different product_slug ("memory_os")
    mos_mgr = LicenseManager(_cfg(tmp_path, product_slug="memory_os", offline_signing_secret=secret))
    mismatch = mos_mgr.verify(key=token)
    assert mismatch.valid is False
    assert "product mismatch" in mismatch.detail

    # Expired token rejected
    expired = issue_offline_token(
        product_slug="acme_cli",
        tier="pro",
        secret=secret,
        expires_at="2020-01-01T00:00:00Z",
    )
    assert acme_mgr.verify(key=expired).valid is False


def test_polar_provider_validation_and_offline_grace_cache(tmp_path: Path):
    calls = []

    def fake_http(method, url, headers, payload, timeout):
        calls.append((method, url, payload))
        return 200, {
            "status": "granted",
            "expires_at": "2099-12-31T00:00:00Z",
            "benefit": {"description": "Memory OS Team CI Gate"},
        }

    cfg = _cfg(tmp_path, polar_organization_id="org_123", sandbox=True)
    mgr = LicenseManager(cfg, http_request=fake_http)
    status = mgr.activate("POLAR-KEY-XYZ")

    assert status.valid is True
    assert status.tier == "team"
    assert status.provider == "polar"
    assert "sandbox-api.polar.sh" in calls[0][1]

    # Simulate network outage -> offline grace cache keeps CI/CLI working
    def failing_http(method, url, headers, payload, timeout):
        raise urllib.error.URLError("offline")

    offline_mgr = LicenseManager(cfg, http_request=failing_http)
    cached = offline_mgr.verify()
    assert cached.valid is True
    assert cached.cached is True
    assert cached.tier == "team"


def test_paddle_provider_subscription_validation(tmp_path: Path):
    def fake_http(method, url, headers, payload, timeout):
        assert method == "GET"
        assert url.endswith("/subscriptions/sub_01abcdef01")
        assert headers["Authorization"] == "Bearer pdl_test_key"
        return 200, {
            "data": {
                "id": "sub_01abcdef01",
                "status": "active",
                "custom_data": {"tier": "pro"},
                "current_billing_period": {"ends_at": "2099-06-01T00:00:00Z"},
            }
        }

    cfg = _cfg(tmp_path, paddle_api_key="pdl_test_key")
    mgr = LicenseManager(cfg, http_request=fake_http)
    status = mgr.verify(key="sub_01abcdef01")

    assert status.valid is True
    assert status.provider == "paddle"
    assert status.tier == "pro"
    assert status.has_feature("sarif_export") is True


def _craft_lic1(payload_obj, secret: str) -> str:
    raw = json.dumps(payload_obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")
    return f"LIC1.{payload_b64}.{sig_b64}"


def test_p0_1_paddle_rejects_path_traversal_and_id_mismatch(tmp_path: Path):
    calls = []

    def tracking_http(method, url, headers, payload, timeout):
        calls.append((method, url))
        return 200, {"data": {"id": "sub_other99999999", "status": "active"}}

    cfg = _cfg(tmp_path, paddle_api_key="pdl_test_key")
    mgr = LicenseManager(cfg, http_request=tracking_http)

    malicious_ids = [
        "sub_01abc",  # too short (<8 chars after sub_)
        "sub_12345678/../customers",
        "sub_12345678?status=active",
        "sub_12345678#fragment",
        "sub_12345678%2f..",
        "sub_" + "a" * 65,
    ]
    for bad_id in malicious_ids:
        res = mgr.verify(key=bad_id, provider="paddle")
        assert res.valid is False, f"expected rejection for {bad_id}"
    assert calls == [], "invalid Paddle sub_id must be rejected before issuing HTTP request"

    # Valid sub_id format, but server returns mismatched or missing data.id
    mismatch = mgr.verify(key="sub_12345678abcd", provider="paddle")
    assert mismatch.valid is False
    assert "mismatch" in mismatch.detail

    def missing_id_http(method, url, headers, payload, timeout):
        return 200, {"data": {"status": "active"}}

    mgr2 = LicenseManager(cfg, http_request=missing_id_http)
    assert mgr2.verify(key="sub_12345678abcd", provider="paddle").valid is False


def test_p0_3_grace_cache_rejects_future_verified_at_and_clock_rollback(tmp_path: Path, monkeypatch):
    base_time = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = {"now": base_time}
    monkeypatch.setattr(licensing_mod, "_now_utc", lambda: clock["now"])

    def online_http(method, url, headers, payload, timeout):
        return 200, {
            "status": "granted",
            "expires_at": "2099-12-31T00:00:00Z",
            "benefit": {"description": "Memory OS Team"},
        }

    def offline_http(method, url, headers, payload, timeout):
        raise urllib.error.URLError("offline")

    cfg = _cfg(tmp_path, polar_organization_id="org_123", grace_days=7)
    online_mgr = LicenseManager(cfg, http_request=online_http)
    assert online_mgr.activate("POLAR-KEY-CLOCK").valid is True

    # 1) Offline check within grace works and advances last_seen_at
    clock["now"] = base_time + timedelta(days=2)
    offline_mgr = LicenseManager(cfg, http_request=offline_http)
    cached_ok = offline_mgr.verify()
    assert cached_ok.valid is True
    assert cached_ok.cached is True

    # 2) Advance past grace window (day 10) -> grace expired, last_seen_at advances to day 10
    clock["now"] = base_time + timedelta(days=10)
    expired_grace = offline_mgr.verify()
    assert expired_grace.valid is False

    # 3) Roll system clock back to day 1 (between verified_at and grace limit) -> MUST fail closed
    clock["now"] = base_time + timedelta(days=1)
    rolled_back = offline_mgr.verify()
    assert rolled_back.valid is False
    assert "rollback" in rolled_back.detail.lower()

    # 4) Tamper license.json with future verified_at (negative age) -> MUST fail closed
    store_path = tmp_path / "license.json"
    future_ts = (base_time + timedelta(days=1, hours=2)).isoformat().replace("+00:00", "Z")
    store_path.write_text(
        json.dumps(
            {
                "product_slug": "memory_os",
                "key": "POLAR-KEY-CLOCK",
                "provider": "polar",
                "tier": "team",
                "expires_at": "2099-12-31T00:00:00Z",
                "verified_at": future_ts,
            }
        ),
        encoding="utf-8",
    )
    assert offline_mgr._load_valid_cache("POLAR-KEY-CLOCK") is None
    assert offline_mgr.verify().valid is False


def test_p0_3_offline_lic1_issued_at_and_rollback_high_water_mark(tmp_path: Path, monkeypatch):
    base_time = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)
    clock = {"now": base_time}
    monkeypatch.setattr(licensing_mod, "_now_utc", lambda: clock["now"])
    secret = "offline-clock-test-secret-32bytes!"
    cfg = _cfg(tmp_path, product_slug="memory_os", offline_signing_secret=secret)
    provider = OfflineTokenProvider()

    # Missing, malformed, non-string, and future issued_at must all fail closed
    for bad_payload in (
        {"product": "memory_os", "tier": "pro"},
        {"product": "memory_os", "tier": "pro", "issued_at": "not-a-timestamp"},
        {"product": "memory_os", "tier": "pro", "issued_at": 1795500000},
        {
            "product": "memory_os",
            "tier": "pro",
            "issued_at": (base_time + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        },
    ):
        tok = _craft_lic1(bad_payload, secret)
        assert provider.verify(tok, cfg).valid is False

    # Valid token expiring in 5 days
    exp_iso = (base_time + timedelta(days=5)).isoformat().replace("+00:00", "Z")
    token = issue_offline_token(product_slug="memory_os", tier="enterprise", secret=secret, expires_at=exp_iso)
    mgr = LicenseManager(cfg)
    assert mgr.activate(token).valid is True

    # Advance past expiry -> fails and advances last_seen_at
    clock["now"] = base_time + timedelta(days=6)
    assert mgr.verify().valid is False

    # Roll clock back to day 2 -> blocked by monotonic last_seen_at
    clock["now"] = base_time + timedelta(days=2)
    res_rb = mgr.verify()
    assert res_rb.valid is False
    assert "rollback" in res_rb.detail.lower()

    # Even deactivate + reactivate after rollback cannot bypass preserved last_seen_at
    assert mgr.deactivate() is True
    assert mgr.activate(token).valid is False


def test_p0_4_offline_lic1_and_provider_fail_closed(tmp_path: Path):
    secret = "p0-4-test-secret-value-32-bytes!!"
    cfg = _cfg(tmp_path, product_slug="memory_os", offline_signing_secret=secret)
    mgr = LicenseManager(cfg)
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    # 1) Empty / missing product must NOT act as wildcard
    for bad_prod in (
        {"tier": "pro", "issued_at": now_iso},
        {"product": "", "tier": "pro", "issued_at": now_iso},
        {"product": "   ", "tier": "pro", "issued_at": now_iso},
        {"product": None, "tier": "pro", "issued_at": now_iso},
    ):
        assert mgr.verify(key=_craft_lic1(bad_prod, secret)).valid is False

    # 2) Malformed / non-string exp or expires_at must fail closed
    for bad_exp in (
        {"product": "memory_os", "tier": "pro", "issued_at": now_iso, "exp": "not-a-date"},
        {"product": "memory_os", "tier": "pro", "issued_at": now_iso, "exp": ""},
        {"product": "memory_os", "tier": "pro", "issued_at": now_iso, "exp": 9999999999},
        {"product": "memory_os", "tier": "pro", "issued_at": now_iso, "expires_at": "bogus"},
        {"product": "memory_os", "tier": "pro", "issued_at": now_iso, "expires_at": 12345},
    ):
        assert mgr.verify(key=_craft_lic1(bad_exp, secret)).valid is False

    # 3) Unknown / invalid tier must fail closed (never escalate to 'pro')
    for bad_tier in (
        {"product": "memory_os", "tier": "godmode", "issued_at": now_iso},
        {"product": "memory_os", "tier": "", "issued_at": now_iso},
        {"product": "memory_os", "issued_at": now_iso},
        {"product": "memory_os", "tier": 42, "issued_at": now_iso},
    ):
        res = mgr.verify(key=_craft_lic1(bad_tier, secret))
        assert res.valid is False
        assert res.tier == "core"

    # 4) Unknown provider fails closed and activate() does NOT persist license.json
    fresh_cfg = _cfg(tmp_path / "fresh", product_slug="memory_os")
    fresh_mgr = LicenseManager(fresh_cfg)
    bad_prov = fresh_mgr.activate("ANY-KEY-123", provider="bogus")
    assert bad_prov.valid is False
    assert not (tmp_path / "fresh" / "license.json").exists()

    # 5) Non-ASCII LIC1 token and non-dict signed JSON fail closed cleanly without crashing
    assert mgr.verify(key="LIC1.héllo.sig").valid is False
    for non_dict in (["pro"], "memory_os", 12345, True):
        assert mgr.verify(key=_craft_lic1(non_dict, secret)).valid is False


def test_p2_readonly_license_store_does_not_crash_verify(tmp_path: Path, monkeypatch):
    def fake_http(method, url, headers, payload, timeout):
        return 200, {
            "status": "granted",
            "expires_at": "2099-01-01T00:00:00Z",
            "benefit": {"description": "Pro"},
        }

    cfg = _cfg(tmp_path, polar_organization_id="org_ro")
    mgr = LicenseManager(cfg, http_request=fake_http)
    assert mgr.activate("POLAR-RO-KEY").valid is True

    # Simulate read-only license.json (OSError on _write_store during _update_cache)
    def raise_os_error(data):
        raise PermissionError("Read-only file system")

    monkeypatch.setattr(mgr, "_write_store", raise_os_error)
    status = mgr.verify()
    assert status.valid is True
    assert status.tier == "pro"
    assert status.provider == "polar"


def test_cli_license_accepts_offline_ed25519_provider():
    from memory_os.cli import build_parser

    parser = build_parser()

    activate_args = parser.parse_args(
        ["license", "activate", "LIC2.payload.sig", "--provider", "offline_ed25519", "--format", "json"]
    )
    assert activate_args.license_cmd == "activate"
    assert activate_args.provider == "offline_ed25519"
    assert activate_args.key == "LIC2.payload.sig"
    assert activate_args.format == "json"

    verify_args = parser.parse_args(
        ["license", "verify", "--key", "LIC2.payload.sig", "--provider", "offline_ed25519"]
    )
    assert verify_args.license_cmd == "verify"
    assert verify_args.provider == "offline_ed25519"
    assert verify_args.key == "LIC2.payload.sig"

