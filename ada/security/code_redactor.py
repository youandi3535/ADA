"""ada.security.code_redactor — 코드 산출물 IP·Secret 필터 (Phase 1.8).

목적:
    Companion zip / Appendix 슬라이드에 노출되는 코드에서 다음을 자동 마스킹:
        · 클라우드 액세스 키 (AWS / GCP / Azure / 일반 토큰 패턴)
        · 내부 호스트·엔드포인트 (`*.internal`, 사내 IP CIDR)
        · MinIO/S3 버킷 경로
        · DB connection string
        · 절대 경로 (`/home/...`, `C:\\Users\\...`)
        · 회사명·프로젝트 코드네임 (화이트리스트 외 차단)
        · 주석 내 이메일·이름 — R-103 PII 마스킹 재활용

R-103 (PII) 와의 분리:
    PIIAnonymizer 는 데이터 행/LLM 응답 양방향 마스킹 (mapping 보존).
    code_redactor 는 **단방향** — 코드 텍스트를 영구 마스킹, 복원 불가.

설계:
    - silent-safe: 패턴 매칭 실패해도 raise 안 함.
    - 통계 동행: ``redact_code(text)`` 는 ``(masked_text, report)`` 반환,
      report.categories 가 종류별 redaction 횟수 → CodeArtifacts.redaction_report 로.
    - 화이트리스트는 모듈 상수 — 사용자가 도메인 용어 확장 시 수정.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# R-103 PII 패턴 재활용 — 코드 주석의 이메일·전화 등도 마스킹.
from ada.security._pii_patterns import COMMON_PATTERNS as PII_PATTERNS

# ==============================================================
# 화이트리스트 — 사내 표준 용어 (마스킹 제외)
# ==============================================================

# 회사명/프로젝트명 화이트리스트 — 이 외 코드네임은 차단 가능 (옵션)
_NAME_WHITELIST: set[str] = {
    "ADA",
    "ada",
    "ADAv2",
    "ada_v2",
    "Python",
    "FastAPI",
    "LangGraph",
    "Pydantic",
    "SQLAlchemy",
    "Alembic",
    "Celery",
    "MinIO",
    "PostgreSQL",
    "MLflow",
    "Langfuse",
    "Pandas",
    "NumPy",
    "scikit-learn",
    "XGBoost",
    "LightGBM",
    "CatBoost",
    "PyTorch",
    "TensorFlow",
    "Prophet",
    "ARIMA",
    "SARIMA",
    "Informer",
    "TFT",
}

# 표준 라이브러리·일반 도메인 단어 — 식별자 패턴이라도 노출 무해
_SAFE_IDENTIFIER_PREFIXES = ("test_", "tests_", "self.", "cls.", "ada.", "agents.", "outputs.")


# ==============================================================
# 마스킹 패턴
# ==============================================================

# 클라우드/토큰
_AWS_ACCESS_KEY = re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")
_AWS_SECRET = re.compile(r"(?i)(aws(.{0,20})?(secret|sk)|secret_access_key)\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{30,})['\"]?")
_GCP_SERVICE_ACCOUNT = re.compile(r"-----BEGIN PRIVATE" + r" KEY-----[\s\S]+?-----END PRIVATE" + r" KEY-----")
_AZURE_KEY = re.compile(r"\b[A-Za-z0-9+/]{86}==\b")
_GENERIC_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}")
_GENERIC_API_KEY_ASSIGN = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|passwd)\s*[:=]\s*['\"]([^'\"\s]{8,})['\"]"
)
_OPENAI_OR_ANTHROPIC = re.compile(r"\b(sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_\-]{20,})\b")
_GITHUB_TOKEN = re.compile(r"\bghp_[A-Za-z0-9]{30,}\b|\bgho_[A-Za-z0-9]{30,}\b")
# JWT — 3-segment base64url (eyJ... . eyJ... . sig)
_JWT_TOKEN = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")
# OAuth refresh/access_token 변수 할당
_OAUTH_TOKEN_ASSIGN = re.compile(r"(?i)(refresh_token|access_token|id_token)\s*[:=]\s*['\"]([^'\"\s]{16,})['\"]")
# SSH 개인 키 (RSA / EC / ED25519 / OPENSSH 등 변종)
_SSH_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ED25519 )?PRIVATE"
    + r" KEY-----[\s\S]+?-----END (?:RSA |EC |DSA |OPENSSH |ED25519 )?PRIVATE"
    + r" KEY-----"
)
# TLS / X.509 certificate
_TLS_CERT = re.compile(r"-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----")
# .env 스타일 변수 — DATABASE_URL=, REDIS_URL= 등 (값 8자 이상)
_DOT_ENV_VAR = re.compile(
    r"(?m)^\s*([A-Z][A-Z0-9_]*(?:URL|HOST|PORT|KEY|TOKEN|SECRET|PASSWORD|PWD|DSN|CONN|ENDPOINT))\s*=\s*[\"']?([^\"'\s#]{8,})[\"']?"
)

# 호스트/엔드포인트/경로
_INTERNAL_HOST = re.compile(r"\b[A-Za-z0-9._-]+\.internal(?:[:/][A-Za-z0-9._:/?#&=\-]*)?\b")
_PRIVATE_IP = re.compile(
    r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b"
)
_S3_OR_MINIO = re.compile(r"\b(s3|gs|azure)://[A-Za-z0-9._\-]+/[A-Za-z0-9._\-/?#&=]*")
_DB_DSN = re.compile(
    r"\b(postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://"
    r"[A-Za-z0-9._\-]+(?::[^\s@]+)?@[A-Za-z0-9._\-]+(?::\d+)?(?:/[A-Za-z0-9._\-]+)?"
)
_ABS_POSIX_PATH = re.compile(r"\B(/home/[A-Za-z0-9._\-]+|/root|/var/[A-Za-z0-9._\-/]+|/etc/[A-Za-z0-9._\-/]+)\b")
_ABS_WIN_PATH = re.compile(r"\b[A-Za-z]:\\\\?(Users|IT|workspace|workspace_python)[\\\\][A-Za-z0-9._\-\\\\]*")

# 회사명/프로젝트 코드네임 (휴리스틱) — 영문 PascalCase 2단어+
_CODENAME = re.compile(r"\b([A-Z][a-z]{2,}){2,}\b")


# ==============================================================
# 결과 dataclass
# ==============================================================


@dataclass
class RedactionReport:
    """마스킹 통계 — CodeArtifacts.redaction_report 에 저장 가능 형태."""

    redacted_count: int = 0
    categories: dict[str, int] = field(default_factory=dict)
    samples: list[str] = field(default_factory=list)  # 디버깅용 — 최대 5건

    def to_dict(self) -> dict[str, Any]:
        return {
            "redacted_count": self.redacted_count,
            "categories": dict(self.categories),
        }

    def _bump(self, category: str, sample: str = "") -> None:
        self.categories[category] = self.categories.get(category, 0) + 1
        self.redacted_count += 1
        if sample and len(self.samples) < 5:
            self.samples.append(f"[{category}] {sample[:80]}")


# ==============================================================
# 공개 API
# ==============================================================


def redact_code(text: str, *, language: str = "python", strict_codename: bool = False) -> tuple[str, RedactionReport]:
    """코드 텍스트를 마스킹.

    Args:
        text: 원본 코드.
        language: "python" 외 "yaml"/"json"/"shell" — 미사용 (placeholder).
        strict_codename: True 면 화이트리스트 외 PascalCase 코드네임도 차단.

    Returns:
        (masked_text, report)
    """
    if not text:
        return "", RedactionReport()

    report = RedactionReport()
    out = text

    # ── 시크릿/키 ──────────────────────────────────────────────
    # 다중라인 블록(SSH/TLS/GCP) 을 먼저 — 토큰 패턴이 블록 안 내용 매칭 못 하도록.
    out, _ = _sub_count(out, _SSH_PRIVATE_KEY, "[REDACTED_SSH_PRIVATE_KEY]", report, "ssh_private_key")
    out, _ = _sub_count(out, _GCP_SERVICE_ACCOUNT, "[REDACTED_PRIVATE_KEY]", report, "gcp_private_key")
    out, _ = _sub_count(out, _TLS_CERT, "[REDACTED_CERTIFICATE]", report, "tls_certificate")
    # 토큰/키
    out, _ = _sub_count(out, _JWT_TOKEN, "[REDACTED_JWT]", report, "jwt_token")
    out, _ = _sub_count(out, _AWS_ACCESS_KEY, "[REDACTED_AWS_KEY]", report, "aws_access_key")
    out, _ = _sub_count(
        out,
        _AWS_SECRET,
        lambda m: f"{m.group(1)}=[REDACTED_AWS_SECRET]",
        report,
        "aws_secret",
    )
    out, _ = _sub_count(out, _OPENAI_OR_ANTHROPIC, "[REDACTED_LLM_KEY]", report, "llm_api_key")
    out, _ = _sub_count(out, _GITHUB_TOKEN, "[REDACTED_GH_TOKEN]", report, "github_token")
    out, _ = _sub_count(
        out,
        _OAUTH_TOKEN_ASSIGN,
        lambda m: f'{m.group(1)}="[REDACTED_OAUTH]"',
        report,
        "oauth_token",
    )
    out, _ = _sub_count(
        out,
        _GENERIC_API_KEY_ASSIGN,
        lambda m: f"{m.group(1)}={m.group(0).split('=')[-1][0]}[REDACTED]",
        report,
        "generic_api_key",
    )
    out, _ = _sub_count(
        out,
        _DOT_ENV_VAR,
        lambda m: f"{m.group(1)}=[REDACTED_ENV]",
        report,
        "dot_env_var",
    )
    out, _ = _sub_count(out, _GENERIC_BEARER, "Bearer [REDACTED_TOKEN]", report, "bearer_token")
    out, _ = _sub_count(out, _AZURE_KEY, "[REDACTED_AZURE_KEY]", report, "azure_key")

    # ── 인프라/경로 ────────────────────────────────────────────
    out, _ = _sub_count(out, _DB_DSN, _db_dsn_replace, report, "db_dsn")
    out, _ = _sub_count(out, _S3_OR_MINIO, _bucket_replace, report, "cloud_path")
    out, _ = _sub_count(out, _INTERNAL_HOST, "[INTERNAL_HOST]", report, "internal_host")
    out, _ = _sub_count(out, _PRIVATE_IP, "[PRIVATE_IP]", report, "private_ip")
    out, _ = _sub_count(out, _ABS_POSIX_PATH, "<workspace>/...", report, "abs_path_posix")
    out, _ = _sub_count(out, _ABS_WIN_PATH, "<workspace>\\...", report, "abs_path_windows")

    # ── 주석/코멘트 안의 PII (R-103 재활용) ─────────────────────
    for kind, pat in PII_PATTERNS:
        out, n = _sub_count(out, pat, "***", report, f"pii_{kind}")
        # 통계는 _sub_count 가 처리

    # ── 코드네임 (옵션) ────────────────────────────────────────
    if strict_codename:

        def _name_repl(m: re.Match) -> str:
            tok = m.group(0)
            if tok in _NAME_WHITELIST:
                return tok
            return "[REDACTED_NAME]"

        out, _ = _sub_count(out, _CODENAME, _name_repl, report, "codename")

    return out, report


def redact_text_block(text: str) -> tuple[str, RedactionReport]:
    """비코드 텍스트(README·주석 블록·log)도 같은 룰로 마스킹.

    사실상 ``redact_code`` 와 동일하지만 strict_codename=False 기본.
    """
    return redact_code(text, language="text", strict_codename=False)


# ==============================================================
# 내부 헬퍼
# ==============================================================


def _sub_count(
    text: str, pattern: re.Pattern[str], repl: Any, report: RedactionReport, category: str
) -> tuple[str, int]:
    """``re.sub`` + count. report 에 통계 누적.

    repl 이 callable 이면 그대로 사용 (re.sub 가 호출).
    """
    if not text:
        return text, 0
    count = 0

    def _wrap(m: re.Match) -> str:
        nonlocal count
        count += 1
        sample = m.group(0)
        report._bump(category, sample)
        if callable(repl):
            try:
                return repl(m)
            except Exception:
                return "[REDACTED]"
        return str(repl)

    new_text = pattern.sub(_wrap, text)
    return new_text, count


def _db_dsn_replace(m: re.Match) -> str:
    """DSN 의 사용자/패스워드/호스트 모두 마스킹, 스킴만 보존."""
    scheme = m.group(0).split("://", 1)[0]
    return f"{scheme}://[REDACTED_DSN]"


def _bucket_replace(m: "re.Match[str]") -> str:
    # s3://my-bucket/path -> s3://<BUCKET>/...
    raw = m.group(0)
    scheme = raw.split("://", 1)[0]
    return f"{scheme}://<BUCKET>/..."
