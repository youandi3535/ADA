#Requires -Version 5.0
<#
.SYNOPSIS
    HJ 2026-06-09 G1 단축 Phase 5 — DD GPU 측정 자동화.

    qwen2.5:7b 의 num_gpu 옵션을 0, 8, 12, 16, 20, 24 로 sweep 하며
    토큰 처리 속도(t/s) 를 측정. OOM 발생 시 그 시점부터 skip.
    결과를 콘솔 + out/ollama_gpu_sweep_result.json 에 기록.

.NOTES
    - 사전 조건: Ollama 가 실행 중 (트레이 아이콘 보임), qwen2.5:7b 모델 pull 완료
    - 실행 시간: ~5분 (각 num_gpu 당 ~30초 + 모델 재로드 시간)
    - 안전: OOM 발생해도 Ollama 자체는 죽지 않음. 그 num_gpu 값 skip 후 계속.

.EXAMPLE
    PS> .\scripts\dev\measure_ollama_gpu_sweep.ps1
#>

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  G1 단축 Phase 5 — DD GPU 측정 (qwen2.5:7b)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Ollama 가용성 확인
try {
    $tags = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5
    $hasModel = $tags.models | Where-Object { $_.name -match "qwen2\.5:7b" }
    if (-not $hasModel) {
        Write-Host "[ERROR] qwen2.5:7b 모델이 없습니다. 먼저 'ollama pull qwen2.5:7b' 실행." -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] Ollama 가용, qwen2.5:7b 확인됨." -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Ollama 접속 실패: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "   트레이의 Ollama 아이콘이 보이는지 확인하세요." -ForegroundColor Yellow
    exit 1
}

# 측정 대상 num_gpu 값들
$nums = @(0, 8, 12, 16, 20, 24)

# 동일 프롬프트 (도메인 분석 비슷한 워크로드)
# HJ 2026-06-09 — 한국어 강제 (ADA 의 with_korean_guard 와 동일 패턴, 측정 일관성).
$systemPrompt = @"
당신은 데이터 분석 어시스턴트.

[언어 규칙 — 반드시 준수]
- 모든 응답은 한국어로만 작성한다.
- 중국어 한자(漢字)·간체자·번체자 사용 금지. 절대로 中文·汉字 출력 금지.
- 일본어 가나(かな·カナ) 사용 금지.
- 영어 단어는 고유명사·기술 용어에만 제한적 허용.
- 한자 사용시 응답이 거부된다.
"@
$prompt = "다음 데이터셋이 어떤 도메인인지 한국어 한 문장으로 답해줘: columns=['age','salary','department','tenure','satisfaction'], 첫 행=[35, 65000, 'engineering', 5, 8.5]"

$results = @()
$ommedAt = $null

