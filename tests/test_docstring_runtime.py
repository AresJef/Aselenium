"""Execute selected prompted docstrings verbatim against controlled real objects.

This is runtime acceptance, separate from the package-wide syntax-only gate.
Every target listed below runs its actual current docstring, including imports,
multiline chains, top-level await, state changes, and explicit printed output.
The browser transport supplies controlled observations; JavaScript is not run in
a browser and no external request, browser process, or real user profile is used.
"""

from __future__ import annotations

import ast
import copy
import doctest
import inspect
from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager, nullcontext, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import mkdtemp
from types import SimpleNamespace
from typing import Any

import pytest

from aselenium import errors
from aselenium import options as options_module
from aselenium._wait import poll
from aselenium.actions import Actions
from aselenium.chrome.options import ChromeOptions
from aselenium.command import Command
from aselenium.element import ELEMENT_KEY, Element
from aselenium.options import BaseOptions, ChromiumBaseOptions, Timeouts
from aselenium.session import Session
from aselenium.utils import KeyboardKeys

ACTION_TARGETS = (
    Actions.actions.fget,
    Actions.move_to,
    Actions.move_by,
    Actions.click,
    Actions.release,
    Actions.drag_and_drop,
    Actions.key_down,
    Actions.key_up,
    Actions.send_keys,
    Actions.send_key_combo,
    Session.actions,
)
OPTION_TARGETS = (
    BaseOptions.session_timeout.fget,
    BaseOptions.timeouts.fget,
    BaseOptions.set_timeouts,
    BaseOptions.add_experimental_options,
    BaseOptions.rem_experimental_option,
    BaseOptions.add_arguments,
    BaseOptions.set_preferences,
    BaseOptions.get_preference,
    BaseOptions.rem_preference,
)
SCRIPT_TARGETS = (
    Session.scripts.fget,
    Session.get_script,
    Session.cache_script,
    Session.remove_script,
    Session.rename_script,
    Session.execute_script,
    Session.execute_async_script,
)
WAIT_TARGETS = (
    Session.wait_for,
    Session.wait_until_element,
    Session.wait_until_elements,
    Session.wait_until_url,
    Element.wait_until,
    poll,
)
TIMEOUT_TARGETS = (Session.timeouts.fget, Session.set_timeouts, Session.reset_timeouts)
PROFILE_TARGETS = (BaseOptions.snapshot, ChromiumBaseOptions.rem_profile)
EXECUTED_DOCSTRINGS = (
    *ACTION_TARGETS,
    *OPTION_TARGETS,
    *SCRIPT_TARGETS,
    *WAIT_TARGETS,
    *TIMEOUT_TARGETS,
    *PROFILE_TARGETS,
)


