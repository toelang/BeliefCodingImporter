# Belief Coding Resource Importer - self-updater.
#
# Pulls the latest project code from GitHub and replaces it in place.
# Your credentials.json, token.json, PDFs/, import history
# (import_state.db / import_log.csv / import_plan.txt), and Python
# virtual environment are never touched - only the project's own .py/
# .bat/.md files are replaced.
#
# Run this any time you're told there's an update: double-click
# update.bat (or run "powershell -File update.ps1" from this folder).

$ErrorActionPreference = "Stop"

$RepoZipUrl = "https://github.com/toelang/BeliefCodingImporter/archive/refs/heads/claude/belief-coding-importer-abvyhd.zip"
$ProjectDir = $PSScriptRoot
$TempDir = Join-Path $env:TEMP ("bci_update_" + [guid]::NewGuid())
$ZipPath = Join-Path $TempDir "update.zip"

# Only these are ever overwritten. Anything not in this list -
# credentials.json, token.json, PDFs/, venv/, import_state.db,
# import_log.csv, import_plan.txt, debug.log - is left completely alone.
$FilesToUpdate = @(
    "main.py", "config.py", "pdf_parser.py", "drive_crawler.py",
    "drive_uploader.py", "local_uploader.py", "duplicate_detector.py",
    "database.py", "plan_report.py", "logger.py", "requirements.txt",
    "run.bat", "update.ps1", "update.bat", "README.md", ".gitignore"
)

try {
    New-Item -ItemType Directory -Path $TempDir | Out-Null

    Write-Host "Downloading latest version..."
    Invoke-WebRequest -Uri $RepoZipUrl -OutFile $ZipPath

    Write-Host "Extracting..."
    Expand-Archive -Path $ZipPath -DestinationPath $TempDir -Force

    $ExtractedDir = Get-ChildItem -Path $TempDir -Directory |
        Where-Object { $_.Name -like "BeliefCodingImporter-*" } |
        Select-Object -First 1

    if (-not $ExtractedDir) {
        Write-Host "Could not find the extracted project folder - aborting. Nothing was changed."
        exit 1
    }

    Write-Host ""
    foreach ($file in $FilesToUpdate) {
        $source = Join-Path $ExtractedDir.FullName $file
        $destination = Join-Path $ProjectDir $file
        if (Test-Path $source) {
            Copy-Item -Path $source -Destination $destination -Force
            Write-Host "Updated: $file"
        }
    }

    $venvPython = Join-Path $ProjectDir "venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        Write-Host ""
        Write-Host "Updating Python dependencies..."
        & $venvPython -m pip install -r (Join-Path $ProjectDir "requirements.txt") --quiet
    }

    Write-Host ""
    Write-Host "Update complete."
    Write-Host "credentials.json, token.json, PDFs/, and your import history were not touched."
}
finally {
    if (Test-Path $TempDir) {
        Remove-Item -Path $TempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
