"""Regression contracts for validated input paths and every binary-output caller."""

from __future__ import annotations

import base64
from os import PathLike
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from aselenium import errors, utils
from aselenium.chrome.options import ChromeOptions
from aselenium.element import Element
from aselenium.firefox.options import FirefoxOptions
from aselenium.firefox.session import FirefoxSession
from aselenium.utils import validate_dir, validate_file, validate_save_file_path


class TextPath:
    """Represent an explicit string-valued filesystem path without normalization."""

    def __init__(self, value: str) -> None:
        """Retain the exact path text supplied by the test.

        Args:
            value: Path text, including empty or whitespace-only inputs.
        """
        self.value = value

    def __fspath__(self) -> str:
        """Return the original path text for filesystem protocol consumers.

        Returns:
            The unmodified string provided to this path object.
        """
        return self.value


@pytest.fixture
def output_session() -> FirefoxSession:
    """Return a started synthetic session exposing every binary-output family.

    Returns:
        Real Firefox session with a recording transport and no owned process.
    """
    service = SimpleNamespace(url="http://127.0.0.1:4444", running=True)
    session = FirefoxSession(FirefoxOptions(), service)
    session._id = "output-paths"
    session._base_url = service.url + "/session/output-paths"
    session._conn = SimpleNamespace(execute=AsyncMock())
    return session


@pytest.mark.parametrize("caller", ["element", "screenshot", "pdf", "firefox-full"])
@pytest.mark.parametrize("path", ["", TextPath(""), "\x00", None, 42, b""])
@pytest.mark.asyncio
async def test_all_output_callers_reject_invalid_paths_before_transport(
    output_session: FirefoxSession, caller: str, path: Any
) -> None:
    """Reject invalid output paths before browser I/O or accidental publication.

    Args:
        output_session: Real session using a recording transport.
        caller: Public binary-output entry point under test.
        path: Empty or malformed destination that cannot denote a text file path.
    """
    output_session._conn.execute.side_effect = AssertionError(
        "Invalid path reached browser transport; no file was written"
    )
    save = {
        "element": Element("field", output_session).save_screenshot,
        "screenshot": output_session.save_screenshot,
        "pdf": output_session.save_page,
        "firefox-full": output_session.save_full_screenshot,
    }[caller]
    with pytest.raises(errors.InvalidArgumentError) as caught:
        await save(path)
    assert isinstance(caught.value.__cause__, errors.AseleniumInvalidPathError)
    output_session._conn.execute.assert_not_called()


@pytest.mark.parametrize("caller", ["element", "screenshot", "pdf", "firefox-full"])
@pytest.mark.parametrize("kind", ["directory", "root", "suffixed-directory"])
@pytest.mark.asyncio
async def test_all_output_callers_reject_directory_destinations(
    output_session: FirefoxSession, tmp_path: Path, caller: str, kind: str
) -> None:
    """Do not convert a directory destination into an unintended sibling file.

    Args:
        output_session: Real session whose transport must remain unused.
        tmp_path: Isolated directory for destination-boundary fixtures.
        caller: Public binary-output entry point under test.
        kind: Existing directory, filesystem root, or suffix-added directory.
    """
    suffix = ".pdf" if caller == "pdf" else ".png"
    if kind == "directory":
        path = tmp_path
    elif kind == "root":
        path = Path(tmp_path.anchor)
    else:
        (tmp_path / ("capture" + suffix)).mkdir()
        path = tmp_path / "capture"
    output_session._conn.execute.side_effect = AssertionError(
        "Directory destination reached browser transport"
    )
    save = {
        "element": Element("field", output_session).save_screenshot,
        "screenshot": output_session.save_screenshot,
        "pdf": output_session.save_page,
        "firefox-full": output_session.save_full_screenshot,
    }[caller]
    with pytest.raises(errors.InvalidArgumentError) as caught:
        await save(path)
    assert isinstance(caught.value.__cause__, errors.AseleniumInvalidPathError)
    output_session._conn.execute.assert_not_called()


@pytest.mark.parametrize("caller", ["element", "screenshot", "pdf", "firefox-full"])
@pytest.mark.parametrize("name", ["capture", "  ", "中文 capture"])
@pytest.mark.asyncio
async def test_output_callers_accept_relative_pathlikes_and_preserve_names(
    output_session: FirefoxSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caller: str,
    name: str,
) -> None:
    """Publish explicit relative filenames without stripping meaningful whitespace.

    Args:
        output_session: Real session supplying base64 binary output.
        tmp_path: Isolated working directory receiving the output.
        monkeypatch: Fixture restoring the working directory after the test.
        caller: Public binary-output entry point under test.
        name: Valid filename, including Unicode and whitespace-only names.
    """
    monkeypatch.chdir(tmp_path)
    data = b"%PDF-fixture" if caller == "pdf" else b"\x89PNG\r\n\x1a\nfixture"
    output_session._conn.execute.return_value = {
        "value": base64.b64encode(data).decode("ascii")
    }
    save = {
        "element": Element("field", output_session).save_screenshot,
        "screenshot": output_session.save_screenshot,
        "pdf": output_session.save_page,
        "firefox-full": output_session.save_full_screenshot,
    }[caller]
    assert await save(TextPath(name)) is True
    suffix = ".pdf" if caller == "pdf" else ".png"
    assert (tmp_path / (name + suffix)).read_bytes() == data
    assert output_session._conn.execute.await_count == 1


