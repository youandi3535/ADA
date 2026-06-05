"""outputs.context.code_extractor — CodeArtifacts (⑪) 적립기 (Phase 1.9).

분석 파이프라인의 핵심 코드 스니펫을 ``ReportContext.code`` 로 적립.
HTML 사이드카 zip (Option β) 의 원본이 된다.

추출 대상:
    1. **Preprocessing 파이프라인 코드** — 카테고리별 handler 의 apply 함수 또는
       state.preprocessing_plan 으로부터 재구성된 의사코드.
    2. **모델 스펙** — best_model.model_name + best_params 로부터 재현 가능한
       모델 정의 코드 (sklearn/lightgbm/xgboost 등).
    3. **추론 스니펫** — 학습 모델을 로드해 추론하는 최소 예제.
    4. **README** — 보고서·코드 구성 안내 (한국어 기본).

모든 산출 코드는 ``ada.security.code_redactor.redact_code`` 통과본만 저장.
실코드 추출이 어려우면 의사코드(pseudocode) 로 폴백 — Companion zip 은 항상 생성.

설계:
    - 멱등: 같은 state 입력 → 같은 출력.
    - silent-safe: 추출 실패해도 빈 CodeArtifacts 반환 (carrier 호출 차단 X).
    - state 미수정: state.report_context 갱신은 caller 가 contribute_to_context 로.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Optional

from ada.core.state import PipelineState
from ada.security.code_redactor import RedactionReport, redact_code
from outputs.context.schema import (
    CodeArtifacts,
    CodeFile,
    NotebookCell,
)

# ==============================================================
# 공개 API
# ==============================================================


def extract_code_artifacts(state: PipelineState) -> CodeArtifacts:
    """``state`` 로부터 ``CodeArtifacts`` 빌드. silent-safe.

    Returns:
        CodeArtifacts — 모든 코드는 redactor 통과본. 환경 정보·재현 명령 포함.
    """
    files: list[CodeFile] = []
    cells: list[NotebookCell] = []
    cumulative = _CumulativeRedactionReport()

    # ── 1) 전처리 코드 ─────────────────────────────────────────
    try:
        preproc_code = _build_preprocessing_code(state)
        if preproc_code:
            masked, rep = redact_code(preproc_code, language="python")
            files.append(
                CodeFile(
                    path="pipeline/preprocess.py",
                    language="python",
                    content=masked,
                    description_ko="전처리 단계 — DataProfiler·PreprocessingStrategist 가 결정한 step 의 재현 코드.",
                )
            )
            cumulative.merge(rep)
    except Exception:
        pass

    # ── 2) 모델 스펙 ───────────────────────────────────────────
    try:
        model_code = _build_model_spec_code(state)
        if model_code:
            masked, rep = redact_code(model_code, language="python")
            files.append(
                CodeFile(
                    path="pipeline/model_spec.py",
                    language="python",
                    content=masked,
                    description_ko="최적 모델 정의 — best_model.model_name 과 best_params 를 사용한 재현 코드.",
                )
            )
            cumulative.merge(rep)
    except Exception:
        pass

    # ── 3) 추론 스니펫 ─────────────────────────────────────────
    try:
        infer_code = _build_infer_code(state)
        if infer_code:
            masked, rep = redact_code(infer_code, language="python")
            files.append(
                CodeFile(
                    path="pipeline/infer.py",
                    language="python",
                    content=masked,
                    description_ko="학습 모델 로드 + 단건 추론 최소 예제.",
                )
            )
            cumulative.merge(rep)
    except Exception:
        pass

    # ── 4) README ──────────────────────────────────────────────
    try:
        readme = _build_readme(state, files)
        from ada.security.code_redactor import redact_text_block

        masked, rep = redact_text_block(readme)
        files.append(
            CodeFile(
                path="README.md",
                language="markdown",
                content=masked,
                description_ko="Companion 코드 구성·재현 안내.",
            )
        )
        cumulative.merge(rep)
    except Exception:
        pass

    # ── 5) requirements.txt 스냅샷 ─────────────────────────────
    env_info = _snapshot_env()
    try:
        req_text = _build_requirements_txt(env_info.get("key_packages") or {})
        files.append(
            CodeFile(
                path="requirements.txt",
                language="text",
                content=req_text,
                description_ko="실행 환경 핵심 패키지 버전 스냅샷.",
            )
        )
    except Exception:
        pass

    # ── 6) Notebook cells (선택 — 본 단계에서는 files 만으로 충분) ─
    # NotebookBuilder (Phase 6 의 zip_bundler) 가 files → cells 변환 담당.

    reproduce_cmd = "python pipeline/preprocess.py && python pipeline/model_spec.py && python pipeline/infer.py"

    return CodeArtifacts(
        files=files,
        notebook_cells=cells,
        environment=env_info,
        reproduce_command=reproduce_cmd,
        redaction_report=cumulative.to_dict(),
    )


# ==============================================================
# 코드 빌더 — best-effort 의사코드 우선
# ==============================================================


def _build_preprocessing_code(state: PipelineState) -> str:
    """state.preprocessing_plan → 재현 가능한 Python 코드."""
    plan = state.preprocessing_plan or []
    if not plan:
        return ""

    lines = [
        '"""전처리 파이프라인 — ADA 자동 생성."""',
        "from __future__ import annotations",
        "",
        "import pandas as pd",
        "from sklearn.impute import SimpleImputer",
        "from sklearn.preprocessing import StandardScaler, OneHotEncoder",
        "",
        "",
        "def preprocess(df: pd.DataFrame) -> pd.DataFrame:",
        '    """전처리 단계 — DataProfiler·Strategist 결정 재현."""',
        "    out = df.copy()",
    ]
    for i, step in enumerate(plan):
        if not isinstance(step, dict):
            continue
        op = str(step.get("name") or step.get("op") or f"step_{i}")
        rationale = str(step.get("rationale") or "")
        cols = step.get("columns") or step.get("scope") or []
        params = {k: v for k, v in step.items() if k not in ("name", "op", "columns", "scope", "rationale")}
        lines.append("")
        lines.append(f"    # ── {op} ──  {rationale}".rstrip())
        if op.startswith("impute"):
            strategy = step.get("strategy", "median")
            target_cols = cols or "out.select_dtypes(include='number').columns"
            lines.append(
                f"    cols = {target_cols!r} if isinstance({target_cols!r}, list) else list(out.select_dtypes(include='number').columns)"
            )
            lines.append(f"    out[cols] = SimpleImputer(strategy={strategy!r}).fit_transform(out[cols])")
        elif op.startswith("scale") or op == "standard_scale":
            target_cols = cols or "list(out.select_dtypes(include='number').columns)"
            lines.append(
                f"    cols = {target_cols!r} if isinstance({target_cols!r}, list) else list(out.select_dtypes(include='number').columns)"
            )
            lines.append("    out[cols] = StandardScaler().fit_transform(out[cols])")
        elif op.startswith("encode") or op == "onehot":
            target_cols = cols or "list(out.select_dtypes(include='object').columns)"
            lines.append(
                f"    cols = {target_cols!r} if isinstance({target_cols!r}, list) else list(out.select_dtypes(include='object').columns)"
            )
            lines.append("    if cols:")
            lines.append("        enc = OneHotEncoder(handle_unknown='ignore', sparse_output=False)")
            lines.append("        arr = enc.fit_transform(out[cols])")
            lines.append(
                "        out = pd.concat([out.drop(columns=cols), pd.DataFrame(arr, index=out.index)], axis=1)"
            )
        else:
            # 알 수 없는 step — 의사코드 주석
            params_str = json.dumps(params, ensure_ascii=False)[:200] if params else ""
            lines.append(f"    # TODO: {op} ({params_str})  — 의사코드, 수동 구현 필요")
    lines.append("    return out")
    lines.append("")
    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append("    import sys")
    lines.append("    df = pd.read_csv(sys.argv[1])")
    lines.append("    out = preprocess(df)")
    lines.append('    out.to_parquet("preprocessed.parquet")')
    return "\n".join(lines) + "\n"


def _build_model_spec_code(state: PipelineState) -> str:
    """best_model + best_params → 모델 스펙 재현 코드."""
    bm = state.best_model or {}
    name = bm.get("model_name") or ""
    framework = bm.get("framework") or ""
    params = bm.get("hyperparameters") or (state.best_params or {}).get(name) or {}
    if not name:
        return ""

    lines = [
        '"""모델 스펙 — ADA 자동 생성."""',
        "from __future__ import annotations",
        "",
    ]
    lname = name.lower()
    if "xgb" in lname:
        lines += [
            "import xgboost as xgb",
            "",
            "",
            "def build_model() -> xgb.XGBClassifier:",
            f"    return xgb.XGBClassifier(**{_safe_repr(params)})",
        ]
    elif "lightgbm" in lname or "lgbm" in lname:
        lines += [
            "import lightgbm as lgb",
            "",
            "",
            "def build_model() -> lgb.LGBMClassifier:",
            f"    return lgb.LGBMClassifier(**{_safe_repr(params)})",
        ]
    elif "catboost" in lname:
        lines += [
            "from catboost import CatBoostClassifier",
            "",
            "",
            "def build_model() -> CatBoostClassifier:",
            f"    return CatBoostClassifier(**{_safe_repr(params)}, verbose=False)",
        ]
    elif "randomforest" in lname or "random_forest" in lname:
        lines += [
            "from sklearn.ensemble import RandomForestClassifier",
            "",
            "",
            "def build_model() -> RandomForestClassifier:",
            f"    return RandomForestClassifier(**{_safe_repr(params)})",
        ]
    elif lname in ("arima", "sarima"):
        lines += [
            "from statsmodels.tsa.arima.model import ARIMA",
            "",
            "",
            "def build_model(y):",
            f"    return ARIMA(y, **{_safe_repr(params)})",
        ]
    elif "prophet" in lname:
        lines += [
            "from prophet import Prophet",
            "",
            "",
            "def build_model() -> Prophet:",
            f"    return Prophet(**{_safe_repr(params)})",
        ]
    elif "isolationforest" in lname or "isolation_forest" in lname:
        lines += [
            "from sklearn.ensemble import IsolationForest",
            "",
            "",
            "def build_model() -> IsolationForest:",
            f"    return IsolationForest(**{_safe_repr(params)})",
        ]
    else:
        # 알 수 없는 모델 — 의사코드
        lines += [
            f"# TODO: 모델 '{name}' (framework={framework or 'unknown'}) 의 구체 import 가 필요합니다.",
            "",
            "",
            "def build_model():",
            f"    # ADA 가 선정한 모델: {name}",
            f"    # 권장 하이퍼파라미터: {_safe_repr(params)}",
            f"    raise NotImplementedError('수동 import: {name}')",
        ]
    return "\n".join(lines) + "\n"


def _build_infer_code(state: PipelineState) -> str:
    """학습 모델 로드 → 단건 추론 최소 예제."""
    bm = state.best_model or {}
    name = bm.get("model_name") or ""
    if not name:
        return ""
    return (
        '"""추론 예제 — ADA 자동 생성."""\n'
        "from __future__ import annotations\n\n"
        "import pickle\n"
        "import pandas as pd\n\n"
        "from pipeline.preprocess import preprocess\n"
        "from pipeline.model_spec import build_model\n\n"
        "\n"
        "def infer(df: pd.DataFrame, model_path: str = 'model.pkl'):\n"
        '    """단건 추론 — 전처리 후 모델 예측."""\n'
        "    X = preprocess(df)\n"
        "    with open(model_path, 'rb') as f:\n"
        "        model = pickle.load(f)\n"
        "    return model.predict(X)\n\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    import sys\n"
        "    df = pd.read_csv(sys.argv[1])\n"
        "    print(infer(df, sys.argv[2] if len(sys.argv) > 2 else 'model.pkl'))\n"
    )


def _build_readme(state: PipelineState, files: list[CodeFile]) -> str:
    """README — 한국어, 구성 안내."""
    job_id = state.job_id or "(unknown)"
    category = state.category or "(unknown)"
    intent = state.user_intent or state.user_question or "(미지정)"
    file_lines = "\n".join(f"- `{f.path}` — {f.description_ko}" for f in files)
    return (
        f"# ADA 분석 코드 — {job_id}\n\n"
        f"- **카테고리**: {category}\n"
        f"- **분석 의도**: {intent}\n\n"
        f"## 구성\n\n{file_lines}\n\n"
        "## 재현 절차\n\n"
        "```bash\n"
        "pip install -r requirements.txt\n"
        "python pipeline/preprocess.py <data.csv>\n"
        "python pipeline/model_spec.py\n"
        "python pipeline/infer.py <data.csv> model.pkl\n"
        "```\n\n"
        "## 주의 사항\n\n"
        "- 본 코드는 ADA 가 분석 결과를 토대로 자동 생성한 재현용 스니펫입니다.\n"
        "- 민감 정보(키·내부 호스트·DB DSN)는 자동 마스킹되었습니다.\n"
        "- 일부 단계는 의사코드일 수 있습니다 — `TODO:` 주석을 참고해 수동 보완하세요.\n"
    )


def _build_requirements_txt(packages: dict[str, str]) -> str:
    """key_packages dict → requirements.txt 직렬화."""
    if not packages:
        return "# (패키지 정보를 환경에서 추출하지 못했습니다)\n"
    lines = [f"{name}=={ver}" for name, ver in sorted(packages.items())]
    return "\n".join(lines) + "\n"


# ==============================================================
# 환경 스냅샷
# ==============================================================


def _snapshot_env() -> dict[str, Any]:
    """실행 환경 핵심 패키지 버전 스냅샷.

    실패해도 빈 dict — Companion zip 은 그대로 생성.
    """
    key_pkgs = (
        "pandas",
        "numpy",
        "scikit-learn",
        "scipy",
        "xgboost",
        "lightgbm",
        "catboost",
        "torch",
        "tensorflow",
        "statsmodels",
        "prophet",
        "fastapi",
        "pydantic",
        "sqlalchemy",
        "langgraph",
        "mlflow",
        "minio",
    )
    versions: dict[str, str] = {}
    for pkg in key_pkgs:
        try:
            import importlib.metadata as md

            versions[pkg] = md.version(pkg)
        except Exception:
            continue
    return {
        "python": ".".join(str(v) for v in sys.version_info[:3]),
        "key_packages": versions,
    }


# ==============================================================
# 내부 유틸
# ==============================================================


def _safe_repr(value: Any) -> str:
    """dict 등을 Python literal 로 안전 직렬화. 너무 길면 축약."""
    try:
        rep = repr(value)
        if len(rep) > 800:
            return rep[:800] + "  # ... (truncated)"
        return rep
    except Exception:
        return "{}"


class _CumulativeRedactionReport:
    """여러 redact 호출의 통계 누적기."""

    def __init__(self) -> None:
        self.redacted_count = 0
        self.categories: dict[str, int] = {}

    def merge(self, report: RedactionReport) -> None:
        self.redacted_count += report.redacted_count
        for k, v in report.categories.items():
            self.categories[k] = self.categories.get(k, 0) + v

    def to_dict(self) -> dict[str, Any]:
        return {"redacted_count": self.redacted_count, "categories": dict(self.categories)}


# ==============================================================
# Convenience — state 에 직접 적립
# ==============================================================


def contribute_code_artifacts(agent: Any, state: PipelineState) -> PipelineState:
    """agent.contribute_to_context 로 ⑪ code 적립까지 일괄.

    Architect / Phase 2 의 G7-α (PipelineTraceFinalizer) 가 호출.
    """
    try:
        artifacts = extract_code_artifacts(state)
        payload = {
            "files": [_codefile_to_dict(f) for f in artifacts.files],
            "notebook_cells": [_notebookcell_to_dict(c) for c in artifacts.notebook_cells],
            "environment": dict(artifacts.environment),
            "reproduce_command": artifacts.reproduce_command,
            "redaction_report": dict(artifacts.redaction_report),
        }
        return agent.contribute_to_context(state, "code", payload)
    except Exception:
        return state


def _codefile_to_dict(f: CodeFile) -> dict[str, Any]:
    return {
        "path": f.path,
        "language": f.language,
        "content": f.content,
        "description_ko": f.description_ko,
        "description_en": f.description_en,
    }


def _notebookcell_to_dict(c: NotebookCell) -> dict[str, Any]:
    return {
        "cell_type": c.cell_type,
        "source": c.source,
        "outputs": c.outputs,
    }


# ==============================================================
# 호환성 — Optional 위한 stub (typing 도구가 깨지지 않게)
# ==============================================================

Optional  # re-export silencer
