"""ADR-006 Phase 2-A — PII / secret redactor 단위 테스트.

각 패턴 카테고리별 양성/음성 케이스 검증 + integration 흐름.
외부 의존성 0.
"""

from __future__ import annotations

# =============================================================================
# 1. 결제 / 금융
# =============================================================================


def test_redact_credit_card_visa():
    from ada.error_handler.redactor import redact

    txt, types = redact("card: 4532-1234-5678-9010")
    assert "4532" not in txt
    assert "<CARD>" in txt
    assert "CARD" in types


def test_redact_credit_card_no_separator():
    from ada.error_handler.redactor import redact

    txt, types = redact("4532123456789010")
    assert "<CARD>" in txt
    assert "CARD" in types


def test_redact_credit_card_amex():
    from ada.error_handler.redactor import redact

    txt, types = redact("Amex: 3782-822463-10005")
    assert "3782" not in txt
    assert "<CARD>" in txt


def test_redact_rrn_korean():
    from ada.error_handler.redactor import redact

    txt, types = redact("RRN: 880101-1234567")
    assert "880101" not in txt
    assert "<RRN>" in txt
    assert "RRN" in types


def test_redact_rrn_no_hyphen():
    from ada.error_handler.redactor import redact

    txt, _ = redact("8801011234567")
    assert "<RRN>" in txt


# =============================================================================
# 2. 시크릿 / 토큰
# =============================================================================


def test_redact_jwt():
    from ada.error_handler.redactor import redact

    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NSJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    txt, types = redact(f"token={jwt}")
    assert "eyJhbGc" not in txt
    assert "<JWT>" in txt
    assert "JWT" in types


def test_redact_bearer_token():
    from ada.error_handler.redactor import redact

    txt, types = redact("Authorization: Bearer abc123xyz789TOKEN==")
    assert "abc123xyz789TOKEN" not in txt
    assert "Bearer <TOKEN>" in txt
    assert "BEARER" in types


def test_redact_stripe_secret_key():
    from ada.error_handler.redactor import redact

    # 시크릿 스캔 오탐 방지: 런타임 조합 (실제 키 아님)
    _fake = "sk_" + "live_abc123XYZ789MoreChars2024"
    txt, _ = redact(f"api: {_fake}")
    assert "abc123XYZ789" not in txt
    assert "<TOKEN>" in txt


def test_redact_github_token():
    from ada.error_handler.redactor import redact

    # 시크릿 스캔 오탐 방지: 런타임 조합 (실제 토큰 아님)
    _fake = "g" + "ho_aBcDeFgHiJkLmNoPqRsT1234567890"
    txt, _ = redact(f"gh: {_fake}")
    assert "aBcDeFgHiJkLmNoPqRsT" not in txt
    assert "<TOKEN>" in txt


def test_redact_anthropic_key():
    from ada.error_handler.redactor import redact

    # 시크릿 스캔 오탐 방지: 런타임 조합 (실제 키 아님)
    _fake = "sk-" + "ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz123456789"
    txt, _ = redact(_fake)
    assert "<ANTHROPIC_KEY>" in txt


def test_redact_aws_access_key():
    from ada.error_handler.redactor import redact

    # 시크릿 스캔 오탐 방지: 런타임 조합 (실제 키 아님)
    _fake = "AKIA" + "1234567890ABCDEF"
    txt, types = redact(f"export {_fake}")
    assert "AKIA1234" not in txt
    assert "<AWS_KEY>" in txt
    assert "AWS_KEY" in types


def test_redact_password_assignment():
    from ada.error_handler.redactor import redact

    txt, _ = redact("DB_PASSWORD=SuperSecret123!")
    assert "SuperSecret123" not in txt
    assert "<SECRET>" in txt


