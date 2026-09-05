"""Adversarial archives stay inside fresh disposable staging directories."""

from __future__ import annotations

import os
import stat
import tarfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from aselenium import errors
from aselenium.manager import _filesystem as safety
from aselenium.manager import file as files

PAYLOAD = b"fixture bytes; never executed"


def make_archive(kind: Any, entries: Any) -> Any:
    """Entries are (name, type, data, mode); all data stays in memory.

    Args:
        kind: Fixture or parametrized kind input for this regression.
        entries: Fixture or parametrized entries input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    stream = BytesIO()
    if kind == "zip":
        with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
            for name, entry_type, data, mode in entries:
                member = ZipInfo(name + "/" if entry_type == "dir" else name)
                member.create_system = 3
                member.external_attr = (
                    {
                        "file": stat.S_IFREG,
                        "dir": stat.S_IFDIR,
                        "symlink": stat.S_IFLNK,
                        "fifo": stat.S_IFIFO,
                    }[entry_type]
                    | mode
                ) << 16
                archive.writestr(member, data)
    else:
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name, entry_type, data, mode in entries:
                member = tarfile.TarInfo(name)
                member.type = {
                    "file": tarfile.REGTYPE,
                    "dir": tarfile.DIRTYPE,
                    "symlink": tarfile.SYMTYPE,
                    "hardlink": tarfile.LNKTYPE,
                    "fifo": tarfile.FIFOTYPE,
                    "device": tarfile.CHRTYPE,
                }[entry_type]
                member.mode = mode
                if entry_type in {"symlink", "hardlink"}:
                    member.linkname = data.decode()
                elif entry_type == "file":
                    member.size = len(data)
                archive.addfile(member, BytesIO(data) if entry_type == "file" else None)
    return stream.getvalue()


def download(kind: Any, entries: Any, os_name: str = "linux") -> Any:
    """Download.

    Args:
        kind: Fixture or parametrized kind input for this regression.
        entries: Fixture or parametrized entries input for this regression.
        os_name: Fixture or parametrized os name input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    suffix = "zip" if kind == "zip" else "tar.gz"
    return files.ChromeDriverFile(
        os_name, "https://offline.invalid/driver." + suffix, make_archive(kind, entries)
    )


def assert_rejected(tmp_path: Path, kind: Any, entries: Any) -> None:
    """Assert rejected.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        kind: Fixture or parametrized kind input for this regression.
        entries: Fixture or parametrized entries input for this regression.
    """
    target = tmp_path / "entry"
    with pytest.raises(errors.InvalidDownloadFileError) as failure:
        download(kind, entries).unpack(str(target))
    assert failure.value.__cause__ is not None
    assert not target.exists()
    assert not list(tmp_path.glob(".aselenium-stage-*"))


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize(
    "name",
    [
        "../escaped",
        "/absolute",
        "nested/../../escaped",
        "C:/absolute",
        "C:relative",
        r"..\escaped",
        r"\\server\share",
        "nested/file:stream",
        "NUL",
        "aux.txt",
        "COM1.log",
        "nested/trailing.",
        "nested/trailing ",
        "bad\nname",
    ],
)
def test_unsafe_member_paths_reject_the_entire_archive(
    tmp_path: Path, kind: Any, name: Any
) -> None:
    """Verify unsafe member paths reject the entire archive.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        kind: Fixture or parametrized kind input for this regression.
        name: Fixture or parametrized name input for this regression.
    """
    assert_rejected(
        tmp_path,
        kind,
        [("chromedriver", "file", PAYLOAD, 0o644), (name, "file", b"bad", 0o644)],
    )
    assert not (tmp_path / "escaped").exists()


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize("alias", ["DRIVER", "./driver", "driver"])
def test_duplicate_and_case_aliases_are_rejected(
    tmp_path: Path, kind: Any, alias: Any
) -> None:
    """Verify duplicate and case aliases are rejected.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        kind: Fixture or parametrized kind input for this regression.
        alias: Fixture or parametrized alias input for this regression.
    """
    entries = [("driver", "file", PAYLOAD, 0o644), (alias, "file", PAYLOAD, 0o644)]
    if kind == "zip" and alias == "driver":
        with pytest.warns(UserWarning, match="Duplicate name"):
            content = make_archive(kind, entries)
        with pytest.raises(errors.InvalidDownloadFileError):
            files.ChromeDriverFile(
                "linux", "https://offline.invalid/driver.zip", content
            ).unpack(str(tmp_path / "entry"))
    else:
        assert_rejected(tmp_path, kind, entries)


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize("reverse", [False, True])
def test_file_directory_collision_is_rejected_in_either_order(
    tmp_path: Path, kind: Any, reverse: Any
) -> None:
    """Verify file directory collision is rejected in either order.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        kind: Fixture or parametrized kind input for this regression.
        reverse: Fixture or parametrized reverse input for this regression.
    """
    entries = [
        ("parent", "file", PAYLOAD, 0o644),
        ("parent/chromedriver", "file", PAYLOAD, 0o644),
    ]
    assert_rejected(tmp_path, kind, entries[::-1] if reverse else entries)


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize(
    "link",
    [b"../../foreign", b"/absolute", b"C:/foreign", b"..\\foreign", b"missing", b"."],
)
def test_unsafe_dangling_and_ancestor_symlinks_are_rejected(
    tmp_path: Path, kind: Any, link: Any
) -> None:
    """Verify unsafe dangling and ancestor symlinks are rejected.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        kind: Fixture or parametrized kind input for this regression.
        link: Fixture or parametrized link input for this regression.
    """
    assert_rejected(tmp_path, kind, [("chromedriver", "symlink", link, 0o777)])


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_symlink_parent_cannot_redirect_later_extraction(
    tmp_path: Path, kind: Any
) -> None:
    """Verify symlink parent cannot redirect later extraction.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        kind: Fixture or parametrized kind input for this regression.
    """
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    assert_rejected(
        tmp_path,
        kind,
        [
            ("redirect", "symlink", b"../../foreign", 0o777),
            ("redirect/chromedriver", "file", PAYLOAD, 0o644),
        ],
    )
    assert list(foreign.iterdir()) == []


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_link_cycle_is_rejected(tmp_path: Path, kind: Any) -> None:
    """Verify link cycle is rejected.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        kind: Fixture or parametrized kind input for this regression.
    """
    assert_rejected(
        tmp_path, kind, [("a", "symlink", b"b", 0o777), ("b", "symlink", b"a", 0o777)]
    )


