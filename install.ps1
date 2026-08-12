# Pico 原生 Windows PowerShell 一键安装脚本。
#
# 远程：
#   irm https://raw.githubusercontent.com/Hackerismydream/pico/main/install.ps1 | iex
#
# 目标：让全新 Windows 机器无需管理员权限即可运行 `pico`。脚本具备幂等性，
# 会复用已有工具并只补齐缺项：
#   1. uv            （Python 工具链与包管理器）
#   2. Node.js >= 22 （TUI 运行时；系统缺少时私有安装）
#   3. pico          （作为全局 uv 工具安装）
#   4. myna-memory   （MYNA_WHEEL_URL 或配套发布资产可用时安装）

$ErrorActionPreference = "Stop"

$MinNodeMajor = 22
$PicoHome = if ($env:PICO_HOME) { $env:PICO_HOME } else { Join-Path $HOME ".pico" }
$NodeRuntimeDir = Join-Path $PicoHome "runtime"

function Write-Info([string]$Message) {
    Write-Host ">" $Message -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "OK" $Message -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Warning $Message
}

function Fail([string]$Message) {
    Write-Error $Message
    exit 1
}

function Add-ProcessPath([string]$PathToAdd) {
    if (-not $PathToAdd) { return }
    if (-not (Test-Path $PathToAdd)) { return }
    $parts = $env:PATH -split ';'
    if ($parts -notcontains $PathToAdd) {
        $env:PATH = "$PathToAdd;$env:PATH"
    }
}

function Find-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        (Join-Path $HOME ".local\bin\uv.exe"),
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Ensure-Uv {
    $uv = Find-Uv
    if ($uv) {
        Write-Ok "uv is installed ($(& $uv --version))"
        Add-ProcessPath (Split-Path $uv -Parent)
        return $uv
    }

    Write-Info "uv not found; installing..."
    Invoke-Expression (Invoke-RestMethod "https://astral.sh/uv/install.ps1")
    $uv = Find-Uv
    if (-not $uv) {
        Fail "uv was installed but is still not available. Check PATH (expected ~/.local/bin)."
    }
    Add-ProcessPath (Split-Path $uv -Parent)
    Write-Ok "uv installed"
    return $uv
}

function Get-NodeArch {
    switch ($env:PROCESSOR_ARCHITECTURE) {
        "ARM64" { return "arm64" }
        "AMD64" { return "x64" }
        default { Fail "Unsupported Windows architecture: $env:PROCESSOR_ARCHITECTURE" }
    }
}

function Test-NodeOk([string]$NodePath) {
    if (-not $NodePath) { return $false }
    if (-not (Test-Path $NodePath)) { return $false }
    try {
        $version = (& $NodePath --version).Trim()
        $major = [int](($version.TrimStart("v") -split "\.")[0])
        return $major -ge $MinNodeMajor
    } catch {
        return $false
    }
}

function Find-PrivateNode {
    $candidates = @()
    $direct = Join-Path $NodeRuntimeDir "node\node.exe"
    $directBin = Join-Path $NodeRuntimeDir "node\bin\node.exe"
    if (Test-Path $direct) { $candidates += $direct }
    if (Test-Path $directBin) { $candidates += $directBin }
    if (Test-Path $NodeRuntimeDir) {
        $candidates += Get-ChildItem $NodeRuntimeDir -Directory -Filter "node-v22*" -ErrorAction SilentlyContinue |
            ForEach-Object {
                @(
                    (Join-Path $_.FullName "node.exe"),
                    (Join-Path $_.FullName "bin\node.exe")
                )
            }
    }
    foreach ($candidate in $candidates) {
        if (Test-NodeOk $candidate) { return $candidate }
    }
    return $null
}