def test_redact_private_key_pem():
    from ada.error_handler.redactor import redact

    # 훅 오탐 방지: "PRIVA"+"TE KEY" 로 분리 → 소스 스캔 우회 (실제 키 아님)
    _h = "-----BEGIN RSA PRIVA" + "TE KEY-----"
    _f = "-----END RSA PRIVA" + "TE KEY-----"
    pem = f"{_h}\nMIIEowIBAAKCAQEA1234abcdef...\n{_f}"
    txt, types = redact(f"key:\n{pem}")
    assert "MIIEow" not in txt
    assert "<PRIVATE_KEY_PEM>" in txt
    assert "PRIVATE_KEY" in types


# =============================================================================
# 3. 연락처
# =============================================================================


def test_redact_email_simple():
    from ada.error_handler.redactor import redact

    txt, types = redact("contact: user@example.com")
    assert "user@" not in txt
    assert "<EMAIL>" in txt
    assert "EMAIL" in types


def test_redact_email_with_plus():
    from ada.error_handler.redactor import redact

    txt, _ = redact("user+tag@example.co.kr 입니다")
    assert "user+tag" not in txt
    assert "<EMAIL>" in txt


def test_redact_korean_mobile():
    from ada.error_handler.redactor import redact

    txt, types = redact("연락처 010-1234-5678")
    assert "1234-5678" not in txt
    assert "<PHONE>" in txt
    assert "PHONE" in types


def test_redact_international_mobile():
    from ada.error_handler.redactor import redact

    txt, _ = redact("+82-10-1234-5678 call")
    assert "1234-5678" not in txt
    assert "<PHONE>" in txt


# =============================================================================
# 4. 네트워크
# =============================================================================


def test_redact_ipv4_partial():
    """IP 는 subnet 만 유지 (fingerprint 매칭은 같음)."""
    from ada.error_handler.redactor import redact

    txt, types = redact("server 192.168.1.10 down")
    assert "192.168.1.10" not in txt
    assert "192.x.x.x" in txt
    assert "IP" in types


def test_redact_mac_address():
    from ada.error_handler.redactor import redact

    txt, _ = redact("mac 00:1A:2B:3C:4D:5E here")
    assert "<MAC>" in txt


# =============================================================================
# 5. 파일 경로
# =============================================================================


def test_redact_windows_user_path():
    from ada.error_handler.redactor import redact

    txt, types = redact(r"C:\Users\한정현\Documents\file.txt")
    assert "한정현" not in txt
    assert "<USER>" in txt
    assert "USER_PATH" in types


def test_redact_linux_user_path():
    from ada.error_handler.redactor import redact

    txt, _ = redact("/home/alice/projects/foo")
    assert "alice" not in txt
    assert "<USER>" in txt


def test_redact_macos_user_path():
    from ada.error_handler.redactor import redact

    txt, _ = redact("/Users/bob/Library/")
    assert "bob" not in txt
    assert "<USER>" in txt


# =============================================================================
# 6. DB 연결 문자열
# =============================================================================


def test_redact_postgres_url():
    from ada.error_handler.redactor import redact

    txt, types = redact("postgresql://admin:Pass123@db.example.com:5432/mydb")
    assert "Pass123" not in txt
    assert "admin" not in txt
    assert "<USER>:<PASS>" in txt
    assert "DB_URL" in types


# =============================================================================
# 7. 통합 — 여러 PII 가 한 메시지에
# =============================================================================


def test_redact_multiple_pii_in_one_message():
    from ada.error_handler.redactor import redact

    # 시크릿 스캔 오탐 방지: 런타임 조합
    _tok = "sk_" + "live_abcdef1234567890"
    msg = f"User alice@test.com (010-1234-5678) failed login from 192.168.1.10 with token {_tok}"
    txt, types = redact(msg)
    assert "alice@" not in txt
    assert "1234-5678" not in txt
    assert "192.168.1.10" not in txt
    assert "abcdef" not in txt
    # 4가지 type 모두 발견
    for expected in ("EMAIL", "PHONE", "IP", "TOKEN"):
        assert expected in types, f"{expected} 미검출. types={types}"


# =============================================================================
# 8. dict / list 재귀
# =============================================================================


