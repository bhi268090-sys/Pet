import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from recon import GhostRecon


REPORT_PATH = Path(tempfile.gettempdir()) / "cubepet_recon_diagnostic_report.json"


def classify_value(value: Any) -> str:
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned.lower() == "unknown":
            return "UNKNOWN"
        return "WORKING"

    if isinstance(value, dict):
        if not value:
            return "UNKNOWN"
        statuses = [classify_value(v) for v in value.values()]
        if all(status == "UNKNOWN" for status in statuses):
            return "UNKNOWN"
        return "WORKING"

    if value is None:
        return "UNKNOWN"
    return "WORKING"


def run_recon_diagnostics() -> dict[str, Any]:
    recon = GhostRecon(debug=True)

    checks: list[tuple[str, Any]] = [
        ("_get_ram", recon._get_ram),
        ("_get_disk", recon._get_disk),
        ("_get_uptime", recon._get_uptime),
        ("_get_cpu", recon._get_cpu),
        ("_get_gpu", recon._get_gpu),
        ("_get_model", recon._get_model),
        ("_get_os", recon._get_os),
        ("_get_hostname", recon._get_hostname),
    ]

    results: list[dict[str, Any]] = []
    for name, fn in checks:
        try:
            value = fn()
            status = classify_value(value)
            results.append(
                {
                    "function": name,
                    "status": status,
                    "value": value,
                    "error": "",
                }
            )
        except Exception as exc:
            results.append(
                {
                    "function": name,
                    "status": "ERROR",
                    "value": "",
                    "error": repr(exc),
                }
            )

    summary = {
        "working": sum(1 for item in results if item["status"] == "WORKING"),
        "unknown": sum(1 for item in results if item["status"] == "UNKNOWN"),
        "error": sum(1 for item in results if item["status"] == "ERROR"),
    }

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "summary": summary,
    }


def print_report(report: dict[str, Any]) -> None:
    print("GhostRecon Diagnostics")
    print("=" * 80)
    print(f"UTC Timestamp: {report['timestamp_utc']}")
    print(
        "Summary: "
        f"WORKING={report['summary']['working']}, "
        f"UNKNOWN={report['summary']['unknown']}, "
        f"ERROR={report['summary']['error']}"
    )
    print("-" * 80)
    for item in report["results"]:
        fn = item["function"]
        status = item["status"]
        value = item["value"]
        error = item["error"]
        print(f"{fn:26} | {status:7} | value={ascii(value)}")
        if error:
            print(f"{'':26} | {'':7} | error={ascii(error)}")


def main() -> None:
    report = run_recon_diagnostics()
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print_report(report)
    print("-" * 80)
    print(f"Saved JSON report to: {REPORT_PATH.resolve()}")


if __name__ == "__main__":
    main()
