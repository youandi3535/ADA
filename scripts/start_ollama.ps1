# scripts/start_ollama.ps1 — Ollama 서비스 시작 스크립트 (Windows)
#
# 사용법:
#   .\scripts\start_ollama.ps1              # 서비스 시작 + 모델 확인
#   .\scripts\start_ollama.ps1 -PullModel   # 모델 없으면 자동 다운로드
#
# 개발 시작 전 Docker Compose 와 함께 실행:
#   .\scripts\start_ollama.ps1
#   cd docker && docker compose --profile core up -d
#
# 모델 역할:
#   qwen2.5:7b        — 팀 KB Q&A 폴백 (일반 질의응답)
#   qwen2.5-coder:7b  — 오류 자동 수정 폴백 (diff 생성 특화)

param(
    [switch]$PullModel
)

$OLLAMA_EXE    = "C:\Users\$env:USERNAME\AppData\Local\Programs\Ollama\ollama.exe"
$OLLAMA_MODEL  = "qwen2.5:7b"
$OLLAMA_CODER  = "qwen2.5-coder:7b"
$OLLAMA_API    = "http://127.0.0.1:11434"

# ── 1. 실행 파일 존재 확인 ──────────────────────────────────────────
if (-not (Test-Path $OLLAMA_EXE)) {
    Write-Error "Ollama 미설치. winget install Ollama.Ollama 실행 후 재시도하세요."
    exit 1
}

# ── 2. 이미 실행 중인지 확인 ───────────────────────────────────────
$proc = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $proc) {
    Write-Host "🚀 Ollama 서버 시작 중..."
    Start-Process -FilePath $OLLAMA_EXE -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5
} else {
    Write-Host "ℹ️  Ollama 이미 실행 중 (PID $($proc.Id))"
}

# ── 3. API 준비 대기 (최대 30초) ──────────────────────────────────
$ready = $false
for ($i = 1; $i -le 10; $i++) {
    try {
        $null = Invoke-RestMethod -Uri "$OLLAMA_API/api/tags" -TimeoutSec 3
        $ready = $true
        break
    } catch {
        Write-Host "  대기 중... ($i/10)"
        Start-Sleep -Seconds 3
    }
}

if (-not $ready) {
    Write-Error "Ollama API가 응답하지 않습니다. 로그를 확인하세요."
    exit 1
}

Write-Host "✅ Ollama API 준비됨 ($OLLAMA_API)"

# ── 4. 모델 확인 및 다운로드 ──────────────────────────────────────
$tags       = Invoke-RestMethod -Uri "$OLLAMA_API/api/tags" -TimeoutSec 5
$modelNames = $tags.models | ForEach-Object { $_.name }

foreach ($m in @($OLLAMA_MODEL, $OLLAMA_CODER)) {
    if ($modelNames -contains $m) {
        Write-Host "✅ 모델 준비됨: $m"
    } else {
        Write-Host "⚠️  모델 없음: $m"
        if ($PullModel) {
            $sizeHint = if ($m -like "*coder*") { "4.7GB" } else { "4.7GB" }
            Write-Host "📥 $m 다운로드 시작 (약 $sizeHint, 시간이 걸립니다)..."
            & $OLLAMA_EXE pull $m
            Write-Host "✅ $m 다운로드 완료"
        } else {
            Write-Host "   다운로드하려면: .\scripts\start_ollama.ps1 -PullModel"
            Write-Host "   또는: ollama pull $m"
        }
    }
}

# ── 5. 현재 상태 출력 ─────────────────────────────────────────────
Write-Host ""
Write-Host "📊 현재 Ollama 상태:"
& $OLLAMA_EXE list
Write-Host ""
Write-Host "🔗 API 엔드포인트: $OLLAMA_API"
Write-Host ""
Write-Host "🤖 모델 역할:"
Write-Host "   Q&A 폴백    : $OLLAMA_MODEL   (팀 KB 미스 → 일반 질의응답)"
Write-Host "   코드 수정   : $OLLAMA_CODER   (ErrorKB 미스 → diff 생성)"
Write-Host ""
Write-Host "📚 오류 수정 체계: ErrorKB → Ollama($OLLAMA_CODER) → Claude Opus"
Write-Host "📚 KB 검색 체계 : 팀KB    → Ollama($OLLAMA_MODEL)  → Claude Opus"
