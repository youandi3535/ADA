"""ADR-006 Phase 2-B — 에러 분류기 단위 테스트.

5종 분류 정확도 + 전략 매트릭스 + 통합.
외부 의존성 0.
"""

from __future__ import annotations

# =============================================================================
# 1. TRANSIENT (네트워크 / 타임아웃)
# =============================================================================


def test_classify_connection_error():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("ConnectionError: Cannot connect to host") == ErrorClass.TRANSIENT


def test_classify_timeout_error():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("TimeoutError: read timed out") == ErrorClass.TRANSIENT


def test_classify_http_503():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("HTTPError 503 Service Unavailable") == ErrorClass.TRANSIENT


def test_classify_dns_lookup_failed():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("socket.gaierror: Name or service not known") == ErrorClass.TRANSIENT


def test_classify_connection_reset():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("ConnectionResetError: Connection reset by peer") == ErrorClass.TRANSIENT


# =============================================================================
# 2. CONFIG (환경변수 / 시크릿)
# =============================================================================


def test_classify_vault_error():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("hvac.exceptions.VaultError: invalid token") == ErrorClass.CONFIG


def test_classify_missing_env_var():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("KeyError: 'ANTHROPIC_API_KEY'") == ErrorClass.CONFIG


def test_classify_aws_key_missing():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("KeyError: 'AWS_ACCESS_KEY_ID'") == ErrorClass.CONFIG


def test_classify_settings_not_set():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("ValueError: Settings DATABASE_URL not set") == ErrorClass.CONFIG


# =============================================================================
# 3. DATA (입력 데이터)
# =============================================================================


def test_classify_pandas_empty():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("pandas.errors.EmptyDataError: No columns to parse") == ErrorClass.DATA


def test_classify_missing_column():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("KeyError: 'target' column missing") == ErrorClass.DATA


def test_classify_csv_not_found():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("FileNotFoundError: data.csv not found") == ErrorClass.DATA


def test_classify_schema_error():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("SchemaError: invalid column dtype") == ErrorClass.DATA


# =============================================================================
# 4. USER_INPUT (4xx 사용자 오류)
# =============================================================================


def test_classify_pydantic_validation():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("pydantic.ValidationError: 1 validation error") == ErrorClass.USER_INPUT


def test_classify_http_400():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("HTTPException 400 Bad Request") == ErrorClass.USER_INPUT


def test_classify_http_422():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("HTTPException 422 Unprocessable Entity") == ErrorClass.USER_INPUT


def test_classify_invalid_argument():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("InvalidArgument: target must be specified") == ErrorClass.USER_INPUT


# =============================================================================
# 5. CODE_BUG (실제 코드 버그)
# =============================================================================


def test_classify_attribute_error():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("AttributeError: 'NoneType' object has no attribute 'foo'") == ErrorClass.CODE_BUG


def test_classify_type_error():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("TypeError: unsupported operand type") == ErrorClass.CODE_BUG


def test_classify_import_error():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("ImportError: cannot import name 'foo'") == ErrorClass.CODE_BUG


def test_classify_module_not_found():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("ModuleNotFoundError: No module named 'xyz'") == ErrorClass.CODE_BUG


def test_classify_name_error():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("NameError: name 'undefined_var' is not defined") == ErrorClass.CODE_BUG


def test_classify_syntax_error():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("SyntaxError: invalid syntax") == ErrorClass.CODE_BUG


# =============================================================================
# 6. UNKNOWN (매칭 안 됨)
# =============================================================================


def test_classify_unknown_error():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("CustomError: something weird happened") == ErrorClass.UNKNOWN


def test_classify_empty_input():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify(None) == ErrorClass.UNKNOWN
    assert classify("") == ErrorClass.UNKNOWN


# =============================================================================
# 7. classify_with_reason
# =============================================================================


