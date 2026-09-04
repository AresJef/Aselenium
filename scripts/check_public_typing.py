"""Check consumer programs against an installed wheel, never the source checkout."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    """Type-check positive contracts and require deliberate misuse to be rejected.

    Args:
        argv: Arguments, or None to read the current command line.

    Returns:
        Zero only if valid consumers pass and the negative controls fail correctly.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    args = parser.parse_args(argv)
    executable = str(args.python.absolute())
    environment = os.environ.copy()
    for key in ("PYTHONPATH", "MYPYPATH", "PYTHONHOME"):
        environment.pop(key, None)
    environment["PYTHONNOUSERSITE"] = "1"
    with tempfile.TemporaryDirectory(prefix="aselenium-typing-consumer-") as directory:
        working = Path(directory)
        identity = subprocess.run(
            [
                executable,
                "-I",
                "-c",
                "import aselenium, json, sys; print(json.dumps([aselenium.__file__, sys.prefix]))",
            ],
            capture_output=True,
            text=True,
            cwd=working,
            env=environment,
            timeout=30,
            check=True,
        )
        location, prefix = map(Path, json.loads(identity.stdout))
        if location.resolve().is_relative_to(
            ROOT
        ) or not location.resolve().is_relative_to(prefix.resolve()):
            raise RuntimeError(
                "Public typing checks require an installed, non-editable wheel"
            )
        shutil.copy2(ROOT / "tests/typing/public_api.py", working / "public_api.py")
        config = working / "mypy.ini"
        config.write_text(
            "[mypy]\nstrict = True\nfollow_imports = silent\n", encoding="utf-8"
        )
        command = [
            sys.executable,
            "-m",
            "mypy",
            "--no-incremental",
            "--config-file",
            str(config),
            "--python-executable",
            executable,
        ]
        positive = subprocess.run(
            command + ["public_api.py"],
            capture_output=True,
            text=True,
            cwd=working,
            env=environment,
            timeout=90,
            check=False,
        )
        print(positive.stdout, end="")
        print(positive.stderr, end="", file=sys.stderr)
        if positive.returncode:
            return positive.returncode
        negative = working / "invalid_api.py"
        negative.write_text(
            "from aselenium import Session\n"
            "async def invalid(session: Session) -> None:\n"
            '    element = await session.find_element("#missing")\n'
            "    await element.click()\n"
            "    await session.load(123)\n",
            encoding="utf-8",
        )
        rejected = subprocess.run(
            command + [str(negative)],
            capture_output=True,
            text=True,
            cwd=working,
            env=environment,
            timeout=90,
            check=False,
        )
        if (
            rejected.returncode != 1
            or "[union-attr]" not in rejected.stdout
            or "[arg-type]" not in rejected.stdout
        ):
            raise RuntimeError(
                "Consumer typing negative controls were not correctly rejected:\n"
                + rejected.stdout
                + rejected.stderr
            )
        print(
            json.dumps(
                {
                    "installed_package": str(location),
                    "valid_consumer": "passed",
                    "negative_controls": [
                        "optional lookup dereference rejected",
                        "invalid navigation argument rejected",
                    ],
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
