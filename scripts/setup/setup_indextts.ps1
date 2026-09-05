# IndexTTS2 setup (default TTS backend)
# Run: .\scripts\setup\setup_indextts.ps1
# Packaged app: prefer %AGENT_RUNTIME_DIR%\engines\IndexTTS (writable).
# Source fetch (real-user path): Gitee mirrors first -> CN git proxies -> ZIP -> official GitHub.
# Does NOT reuse developer tools/IndexTTS (simulates clean machine).

param(
    [string]$Root = "",
    [string]$InstallDir = "",
    [string]$RepoUrl = "https://github.com/index-tts/index-tts.git"
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "_project_root.ps1")
if (-not $Root) {
    $Root = $ProjectRoot
}
if (-not $InstallDir) {
    if ($env:AGENT_RUNTIME_DIR) {
        $InstallDir = Join-Path $env:AGENT_RUNTIME_DIR "engines\IndexTTS"
    } else {
        $InstallDir = Join-Path $Root "tools\IndexTTS"
    }
}

Write-Host "==> Root=$Root"
Write-Host "==> InstallDir=$InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

$parentDir = Split-Path $InstallDir
$staging = Join-Path $parentDir "IndexTTS_staging"
$zipPath = Join-Path $parentDir "IndexTTS_src.zip"

function Test-IndexTtsSource([string]$Dir) {
    return (Test-Path (Join-Path $Dir "pyproject.toml"))
}

function Copy-IndexTtsTree([string]$From, [string]$To) {
    New-Item -ItemType Directory -Force -Path $To | Out-Null
    robocopy $From $To /E /XD venv .venv .git __pycache__ /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    # robocopy exit 0-7 = success-ish
    return (Test-IndexTtsSource $To)
}