def test_classify_with_reason_returns_tuple():
    from ada.error_handler.classifier import ErrorClass, classify_with_reason

    cls, reason = classify_with_reason("ConnectionError: timeout")
    assert cls == ErrorClass.TRANSIENT
    assert "네트워크" in reason or "타임아웃" in reason


def test_classify_with_reason_unknown():
    from ada.error_handler.classifier import ErrorClass, classify_with_reason

    cls, reason = classify_with_reason("WeirdError: ...")
    assert cls == ErrorClass.UNKNOWN
    assert "매칭" in reason or "폴백" in reason


# =============================================================================
# 8. 전략 매트릭스
# =============================================================================


def test_strategy_transient_is_retry():
    from ada.error_handler.classifier import ErrorClass, HandlingStrategy, get_strategy

    assert get_strategy(ErrorClass.TRANSIENT) == HandlingStrategy.RETRY_BACKOFF


def test_strategy_code_bug_is_llm_patch():
    from ada.error_handler.classifier import ErrorClass, HandlingStrategy, get_strategy

    assert get_strategy(ErrorClass.CODE_BUG) == HandlingStrategy.LLM_PATCH


def test_strategy_config_is_human_only():
    from ada.error_handler.classifier import ErrorClass, HandlingStrategy, get_strategy

    assert get_strategy(ErrorClass.CONFIG) == HandlingStrategy.HUMAN_ONLY


def test_strategy_data_is_user_message():
    from ada.error_handler.classifier import ErrorClass, HandlingStrategy, get_strategy

    assert get_strategy(ErrorClass.DATA) == HandlingStrategy.USER_MESSAGE


def test_strategy_user_input_is_user_message():
    from ada.error_handler.classifier import ErrorClass, HandlingStrategy, get_strategy

    assert get_strategy(ErrorClass.USER_INPUT) == HandlingStrategy.USER_MESSAGE


def test_strategy_unknown_is_llm_patch():
    from ada.error_handler.classifier import ErrorClass, HandlingStrategy, get_strategy

    # 보수적 폴백 — 모르면 LLM
    assert get_strategy(ErrorClass.UNKNOWN) == HandlingStrategy.LLM_PATCH


# =============================================================================
# 9. should_skip_llm
# =============================================================================


def test_should_skip_llm_for_transient():
    from ada.error_handler.classifier import ErrorClass, should_skip_llm

    assert should_skip_llm(ErrorClass.TRANSIENT) is True


def test_should_skip_llm_for_config():
    from ada.error_handler.classifier import ErrorClass, should_skip_llm

    assert should_skip_llm(ErrorClass.CONFIG) is True


def test_should_skip_llm_for_data():
    from ada.error_handler.classifier import ErrorClass, should_skip_llm

    assert should_skip_llm(ErrorClass.DATA) is True


def test_should_call_llm_for_code_bug():
    from ada.error_handler.classifier import ErrorClass, should_skip_llm

    assert should_skip_llm(ErrorClass.CODE_BUG) is False


def test_should_call_llm_for_unknown():
    from ada.error_handler.classifier import ErrorClass, should_skip_llm

    assert should_skip_llm(ErrorClass.UNKNOWN) is False


# =============================================================================
# 10. 우선순위 회귀 (CONFIG > TRANSIENT > DATA > USER_INPUT > CODE_BUG)
# =============================================================================


def test_config_takes_priority_over_others():
    """ENV 변수 KeyError 는 CONFIG (CODE_BUG 의 KeyError 가 아님)."""
    from ada.error_handler.classifier import ErrorClass, classify

    msg = "KeyError: 'ANTHROPIC_API_KEY'"
    assert classify(msg) == ErrorClass.CONFIG


def test_data_csv_not_data_code_bug():
    """FileNotFoundError 의 .csv 는 DATA (CODE_BUG 가 아님)."""
    from ada.error_handler.classifier import ErrorClass, classify

    msg = "FileNotFoundError: /home/user/data.csv not found"
    assert classify(msg) == ErrorClass.DATA
