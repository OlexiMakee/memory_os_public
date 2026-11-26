"""Reusable, product-agnostic licensing & billing verification module.

Supports Merchant-of-Record providers (Polar.sh, Paddle), self-contained
offline signed tokens (for air-gapped CI/Enterprise environments), and a
zero-cost deterministic sandbox mode for local development and testing.

Zero external dependencies (Python standard library only). Configure
``LicenseConfig(product_slug=..., env_prefix=...)`` to embed in any Python CLI,
CI action, or service.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Protocol, Tuple

UTC = timezone.utc
_CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)
_PADDLE_SUB_ID_RE = re.compile(r"sub_[0-9A-Za-z]{8,64}")

DEFAULT_TIER_FEATURES: Dict[str, Tuple[str, ...]] = {
    "core": (
        "local_memory",
        "mcp_stdio",
        "evidence_local",
        "security_default",
    ),
    "pro": (
        "local_memory",
        "mcp_stdio",
        "evidence_local",
        "security_default",
        "web_ui",
        "sarif_export",
        "multi_repo",
        "encrypted_sync",
    ),
    "team": (
        "local_memory",
        "mcp_stdio",
        "evidence_local",
        "security_default",
        "web_ui",
        "sarif_export",
        "multi_repo",
        "encrypted_sync",
        "ci_pr_gate",
        "pr_comment",
        "audit_logs",
        "unlimited_seats",
    ),
    "enterprise": (
        "local_memory",
        "mcp_stdio",
        "evidence_local",
        "security_default",
        "web_ui",
        "sarif_export",
        "multi_repo",
        "encrypted_sync",
        "ci_pr_gate",
        "pr_comment",
        "audit_logs",
        "unlimited_seats",
        "offline_airgap",
        "custom_policies",
    ),
}

HttpRequestFn = Callable[[str, str, Dict[str, str], Optional[Dict[str, Any]], float], Tuple[int, Dict[str, Any]]]


def _default_http_json(
    method: str,
    url: str,
    headers: Dict[str, str],
    payload: Optional[Dict[str, Any]],
    timeout: float,
) -> Tuple[int, Dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return int(resp.status), json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            body = {"detail": raw[:300]}
        return int(exc.code), body


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts or not isinstance(ts, str):
        return None
    normalized = ts.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


@dataclass(frozen=True)
class LicenseConfig:
    """Product-agnostic licensing configuration."""

    product_slug: str = "memory_os"
    env_prefix: str = "MEMORY_OS"
    storage_path: Optional[Path] = None
    grace_days: int = 7
    sandbox: bool = False
    polar_organization_id: str = ""
    paddle_api_key: str = ""
    offline_signing_secret: str = ""
    offline_ed25519_public_key: str = ""
    http_timeout: float = 8.0
    tier_features: Dict[str, Tuple[str, ...]] = field(default_factory=lambda: dict(DEFAULT_TIER_FEATURES))

    def resolved_storage_path(self) -> Path:
        if self.storage_path is not None:
            return Path(self.storage_path)
        return Path.home() / f".{self.product_slug}" / "license.json"

    def env_get(self, suffix: str, default: str = "") -> str:
        return os.environ.get(f"{self.env_prefix}_{suffix}", default).strip()

    def is_sandbox(self) -> bool:
        if self.sandbox:
            return True
        return self.env_get("LICENSE_SANDBOX", "").lower() in {"1", "true", "yes", "on"}

    def resolved_polar_org_id(self) -> str:
        return self.polar_organization_id or self.env_get("POLAR_ORG_ID", "")

    def resolved_paddle_api_key(self) -> str:
        return self.paddle_api_key or self.env_get("PADDLE_API_KEY", "")

    def resolved_offline_secret(self) -> str:
        return self.offline_signing_secret or self.env_get("LICENSE_OFFLINE_SECRET", "")

    def resolved_ed25519_public_key(self) -> str:
        return self.offline_ed25519_public_key or self.env_get("LICENSE_ED25519_PUBKEY", "")

    def features_for(self, tier: str) -> Tuple[str, ...]:
        return self.tier_features.get(tier.lower(), self.tier_features.get("core", ()))


@dataclass(frozen=True)
class LicenseStatus:
    """Result of a license verification check."""

    valid: bool
    tier: str
    provider: str
    product_slug: str
    features: Tuple[str, ...]
    detail: str
    expires_at: Optional[str] = None
    cached: bool = False

    def has_feature(self, feature: str) -> bool:
        return feature in self.features

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "tier": self.tier,
            "provider": self.provider,
            "product_slug": self.product_slug,
            "features": list(self.features),
            "expires_at": self.expires_at,
            "cached": self.cached,
            "detail": self.detail,
        }


class LicenseProvider(Protocol):
    name: str

    def verify(self, key: str, config: LicenseConfig) -> LicenseStatus:
        ...


class SandboxLicenseProvider:
    """Deterministic zero-cost provider for local & CI testing.

    Accepts keys formatted as ``SANDBOX-<TIER>-<ANY_SUFFIX>`` where TIER is
    ``PRO``, ``TEAM``, or ``ENTERPRISE`` when sandbox mode is enabled.
    """

    name = "sandbox"

    def verify(self, key: str, config: LicenseConfig) -> LicenseStatus:
        if not config.is_sandbox():
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail=f"sandbox key rejected (set {config.env_prefix}_LICENSE_SANDBOX=1 to enable sandbox mode)",
            )
        parts = key.strip().split("-")
        tier = parts[1].lower() if len(parts) >= 3 else ""
        if tier not in {"pro", "team", "enterprise"}:
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail="invalid sandbox key format (expected SANDBOX-<PRO|TEAM|ENTERPRISE>-<ID>)",
            )
        return LicenseStatus(
            valid=True,
            tier=tier,
            provider=self.name,
            product_slug=config.product_slug,
            features=config.features_for(tier),
            detail=f"sandbox {tier} license active",
        )


def issue_offline_token(
    *,
    product_slug: str,
    tier: str,
    secret: str,
    expires_at: Optional[str] = None,
    holder: str = "",
) -> str:
    """Generate a signed offline license token (``LIC1.<payload>.<sig>``)."""
    payload_obj: Dict[str, Any] = {
        "product": product_slug,
        "tier": tier.lower(),
        "issued_at": _now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    if expires_at:
        payload_obj["exp"] = expires_at
    if holder:
        payload_obj["holder"] = holder

    payload_b64 = _b64url_encode(json.dumps(payload_obj, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"LIC1.{payload_b64}.{_b64url_encode(sig)}"


def _validate_offline_payload(
    payload: Any,
    config: LicenseConfig,
    provider_name: str,
) -> LicenseStatus:
    """Validate decoded offline license payload (shared by LIC1 HMAC & LIC2 Ed25519)."""
    if not isinstance(payload, dict):
        return LicenseStatus(
            valid=False,
            tier="core",
            provider=provider_name,
            product_slug=config.product_slug,
            features=config.features_for("core"),
            detail="offline license payload must be a JSON object",
        )

    token_product = payload.get("product")
    if not isinstance(token_product, str) or not token_product.strip() or token_product != config.product_slug:
        return LicenseStatus(
            valid=False,
            tier="core",
            provider=provider_name,
            product_slug=config.product_slug,
            features=config.features_for("core"),
            detail=f"license product mismatch: token is for '{token_product or ''}', expected '{config.product_slug}'",
        )

    now = _now_utc()
    issued_raw = payload.get("issued_at")
    if not isinstance(issued_raw, str):
        return LicenseStatus(
            valid=False,
            tier="core",
            provider=provider_name,
            product_slug=config.product_slug,
            features=config.features_for("core"),
            detail="offline license missing or invalid issued_at",
        )
    issued_dt = _parse_iso(issued_raw)
    if issued_dt is None:
        return LicenseStatus(
            valid=False,
            tier="core",
            provider=provider_name,
            product_slug=config.product_slug,
            features=config.features_for("core"),
            detail="offline license has malformed issued_at timestamp",
        )
    if issued_dt > now + _CLOCK_SKEW_TOLERANCE:
        return LicenseStatus(
            valid=False,
            tier="core",
            provider=provider_name,
            product_slug=config.product_slug,
            features=config.features_for("core"),
            detail="offline license issued_at is in the future (clock rollback detected)",
        )

    resolved_exp_raw: Optional[str] = None
    for exp_key in ("exp", "expires_at"):
        if exp_key in payload and payload[exp_key] is not None:
            exp_val = payload[exp_key]
            if not isinstance(exp_val, str):
                return LicenseStatus(
                    valid=False,
                    tier="core",
                    provider=provider_name,
                    product_slug=config.product_slug,
                    features=config.features_for("core"),
                    detail=f"offline license has non-string {exp_key} field",
                )
            exp_dt = _parse_iso(exp_val)
            if exp_dt is None:
                return LicenseStatus(
                    valid=False,
                    tier="core",
                    provider=provider_name,
                    product_slug=config.product_slug,
                    features=config.features_for("core"),
                    detail=f"offline license has malformed {exp_key} timestamp",
                )
            if exp_dt < now:
                return LicenseStatus(
                    valid=False,
                    tier="core",
                    provider=provider_name,
                    product_slug=config.product_slug,
                    features=config.features_for("core"),
                    expires_at=exp_val,
                    detail=f"offline license expired at {exp_val}",
                )
            if resolved_exp_raw is None:
                resolved_exp_raw = exp_val

    raw_tier = payload.get("tier")
    if not isinstance(raw_tier, str) or raw_tier.lower() not in config.tier_features:
        return LicenseStatus(
            valid=False,
            tier="core",
            provider=provider_name,
            product_slug=config.product_slug,
            features=config.features_for("core"),
            detail=f"offline license has unknown or invalid tier '{raw_tier}'",
        )
    tier = raw_tier.lower()
    label = "Ed25519 offline" if provider_name == "offline_ed25519" else "offline"
    return LicenseStatus(
        valid=True,
        tier=tier,
        provider=provider_name,
        product_slug=config.product_slug,
        features=config.features_for(tier),
        expires_at=resolved_exp_raw,
        detail=f"{label} {tier} license verified",
    )


class OfflineTokenProvider:
    """Verifies self-contained HMAC-SHA256 tokens for air-gapped runners."""

    name = "offline"

    def verify(self, key: str, config: LicenseConfig) -> LicenseStatus:
        secret = config.resolved_offline_secret()
        if not secret:
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail=f"offline verification secret not configured ({config.env_prefix}_LICENSE_OFFLINE_SECRET)",
            )

        parts = key.strip().split(".")
        if len(parts) != 3 or parts[0] != "LIC1":
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail="malformed offline license token",
            )

        _, payload_b64, sig_b64 = parts
        try:
            payload_b64_bytes = payload_b64.encode("ascii")
            expected_sig = hmac.new(secret.encode("utf-8"), payload_b64_bytes, hashlib.sha256).digest()
            actual_sig = _b64url_decode(sig_b64)
            payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        except Exception:
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail="corrupted offline license encoding",
            )

        if not hmac.compare_digest(actual_sig, expected_sig):
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail="offline license signature mismatch",
            )

        return _validate_offline_payload(payload, config, self.name)


# ---------------------------------------------------------------------------
# Pure-Python RFC 8032 Ed25519 (zero external dependencies) for LIC2 tokens
# ---------------------------------------------------------------------------
_ED_P = (1 << 255) - 19
_ED_Q = (1 << 252) + 27742317777372353535851937790883648493
_ED_D = (-121665 * pow(121666, -1, _ED_P)) % _ED_P
_ED_I = pow(2, (_ED_P - 1) // 4, _ED_P)
_ED_GY = (4 * pow(5, -1, _ED_P)) % _ED_P


def _ed_recover_x(y: int, sign: int) -> Optional[int]:
    if y >= _ED_P:
        return None
    u = (y * y - 1) % _ED_P
    v = (_ED_D * y * y + 1) % _ED_P
    x2 = (u * pow(v, -1, _ED_P)) % _ED_P
    x = pow(x2, (_ED_P + 3) // 8, _ED_P)
    if (x * x - x2) % _ED_P != 0:
        x = (x * _ED_I) % _ED_P
    if (x * x - x2) % _ED_P != 0:
        return None
    if x == 0 and sign == 1:
        return None
    if (x & 1) != sign:
        x = _ED_P - x
    return x


_ED_GX = _ed_recover_x(_ED_GY, 0)
assert _ED_GX is not None
_ED_G = (_ED_GX, _ED_GY, 1, (_ED_GX * _ED_GY) % _ED_P)
_ED_NEUTRAL = (0, 1, 1, 0)


def _ed_point_add(
    p1: Tuple[int, int, int, int], p2: Tuple[int, int, int, int]
) -> Tuple[int, int, int, int]:
    x1, y1, z1, t1 = p1
    x2, y2, z2, t2 = p2
    a = ((y1 - x1) * (y2 - x2)) % _ED_P
    b = ((y1 + x1) * (y2 + x2)) % _ED_P
    c = (2 * _ED_D * t1 * t2) % _ED_P
    d = (2 * z1 * z2) % _ED_P
    e = (b - a) % _ED_P
    f = (d - c) % _ED_P
    g = (d + c) % _ED_P
    h = (b + a) % _ED_P
    return ((e * f) % _ED_P, (g * h) % _ED_P, (f * g) % _ED_P, (e * h) % _ED_P)


def _ed_point_mul(s: int, pt: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    acc = _ED_NEUTRAL
    cur = pt
    while s > 0:
        if s & 1:
            acc = _ed_point_add(acc, cur)
        cur = _ed_point_add(cur, cur)
        s >>= 1
    return acc


def _ed_point_equal(p1: Tuple[int, int, int, int], p2: Tuple[int, int, int, int]) -> bool:
    return (p1[0] * p2[2] - p2[0] * p1[2]) % _ED_P == 0 and (
        p1[1] * p2[2] - p2[1] * p1[2]
    ) % _ED_P == 0


def _ed_point_compress(pt: Tuple[int, int, int, int]) -> bytes:
    zinv = pow(pt[2], -1, _ED_P)
    x = (pt[0] * zinv) % _ED_P
    y = (pt[1] * zinv) % _ED_P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _ed_point_decompress(encoded: bytes) -> Optional[Tuple[int, int, int, int]]:
    if len(encoded) != 32:
        return None
    y_int = int.from_bytes(encoded, "little")
    sign = (y_int >> 255) & 1
    y = y_int & ((1 << 255) - 1)
    x = _ed_recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, (x * y) % _ED_P)


def _ed_secret_expand(seed: bytes) -> Tuple[int, bytes]:
    if len(seed) != 32:
        raise ValueError("Ed25519 private seed must be exactly 32 bytes")
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= ~7
    a &= (1 << 254) - 1
    a |= 1 << 254
    return a, h[32:]


def ed25519_public_key_from_seed(seed: bytes) -> bytes:
    """Derive 32-byte Ed25519 public key from a 32-byte private seed (RFC 8032)."""
    a, _ = _ed_secret_expand(seed)
    return _ed_point_compress(_ed_point_mul(a, _ED_G))


def generate_ed25519_keypair() -> Tuple[str, str]:
    """Generate `(private_seed_b64url, public_key_b64url)` for `LIC2.` tokens."""
    seed = os.urandom(32)
    pub = ed25519_public_key_from_seed(seed)
    return _b64url_encode(seed), _b64url_encode(pub)


def ed25519_sign(seed: bytes, message: bytes) -> bytes:
    """Sign `message` using a 32-byte Ed25519 private seed (RFC 8032)."""
    a, prefix = _ed_secret_expand(seed)
    pub = _ed_point_compress(_ed_point_mul(a, _ED_G))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % _ED_Q
    r_enc = _ed_point_compress(_ed_point_mul(r, _ED_G))
    h = int.from_bytes(hashlib.sha512(r_enc + pub + message).digest(), "little") % _ED_Q
    s = (r + h * a) % _ED_Q
    return r_enc + s.to_bytes(32, "little")


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Verify a 64-byte Ed25519 signature against a 32-byte public key (RFC 8032)."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    a_pt = _ed_point_decompress(public_key)
    r_pt = _ed_point_decompress(signature[:32])
    if a_pt is None or r_pt is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _ED_Q:
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % _ED_Q
    lhs = _ed_point_mul(s, _ED_G)
    rhs = _ed_point_add(r_pt, _ed_point_mul(h, a_pt))
    return _ed_point_equal(lhs, rhs)


def issue_ed25519_token(
    *,
    product_slug: str,
    tier: str,
    private_seed_b64: str,
    expires_at: Optional[str] = None,
    holder: str = "",
) -> str:
    """Generate an asymmetrically signed offline license token (`LIC2.<payload>.<ed25519_sig>`)."""
    seed = _b64url_decode(private_seed_b64.strip())
    payload_obj: Dict[str, Any] = {
        "product": product_slug,
        "tier": tier.lower(),
        "issued_at": _now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    if expires_at:
        payload_obj["exp"] = expires_at
    if holder:
        payload_obj["holder"] = holder

    payload_b64 = _b64url_encode(json.dumps(payload_obj, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    sig = ed25519_sign(seed, payload_b64.encode("ascii"))
    return f"LIC2.{payload_b64}.{_b64url_encode(sig)}"


class OfflineEd25519Provider:
    """Verifies asymmetric Ed25519 (`LIC2.`) tokens using only an embedded public key."""

    name = "offline_ed25519"

    def verify(self, key: str, config: LicenseConfig) -> LicenseStatus:
        pub_b64 = config.resolved_ed25519_public_key()
        if not pub_b64:
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail=f"Ed25519 public key not configured ({config.env_prefix}_LICENSE_ED25519_PUBKEY)",
            )

        parts = key.strip().split(".")
        if len(parts) != 3 or parts[0] != "LIC2":
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail="malformed Ed25519 offline license token",
            )

        _, payload_b64, sig_b64 = parts
        try:
            payload_b64_bytes = payload_b64.encode("ascii")
            pub_bytes = _b64url_decode(pub_b64)
            sig_bytes = _b64url_decode(sig_b64)
            payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        except Exception:
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail="corrupted Ed25519 license encoding",
            )

        if not ed25519_verify(pub_bytes, payload_b64_bytes, sig_bytes):
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail="Ed25519 license signature verification failed",
            )

        return _validate_offline_payload(payload, config, self.name)


class PolarLicenseProvider:
    """Validates license keys via Polar.sh Customer Portal API (MoR)."""

    name = "polar"

    def __init__(self, http_request: HttpRequestFn = _default_http_json):
        self._http_request = http_request

    def verify(self, key: str, config: LicenseConfig) -> LicenseStatus:
        org_id = config.resolved_polar_org_id()
        if not org_id:
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail=f"Polar organization_id missing ({config.env_prefix}_POLAR_ORG_ID)",
            )

        base = "https://sandbox-api.polar.sh" if config.is_sandbox() else "https://api.polar.sh"
        url = f"{base}/v1/customer-portal/license-keys/validate"
        status_code, body = self._http_request(
            "POST",
            url,
            {"Content-Type": "application/json", "Accept": "application/json"},
            {"key": key.strip(), "organization_id": org_id},
            config.http_timeout,
        )

        if status_code != 200:
            detail = (body.get("detail") or body.get("error")) if isinstance(body, dict) else None
            detail = detail or f"HTTP {status_code}"
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail=f"Polar validation failed: {detail}",
            )

        if not isinstance(body, dict):
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail="Polar validation returned malformed JSON payload",
            )

        key_status = str(body.get("status", "")).lower()
        if key_status != "granted":
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                expires_at=body.get("expires_at"),
                detail=f"Polar license status is '{key_status or 'unknown'}'",
            )

        tier = _extract_tier(body, default="pro")
        return LicenseStatus(
            valid=True,
            tier=tier,
            provider=self.name,
            product_slug=config.product_slug,
            features=config.features_for(tier),
            expires_at=body.get("expires_at"),
            detail=f"Polar {tier} license verified",
        )


class PaddleLicenseProvider:
    """Validates subscriptions via Paddle Billing API (MoR)."""

    name = "paddle"

    def __init__(self, http_request: HttpRequestFn = _default_http_json):
        self._http_request = http_request

    def verify(self, key: str, config: LicenseConfig) -> LicenseStatus:
        api_key = config.resolved_paddle_api_key()
        if not api_key:
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail=f"Paddle API key missing ({config.env_prefix}_PADDLE_API_KEY)",
            )

        sub_id = key.strip()
        if not _PADDLE_SUB_ID_RE.fullmatch(sub_id):
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail="invalid Paddle subscription id format (expected sub_<8-64 alphanumeric chars>)",
            )

        base = "https://sandbox-api.paddle.com" if config.is_sandbox() else "https://api.paddle.com"
        encoded_sub_id = urllib.parse.quote(sub_id, safe="")
        url = f"{base}/subscriptions/{encoded_sub_id}"
        status_code, body = self._http_request(
            "GET",
            url,
            {"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            None,
            config.http_timeout,
        )

        if status_code != 200:
            err = body.get("error", {}) if isinstance(body, dict) else {}
            detail = err.get("detail") if isinstance(err, dict) else f"HTTP {status_code}"
            detail = detail or f"HTTP {status_code}"
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail=f"Paddle validation failed: {detail}",
            )

        if not isinstance(body, dict):
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail="Paddle validation returned malformed JSON payload",
            )

        data = body.get("data") if "data" in body else body
        if not isinstance(data, dict) or data.get("id") != sub_id:
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail="Paddle subscription response id mismatch",
            )

        sub_status = str(data.get("status", "")).lower()
        if sub_status not in {"active", "trialing"}:
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=self.name,
                product_slug=config.product_slug,
                features=config.features_for("core"),
                detail=f"Paddle subscription status is '{sub_status or 'unknown'}'",
            )

        tier = _extract_tier(data, default="team")
        expires_at = None
        billing_period = data.get("current_billing_period")
        if isinstance(billing_period, dict):
            expires_at = billing_period.get("ends_at")
        return LicenseStatus(
            valid=True,
            tier=tier,
            provider=self.name,
            product_slug=config.product_slug,
            features=config.features_for(tier),
            expires_at=expires_at,
            detail=f"Paddle {tier} subscription active ({sub_status})",
        )


def _extract_tier(payload: Dict[str, Any], default: str = "pro") -> str:
    """Resolve tier name from provider metadata/custom_data/benefit fields."""
    candidates = []
    for field_name in ("tier", "plan"):
        if isinstance(payload.get(field_name), str):
            candidates.append(payload[field_name])
    for nested_name in ("metadata", "custom_data", "benefit"):
        nested = payload.get(nested_name)
        if isinstance(nested, dict):
            for key in ("tier", "plan", "description", "name"):
                val = nested.get(key)
                if isinstance(val, str):
                    candidates.append(val)
    for raw in candidates:
        lowered = raw.lower()
        for tier in ("enterprise", "team", "pro"):
            if tier in lowered:
                return tier
    return default


def detect_provider_name(key: str, explicit: str = "auto") -> str:
    if explicit and explicit != "auto":
        return explicit.lower()
    cleaned = key.strip()
    if cleaned.upper().startswith("SANDBOX-"):
        return "sandbox"
    if cleaned.startswith("LIC1."):
        return "offline"
    if cleaned.startswith("LIC2."):
        return "offline_ed25519"
    if cleaned.startswith("sub_"):
        return "paddle"
    return "polar"


class LicenseManager:
    """High-level license manager with offline grace caching and Core fallback."""

    def __init__(
        self,
        config: Optional[LicenseConfig] = None,
        http_request: HttpRequestFn = _default_http_json,
    ):
        self.config = config or LicenseConfig()
        self.providers: Dict[str, LicenseProvider] = {
            "sandbox": SandboxLicenseProvider(),
            "offline": OfflineTokenProvider(),
            "offline_ed25519": OfflineEd25519Provider(),
            "polar": PolarLicenseProvider(http_request=http_request),
            "paddle": PaddleLicenseProvider(http_request=http_request),
        }

    def resolve_key(self, explicit_key: Optional[str] = None) -> Tuple[str, str]:
        """Return ``(key, provider_hint)`` from args, env var, or persisted file."""
        if explicit_key:
            return explicit_key.strip(), self.config.env_get("LICENSE_PROVIDER", "auto") or "auto"

        env_key = self.config.env_get("LICENSE_KEY", "")
        if env_key:
            return env_key, self.config.env_get("LICENSE_PROVIDER", "auto") or "auto"

        stored = self._read_store()
        if stored and stored.get("key"):
            return str(stored["key"]), str(stored.get("provider", "auto"))
        return "", "core"

    def verify(
        self,
        key: Optional[str] = None,
        provider: str = "auto",
        allow_cache: bool = True,
    ) -> LicenseStatus:
        resolved_key, stored_provider = self.resolve_key(key)
        if not resolved_key:
            return self._core_status("no commercial license configured (running Core MIT tier)")

        provider_name = detect_provider_name(
            resolved_key,
            explicit=provider if provider != "auto" else stored_provider,
        )
        impl = self.providers.get(provider_name)
        if impl is None:
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=provider_name,
                product_slug=self.config.product_slug,
                features=self.config.features_for("core"),
                detail=f"unsupported license provider '{provider_name}'",
            )

        now = _now_utc()
        stored = self._read_store()
        if stored is not None and self._is_clock_rolled_back(stored, now):
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=provider_name,
                product_slug=self.config.product_slug,
                features=self.config.features_for("core"),
                detail="system clock rollback detected (current time precedes high-water mark)",
            )

        try:
            result = impl.verify(resolved_key, self.config)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if allow_cache:
                cached = self._load_valid_cache(resolved_key)
                if cached is not None:
                    return cached
            if stored is not None:
                self._advance_last_seen(stored, now)
            return LicenseStatus(
                valid=False,
                tier="core",
                provider=provider_name,
                product_slug=self.config.product_slug,
                features=self.config.features_for("core"),
                detail=f"network unreachable during {provider_name} verification: {exc}",
            )

        if result.valid:
            if key is None:
                self._update_cache(resolved_key, result, now=now)
            else:
                self._record_last_seen(now)
        elif stored is not None:
            self._advance_last_seen(stored, now)
        return result

    def activate(self, key: str, provider: str = "auto") -> LicenseStatus:
        status = self.verify(key=key, provider=provider, allow_cache=False)
        if status.valid:
            now = _now_utc()
            existing = self._read_store() or {}
            prev_dt = _parse_iso(existing.get("last_seen_at"))
            high_water = max(now, prev_dt) if prev_dt is not None else now
            self._write_store(
                {
                    "product_slug": self.config.product_slug,
                    "key": key.strip(),
                    "provider": status.provider,
                    "tier": status.tier,
                    "expires_at": status.expires_at,
                    "verified_at": _iso_utc(now),
                    "last_seen_at": _iso_utc(high_water),
                }
            )
        return status

    def deactivate(self) -> bool:
        path = self.config.resolved_storage_path()
        if not path.exists():
            return False
        stored = self._read_store()
        if stored is None:
            path.unlink()
            return True
        had_key = bool(stored.get("key"))
        last_seen = stored.get("last_seen_at")
        if isinstance(last_seen, str) and _parse_iso(last_seen) is not None:
            self._write_store({"last_seen_at": last_seen})
        else:
            path.unlink()
        return had_key

    def require_feature(self, feature: str) -> Tuple[bool, LicenseStatus]:
        status = self.verify()
        return status.has_feature(feature), status

    def _core_status(self, detail: str) -> LicenseStatus:
        return LicenseStatus(
            valid=True,
            tier="core",
            provider="core",
            product_slug=self.config.product_slug,
            features=self.config.features_for("core"),
            detail=detail,
        )

    def _read_store(self) -> Optional[Dict[str, Any]]:
        path = self.config.resolved_storage_path()
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _write_store(self, data: Dict[str, Any]) -> None:
        path = self.config.resolved_storage_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _is_clock_rolled_back(self, stored: Dict[str, Any], now: datetime) -> bool:
        last_seen_raw = stored.get("last_seen_at")
        if last_seen_raw is not None:
            if not isinstance(last_seen_raw, str):
                return True
            last_seen_dt = _parse_iso(last_seen_raw)
            if last_seen_dt is None or now + _CLOCK_SKEW_TOLERANCE < last_seen_dt:
                return True

        verified_raw = stored.get("verified_at")
        if verified_raw is not None:
            if not isinstance(verified_raw, str):
                return True
            verified_dt = _parse_iso(verified_raw)
            if verified_dt is None or verified_dt > now + _CLOCK_SKEW_TOLERANCE:
                return True
        return False

    def _advance_last_seen(self, stored: Dict[str, Any], now: datetime) -> None:
        prev_dt = _parse_iso(stored.get("last_seen_at"))
        if prev_dt is not None and now <= prev_dt:
            return
        updated = dict(stored)
        updated["last_seen_at"] = _iso_utc(now)
        try:
            self._write_store(updated)
        except OSError:
            pass

    def _record_last_seen(self, now: datetime) -> None:
        stored = self._read_store() or {}
        prev_dt = _parse_iso(stored.get("last_seen_at"))
        if prev_dt is not None and now <= prev_dt:
            return
        stored["last_seen_at"] = _iso_utc(now)
        try:
            self._write_store(stored)
        except OSError:
            pass

    def _update_cache(self, key: str, status: LicenseStatus, now: Optional[datetime] = None) -> None:
        current = now or _now_utc()
        stored = self._read_store()
        if stored and stored.get("key") == key:
            prev_dt = _parse_iso(stored.get("last_seen_at"))
            high_water = max(current, prev_dt) if prev_dt is not None else current
            stored["tier"] = status.tier
            stored["provider"] = status.provider
            stored["expires_at"] = status.expires_at
            stored["verified_at"] = _iso_utc(current)
            stored["last_seen_at"] = _iso_utc(high_water)
            try:
                self._write_store(stored)
            except OSError:
                pass
        else:
            self._record_last_seen(current)

    def _load_valid_cache(self, key: str) -> Optional[LicenseStatus]:
        stored = self._read_store()
        if not stored or stored.get("key") != key:
            return None
        now = _now_utc()
        if self._is_clock_rolled_back(stored, now):
            return None
        verified_at = _parse_iso(stored.get("verified_at"))
        if verified_at is None:
            return None
        if verified_at > now + _CLOCK_SKEW_TOLERANCE:
            return None
        if now - verified_at > timedelta(days=self.config.grace_days):
            return None
        exp_raw = stored.get("expires_at")
        if exp_raw is not None:
            if not isinstance(exp_raw, str):
                return None
            exp_dt = _parse_iso(exp_raw)
            if exp_dt is None or exp_dt < now:
                return None
        tier = str(stored.get("tier", "")).lower()
        if tier not in self.config.tier_features:
            return None
        self._advance_last_seen(stored, now)
        return LicenseStatus(
            valid=True,
            tier=tier,
            provider=str(stored.get("provider", "cached")),
            product_slug=self.config.product_slug,
            features=self.config.features_for(tier),
            expires_at=exp_raw,
            cached=True,
            detail=f"using offline grace cache (last verified {stored.get('verified_at')})",
        )


def handle_license_cli(args: Any, config: Any = None) -> int:
    """CLI handler for ``memory_os license [status|activate|verify|deactivate]``."""
    del config
    lic_cfg = LicenseConfig(
        product_slug=getattr(args, "product", "memory_os") or "memory_os",
        sandbox=bool(getattr(args, "sandbox", False)),
    )
    manager = LicenseManager(lic_cfg)
    action = getattr(args, "license_cmd", None) or "status"
    out_fmt = getattr(args, "format", "text")

    if action == "deactivate":
        removed = manager.deactivate()
        payload = {"ok": True, "removed": removed, "detail": "license removed" if removed else "no license stored"}
        if out_fmt == "json":
            print(json.dumps(payload, indent=2))
        else:
            print(payload["detail"])
        return 0

    if action == "activate":
        status = manager.activate(args.key, provider=getattr(args, "provider", "auto"))
    elif action == "verify":
        status = manager.verify(
            key=getattr(args, "key", None),
            provider=getattr(args, "provider", "auto"),
            allow_cache=not bool(getattr(args, "no_cache", False)),
        )
    else:
        status = manager.verify()

    if out_fmt == "json":
        print(json.dumps(status.to_dict(), indent=2))
    else:
        state = "VALID" if status.valid else "INVALID"
        print(f"License [{state}] tier={status.tier} provider={status.provider} product={status.product_slug}")
        print(f"  detail: {status.detail}")
        print(f"  features: {', '.join(status.features)}")
    return 0 if status.valid else 1