function Get-GitExe {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in @(
        "C:\Program Files\Git\cmd\git.exe",
        "C:\Program Files (x86)\Git\cmd\git.exe"
    )) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Clone-WithGit([string]$Url, [string]$Target) {
    $git = Get-GitExe
    if (-not $git) {
        Write-Host "    skip git: not found on PATH"
        return $false
    }
    Remove-Item $Target -Recurse -Force -ErrorAction SilentlyContinue
    $outFile = Join-Path $parentDir "_git_out.txt"
    $errFile = Join-Path $parentDir "_git_err.txt"
    Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
    Write-Host "==> git clone --depth 1 $Url"
    # Gitee mirrors often lack paid LFS; skip smudge (examples fetched later; weights via ModelScope)
    $prevLfs = $env:GIT_LFS_SKIP_SMUDGE
    $env:GIT_LFS_SKIP_SMUDGE = "1"
    try {
        $p = Start-Process -FilePath $git -ArgumentList @("clone", "--depth", "1", $Url, $Target) `
            -NoNewWindow -Wait -PassThru -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    } finally {
        if ($null -eq $prevLfs) { Remove-Item Env:GIT_LFS_SKIP_SMUDGE -ErrorAction SilentlyContinue }
        else { $env:GIT_LFS_SKIP_SMUDGE = $prevLfs }
    }
    $err = ""
    if (Test-Path $errFile) { $err = (Get-Content $errFile -Raw -ErrorAction SilentlyContinue) }
    if (Test-Path $outFile) {
        $out = Get-Content $outFile -Raw -ErrorAction SilentlyContinue
        if ($out) { Write-Host $out.TrimEnd() }
    }
    # Accept clone even if LFS checkout warned, as long as pyproject.toml exists
    if ((Test-IndexTtsSource $Target) -and ($p.ExitCode -eq 0 -or (Test-Path (Join-Path $Target "indextts")))) {
        if ($p.ExitCode -ne 0) {
            Write-Host "    clone had warnings (exit=$($p.ExitCode)) but source tree looks usable"
        }
        return $true
    }
    if ($err) {
        $msg = ($err.Trim() -replace '\s+', ' ')
        if ($msg.Length -gt 400) { $msg = $msg.Substring(0, 400) }
        Write-Host ("    git failed exit={0}: {1}" -f $p.ExitCode, $msg)
    } else {
        Write-Host ("    git failed exit={0}" -f $p.ExitCode)
    }
    Remove-Item $Target -Recurse -Force -ErrorAction SilentlyContinue
    return $false
}

function Download-File([string]$Url, [string]$Out) {
    Write-Host "==> download $Url"
    try {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curl) {
            & curl.exe -L --fail --retry 2 --connect-timeout 20 --max-time 600 -o $Out $Url
            if (($LASTEXITCODE -eq 0) -and (Test-Path $Out) -and ((Get-Item $Out).Length -gt 50000)) {
                return $true
            }
        }
        Invoke-WebRequest -Uri $Url -OutFile $Out -UseBasicParsing -TimeoutSec 600
        if ((Test-Path $Out) -and ((Get-Item $Out).Length -gt 50000)) {
            return $true
        }
    } catch {
        Write-Host "    download failed: $($_.Exception.Message)"
    }
    Remove-Item $Out -Force -ErrorAction SilentlyContinue
    return $false
}

function Expand-IndexTtsZip([string]$Zip, [string]$Target) {
    $unpack = Join-Path $parentDir "IndexTTS_zip_unpack"
    Remove-Item $unpack -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $unpack | Out-Null
    Expand-Archive -Path $Zip -DestinationPath $unpack -Force
    $inner = Get-ChildItem $unpack -Directory | Select-Object -First 1
    if (-not $inner) {
        Write-Host "    zip has no folder"
        return $false
    }
    Remove-Item $Target -Recurse -Force -ErrorAction SilentlyContinue
    Move-Item $inner.FullName $Target
    Remove-Item $unpack -Recurse -Force -ErrorAction SilentlyContinue
    return (Test-IndexTtsSource $Target)
}

function Fetch-IndexTtsSource([string]$Target) {
    # Community Gitee mirrors (verified reachable in CN). Official is GitHub only;
    # these are third-party syncs — we skip LFS and pull weights from ModelScope.
    $giteeUrls = @(
        "https://gitee.com/chongho/index-tts.git",
        "https://gitee.com/airhand/index-tts.git",
        "https://gitee.com/okhelper/index-tts.git"
    )
    $proxyGitUrls = @(
        "https://ghfast.top/https://github.com/index-tts/index-tts.git",
        "https://kkgithub.com/index-tts/index-tts.git",
        "https://hub.gitmirror.com/https://github.com/index-tts/index-tts.git",
        "https://mirror.ghproxy.com/https://github.com/index-tts/index-tts.git",
        "https://gitclone.com/github.com/index-tts/index-tts.git",
        $RepoUrl
    )

    if (-not (Get-GitExe)) {
        Write-Host "==> Git not installed — try ZIP mirrors (recommend installing Git for Gitee)"
        Write-Host "    https://git-scm.com/download/win"
    } else {
        Write-Host "==> try Gitee mirrors first (CN)"
        foreach ($url in $giteeUrls) {
            if (Clone-WithGit $url $Target) { return $true }
        }
        Write-Host "==> Gitee failed, try GitHub proxy mirrors"
        foreach ($url in $proxyGitUrls) {
            if (Clone-WithGit $url $Target) { return $true }
        }
    }

    Write-Host "==> try ZIP downloads (no git)"
    $zipUrls = @(
        "https://ghfast.top/https://github.com/index-tts/index-tts/archive/refs/heads/main.zip",
        "https://kkgithub.com/index-tts/index-tts/archive/refs/heads/main.zip",
        "https://hub.gitmirror.com/https://github.com/index-tts/index-tts/archive/refs/heads/main.zip",
        "https://mirror.ghproxy.com/https://github.com/index-tts/index-tts/archive/refs/heads/main.zip",
        "https://codeload.github.com/index-tts/index-tts/zip/refs/heads/main",
        "https://github.com/index-tts/index-tts/archive/refs/heads/main.zip"
    )
    foreach ($url in $zipUrls) {
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        if (-not (Download-File $url $zipPath)) { continue }
        Write-Host "==> expand zip -> $Target"
        if (Expand-IndexTtsZip $zipPath $Target) {
            Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
            return $true
        }
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        Remove-Item $Target -Recurse -Force -ErrorAction SilentlyContinue
    }

    return $false
}

# --- acquire source ---
if (-not (Test-IndexTtsSource $InstallDir)) {
    Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
    if (-not (Fetch-IndexTtsSource $staging)) {
        throw @"
无法获取 IndexTTS 源码（Gitee / 代理 / ZIP 均失败）。

官方仓库仅在 GitHub；国内可用社区 Gitee 镜像（已内置尝试）：
  https://gitee.com/chongho/index-tts
  https://gitee.com/airhand/index-tts
  https://gitee.com/okhelper/index-tts

请任选其一后重试：
1) 安装 Git for Windows：https://git-scm.com/download/win
2) 手动 git clone 上述任一 Gitee 地址到：
   $InstallDir
   （目录内需有 pyproject.toml；权重仍由安装脚本从 ModelScope 拉取）
3) 或从 GitHub ZIP 解压到同一目录后点「重新排队」

目标目录：$InstallDir
"@
    }
    if (-not (Copy-IndexTtsTree $staging $InstallDir)) {
        # staging may already be the tree
        if (Test-IndexTtsSource $staging) {
            Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
            Move-Item $staging $InstallDir
        }
    }
    Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
    if (-not (Test-IndexTtsSource $InstallDir)) {
        throw "源码同步失败：$InstallDir 缺少 pyproject.toml"
    }
} else {
    Write-Host "==> IndexTTS source exists, skip download"
}

Set-Location $InstallDir

# Prefer runtime / system Python (packaged app may not have bare "python" on PATH)
function Resolve-Python {
    $cands = @()
    if ($env:AGENT_RUNTIME_DIR) {
        $cands += (Join-Path $env:AGENT_RUNTIME_DIR "venv\Scripts\python.exe")
        $cands += (Join-Path $env:AGENT_RUNTIME_DIR "python\python.exe")
    }
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pyCmd) { $cands += $pyCmd.Source }
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    foreach ($c in $cands) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    if ($pyLauncher) { return "py" }
    throw "找不到 Python。请先完成桌面端首次运行时引导，或安装 Python 3.11。"
}

$Py = Resolve-Python
Write-Host "==> Python: $Py"
Write-Host "==> Install uv + sync dependencies (skip DeepSpeed on Windows)"
if ($Py -eq "py") {
    & py -3.11 -m pip install --upgrade pip uv
} else {
    & $Py -m pip install --upgrade pip uv
}
$env:UV_INDEX_URL = "https://mirrors.aliyun.com/pypi/simple"
uv sync --extra webui

# Remove stale venv from older setup attempts; uv uses .venv
if (Test-Path "$InstallDir\.venv") {
    Remove-Item "$InstallDir\venv" -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "==> Download IndexTTS-2 checkpoints (large, may take a while)..."
$env:HF_ENDPOINT = "https://hf-mirror.com"
$ckpt = Join-Path $InstallDir "checkpoints"
if (-not (Test-Path (Join-Path $ckpt "config.yaml"))) {
    # Prefer ModelScope in CN when available.
    # Use a temp .py file — inline `python -c "..."` breaks under nested quotes / paths.
    $msOk = $false
    try {
        if ($Py -eq "py") { & py -3.11 -m pip install -q modelscope }
        else { & $Py -m pip install -q modelscope }
        Write-Host "==> try ModelScope download IndexTeam/IndexTTS-2"
        $dlPy = Join-Path $InstallDir "_ms_download_indextts2.py"
        $env:INDEXTTS_CKPT_DIR = $ckpt
        @(
            "import os"
            "from modelscope import snapshot_download"
            "snapshot_download('IndexTeam/IndexTTS-2', local_dir=os.environ['INDEXTTS_CKPT_DIR'])"
        ) | Set-Content -Path $dlPy -Encoding UTF8
        try {
            if ($Py -eq "py") { & py -3.11 $dlPy }
            else { & $Py $dlPy }
        } finally {
            Remove-Item $dlPy -Force -ErrorAction SilentlyContinue
            Remove-Item Env:INDEXTTS_CKPT_DIR -ErrorAction SilentlyContinue
        }
        if (Test-Path (Join-Path $ckpt "config.yaml")) { $msOk = $true }
    } catch {
        Write-Host "    ModelScope failed: $($_.Exception.Message)"
    }
    if (-not $msOk) {
        Write-Host "==> fallback: hf-mirror download"
        uv run hf download IndexTeam/IndexTTS-2 --local-dir $ckpt
    }
}

Write-Host "==> Download example reference audio (preset voices need voice_01.wav)..."
$venvPy = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { $venvPy = Join-Path $InstallDir "venv\Scripts\python.exe" }
if (Test-Path $venvPy) {
    & $venvPy -c "from indextts.utils.examples_downloader import ensure_examples_available; ensure_examples_available()"
    $exSrc = Join-Path $InstallDir "examples\voice_01.wav"
    $exDstDir = Join-Path $ckpt "examples"
    if ((Test-Path $exSrc) -and -not (Test-Path (Join-Path $exDstDir "voice_01.wav"))) {
        New-Item -ItemType Directory -Force -Path $exDstDir | Out-Null
        Copy-Item $exSrc (Join-Path $exDstDir "voice_01.wav")
        Write-Host "    copied examples/voice_01.wav -> checkpoints/examples/"
    }
}

# Point config at the real install dir (runtime config for packaged; project config for dev)
# YAML double-quoted strings treat \ as escape — never write "D:\path" raw.
function Update-IndexTtsConfigPath([string]$CfgPath, [string]$Dir) {
    if (-not (Test-Path $CfgPath)) { return $false }
    # Prefer forward slashes (Pathlib-safe on Windows, YAML-safe).
    $DirYaml = ($Dir -replace '\\', '/')
    try {
        $rtPy = $null
        if ($env:AGENT_RUNTIME_DIR) {
            $cand = Join-Path $env:AGENT_RUNTIME_DIR "venv\Scripts\python.exe"
            if (Test-Path $cand) { $rtPy = $cand }
        }
        if ($rtPy) {
            $pyFile = Join-Path (Split-Path $CfgPath) "_patch_indextts_path.py"
            $env:AGENT_PATCH_CFG = $CfgPath
            $env:AGENT_PATCH_DIR = $DirYaml
            @(
                "import os"
                "from pathlib import Path"
                "import yaml"
                "p = Path(os.environ['AGENT_PATCH_CFG'])"
                "d = yaml.safe_load(p.read_text(encoding='utf-8')) or {}"
                "d.setdefault('paths', {})['indextts_dir'] = os.environ['AGENT_PATCH_DIR']"
                "p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding='utf-8')"
                "print('ok')"
            ) | Set-Content -Path $pyFile -Encoding UTF8
            try {
                & $rtPy $pyFile
                if ($LASTEXITCODE -ne 0) { throw "python patch exit=$LASTEXITCODE" }
            } finally {
                Remove-Item $pyFile -Force -ErrorAction SilentlyContinue
                Remove-Item Env:AGENT_PATCH_CFG -ErrorAction SilentlyContinue
                Remove-Item Env:AGENT_PATCH_DIR -ErrorAction SilentlyContinue
            }
        } else {
            $raw = Get-Content $CfgPath -Raw -Encoding UTF8
            if ($raw -match '(?m)^(\s*indextts_dir:\s*).*$') {
                $raw = [regex]::Replace($raw, '(?m)^(\s*indextts_dir:\s*).*$', "`$1'$DirYaml'")
            } elseif ($raw -match '(?m)^paths:\s*$') {
                $raw = $raw -replace '(?m)^(paths:\s*\r?\n)', "`$1  indextts_dir: '$DirYaml'`r`n"
            } else {
                $raw = $raw.TrimEnd() + "`r`npaths:`r`n  indextts_dir: '$DirYaml'`r`n"
            }
            Set-Content -Path $CfgPath -Value $raw -Encoding UTF8
        }
        Write-Host "==> updated $CfgPath -> paths.indextts_dir=$DirYaml"
        return $true
    } catch {
        Write-Host "!! config update skipped: $($_.Exception.Message)"
        return $false
    }
}

$cfgCandidates = @()
if ($env:AGENT_CONFIG) { $cfgCandidates += $env:AGENT_CONFIG }
if ($env:AGENT_RUNTIME_DIR) { $cfgCandidates += (Join-Path $env:AGENT_RUNTIME_DIR "config.yaml") }
$cfgCandidates += (Join-Path $Root "config.yaml")
foreach ($c in $cfgCandidates) {
    if ($c -and (Test-Path $c)) {
        Update-IndexTtsConfigPath $c $InstallDir
        break
    }
}

Write-Host ""
Write-Host "Done. config.yaml should have:"
Write-Host "  paths.indextts_dir: $InstallDir"
Write-Host "  tts.backend: indextts"
Write-Host "Test (from project root):"
Write-Host "  $InstallDir\.venv\Scripts\python.exe .\tts\run_indextts.py --config config.yaml --text hello --output .\output\indextts_test.wav --mode preset --preset mandarin_female_warm"
