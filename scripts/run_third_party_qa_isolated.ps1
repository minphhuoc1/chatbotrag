param(
    [string]$SourceReport = "reports/legal_qa/legal_qa_report_20260420_215203.json",
    [string]$VendorPath = "D:\\chatbotrag\\.vendor\\Lib\\site-packages",
    [switch]$DisableRagas,
    [switch]$DisableTruLens
)

$workspace = (Resolve-Path ".").Path
if (-not (Test-Path $VendorPath)) {
    Write-Error "Vendor path not found: $VendorPath"
    exit 1
}
if (-not (Test-Path $SourceReport)) {
    Write-Error "Source report not found: $SourceReport"
    exit 1
}

$env:PYTHONUTF8 = "1"
$env:PYTHONNOUSERSITE = "1"
$env:PYTHONPATH = "$VendorPath;$workspace"

# Keep QA run stable on Windows by isolating from global site-packages.
$env:LEGAL_CHATBOT_LANGFUSE_ENABLED = "0"
$env:RAGAS_USE_VENDOR_PATH = "0"
$env:TRULENS_USE_VENDOR_PATH = "0"
$env:THIRD_PARTY_SOURCE_REPORT = $SourceReport
$env:ENABLE_RAGAS = "1"
$env:ENABLE_TRULENS = "1"
$env:ENABLE_LANGSMITH_DATASET_SYNC = "0"
$env:ENABLE_LANGFUSE_DATASET_SYNC = "0"

if ($DisableRagas.IsPresent) {
    $env:ENABLE_RAGAS = "0"
}
if ($DisableTruLens.IsPresent) {
    $env:ENABLE_TRULENS = "0"
}

python -u -S scripts/third_party_qa_runner.py
exit $LASTEXITCODE