class DocstringTransport:
    """Supply deterministic browser observations while recording actual wire payloads."""

    def __init__(self) -> None:
        """Initialize independent timeouts, URL state, and command observations."""
        self.timeouts = {"implicit": 0, "pageLoad": 300000, "script": 30000}
        self.url = "about:blank"
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def transaction(self) -> AbstractAsyncContextManager[None]:
        """Provide transaction structure for single-task documentation recipes.

        Returns:
            An asynchronous no-op context; concurrency uses real-Connection tests.
        """
        return nullcontext()

    async def execute(
        self,
        base_url: str,
        command: str,
        body: dict[str, Any] | None = None,
        keys: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Record real package serialization and return only known fixture responses.

        Args:
            base_url: Session or element endpoint selected by the package.
            command: Actual command selected by the exercised public API.
            body: Serialized WebDriver request data.
            keys: Optional route parameters, unused by these selected examples.
            timeout: Optional command budget, unused by this immediate fixture.

        Returns:
            A deterministic W3C envelope for the requested fixture observation.
        """
        self.calls.append((base_url, command, copy.deepcopy(body)))
        if command == Command.GET_TIMEOUTS:
            return {"value": self.timeouts.copy()}
        if command == Command.SET_TIMEOUTS:
            assert body is not None
            self.timeouts.update(body)
            return {"value": None}
        if command == Command.FIND_ELEMENT:
            assert body is not None and body["using"] == "css selector"
            return {"value": {ELEMENT_KEY: body["value"].removeprefix("#")}}
        if command == Command.IS_ELEMENT_ENABLED:
            return {"value": True}
        if command == Command.GET_ELEMENT_TEXT:
            return {"value": "Fixture text"}
        if command == Command.W3C_ACTIONS:
            return {"value": None}
        if command == Command.GET:
            assert body is not None
            self.url = body["url"]
            return {"value": None}
        if command == Command.GET_CURRENT_URL:
            return {"value": self.url}
        if command == Command.W3C_EXECUTE_SCRIPT:
            assert body is not None
            if body["script"] == "return document.title;":
                return {"value": "Fixture title"}
            if "querySelector" in body["script"]:
                return {"value": {ELEMENT_KEY: body["args"][0].removeprefix("#")}}
            if "getBoundingClientRect" in body["script"]:
                return {"value": True}
        if command == Command.W3C_EXECUTE_SCRIPT_ASYNC:
            assert body is not None and "callback('timeout')" in body["script"]
            return {"value": "timeout"}
        pytest.fail(f"Docstring issued an unexpected fixture command: {command}")


@pytest.fixture
def runtime_session() -> Iterator[Session]:
    """Yield a real session and options with an explicitly controlled transport.

    Yields:
        Started synthetic session, without any browser process or HTTP client.
    """
    options = ChromeOptions()
    session = Session(options, SimpleNamespace(url="http://127.0.0.1:4444"))
    session._id = "docstring-session"
    session._base_url = "http://127.0.0.1:4444/session/docstring-session"
    session._conn = DocstringTransport()
    try:
        yield session
    finally:
        options.close()


async def execute_prompted_docstring(
    target: Callable[..., Any],
    namespace: dict[str, Any],
    retain_results: bool = True,
) -> list[Any]:
    """Execute the current documented statements with native top-level await support.

    Args:
        target: Method, function, or property getter whose actual docstring is read.
        namespace: Explicit fixture bindings shared by every statement in the example.
        retain_results: Whether to retain expression values; disabling this avoids
            extending the lifetime of temporary profile objects created by examples.

    Returns:
        Expression results in prompt order, with None for statement blocks. Explicit
        expected output is checked; omitted interactive repr output is not invented.
    """
    doc = inspect.getdoc(target) or ""
    examples = doctest.DocTestParser().get_examples(doc)
    assert examples, f"No executable prompts found for {target.__qualname__}"
    assert "Example:" in doc and "Examples:" not in doc
    results = []
    for index, example in enumerate(examples):
        label = f"{target.__module__}.{target.__qualname__}:prompt-{index + 1}"
        tree = ast.parse(example.source, filename=label)
        expression = len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr)
        code = compile(
            ast.Expression(tree.body[0].value) if expression else example.source,
            label,
            "eval" if expression else "exec",
            flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
        )
        output = StringIO()
        with redirect_stdout(output):
            value = eval(code, namespace)
            if inspect.isawaitable(value):
                value = await value
        if example.want:
            actual = output.getvalue()
            if expression and value is not None:
                actual += repr(value) + "\n"
            assert doctest.OutputChecker().check_output(example.want, actual, 0), label
        results.append(value if retain_results else None)
    return results


def test_runtime_docstring_manifest_is_explicit_and_unique() -> None:
    """Keep the runtime-tested example inventory separate from compile-only coverage."""
    names = [target.__qualname__ for target in EXECUTED_DOCSTRINGS]
    assert len(names) == len(set(names)) == 38
    assert not {"Proxy.__init__", "Timeouts.__init__", "Version.__init__"} & set(names)


@pytest.mark.parametrize(
    "target", ACTION_TARGETS, ids=lambda target: target.__qualname__
)
@pytest.mark.asyncio
async def test_action_docstrings_execute_real_chains(
    runtime_session: Session, target: Callable[..., Any]
) -> None:
    """Run documented chains verbatim and independently inspect the emitted W3C actions.

    Args:
        runtime_session: Real session using a recording deterministic transport.
        target: Actual action-related docstring selected by its qualified name.
    """
    namespace = {"session": runtime_session}
    await execute_prompted_docstring(target, namespace)
    bodies = [
        body
        for _, command, body in runtime_session._conn.calls
        if command == Command.W3C_ACTIONS
    ]
    name = target.__qualname__
    expected_count = {
        "Actions.actions": 0,
        "Actions.move_to": 2,
        "Actions.click": 3,
    }.get(name, 1)
    assert len(bodies) == expected_count
    if name == "Actions.actions":
        payload = namespace["payload"]
        assert set(payload) == {"pointer", "key", "wheel"}
        assert [action["type"] for action in payload["pointer"]["actions"]] == [
            "pointerDown",
            "pointerUp",
        ]
        bodies = [{"actions": [device for device in payload.values() if device]}]
    for body in bodies:
        assert body is not None and body["actions"]
        assert all(
            device["id"] in {"mouse", "key", "wheel"} for device in body["actions"]
        )
        lengths = {len(device["actions"]) for device in body["actions"]}
        assert len(lengths) == 1
    if name in {"Actions.send_keys", "Actions.send_key_combo", "Session.actions"}:
        key_actions = next(
            device["actions"]
            for device in bodies[0]["actions"]
            if device["type"] == "key"
        )
        typed = "".join(
            action["value"] for action in key_actions if action["type"] == "keyDown"
        )
        prefix = "Hello World!" if name == "Session.actions" else "Hello world!"
        assert typed.startswith(prefix)
        if name.endswith("send_key_combo"):
            assert (
                typed[len(prefix) :]
                == KeyboardKeys.CONTROL
                + "a"
                + KeyboardKeys.CONTROL
                + "x"
                + KeyboardKeys.CONTROL
                + "v"
            )
        else:
            assert typed == prefix + KeyboardKeys.ENTER
    elif name in {"Actions.key_down", "Actions.key_up"}:
        key_actions = next(
            device["actions"]
            for device in bodies[0]["actions"]
            if device["type"] == "key"
        )
        assert [(action["type"], action["value"]) for action in key_actions] == [
            ("keyDown", KeyboardKeys.CONTROL),
            ("keyDown", "a"),
            ("keyUp", "a"),
            ("keyUp", KeyboardKeys.CONTROL),
        ]
    elif name == "Actions.drag_and_drop":
        pointer = next(
            device["actions"]
            for device in bodies[0]["actions"]
            if device["type"] == "pointer"
        )
        assert [
            action["origin"] for action in pointer if action["type"] == "pointerMove"
        ] == [{ELEMENT_KEY: "left_element"}, {ELEMENT_KEY: "right_element"}]
        assert [
            action["type"] for action in pointer if action["type"] != "pointerMove"
        ] == ["pointerDown", "pointerUp"]
    elif name == "Actions.move_by":
        pointer = bodies[0]["actions"][0]["actions"][0]
        assert pointer["origin"] == "pointer" and (pointer["x"], pointer["y"]) == (
            100,
            100,
        )


@pytest.mark.parametrize(
    "target", OPTION_TARGETS, ids=lambda target: target.__qualname__
)
@pytest.mark.asyncio
async def test_option_docstrings_execute_real_configuration(
    runtime_session: Session, target: Callable[..., Any]
) -> None:
    """Execute option examples and inspect their real configuration effects.

    Args:
        runtime_session: Session providing a fresh real ChromeOptions instance.
        target: Actual option docstring selected by its qualified name.
    """
    options = runtime_session.options
    options.add_experimental_options(excludeSwitches=["fixture"])
    options.set_preferences(**{"media.navigator.permission.disabled": True})
    namespace = {"options": options, "driver": SimpleNamespace(options=options)}
    results = await execute_prompted_docstring(target, namespace)
    name = target.__name__
    if name == "session_timeout":
        assert options.session_timeout == 30
        assert options.timeouts.dict == {
            "implicit": 0,
            "pageLoad": 20000,
            "script": 5000,
        }
    elif name == "timeouts":
        assert isinstance(namespace["timeouts"], Timeouts)
        assert namespace["timeouts"].dict == options.timeouts.dict
    elif name == "set_timeouts":
        assert options.timeouts.dict == {
            "implicit": 100,
            "pageLoad": 30000,
            "script": 3000,
        }
    elif name == "add_experimental_options":
        assert options.experimental_options["excludeSwitches"] == ["enable-automation"]
        assert options.experimental_options["useAutomationExtension"] is False
    elif name == "rem_experimental_option":
        assert "excludeSwitches" not in options.experimental_options
    elif name == "add_arguments":
        assert (
            "--headless=new" in options.arguments
            and "--disable-gpu" in options.arguments
        )
    elif name == "set_preferences":
        assert (
            options.get_preference("download.default_directory")
            == "/path/to/download/directory"
        )
        assert options.get_preference("download.prompt_for_download") is False
    elif name == "get_preference":
        assert results[-1] is True
    elif name == "rem_preference":
        with pytest.raises(errors.OptionsNotSetError):
            options.get_preference("media.navigator.permission.disabled")
    assert not runtime_session._conn.calls


@pytest.mark.parametrize(
    "target", SCRIPT_TARGETS, ids=lambda target: target.__qualname__
)
@pytest.mark.asyncio
async def test_script_cache_docstrings_execute_in_one_namespace(
    runtime_session: Session, target: Callable[..., Any]
) -> None:
    """Run every script example section in sequence, retaining real cache state.

    Args:
        runtime_session: Real session whose JavaScript cache and serialization are tested.
        target: Actual cache or script-execution docstring.
    """
    original = runtime_session.cache_script("myscript", "return document.title;")
    namespace = {"session": runtime_session}
    results = await execute_prompted_docstring(target, namespace)
    name = target.__name__
    if name == "scripts":
        assert namespace["scripts"] == [original]
    elif name == "get_script":
        assert namespace["js"] is original
    elif name == "cache_script":
        assert (
            runtime_session.get_script("get_title").script == "return document.title;"
        )
        assert namespace["js"].args == [100]
        assert namespace["js"].name == "scroll_y"
    elif name == "remove_script":
        assert results[-1] is True and runtime_session.get_script("myscript") is None
    elif name == "rename_script":
        assert runtime_session.get_script("script1") is None
        assert namespace["js"].name == "script2"
        assert runtime_session.get_script("script2") is namespace["js"]
    elif name == "execute_script":
        assert namespace["title"] == "Fixture title"
        assert len(runtime_session._conn.calls) == 3
        for _, command, body in runtime_session._conn.calls:
            assert command == Command.W3C_EXECUTE_SCRIPT
            assert body == {"script": "return document.title;", "args": []}
    elif name == "execute_async_script":
        assert results[-1] == "timeout"
        assert len(runtime_session._conn.calls) == 3
        for _, command, body in runtime_session._conn.calls:
            assert command == Command.W3C_EXECUTE_SCRIPT_ASYNC
            assert body["args"] == [] and "callback('timeout')" in body["script"]


@pytest.mark.parametrize("target", WAIT_TARGETS, ids=lambda target: target.__qualname__)
@pytest.mark.asyncio
async def test_wait_docstrings_execute_real_predicates(
    runtime_session: Session, target: Callable[..., Any]
) -> None:
    """Execute documented wait callbacks and observe their actual returned values.

    Args:
        runtime_session: Real session whose controlled browser observations are ready.
        target: Actual direct, descendant, URL, or generic wait example.
    """
    namespace = {
        "session": runtime_session,
        "element": Element("fixture", runtime_session),
        "poll": poll,
    }
    results = await execute_prompted_docstring(target, namespace)
    if target is Session.wait_for:
        assert (
            isinstance(namespace["field"], Element) and namespace["field"].id == "name"
        )
        assert runtime_session._conn.timeouts["implicit"] == 0
        assert any(
            command == Command.IS_ELEMENT_ENABLED
            for _, command, _ in runtime_session._conn.calls
        )
    elif target is poll:
        assert namespace["value"] == "Fixture text"
    else:
        assert results[-1] is True
    assert runtime_session._conn.calls


@pytest.mark.parametrize(
    "target", TIMEOUT_TARGETS, ids=lambda target: target.__qualname__
)
@pytest.mark.asyncio
async def test_timeout_docstrings_distinguish_session_and_option_access(
    runtime_session: Session, target: Callable[..., Any]
) -> None:
    """Run asynchronous session-timeout examples without awaiting synchronous options.

    Args:
        runtime_session: Real session with a stateful timeout transport boundary.
        target: Actual session-timeout getter, setter, or reset example.
    """
    namespace = {"session": runtime_session, "options": runtime_session.options}
    await execute_prompted_docstring(target, namespace)
    assert isinstance(namespace["timeouts"], Timeouts)
    expected = (
        {"implicit": 100, "pageLoad": 30000, "script": 3000}
        if target is Session.set_timeouts
        else runtime_session.options.timeouts.dict
    )
    assert namespace["timeouts"].dict == expected


@pytest.mark.parametrize(
    "target", PROFILE_TARGETS, ids=lambda target: target.__qualname__
)
@pytest.mark.asyncio
async def test_profile_docstrings_use_disposable_real_clones(
    runtime_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: Callable[..., Any],
) -> None:
    """Run profile/snapshot recipes with real temporary cloning and cleanup.

    Args:
        runtime_session: Real session exposing the configured ChromeOptions object.
        tmp_path: Isolated directory containing a synthetic source profile.
        monkeypatch: Fixture restoring the temporary-directory allocation boundary.
        target: Actual snapshot or profile-removal example.
    """
    source = tmp_path / "source"
    (source / "Default").mkdir(parents=True)
    (source / "Default" / "Preferences").write_text(
        '{"fixture":true}', encoding="utf-8"
    )
    allocated: list[Path] = []

    def allocate(*, prefix: str) -> str:
        """Allocate real owned profile directories inside the disposable test root.

        Args:
            prefix: Package-supplied temporary directory prefix.

        Returns:
            Newly created directory recorded for independent cleanup verification.
        """
        value = mkdtemp(prefix=prefix, dir=tmp_path)
        allocated.append(Path(value))
        return value

    monkeypatch.setattr(options_module, "mkdtemp", allocate)
    options = runtime_session.options
    namespace = {
        "options": options,
        "driver": SimpleNamespace(options=options),
        "directory": str(source),
        "profile": "Default",
    }
    if target is BaseOptions.snapshot:
        options.set_profile(str(source), "Default")
        original = options.profile
        original_timeouts = options.timeouts.dict
        await execute_prompted_docstring(target, namespace, retain_results=False)
        assert namespace["snapshot"] is not options
        assert namespace["snapshot"].profile is None
        assert (
            options.profile is original and options.timeouts.dict == original_timeouts
        )
        assert (
            len(allocated) == 2 and allocated[0].exists() and not allocated[1].exists()
        )
    else:
        await execute_prompted_docstring(target, namespace, retain_results=False)
        assert options.profile is None
        assert not any(arg.startswith("--user-data-dir=") for arg in options.arguments)
        assert len(allocated) == 1 and not allocated[0].exists()
    options.close()
    assert all(not path.exists() for path in allocated)
    assert (source / "Default" / "Preferences").read_text(
        encoding="utf-8"
    ) == '{"fixture":true}'
