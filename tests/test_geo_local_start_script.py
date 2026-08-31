from pathlib import Path


def test_local_start_script_accepts_explicit_scan_proxy():
    script = (Path(__file__).resolve().parents[1] / "scripts" / "start_local_geo_demo.ps1").read_text(encoding="utf-8")

    assert "[string]$GeoScanProxy" in script
    assert '$env:HTTP_PROXY = $GeoScanProxy' in script
    assert '$env:HTTPS_PROXY = $GeoScanProxy' in script