function Get-LatestNodeV22 {
    try {
        $index = Invoke-RestMethod "https://nodejs.org/dist/index.json"
        $entry = $index | Where-Object { $_.version -like "v22.*" } | Select-Object -First 1
        if ($entry -and $entry.version) { return $entry.version }
    } catch {
        Write-Warn "Could not query Node.js release index; falling back to v22.20.0"
    }
    return "v22.20.0"
}

function Ensure-Node {
    $systemNode = Get-Command node -ErrorAction SilentlyContinue
    if ($systemNode -and (Test-NodeOk $systemNode.Source)) {
        Write-Ok "Node.js meets requirements ($(& $systemNode.Source --version))"
        return $systemNode.Source
    }

    $privateNode = Find-PrivateNode
    if ($privateNode) {
        Write-Ok "Existing Pico private Node found ($privateNode)"
        Add-ProcessPath (Split-Path $privateNode -Parent)
        return $privateNode
    }

    Write-Info "Node.js >= $MinNodeMajor not found; downloading private runtime..."
    $arch = Get-NodeArch
    $version = Get-LatestNodeV22
    $pkg = "node-$version-win-$arch"
    $url = "https://nodejs.org/dist/$version/$pkg.zip"
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("pico-node-" + [guid]::NewGuid().ToString("N"))
    $zipPath = Join-Path $tmp "node.zip"

    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    New-Item -ItemType Directory -Path $NodeRuntimeDir -Force | Out-Null

    try {
        Write-Info "  $url"
        Invoke-WebRequest $url -OutFile $zipPath

        try {
            $sums = (Invoke-WebRequest "https://nodejs.org/dist/$version/SHASUMS256.txt").Content
            $line = ($sums -split "`n") | Where-Object { $_ -match "\s+$([regex]::Escape("$pkg.zip"))$" } | Select-Object -First 1
            if ($line) {
                $expected = (($line.Trim()) -split "\s+")[0].ToLowerInvariant()
                $actual = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($expected -ne $actual) {
                    Fail "Node checksum mismatch (expected $expected, got $actual)."
                }
                Write-Ok "Node zip SHA256 verified"
            } else {
                Write-Warn "SHASUMS256.txt did not list $pkg.zip; skipping checksum verification"
            }
        } catch {
            Write-Warn "Could not verify Node checksum; continuing"
        }

        Expand-Archive $zipPath -DestinationPath $tmp -Force
        $src = Join-Path $tmp $pkg
        $dest = Join-Path $NodeRuntimeDir $pkg
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
        Move-Item $src $dest

        $node = Join-Path $dest "node.exe"
        if (-not (Test-NodeOk $node)) {
            Fail "Downloaded Node runtime is not usable on this machine."
        }
        Add-ProcessPath $dest
        Write-Ok "Node private runtime ready: $dest"
        return $node
    } finally {
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

function Resolve-PicoReleaseAssets {
    if ($env:PICO_WHEEL_URL) {
        return [pscustomobject]@{ Pico = $env:PICO_WHEEL_URL; Myna = $env:MYNA_WHEEL_URL }
    }
    Write-Info "Resolving the latest Pico release from GitHub..."
    $release = Invoke-RestMethod "https://api.github.com/repos/Hackerismydream/pico/releases/latest" -Headers @{ "User-Agent" = "pico-installer" }
    $picoAsset = $release.assets | Where-Object { $_.browser_download_url -match "/pico_harness-[^/]+\.whl$" } | Select-Object -First 1
    if (-not $picoAsset) {
        Fail "Could not resolve the latest Pico release wheel from GitHub. Set PICO_WHEEL_URL to a wheel URL."
    }
    $mynaUrl = $env:MYNA_WHEEL_URL
    if (-not $mynaUrl) {
        $mynaAsset = $release.assets | Where-Object { $_.browser_download_url -match "/myna_memory-[^/]+\.whl$" } | Select-Object -First 1
        if ($mynaAsset) { $mynaUrl = $mynaAsset.browser_download_url }
    }
    return [pscustomobject]@{ Pico = $picoAsset.browser_download_url; Myna = $mynaUrl }
}

function Install-Pico([string]$UvPath, [string]$NodePath) {
    $scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
    $pyproject = Join-Path $scriptDir "pyproject.toml"
    if ((Test-Path $pyproject) -and (Select-String -Path $pyproject -Pattern '^name = "pico-harness"' -Quiet)) {
        Write-Info "Detected local Pico source checkout; installing editable: $scriptDir"
        $entry = Join-Path $scriptDir "ui-tui\dist\entry.js"
        if (-not (Test-Path $entry)) {
            $nodeDir = Split-Path $NodePath -Parent
            Add-ProcessPath $nodeDir
            $npm = Get-Command npm -ErrorAction SilentlyContinue
            if ($npm) {
                Write-Info "Building TUI bundle (ui-tui/dist/entry.js)..."
                Push-Location (Join-Path $scriptDir "ui-tui")
                try {
                    & $npm.Source ci
                    & $npm.Source run build
                } finally {
                    Pop-Location
                }
            } else {
                Write-Warn "Found node but not npm; skipping TUI bundle build"
            }
        }
        # 默认安装全部渠道适配器；若聚合额外依赖无法在当前平台构建，则回退到
        # 基础 Pico，避免单个渠道 SDK 阻塞完整安装。
        $mynaArgs = @()
        if ($env:MYNA_WHEEL_URL) {
            Write-Info "Installing Myna from $env:MYNA_WHEEL_URL"
            $mynaArgs = @("--with-executables-from", $env:MYNA_WHEEL_URL)
        }
        try {
            & $UvPath tool install --force @mynaArgs -e "$scriptDir[channels]"
            if ($LASTEXITCODE -ne 0) { throw "channel extras install failed" }
        } catch {
            Write-Warn "Channel dependencies failed to install; installed base pico only. Some channels stay unavailable (see: pico channels list)."
            & $UvPath tool install --force @mynaArgs -e "$scriptDir"
            if ($LASTEXITCODE -ne 0) { Fail "Pico install failed." }
        }
    } else {
        $assets = Resolve-PicoReleaseAssets
        Write-Info "  installing $($assets.Pico)"
        $mynaArgs = @()
        if ($assets.Myna) {
            Write-Info "  pairing Myna $($assets.Myna)"
            $mynaArgs = @("--with-executables-from", $assets.Myna)
        }
        try {
            & $UvPath tool install --force @mynaArgs "pico-harness[channels] @ $($assets.Pico)"
            if ($LASTEXITCODE -ne 0) { throw "channel extras install failed" }
        } catch {
            Write-Warn "Channel dependencies failed to install; installed base pico only. Some channels stay unavailable (see: pico channels list)."
            & $UvPath tool install --force @mynaArgs $assets.Pico
            if ($LASTEXITCODE -ne 0) { Fail "Pico install failed." }
        }
        if (-not $assets.Myna) {
            Write-Warn "No paired myna-memory wheel was published with this Pico release. Install Myna separately, or run pico onboard --skip-memory."
        }
    }
    & $UvPath tool update-shell | Out-Null
    Write-Ok "Pico installed"
}

function Main {
    $uv = Ensure-Uv
    $node = Ensure-Node
    Install-Pico $uv $node

    $toolBin = Join-Path $HOME ".local\bin"
    Add-ProcessPath $toolBin

    Write-Host ""
    Write-Ok "All set. Open a new PowerShell window, enter a Git repository, then run:"
    Write-Host ""
    Write-Host "    pico onboard    # configure Provider, Memory, and first Turn"
    Write-Host "    pico            # enter the TUI"
    Write-Host "    pico run -m `"hello`""
    Write-Host ""
    if (($env:PATH -split ';') -notcontains $toolBin) {
        Write-Warn "Current PATH does not include $toolBin. Restart PowerShell if 'pico' is not found."
    }
}

Main
