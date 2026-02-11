# Extracted into module Private/
# Source: run_today_and_export.ps1:17-35
function Resolve-Python {
    $candidates = @(
        "C:\Users\rick\AppData\Local\Programs\Python\Python311\python.exe",
        "C:\Users\rick\AppData\Local\Programs\Python\Python310\python.exe",
        "C:\Python311\python.exe",
        "py"
    )
    foreach ($c in $candidates) {
        if ($c -eq "py") {
            try {
                $v = & py -3 -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $v) { return "py -3" }
            } catch {}
        } else {
            if (Test-Path $c) { return $c }
        }
    }
    throw "Python not found. Install Python 3.11 or update Resolve-Python candidates."
}

