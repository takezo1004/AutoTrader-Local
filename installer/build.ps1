# ============================================================
#  AutoTrader Local — インストーラーを作る
#
#  配布仕様の正本＝リポルート DISTRIBUTION_MAP.md「ローカル版の配布仕様（D15）」。
#  ここに仕様を書き写さない。
#
#  やること:
#    1. ランチャー（AutoTrader-Local.exe）を PyInstaller で作る
#    2. payload\lib に依存を入れる（numpy / pandas / pyarrow / requests / bs4 / openpyxl）
#    3. lib から配布に不要なもの（tests・開発用ヘッダ・静的ライブラリ）を削る
#    4. payload にソース（run_dashboard.py・app）とマニュアルを入れる
#    5. Inno Setup で Setup.exe を作る → installer\output\
#
#  使い方:
#    pwsh N225LocalEngine\installer\build.ps1
#    -SkipLauncher … ランチャーを作り直さない
#    -SkipLib      … lib を作り直さない（削りだけやり直す）
# ============================================================
param(
    [switch]$SkipLauncher,
    [switch]$SkipLib
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$here    = $PSScriptRoot                                  # …\N225LocalEngine\installer
$root    = Split-Path -Parent $here                       # …\N225LocalEngine
$repo    = Split-Path -Parent $root                       # …\N225TradingSystem
$python  = Join-Path $repo ".venv\Scripts\python.exe"
$payload = Join-Path $here "payload"
$dist    = Join-Path $here "dist"
$output  = Join-Path $here "output"

function Write-Head($s) { Write-Host "==== $s ====" -ForegroundColor Cyan }
function Get-Size($path) {
    if (-not (Test-Path $path)) { return 0 }
    (Get-ChildItem $path -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
}

# 版 = pyproject.toml の version（D15）。ここで決め打ちしない。
$pyproject = Get-Content (Join-Path $root "pyproject.toml") -Raw
if ($pyproject -notmatch '(?m)^version\s*=\s*"([^"]+)"') { throw "pyproject.toml から version を読めません" }
$version = $Matches[1]
Write-Head "ローカル版 インストーラー作成（版 $version）"

# --- 1. ランチャー ------------------------------------------------------
if ($SkipLauncher) {
    Write-Head "[1/5] ランチャーは作り直さない（-SkipLauncher）"
} else {
    Write-Head "[1/5] ランチャーを作る（PyInstaller）"
    & $python -m PyInstaller --noconfirm --log-level WARN `
        --distpath $dist --workpath (Join-Path $here "build") (Join-Path $here "n225local.spec")
    if ($LASTEXITCODE -ne 0) { throw "ランチャーの作成に失敗しました" }
}
$launcher = Join-Path $dist "AutoTrader-Local.exe"
if (-not (Test-Path $launcher)) { throw "ランチャーがありません: $launcher" }
Write-Host ("  AutoTrader-Local.exe  {0:N1} MB" -f ((Get-Item $launcher).Length / 1MB))

# --- 2. 依存 ------------------------------------------------------------
$lib = Join-Path $payload "lib"
if ($SkipLib -and (Test-Path $lib)) {
    Write-Head "[2/5] lib は作り直さない（-SkipLib）"
} else {
    Write-Head "[2/5] 依存を lib へ入れる"
    if (Test-Path $lib) { Remove-Item $lib -Recurse -Force }
    & $python -m pip install --quiet --target $lib `
        numpy==2.2.6 pandas==2.3.3 "pyarrow>=14" "requests>=2.28" "beautifulsoup4>=4.12" "openpyxl>=3.1"
    if ($LASTEXITCODE -ne 0) { throw "依存の取得に失敗しました" }
}
Write-Host ("  入れた直後: {0:N1} MB" -f ((Get-Size $lib) / 1MB))

# --- 3. lib を削る ------------------------------------------------------
# 配布に不要なもの＝自動テスト・開発用ヘッダ（他言語から使うためのもの）・静的ライブラリ・キャッシュ。
# ★ここを削っても実行時の import には影響しない（実測で確認してから足すこと）。
Write-Head "[3/5] lib から配布に不要なものを削る"
$dropDirs = @("tests", "test", "include", "src", "__pycache__", "*.dist-info\license_files")
foreach ($pat in $dropDirs) {
    Get-ChildItem $lib -Recurse -Directory -Filter $pat -ErrorAction SilentlyContinue |
        Sort-Object { $_.FullName.Length } -Descending |
        ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
}
foreach ($pat in @("*.lib", "*.pdb", "*.pyi", "*.c", "*.h", "*.hpp", "*.cmake")) {
    Get-ChildItem $lib -Recurse -File -Filter $pat -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }
}
Write-Host ("  削った後  : {0:N1} MB" -f ((Get-Size $lib) / 1MB))

# --- 4. payload を組み立てる -------------------------------------------
Write-Head "[4/5] payload を組み立てる（ランチャー・ソース・マニュアル）"
# 直下の古いランチャー（名前を変えたときの残り）を消してから入れ直す
Get-ChildItem $payload -Filter "*.exe" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne (Split-Path $launcher -Leaf) } |
    ForEach-Object { Write-Host ("  古いランチャーを削除: {0}" -f $_.Name) -ForegroundColor DarkGray; Remove-Item $_.FullName -Force }

Copy-Item $launcher $payload -Force
Copy-Item (Join-Path $root "run_dashboard.py") $payload -Force

# app\（ソースのまま。キャッシュと状態は入れない）
$appDst = Join-Path $payload "app"
if (Test-Path $appDst) { Remove-Item $appDst -Recurse -Force }
$rc = Start-Process robocopy -ArgumentList @(
    (Join-Path $root "app"), $appDst, "/E",
    "/XD", "__pycache__", "state", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"
) -Wait -NoNewWindow -PassThru
if ($rc.ExitCode -ge 8) { throw "app のコピーに失敗しました (robocopy exit=$($rc.ExitCode))" }

# マニュアル（HTML 1 枚）
$manualSrc = Join-Path $root "manual\_preview\manual.html"
if (-not (Test-Path $manualSrc)) { throw "マニュアルがありません: $manualSrc（manual\_tools\build_html.py を実行してください）" }
$manualDst = Join-Path $payload "manual"
New-Item -ItemType Directory -Force $manualDst | Out-Null
Copy-Item $manualSrc (Join-Path $manualDst "manual.html") -Force

Write-Host ("  payload 合計: {0:N1} MB" -f ((Get-Size $payload) / 1MB))

# --- 5. Setup.exe -------------------------------------------------------
Write-Head "[5/5] Inno Setup で Setup.exe を作る"
$iscc = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { throw "Inno Setup が見つかりません: $iscc" }
New-Item -ItemType Directory -Force $output | Out-Null
& $iscc "/DMyAppVersion=$version" "/DPayloadDir=$payload" "/DOutDir=$output" (Join-Path $here "N225Local.iss")
if ($LASTEXITCODE -ne 0) { throw "Setup.exe の作成に失敗しました" }

Get-ChildItem $output -Filter "*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1 |
    ForEach-Object {
        Write-Host ""
        Write-Host ("出来上がり: {0}  ({1:N1} MB)" -f $_.FullName, ($_.Length / 1MB)) -ForegroundColor Green
    }