@pytest.mark.skipif(
    os.name == "nt", reason="Native Windows symlink privileges are not assumed"
)
@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_deferred_link_cannot_change_an_earlier_parent_traversal_to_escape(
    tmp_path: Path, kind: Any
) -> None:
    """Verify deferred link cannot change an earlier parent traversal to escape.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        kind: Fixture or parametrized kind input for this regression.
    """
    assert_rejected(
        tmp_path,
        kind,
        [
            ("safe", "file", PAYLOAD, 0o644),
            ("deep/seed", "file", PAYLOAD, 0o644),
            ("shallow/seed", "file", PAYLOAD, 0o644),
            ("chromedriver", "symlink", b"deep/alias/../../safe", 0o777),
            ("deep/alias", "symlink", b"../shallow", 0o777),
        ],
    )


@pytest.mark.skipif(
    os.name == "nt", reason="Native Windows symlink privileges are not assumed"
)
@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_safe_internal_bundle_links_and_helper_permissions_survive(
    tmp_path: Path, kind: Any
) -> None:
    """Verify safe internal bundle links and helper permissions survive.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        kind: Fixture or parametrized kind input for this regression.
    """
    entries = [
        ("bundle/chromedriver", "symlink", b"Versions/Current/driver", 0o777),
        ("bundle/Versions/Current", "symlink", b"1", 0o777),
        ("bundle/Versions/1/driver", "file", PAYLOAD, 0o6755),
        ("bundle/helper", "file", PAYLOAD, 0o755),
        ("bundle/LICENSE", "file", b"license", 0o666),
    ]
    target = tmp_path / "entry"
    result = Path(download(kind, entries).unpack(str(target)))
    assert result.read_bytes() == PAYLOAD
    result.relative_to(target / "extracted")
    assert result.stat().st_mode & 0o7777 == 0o711
    assert (target / "extracted/bundle/helper").stat().st_mode & stat.S_IXUSR
    assert not ((target / "extracted/bundle/LICENSE").stat().st_mode & 0o111)
    assert (target / "extracted/bundle/chromedriver").is_symlink()
    assert (target / "extracted/bundle/chromedriver").read_bytes() == PAYLOAD