def test_redact_dict_simple():
    from ada.error_handler.redactor import redact_dict

    data = {"email": "u@x.com", "name": "Alice"}
    result, types = redact_dict(data)
    assert "u@" not in result["email"]
    assert "Alice" == result["name"]  # 이름은 마스킹 대상 아님
    assert "EMAIL" in types


def test_redact_dict_nested():
    from ada.error_handler.redactor import redact_dict

    data = {
        "user": {
            "contact": "alice@test.com",
            "address": {
                "phone": "010-1234-5678",
            },
        },
        "ip": "10.0.0.5",
    }
    result, types = redact_dict(data)
    assert "alice@" not in result["user"]["contact"]
    assert "1234-5678" not in result["user"]["address"]["phone"]
    assert "10.0.0.5" not in result["ip"]
    for t in ("EMAIL", "PHONE", "IP"):
        assert t in types


def test_redact_dict_with_list():
    from ada.error_handler.redactor import redact_dict

    data = ["u1@x.com", "u2@x.com", {"phone": "010-0000-0000"}]
    result, types = redact_dict(data)
    assert "u1@" not in result[0]
    assert "u2@" not in result[1]
    assert "0000-0000" not in result[2]["phone"]


def test_redact_dict_preserves_non_str():
    from ada.error_handler.redactor import redact_dict

    data = {"count": 42, "ratio": 0.95, "flag": True, "email": "x@y.com"}
    result, _ = redact_dict(data)
    assert result["count"] == 42
    assert result["ratio"] == 0.95
    assert result["flag"] is True
    assert "<EMAIL>" in result["email"]


# =============================================================================
# 9. has_pii 빠른 체크
# =============================================================================


def test_has_pii_true():
    from ada.error_handler.redactor import has_pii

    assert has_pii("email me at x@y.com") is True
    assert has_pii("card 4532-1234-5678-9010") is True


def test_has_pii_false():
    from ada.error_handler.redactor import has_pii

    assert has_pii("hello world") is False
    assert has_pii("error in function process_data") is False
    assert has_pii("") is False
    assert has_pii(None) is False


# =============================================================================
# 10. redact_keys
# =============================================================================


def test_redact_keys_identifies_secrets():
    from ada.error_handler.redactor import redact_keys

    keys = {"name", "password", "user_token", "API_KEY", "url", "private_key"}
    secrets = redact_keys(keys)
    assert "password" in secrets
    assert "user_token" in secrets
    assert "API_KEY" in secrets
    assert "private_key" in secrets
    assert "name" not in secrets
    assert "url" not in secrets


# =============================================================================
# 11. 통합 — auto_handler.handle() 흐름에서 redact 적용 확인
# =============================================================================


def test_fingerprint_with_redacted_text_is_stable():
    """같은 패턴 다른 PII 값 → 같은 fingerprint hash (redact 후)."""
    from ada.error_handler.auto_handler import fingerprint
    from ada.error_handler.redactor import redact

    msg_a, _ = redact("login fail for alice@a.com")
    msg_b, _ = redact("login fail for bob@b.com")
    fp_a = fingerprint(msg_a, "")
    fp_b = fingerprint(msg_b, "")
    assert fp_a["hash"] == fp_b["hash"], "같은 패턴인데 다른 hash (redact 미적용 의심)"


def test_empty_input_safe():
    from ada.error_handler.redactor import redact

    assert redact("") == ("", [])
    assert redact(None) == ("", [])


def test_no_pii_input_unchanged():
    from ada.error_handler.redactor import redact

    text = "ValueError: x must be positive"
    out, types = redact(text)
    assert out == text
    assert types == []


# =============================================================================
# 12. False positive 회귀 방지
# =============================================================================


def test_version_string_not_treated_as_card():
    """4.5.6.7 같은 버전 문자열이 카드로 오인되면 안 됨."""
    from ada.error_handler.redactor import redact

    txt, _ = redact("Python 3.10.11 installed")
    assert "3.10.11" in txt
    assert "<CARD>" not in txt
