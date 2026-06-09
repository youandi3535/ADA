"""tools.visual.stock_image — Stock 사진 API + 로컬 캐시 (Unsplash·Pexels·Pixabay).

env 우선순위 (있는 것만 사용):
    UNSPLASH_ACCESS_KEY : 50 req/h, 고품질
    PEXELS_API_KEY      : 200 req/h, 고품질
    PIXABAY_API_KEY     : 사실상 무제한, 품질 중급

캐시:
    assets/cache/stock_images/<keyword_hash>.jpg
    한 번 다운받은 키워드는 재사용 (offline 작동).

키워드 매핑 (슬라이드 ID → 검색 키워드):
    cover            → "business office cityscape"
    section_divider  → "abstract gradient blue"
    p1_market        → "city skyline business"
    method_model     → "data analytics dashboard"
    architecture     → "server room technology"
    closing          → "team handshake meeting"

HJ 단독 영역.
"""

from __future__ import annotations

import hashlib
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

# 캐시 디렉토리
_CACHE_DIR = Path(__file__).resolve().parents[2] / "assets" / "cache" / "stock_images"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 슬라이드 ID → 검색 키워드 매핑
_KEYWORD_BY_SLIDE: dict[str, str] = {
    "cover": "business meeting professional",
    "exec_summary": "business analytics dashboard",
    "agenda": "abstract blue gradient minimal",
    "hypothesis": "lightbulb idea thinking",
    "p1_market": "city skyline business district",
    "p2_pain": "frustrated workplace office",
    "p3_alt_limits": "old technology legacy",
    "why_dl": "neural network ai brain",
    "why_timeseries": "time clock data flow",
    "why_anomaly": "fraud detection security",
    "why_ml": "data analytics insights",
    "method_model": "machine learning model architecture",
    "architecture_deep": "server room datacenter blue",
    "tech_architecture": "cloud infrastructure abstract",
    "tech_stack": "code developer screen",
    "s3_differentiation": "competitive business strategy",
    "i1_kpi": "performance dashboard graphs",
    "training_dynamics": "growth chart progress",
    "eda_findings": "data visualization research",
    "error_analysis": "magnifying glass investigation",
    "score_distribution": "statistics analysis chart",
    "forecast_plot": "forecast chart predictive",
    "insights_derived": "insight discovery aha",
    "as_is_to_be": "transformation before after",
    "i3_roi": "business growth profit",
    "risk_mitigation": "shield protection security",
    "roadmap": "roadmap journey path forward",
    "closing": "team success celebration handshake",
}

# Sentinel — 인터넷·키 없을 때 placeholder 안전 반환
_PLACEHOLDER_PNG = b""  # 빈 이미지 → caller 가 None 처리


def _cache_key(keyword: str, width: int, height: int) -> Path:
    """키워드+사이즈로 캐시 파일 경로 생성."""
    h = hashlib.md5(f"{keyword}|{width}x{height}".encode()).hexdigest()[:16]
    return _CACHE_DIR / f"{h}.jpg"


def _try_unsplash(keyword: str, width: int, height: int) -> bytes | None:
    """Unsplash API — UNSPLASH_ACCESS_KEY env 필요."""
    key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not key:
        return None
    try:
        q = urllib.parse.quote(keyword)
        url = f"https://api.unsplash.com/photos/random?query={q}&orientation=landscape&client_id={key}"
        req = urllib.request.Request(url, headers={"Accept-Version": "v1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json

            data = json.loads(resp.read())
        img_url = data.get("urls", {}).get("regular")
        if not img_url:
            return None
        # 이미지 다운로드
        with urllib.request.urlopen(img_url, timeout=15) as img_resp:
            return img_resp.read()
    except Exception:
        return None


def _try_pexels(keyword: str, width: int, height: int) -> bytes | None:
    """Pexels API — PEXELS_API_KEY env 필요."""
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return None
    try:
        q = urllib.parse.quote(keyword)
        url = f"https://api.pexels.com/v1/search?query={q}&per_page=1&orientation=landscape"
        req = urllib.request.Request(url, headers={"Authorization": key})
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json

            data = json.loads(resp.read())
        photos = data.get("photos", [])
        if not photos:
            return None
        img_url = photos[0].get("src", {}).get("large2x")
        if not img_url:
            return None
        with urllib.request.urlopen(img_url, timeout=15) as img_resp:
            return img_resp.read()
    except Exception:
        return None


def _try_pixabay(keyword: str, width: int, height: int) -> bytes | None:
    """Pixabay API — PIXABAY_API_KEY env 필요."""
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return None
    try:
        q = urllib.parse.quote(keyword)
        url = (
            f"https://pixabay.com/api/?key={key}&q={q}&image_type=photo"
            "&orientation=horizontal&safesearch=true&per_page=3"
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            import json

            data = json.loads(resp.read())
        hits = data.get("hits", [])
        if not hits:
            return None
        img_url = hits[0].get("largeImageURL")
        if not img_url:
            return None
        with urllib.request.urlopen(img_url, timeout=15) as img_resp:
            return img_resp.read()
    except Exception:
        return None


def fetch_stock_image(keyword: str, width: int = 1920, height: int = 1080) -> Optional[Path]:
    """키워드로 스톡 사진 다운로드 (캐시 우선). 반환: 로컬 파일 경로 또는 None.

    1) 캐시 hit 면 즉시 반환
    2) Unsplash → Pexels → Pixabay 순서 시도
    3) 셋 다 실패면 None
    """
    cache_path = _cache_key(keyword, width, height)
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path

    # 각 API fallback
    img_bytes = (
        _try_unsplash(keyword, width, height)
        or _try_pexels(keyword, width, height)
        or _try_pixabay(keyword, width, height)
    )
    if not img_bytes:
        return None

    cache_path.write_bytes(img_bytes)
    return cache_path


def get_cover_image(slide_id: str, user_intent: str = "") -> Optional[Path]:
    """슬라이드 ID + 사용자 의도 로부터 적절한 스톡 사진 다운로드.

    Args:
        slide_id: SlideSpec.id (예: "cover", "p1_market", "closing").
        user_intent: 사용자 분석 의도 (예: "고객 이탈 예측"). 슬라이드별 키워드에 결합.

    Returns:
        로컬 파일 경로 또는 None (모든 API 실패·키 부재).
    """
    base_keyword = _KEYWORD_BY_SLIDE.get(slide_id, "abstract business")
    # 사용자 의도의 *영문* 키워드만 추출 (한국어 검색은 stock 사이트에서 약함)
    intent_en = "".join(c for c in user_intent if c.isascii()).strip()
    if intent_en:
        keyword = f"{base_keyword} {intent_en}"
    else:
        keyword = base_keyword
    return fetch_stock_image(keyword)


__all__ = [
    "fetch_stock_image",
    "get_cover_image",
]