def test_contained_tar_hardlink_to_regular_data_is_supported(tmp_path: Path) -> None:
    """Verify contained tar hardlink to regular data is supported.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    result = Path(
        download(
            "tar",
            [
                ("chromedriver", "hardlink", b"real-driver", 0o777),
                ("real-driver", "file", PAYLOAD, 0o644),
            ],
        ).unpack(str(tmp_path / "entry"))
    )
    assert result.read_bytes() == PAYLOAD
    assert result.stat().st_ino == (result.parent / "real-driver").stat().st_ino


def test_archive_writer_retains_validated_link_targets_as_pure_posix_paths(
    tmp_path: Path,
) -> None:
    """Keep portable link metadata parsed between validation and publication.

    Args:
        tmp_path: Isolated directory containing the private extraction root.
    """
    writer = safety.ArchiveWriter(tmp_path / "extracted")
    writer.add(
        "bundle/bin/chromedriver",
        "symlink",
        0,
        0o777,
        link="../lib/driver",
    )

    assert writer.links == [
        (
            tmp_path / "extracted/bundle/bin/chromedriver",
            PurePosixPath("../lib/driver"),
            "symlink",
        )
    ]
    assert isinstance(writer.links[0][1], PurePosixPath)


@pytest.mark.skipif(
    os.name == "nt", reason="Native Windows symlink privileges are not assumed"
)
def test_contained_symlink_parent_traversal_is_supported(tmp_path: Path) -> None:
    """Allow meaningful ``..`` targets that remain inside the extraction root.

    Args:
        tmp_path: Isolated directory containing the published archive.
    """
    result = download(
        "tar",
        [
            ("bundle/bin/chromedriver", "symlink", b"../lib/driver", 0o777),
            ("bundle/lib/driver", "file", PAYLOAD, 0o755),
        ],
    ).unpack(tmp_path / "entry")

    link = tmp_path / "entry/extracted/bundle/bin/chromedriver"
    assert result == tmp_path / "entry/extracted/bundle/lib/driver"
    assert link.is_symlink()
    assert result.read_bytes() == PAYLOAD


@pytest.mark.parametrize(
    "target",
    [
        "NUL",
        "aux.txt",
        "COM1.log",
        "folder/trailing.",
        "folder/trailing ",
        "folder/bad\nname",
        "folder:stream",
        "C:/absolute",
        "../outside",
        "\ud800",
    ],
)
def test_nonportable_or_escaping_link_targets_are_rejected(
    target: str,
) -> None:
    """Reject link targets that are unsafe on any supported host filesystem.

    Args:
        target: Adversarial archive link target.
    """
    with pytest.raises(ValueError):
        safety.link_path(target, PurePosixPath())


def test_link_target_depth_is_bounded_after_parent_resolution() -> None:
    """Bound both raw target depth and the resulting archive-relative path."""
    too_deep = "/".join("part" for _ in range(safety.MAX_PATH_DEPTH + 1))
    with pytest.raises(ValueError, match="Unsafe|depth"):
        safety.link_path(too_deep, PurePosixPath())

    deep_origin = PurePosixPath(*("parent" for _ in range(safety.MAX_PATH_DEPTH)))
    with pytest.raises(ValueError, match="depth"):
        safety.link_path("child", deep_origin)


@pytest.mark.parametrize(
    "link", [b"../../foreign", b"/absolute", b"C:/foreign", b"folder"]
)
def test_unsafe_tar_hardlinks_are_rejected(tmp_path: Path, link: Any) -> None:
    """Verify unsafe tar hardlinks are rejected.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        link: Fixture or parametrized link input for this regression.
    """
    assert_rejected(
        tmp_path,
        "tar",
        [("folder", "dir", b"", 0o755), ("chromedriver", "hardlink", link, 0o755)],
    )


@pytest.mark.parametrize(
    ("kind", "entry_type"), [("zip", "fifo"), ("tar", "fifo"), ("tar", "device")]
)
def test_devices_and_fifos_are_rejected(
    tmp_path: Path, kind: Any, entry_type: Any
) -> None:
    """Verify devices and fifos are rejected.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        kind: Fixture or parametrized kind input for this regression.
        entry_type: Fixture or parametrized entry type input for this regression.
    """
    assert_rejected(tmp_path, kind, [("chromedriver", entry_type, b"", 0o644)])


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize(
    ("constant", "limit", "entries"),
    [
        (
            "MAX_MEMBERS",
            1,
            [("chromedriver", "file", PAYLOAD, 0o644), ("extra", "file", b"x", 0o644)],
        ),
        ("MAX_MEMBER_BYTES", 3, [("chromedriver", "file", PAYLOAD, 0o644)]),
        (
            "MAX_TOTAL_BYTES",
            len(PAYLOAD),
            [("chromedriver", "file", PAYLOAD, 0o644), ("extra", "file", b"x", 0o644)],
        ),
        ("MAX_PATH_DEPTH", 2, [("a/b/chromedriver", "file", PAYLOAD, 0o644)]),
        ("MAX_LINK_BYTES", 3, [("chromedriver", "symlink", b"long-link", 0o777)]),
    ],
)
def test_archive_limits_are_enforced_without_large_fixtures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: Any,
    constant: Any,
    limit: Any,
    entries: Any,
) -> None:
    """Verify archive limits are enforced without large fixtures.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        kind: Fixture or parametrized kind input for this regression.
        constant: Fixture or parametrized constant input for this regression.
        limit: Fixture or parametrized limit input for this regression.
        entries: Fixture or parametrized entries input for this regression.
    """
    monkeypatch.setattr(safety, constant, limit)
    assert_rejected(tmp_path, kind, entries)


@pytest.mark.parametrize("actual", [b"ab", b"abcd"])
def test_expanded_data_must_match_declared_size(tmp_path: Path, actual: Any) -> None:
    """Verify expanded data must match declared size.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        actual: Fixture or parametrized actual input for this regression.
    """
    writer = safety.ArchiveWriter(tmp_path / "extracted")
    with pytest.raises(ValueError, match="size"):
        writer.add("driver", "file", 3, 0o644, source=BytesIO(actual))


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_ambiguous_executables_are_rejected(tmp_path: Path, kind: Any) -> None:
    """Verify ambiguous executables are rejected.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        kind: Fixture or parametrized kind input for this regression.
    """
    assert_rejected(
        tmp_path,
        kind,
        [
            ("one/chromedriver", "file", PAYLOAD, 0o755),
            ("two/chromedriver", "file", PAYLOAD, 0o755),
        ],
    )


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_existing_destination_is_preserved_even_with_invalid_download(
    tmp_path: Path, kind: Any
) -> None:
    """Verify existing destination is preserved even with invalid download.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        kind: Fixture or parametrized kind input for this regression.
    """
    destination = tmp_path / "entry"
    destination.mkdir()
    sentinel = destination / "existing-driver"
    sentinel.write_bytes(PAYLOAD)
    with pytest.raises(errors.InvalidDownloadFileError, match="overwrite"):
        download(kind, [("../bad", "file", b"bad", 0o644)]).unpack(str(destination))
    assert sentinel.read_bytes() == PAYLOAD
    assert list(destination.iterdir()) == [sentinel]
    assert not list(tmp_path.glob(".aselenium-stage-*"))


@pytest.mark.skipif(
    os.name == "nt", reason="Native Windows symlink privileges are not assumed"
)
def test_symlink_destination_is_never_followed(tmp_path: Path) -> None:
    """Verify symlink destination is never followed.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    destination = tmp_path / "entry"
    destination.symlink_to(foreign, target_is_directory=True)
    with pytest.raises(errors.InvalidDownloadFileError):
        download("zip", [("chromedriver", "file", PAYLOAD, 0o755)]).unpack(
            str(destination)
        )
    assert list(foreign.iterdir()) == []
    assert destination.is_symlink()


