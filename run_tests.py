"""Run the project's standalone test files with the current Python interpreter."""
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TEST_DIR = ROOT / "tests"


def main() -> int:
    tests = sorted(TEST_DIR.glob("test_*.py"))
    if not tests:
        print("No tests found.")
        return 1

    failed: list[Path] = []
    for test in tests:
        rel = test.relative_to(ROOT)
        print(f"\n== {rel} ==", flush=True)
        result = subprocess.run([sys.executable, str(test)], cwd=ROOT)
        if result.returncode != 0:
            failed.append(rel)

    print("\n== Summary ==", flush=True)
    print(f"Ran {len(tests)} test files.")
    if failed:
        print("Failed:")
        for path in failed:
            print(f"- {path}")
        return 1
    print("All test files passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