foreach ($n in $nums) {
    Write-Host ""
    Write-Host "[--] OLLAMA_NUM_GPU=$n 측정 중..." -ForegroundColor Cyan

    $body = @{
        model = "qwen2.5:7b"
        messages = @(
            @{ role = "system"; content = $systemPrompt },
            @{ role = "user";   content = $prompt }
        )
        stream = $false
        keep_alive = "20s"  # 짧게 — 다음 측정에 메모리 양보
        options = @{
            num_predict = 150
            temperature = 0.0
            num_gpu = $n
            num_thread = 14
            top_p = 0.9
        }
    } | ConvertTo-Json -Depth 5

    try {
        $start = Get-Date
        $resp = Invoke-RestMethod `
            -Uri "http://localhost:11434/api/chat" `
            -Method POST `
            -Body $body `
            -ContentType "application/json" `
            -TimeoutSec 180
        $wallSec = ((Get-Date) - $start).TotalSeconds

        # Ollama 응답 필드:
        #   eval_count (생성 토큰 수)
        #   eval_duration (ns)
        #   load_duration (ns) — 모델 로드 시간 (재로드 시 큼)
        #   prompt_eval_count, prompt_eval_duration
        $tps = if ($resp.eval_duration -gt 0) { $resp.eval_count / ($resp.eval_duration / 1e9) } else { 0 }
        $loadSec = if ($resp.load_duration) { [math]::Round($resp.load_duration / 1e9, 2) } else { 0 }

        $row = [PSCustomObject]@{
            num_gpu          = $n
            status           = "OK"
            eval_count       = $resp.eval_count
            eval_duration_s  = [math]::Round($resp.eval_duration / 1e9, 2)
            load_duration_s  = $loadSec
            wall_clock_s     = [math]::Round($wallSec, 2)
            tokens_per_sec   = [math]::Round($tps, 2)
            response_preview = if ($resp.message.content) { $resp.message.content.Substring(0, [math]::Min(60, $resp.message.content.Length)) } else { "" }
        }
        $results += $row
        Write-Host ("  [OK] {0} tokens, {1} t/s (load {2}s, total {3}s)" -f $row.eval_count, $row.tokens_per_sec, $row.load_duration_s, $row.wall_clock_s) -ForegroundColor Green
    } catch {
        $msg = $_.Exception.Message
        Write-Host "  [FAIL] $msg" -ForegroundColor Red
        $results += [PSCustomObject]@{
            num_gpu = $n
            status  = "FAIL: $($msg.Substring(0, [math]::Min(80, $msg.Length)))"
        }
        # OOM 추정 키워드 — 그 이상 num_gpu 는 더 큰 메모리 필요 → skip
        if ($msg -match "out of memory|OOM|CUDA|VRAM|insufficient memory|cudaMalloc") {
            $ommedAt = $n
            Write-Host "  [WARN] OOM 감지 — num_gpu >= $n 측정 중단" -ForegroundColor Yellow
            break
        }
    }

    Start-Sleep -Seconds 2  # 다음 측정 전 메모리 정리
}

# 결과 정리
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  측정 결과" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
$results | Format-Table -AutoSize

# 출력 파일
$outDir = Join-Path $PSScriptRoot "..\..\out"
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }
$outPath = Join-Path $outDir "ollama_gpu_sweep_result.json"
$outObj = [PSCustomObject]@{
    measured_at = (Get-Date).ToString("o")
    gpu_model   = "GTX 1060 3GB (memory record)"
    model       = "qwen2.5:7b"
    omm_at      = $ommedAt
    results     = $results
}
$outObj | ConvertTo-Json -Depth 5 | Out-File -FilePath $outPath -Encoding UTF8
Write-Host "[FILE] 결과 저장: $outPath" -ForegroundColor Green

# 자동 권장
$okResults = $results | Where-Object { $_.status -eq "OK" }
if ($okResults.Count -eq 0) {
    Write-Host "[ERROR] 측정된 OK 결과 없음. 환경 점검 필요." -ForegroundColor Red
    exit 2
}

$baseline = $okResults | Where-Object { $_.num_gpu -eq 0 } | Select-Object -First 1
$best = $okResults | Sort-Object tokens_per_sec -Descending | Select-Object -First 1

Write-Host ""
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host "  분석 + 권장" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Yellow

if ($baseline -and $best -and $best.num_gpu -gt 0) {
    $gainPct = [math]::Round(($best.tokens_per_sec / $baseline.tokens_per_sec - 1) * 100, 1)
    $g1BaselineSec = 242  # Phase 4 까지 적용한 현재 추정 G1 시간
    $newG1Sec = [math]::Round($g1BaselineSec / ($best.tokens_per_sec / $baseline.tokens_per_sec), 0)
    $g1Saved = $g1BaselineSec - $newG1Sec

    Write-Host ""
    Write-Host "  Baseline (num_gpu=0): $($baseline.tokens_per_sec) t/s" -ForegroundColor White
    Write-Host "  Best (num_gpu=$($best.num_gpu)): $($best.tokens_per_sec) t/s" -ForegroundColor White
    Write-Host "  Gain: +$gainPct%" -ForegroundColor White
    Write-Host ""

    if ($gainPct -ge 30) {
        Write-Host "  >>> 권장: OLLAMA_NUM_GPU=$($best.num_gpu) 적용 <<<" -ForegroundColor Green
        Write-Host "  G1 예상 단축: $g1BaselineSec s -> $newG1Sec s (-$g1Saved s)" -ForegroundColor Green
        Write-Host ""
        Write-Host "  .env 에 다음 라인 추가/수정:" -ForegroundColor Cyan
        Write-Host "    OLLAMA_NUM_GPU=$($best.num_gpu)" -ForegroundColor Cyan
        Write-Host "  그 후 docker compose restart worker api" -ForegroundColor Cyan
    } elseif ($gainPct -ge 10) {
        Write-Host "  >>> 권장: OLLAMA_NUM_GPU=$($best.num_gpu) 시도 가능 (효과 보통) <<<" -ForegroundColor Yellow
        Write-Host "  G1 단축 -$g1Saved s — 적용 결정은 사용자 판단." -ForegroundColor Yellow
    } else {
        Write-Host "  >>> 권장: OLLAMA_NUM_GPU=0 유지 (GPU 효과 미미) <<<" -ForegroundColor Yellow
        Write-Host "  메모리 기록의 '역효과' 가 7b 에서도 재현됨." -ForegroundColor Yellow
    }
} else {
    Write-Host "  >>> 권장: OLLAMA_NUM_GPU=0 유지 (GPU 측정 케이스 모두 baseline 이하) <<<" -ForegroundColor Yellow
}

if ($ommedAt) {
    Write-Host ""
    Write-Host "  OOM 발생: num_gpu >= $ommedAt — VRAM 부족" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[NEXT] 결과 파일 을 Claude 에게 공유하면 .env 자동 적용 안내합니다: $outPath" -ForegroundColor Cyan
