# PowerSeed 작업 시작: 최신 코드 받기 → 가상환경 → 패키지·DB 맞추기 → 서버 실행
#   .\start.ps1            서버까지 실행
#   .\start.ps1 -NoServer  작업 준비만 (가상환경이 켜진 채로 끝남)
#   .\start.ps1 -Branch feat/discovery-flow   작업 중인 브랜치로 받기 (기본 main)
[CmdletBinding()]
param(
    [switch]$NoServer,
    [string]$Branch = 'main'
)

Set-Location -LiteralPath $PSScriptRoot

function Write-Step($Message) { Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Write-Caution($Message) { Write-Host "[주의] $Message" -ForegroundColor Yellow }
function Stop-Start($Message) {
    Write-Host "[중단] $Message" -ForegroundColor Red
    exit 1
}

Write-Step '최신 코드 받는 중'
git fetch origin
$fetched = $LASTEXITCODE -eq 0
# 추적 중인 파일의 변경만 본다. 새 파일은 pull에 방해되지 않는 한 그대로 둔다.
$changes = git status --porcelain --untracked-files=no

if (-not $fetched) {
    Write-Caution '원격에 연결하지 못해 현재 코드로 계속합니다.'
} elseif ($changes) {
    $behind = git rev-list --count "HEAD..origin/$Branch"
    Write-Caution "커밋하지 않은 변경이 있어 코드를 받지 않았습니다. (origin/$Branch 보다 $behind 커밋 뒤)"
    $changes | ForEach-Object { Write-Host "  $_" }
} else {
    if ((git branch --show-current) -ne $Branch) {
        git switch $Branch
        if ($LASTEXITCODE -ne 0) { Stop-Start "$Branch 브랜치로 전환하지 못했습니다." }
    }
    git pull --ff-only origin $Branch
    if ($LASTEXITCODE -ne 0) {
        Stop-Start '로컬과 원격의 커밋이 갈라져 자동으로 받을 수 없습니다. git status 로 확인하세요.'
    }
}

Write-Step '가상환경 켜는 중'
if (-not (Test-Path 'venv\Scripts\python.exe')) {
    python -m venv venv
    if ($LASTEXITCODE -ne 0) { Stop-Start '가상환경을 만들지 못했습니다. Python 설치를 확인하세요.' }
}
. .\venv\Scripts\Activate.ps1

Write-Step '패키지 확인 중'
$hashFile = 'venv\.requirements.sha256'
$currentHash = (Get-FileHash 'requirements.txt' -Algorithm SHA256).Hash
$savedHash = if (Test-Path $hashFile) { (Get-Content $hashFile -Raw).Trim() } else { '' }
if ($currentHash -ne $savedHash) {
    python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Stop-Start '패키지 설치에 실패했습니다.' }
    Set-Content -Path $hashFile -Value $currentHash
} else {
    Write-Host '변경 없음'
}

if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    Write-Caution '.env가 없어 .env.example로 만들었습니다.'
}

Write-Step 'DB 마이그레이션'
python manage.py migrate
if ($LASTEXITCODE -ne 0) { Stop-Start '마이그레이션에 실패했습니다.' }

if ($NoServer) {
    Write-Step "작업 준비 완료 ($(git branch --show-current))"
    return
}

Write-Step '서버 실행: http://127.0.0.1:8000 (종료: Ctrl+C)'
python manage.py runserver
