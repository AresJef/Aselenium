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
                "import aselenium, aselenium._paths, json, sys; "
                "from pathlib import Path; "
                "root = Path(aselenium.__file__).resolve().parent; "
                "print(json.dumps({'module': aselenium.__file__, "
                "'package_paths': list(aselenium.__path__), "
                "'path_module': aselenium._paths.__file__, "
                "'typing_marker': str(root / 'py.typed'), 'prefix': sys.prefix}))",
            ],
            capture_output=True,
            text=True,
            cwd=working,
            env=environment,
            timeout=30,
            check=True,
        )
        installation = json.loads(identity.stdout)
        location = Path(installation["module"]).resolve()
        prefix = Path(installation["prefix"]).resolve()
        package_paths = [
            location,
            Path(installation["path_module"]).resolve(),
            *(Path(path).resolve() for path in installation["package_paths"]),
        ]
        if any(
            path.is_relative_to(ROOT) or not path.is_relative_to(prefix)
            for path in package_paths
        ):
            raise RuntimeError(
                "Public typing checks require an installed, non-editable wheel"
            )
        typing_marker = Path(installation["typing_marker"]).resolve()
        if not typing_marker.is_file() or not typing_marker.is_relative_to(prefix):
            raise RuntimeError("Installed wheel does not contain its PEP 561 marker")
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
            "    await session.load(123)\n"
            "    await session.save_screenshot(b'capture')\n",
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
            or "save_screenshot" not in rejected.stdout
            or "bytes" not in rejected.stdout
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
                    "package_paths": [str(path) for path in package_paths],
                    "typing_marker": str(typing_marker),
                    "valid_consumer": "passed",
                    "negative_controls": [
                        "optional lookup dereference rejected",
                        "invalid navigation argument rejected",
                        "byte-valued output path rejected",
                    ],
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