def test_staging_is_private_and_not_published_until_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify staging is private and not published until selection.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    archive = download("zip", [("chromedriver", "file", PAYLOAD, 0o755)])
    destination = tmp_path / "entry"
    original = archive._find_target_executable

    def check(base: Any, names: Any) -> Any:
        """Observe the enclosing wait predicate once.

        Args:
            base: Fixture or parametrized base input for this regression.
            names: Fixture or parametrized names input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        staging = Path(base).parent
        assert staging.parent == tmp_path
        assert staging.name.startswith(".aselenium-stage-")
        if os.name != "nt":
            assert staging.stat().st_mode & 0o777 == 0o700
        assert not destination.exists()
        return original(base, names)

    monkeypatch.setattr(archive, "_find_target_executable", check)
    assert Path(archive.unpack(str(destination))).is_file()
    assert not list(tmp_path.glob(".aselenium-stage-*"))


@pytest.mark.skipif(
    os.name == "nt", reason="Native Windows symlink privileges are not assumed"
)
def test_extraction_helper_rejects_a_symlink_parent(tmp_path: Path) -> None:
    """Verify extraction helper rejects a symlink parent.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    link = tmp_path / "link"
    link.symlink_to(foreign, target_is_directory=True)
    with pytest.raises(ValueError):
        safety.ArchiveWriter(link / "extracted")
    assert list(foreign.iterdir()) == []


def test_cleanup_error_preserves_primary_archive_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify cleanup error preserves primary archive failure.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        caplog: Pytest fixture capturing log records emitted by the operation.
    """

    def denied(*args: Any, **kwargs: Any) -> None:
        """Denied.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        raise PermissionError("synthetic staging cleanup denial")

    monkeypatch.setattr(files, "rmtree", denied)
    archive = files.ChromeDriverFile(
        "linux", "https://offline.invalid/driver.zip", b"broken ZIP"
    )
    with pytest.raises(errors.InvalidDownloadFileError) as failure:
        archive.unpack(str(tmp_path / "entry"))
    assert "Failed to extract" in str(failure.value.__cause__)
    assert "staging retained" in caplog.text
    assert not (tmp_path / "entry").exists()
    assert len(list(tmp_path.glob(".aselenium-stage-*"))) == 1