@pytest.mark.parametrize("path", ["", TextPath(""), b"", b"input.txt", "bad\x00path"])
def test_path_validators_reject_empty_or_nontext_inputs(path: Any) -> None:
    """Do not turn invalid input paths into the current working directory.

    Args:
        path: Empty, byte-valued, or null-containing filesystem-path input.
    """
    for validate in (validate_file, validate_dir):
        with pytest.raises(errors.AseleniumInvalidPathError):
            validate(path)
    with pytest.raises(errors.AseleniumInvalidPathError):
        validate_save_file_path(path, ".png")


@pytest.mark.parametrize("kind", ["file", "directory"])
@pytest.mark.parametrize("path_kind", ["string", "pathlib", "custom"])
def test_input_validators_make_relative_pathlikes_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, path_kind: str
) -> None:
    """Apply the documented absolute-return contract to all text-path inputs.

    Args:
        tmp_path: Isolated working directory holding the real path target.
        monkeypatch: Fixture restoring the working directory after the test.
        kind: Whether the existing target is a file or directory.
        path_kind: String, pathlib, or custom filesystem-path input representation.
    """
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "  fixture 中文  "
    if kind == "file":
        target.touch()
        validate = validate_file
    else:
        target.mkdir()
        validate = validate_dir
    source: str | PathLike[str] = {
        "string": target.name,
        "pathlib": Path(target.name),
        "custom": TextPath(target.name),
    }[path_kind]
    result = validate(source)
    assert result == str(target) and isinstance(result, str)
    assert Path(result).samefile(target)


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_input_validators_expand_home_and_preserve_symlink_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Expand home paths without replacing a symlink alias with its resolved target.

    Args:
        tmp_path: Isolated directory containing the symbolic-link fixture.
        monkeypatch: Fixture restoring the controlled home-expansion dependency.
        kind: Whether the symlink refers to a regular file or directory.
    """
    target = tmp_path / "target"
    alias = tmp_path / "alias"
    if kind == "file":
        target.touch()
        validate = validate_file
    else:
        target.mkdir()
        validate = validate_dir
    alias.symlink_to(target, target_is_directory=kind == "directory")

    def expand_home(path: str) -> str:
        """Map the tested home-relative alias without changing process environment.

        Args:
            path: Original text passed to the standard-library expansion boundary.

        Returns:
            Absolute fixture alias as if supplied by user-home expansion.
        """
        assert path == "~/alias"
        return str(alias)

    monkeypatch.setattr(utils, "expanduser", expand_home)
    result = validate("~/alias")
    assert result == str(alias)
    assert Path(result).samefile(target)


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_input_validators_preserve_symlink_parent_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Do not silently choose a lexical decoy when '..' follows a directory symlink.

    Args:
        tmp_path: Isolated working directory containing intended and decoy targets.
        monkeypatch: Fixture restoring the working directory after the test.
        kind: Whether the validated target is a file or directory.
    """
    monkeypatch.chdir(tmp_path)
    launch, actual = tmp_path / "launch", tmp_path / "actual"
    launch.mkdir()
    (actual / "nested").mkdir(parents=True)
    (launch / "link").symlink_to(actual / "nested", target_is_directory=True)
    target, decoy = actual / "target", launch / "target"
    if kind == "file":
        target.touch()
        decoy.touch()
        validate = validate_file
    else:
        target.mkdir()
        decoy.mkdir()
        validate = validate_dir
    result = validate(Path("launch/link/../target"))
    assert Path(result).is_absolute() and ".." in Path(result).parts
    assert Path(result).samefile(target)
    assert not Path(result).samefile(decoy)


@pytest.mark.asyncio
async def test_output_path_preserves_symlink_parent_destination(
    output_session: FirefoxSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Write to the filesystem-intended parent without collapsing a symlink traversal.

    Args:
        output_session: Real session returning synthetic screenshot bytes.
        tmp_path: Isolated directory containing a symlink and distinct parent paths.
        monkeypatch: Fixture restoring the working directory after the test.
    """
    monkeypatch.chdir(tmp_path)
    launch, actual = tmp_path / "launch", tmp_path / "actual"
    launch.mkdir()
    (actual / "nested").mkdir(parents=True)
    (launch / "link").symlink_to(actual / "nested", target_is_directory=True)
    output_session._conn.execute.return_value = {
        "value": base64.b64encode(b"PNG fixture").decode("ascii")
    }
    assert await output_session.save_screenshot("launch/link/../capture") is True
    assert (actual / "capture.png").read_bytes() == b"PNG fixture"
    assert not (launch / "capture.png").exists()


@pytest.mark.asyncio
async def test_relative_upload_and_browser_binary_are_stored_as_absolute_paths(
    output_session: FirefoxSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expose normalized paths at upload and browser-option caller boundaries.

    Args:
        output_session: Real session with a recording transport for upload commands.
        tmp_path: Isolated directory containing a synthetic upload/browser file.
        monkeypatch: Fixture restoring the working directory after the test.
    """
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "fixture"
    target.touch()
    await Element("upload", output_session).upload("fixture")
    assert output_session._conn.execute.await_args.kwargs["body"] == {
        "text": str(target)
    }
    options = ChromeOptions()
    options.browser_location = "fixture"
    assert options.browser_location == str(target)


def test_directory_validator_accepts_explicit_current_directory_and_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep valid directory inputs supported while rejecting empty input strings.

    Args:
        tmp_path: Isolated current directory.
        monkeypatch: Fixture restoring the working directory after the test.
    """
    monkeypatch.chdir(tmp_path)
    assert validate_dir(Path(".")) == str(tmp_path)
    root = Path(tmp_path.anchor)
    assert validate_dir(root) == str(root)
    assert validate_dir("~") == str(Path.home())
    with pytest.raises(errors.AseleniumFileNotFoundError):
        validate_file(root)
