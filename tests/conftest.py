"""pytest 공통 fixture — Day14."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

# Prophet/CmdStan: Windows 환경 자동 설정
import pathlib as _pathlib
import sys as _sys

if _sys.platform == "win32":
    # 1) MinGW DLL 경로 추가 (PATH + add_dll_directory)
    _mingw_bin = _pathlib.Path(r"C:\Program Files\Git\mingw64\bin")
    if _mingw_bin.exists():
        os.environ["PATH"] = str(_mingw_bin) + os.pathsep + os.environ.get("PATH", "")
        os.add_dll_directory(str(_mingw_bin))

    # 2) prophet stan_model 디렉토리를 DLL 검색 경로에 추가
    #    prophet_model.bin 이 요구하는 tbb.dll 이 여기에 있음
    try:
        import prophet as _prophet

        _stan_dir = _pathlib.Path(_prophet.__file__).parent / "stan_model"
        if _stan_dir.exists():
            os.add_dll_directory(str(_stan_dir))
    except ImportError:
        pass

# 3) CMDSTAN 경로: 시스템에 설치된 cmdstan 자동 감지
if "CMDSTAN" not in os.environ:
    _base = _pathlib.Path.home() / ".cmdstan"
    if _base.exists():
        _installs = sorted(_base.glob("cmdstan-*"), reverse=True)
        if _installs:
            os.environ["CMDSTAN"] = str(_installs[0])
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "test")


@pytest.fixture
def titanic_df():
    import pandas as pd

    return pd.DataFrame(
        {
            "Pclass": [1, 2, 3, 1, 3, 2, 1, 3, 2, 3] * 12,
            "Age": [22, 35, 26, 54, 2, 27, 14, 4, 58, 20] * 12,
            "Fare": [7.25, 71.83, 7.92, 51.86, 21.07, 11.13, 30.07, 16.7, 26.55, 8.05] * 12,
            "Sex_male": [1, 0, 0, 0, 1, 1, 1, 0, 0, 1] * 12,
            "Survived": [0, 1, 1, 1, 0, 0, 0, 1, 1, 0] * 12,
        }
    )


@pytest.fixture
def pipeline_state_min():
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000001",
        file_id="uploads/test/iris.csv",
        category="tabular_ml",
        target_column="Survived",
        user_intent="고객 생존 예측",
    )
