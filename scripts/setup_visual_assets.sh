#!/usr/bin/env bash
# scripts/setup_visual_assets.sh
# PPT 시각 품질 향상용 자산 다운로드 — 1회 실행.
# 의존성: curl, unzip, git (or wget alternatives)
# 디스크: ~25MB
# HJ 2026-06-08

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ASSETS="$REPO_ROOT/assets"

mkdir -p "$ASSETS/fonts" "$ASSETS/icons/lucide" "$ASSETS/illustrations/undraw"

echo "=== Pretendard 폰트 (OFL, ~5MB) ==="
PRETENDARD_VER="1.3.9"
PRETENDARD_BASE="https://github.com/orioncactus/pretendard/raw/v${PRETENDARD_VER}/packages/pretendard/dist/public/static"
for weight in Regular Medium SemiBold Bold ExtraBold; do
  target="$ASSETS/fonts/Pretendard-${weight}.otf"
  if [ -f "$target" ]; then
    echo "  ✓ Pretendard-${weight}.otf (캐시)"
    continue
  fi
  echo "  ↓ Pretendard-${weight}.otf"
  curl -sL "$PRETENDARD_BASE/Pretendard-${weight}.otf" -o "$target" || {
    echo "  ⚠️  Pretendard ${weight} 다운로드 실패 — 인터넷 확인"
  }
done

echo ""
echo "=== Lucide 아이콘 (MIT, ~10MB) ==="
LUCIDE_VER="0.469.0"
LUCIDE_TMP="/tmp/lucide-icons.tar.gz"
LUCIDE_EXTRACT="/tmp/lucide-extract"

if [ -z "$(ls -A "$ASSETS/icons/lucide" 2>/dev/null)" ]; then
  echo "  ↓ Lucide ${LUCIDE_VER} (tarball)"
  curl -sL "https://github.com/lucide-icons/lucide/archive/refs/tags/${LUCIDE_VER}.tar.gz" -o "$LUCIDE_TMP"
  mkdir -p "$LUCIDE_EXTRACT"
  tar -xzf "$LUCIDE_TMP" -C "$LUCIDE_EXTRACT" --strip-components=1 \
    "lucide-${LUCIDE_VER}/icons" 2>/dev/null || true
  # SVG 만 추출
  if [ -d "$LUCIDE_EXTRACT/icons" ]; then
    cp "$LUCIDE_EXTRACT/icons/"*.svg "$ASSETS/icons/lucide/" 2>/dev/null || true
    rm -rf "$LUCIDE_EXTRACT" "$LUCIDE_TMP"
    echo "  ✓ Lucide $(ls "$ASSETS/icons/lucide/" | wc -l) 개 아이콘 설치"
  else
    echo "  ⚠️  Lucide 추출 실패"
  fi
else
  echo "  ✓ Lucide $(ls "$ASSETS/icons/lucide/" | wc -l) 개 아이콘 (캐시)"
fi

echo ""
echo "=== unDraw 일러스트 (MIT, ~5MB 큐레이션 30개) ==="
# unDraw 공식 일러스트 URL — 큐레이션 리스트만 다운로드
UNDRAW_BASE="https://undraw.co/api/illustrations"
# 큐레이션된 일러스트 슬러그 (slide_id 매핑과 동기)
UNDRAW_SLUGS=(
  "frustrated" "lost" "creative_thinking" "city_life" "engineering_team"
  "server_status" "cloud_hosting" "programmer" "winners" "growth_analytics"
  "progress_indicator" "data_extraction" "investigation" "knowledge"
  "before_dawn" "growth_curve" "safety" "navigation" "well_done"
  "presentation" "artificial_intelligence" "calendar" "security_on"
  "predictive_analytics" "data_trends" "scientist" "report"
)

# unDraw 는 자동 다운로드 미러가 모두 404 / 비공식 변경 잦음.
# 권장: 사용자가 https://undraw.co/illustrations 에서 직접 다운로드
# 또는 unDraw 의 illustrations.com (Storyset by Freepik) 사용
echo "  ⚠️  unDraw 는 자동 다운로드 미러 불안정 — 수동 다운로드 권장"
echo "      1. https://undraw.co/illustrations 방문"
echo "      2. 카테고리 색상 선택 (#2563eb 파랑 권장)"
echo "      3. 아래 30개 SVG 다운로드 → $ASSETS/illustrations/undraw/"
echo "         (없어도 PPT 생성은 정상 — illustration 슬라이드만 비어보임)"
echo ""
echo "      필요한 SVG 목록 (총 ~30개):"
for slug in "${UNDRAW_SLUGS[@]}"; do
  echo "        - ${slug}.svg"
done | head -10
echo "        - ..."

echo ""
echo "=== Python 의존성 ==="
pip install cairosvg --break-system-packages --quiet 2>&1 | tail -2
pip show cairosvg 2>/dev/null | grep -E "Name|Version" || echo "  ⚠️  cairosvg 설치 필요"

echo ""
echo "=== 시스템 폰트 등록 (Linux) ==="
if command -v fc-cache &> /dev/null; then
  FONTS_DIR="$HOME/.local/share/fonts"
  mkdir -p "$FONTS_DIR"
  cp "$ASSETS/fonts/Pretendard-"*.otf "$FONTS_DIR/" 2>/dev/null || true
  fc-cache -f "$FONTS_DIR" 2>/dev/null || true
  echo "  ✓ ~/.local/share/fonts 에 Pretendard 등록"
else
  echo "  ⚠️  fc-cache 없음 — 수동 설치 필요"
fi

echo ""
echo "=== API 키 (선택) ==="
echo "  Unsplash : https://unsplash.com/developers (무료 50/h)"
echo "  Pexels   : https://www.pexels.com/api (무료 200/h)"
echo "  Pixabay  : https://pixabay.com/api/docs (무료 무제한)"
echo ""
echo "  환경변수 설정 (.env):"
echo "    UNSPLASH_ACCESS_KEY=..."
echo "    PEXELS_API_KEY=..."
echo "    PIXABAY_API_KEY=..."
echo ""
echo "=== 설치 완료 ==="
ls -lh "$ASSETS/fonts/" "$ASSETS/icons/lucide" "$ASSETS/illustrations/undraw" 2>/dev/null | head -20
