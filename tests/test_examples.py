"""Check README links, real API contracts, and executable recipes without browsers."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import inspect
import re
import shlex
import sys
import typing
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock
from urllib.parse import unquote, urlsplit

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import pytest

from aselenium import Chrome, Cookie, Element, Network, SessionTimeoutError

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
TEXT = README.read_text(encoding="utf-8")
with (ROOT / "pyproject.toml").open("rb") as _metadata_stream:
    VERSION = tomllib.load(_metadata_stream)["project"]["version"]
PYTHON_BLOCKS = re.findall(r"```python\s*\n(.*?)```", TEXT, flags=re.DOTALL)
BASH_BLOCKS = re.findall(r"```bash\s*\n(.*?)```", TEXT, flags=re.DOTALL)
DEMO_COMMANDS = sorted(
    {
        tuple(parts[1:])
        for block in BASH_BLOCKS
        for line in block.replace("\\\n", " ").splitlines()
        if (parts := shlex.split(line, comments=True))
        and len(parts) >= 2
        and parts[0] == ".venv/bin/python"
        and parts[1] in {"src/demo_local.py", "src/demo_google.py"}
    }
)
EXAMPLE_IDS = [
    next(
        node.name
        for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    for source in PYTHON_BLOCKS
]


def load_example(source: Any) -> Any:
    # Examples only import modules and define functions at top level. The complete
    # quick start uses a main guard, so loading it never provisions a browser.
    """Load example.

    Args:
        source: Fixture or parametrized source input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    tree = ast.parse(source)
    allowed = (
        ast.Import,
        ast.ImportFrom,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.If,
    )
    assert all(isinstance(node, allowed) for node in tree.body)
    for node in tree.body:
        if isinstance(node, ast.If):
            assert ast.unparse(node.test) == "__name__ == '__main__'"
    namespace = {"__name__": "readme_example"}
    exec(compile(tree, "README.md:example", "exec"), namespace)
    return namespace


@pytest.fixture
def examples() -> Any:
    """Examples.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    result = {}
    for source in PYTHON_BLOCKS:
        namespace = load_example(source)
        for name, value in namespace.items():
            if inspect.isfunction(value) and value.__module__ == "readme_example":
                assert name not in result, "Recipe names should be unambiguous"
                result[name] = value
    return result


@pytest.mark.parametrize("source", PYTHON_BLOCKS, ids=EXAMPLE_IDS)
def test_readme_python_fences_compile_and_import(source: Any) -> None:
    """Verify readme python fences compile and import.

    Args:
        source: Fixture or parametrized source input for this regression.
    """
    load_example(source)  # compile(), unlike ast.parse(), rejects top-level await.


def package_types(annotation: Any) -> Any:
    """Extract public package object types from return annotations and unions.

    Args:
        annotation: Fixture or parametrized annotation input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    candidates = typing.get_args(annotation) or (annotation,)
    return tuple(
        candidate
        for candidate in candidates
        if inspect.isclass(candidate) and candidate.__module__.startswith("aselenium")
    )


def returned_types(member: Any) -> Any:
    """Returned types.

    Args:
        member: Fixture or parametrized member input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    target = member.fget if isinstance(member, property) else member
    if not callable(target):
        return ()
    try:
        return package_types(typing.get_type_hints(target).get("return"))
    except (NameError, TypeError):
        return ()  # Unresolvable legacy annotations are outside this small gate.


def infer_types(node: Any, bindings: Any, namespace: Any) -> Any:
    """Infer types.

    Args:
        node: Fixture or parametrized node input for this regression.
        bindings: Fixture or parametrized bindings input for this regression.
        namespace: Fixture or parametrized namespace input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    if isinstance(node, ast.Name):
        return bindings.get(node.id, ())
    if isinstance(node, ast.Await):
        return infer_types(node.value, bindings, namespace)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            return package_types(namespace.get(node.func.id))
        if isinstance(node.func, ast.Attribute):
            return infer_types(node.func, bindings, namespace)
    if isinstance(node, ast.Attribute):
        types = infer_types(node.value, bindings, namespace)
        return tuple(
            result
            for owner in types
            for result in returned_types(inspect.getattr_static(owner, node.attr, None))
        )
    return ()


@pytest.mark.parametrize("source", PYTHON_BLOCKS, ids=EXAMPLE_IDS)
def test_readme_typed_api_members_and_call_signatures_exist(source: Any) -> None:
    """Catch renamed APIs/keywords on objects whose types can be inferred safely.

    Args:
        source: Fixture or parametrized source input for this regression.
    """
    namespace = load_example(source)
    tree = ast.parse(source)
    for function in (
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        hints = typing.get_type_hints(namespace[function.name])
        bindings = {
            name: package_types(annotation) for name, annotation in hints.items()
        }
        assignments = [
            node for node in ast.walk(function) if isinstance(node, ast.Assign)
        ]
        # A few fixed-point passes cover driver.options and lookup-result aliases.
        for _ in range(4):
            for assignment in assignments:
                for target in assignment.targets:
                    if isinstance(target, ast.Name):
                        found = infer_types(assignment.value, bindings, namespace)
                        if found:
                            bindings[target.id] = found
        for node in ast.walk(function):
            if isinstance(node, ast.Attribute):
                for owner in infer_types(node.value, bindings, namespace):
                    assert inspect.getattr_static(
                        owner, node.attr, None
                    ) is not None or node.attr in getattr(
                        owner, "__dataclass_fields__", {}
                    ), f"{function.name}: {owner.__name__}.{node.attr} does not exist"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                for owner in infer_types(node.func.value, bindings, namespace):
                    member = inspect.getattr_static(owner, node.func.attr, None)
                    if not inspect.isfunction(member):
                        continue
                    # Expanded *args/**kwargs cannot be evaluated statically.
                    if any(isinstance(arg, ast.Starred) for arg in node.args) or any(
                        keyword.arg is None for keyword in node.keywords
                    ):
                        continue
                    inspect.signature(member).bind(
                        object(),
                        *(object() for _ in node.args),
                        **{keyword.arg: object() for keyword in node.keywords},
                    )


def markdown_anchors(text: Any) -> Any:
    # Headings here use plain ASCII words; fence contents must not become anchors.
    """Markdown anchors.

    Args:
        text: Fixture or parametrized text input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    plain = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    headings = re.findall(r"^#{1,6}\s+(.+?)\s*$", plain, flags=re.MULTILINE)
    counts = Counter()
    anchors = set()
    for heading in headings:
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = counts[slug]
        anchors.add(slug if count == 0 else f"{slug}-{count}")
        counts[slug] += 1
    return anchors


def test_readme_has_guide_and_all_local_links_resolve() -> None:
    """Verify readme has guide and all local links resolve."""
    assert "## Usage guide" in TEXT
    assert "## Quick start" in TEXT
    assert len(PYTHON_BLOCKS) >= 20
    for destination in re.findall(r"\[[^\]]+\]\(([^)]+)\)", TEXT):
        parsed = urlsplit(destination)
        repository_path = None
        for kind in ("blob", "tree"):
            prefix = f"/AresJef/Aselenium/{kind}/v{VERSION}/"
            if parsed.netloc == "github.com" and parsed.path.startswith(prefix):
                repository_path = parsed.path.removeprefix(prefix)
                break
        if repository_path is not None:
            path = ROOT / unquote(repository_path)
        elif parsed.scheme or parsed.netloc:
            continue  # No network access for unrelated documentation links.
        else:
            path = ROOT / unquote(parsed.path) if parsed.path else README
        assert path.exists(), f"Broken README link: {destination}"
        if parsed.fragment:
            assert path.is_file()
            assert unquote(parsed.fragment) in markdown_anchors(
                path.read_text(encoding="utf-8")
            ), destination


@pytest.mark.parametrize(
    "command", DEMO_COMMANDS, ids=lambda command: " ".join(command)
)
def test_readme_demo_commands_match_real_cli_without_launching(
    command: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify readme demo commands match real cli without launching.

    Args:
        command: Fixture or parametrized command input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    path = ROOT / command[0]
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("readme_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    driver_factory = Mock(
        side_effect=AssertionError("README command parsing must not launch a browser")
    )
    monkeypatch.setattr(module, "make_driver", driver_factory)
    args = module.parse_args(list(command[1:]))
    assert args.command == (command[1] if len(command) > 1 else None)
    driver_factory.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_readme_options_recipe_uses_real_defensive_configuration(
    examples: Any, tmp_path: Path
) -> None:
    """Verify readme options recipe uses real defensive configuration.

    Args:
        examples: Fixture or parametrized examples input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    driver = Chrome(directory=str(tmp_path))
    try:
        examples["configure_chrome"](driver)
        assert "--headless=new" in driver.options.arguments
        assert driver.options.session_timeout == 30
        assert driver.options.timeouts.dict == {
            "implicit": 0,
            "pageLoad": 20000,
            "script": 5000,
        }
        assert driver.options.accept_insecure_certs is False
        detached = driver.options.capabilities
        detached["pageLoadStrategy"] = "none"
        assert driver.options.capabilities["pageLoadStrategy"] == "normal"
        examples["configure_browser_proxy"](driver, "http://127.0.0.1:8080")
        assert driver.options.proxy.to_capabilities()["noProxy"] == [
            "localhost",
            "127.0.0.1",
        ]
    finally:
        driver.options.close()


class FakeContext:
    """Represent FakeContext using the inherited implementation."""

    def __init__(self, session: Any) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            session: Fixture or parametrized session input for this regression.
        """
        self.session = session
        self.start = AsyncMock(return_value=session)
        self.quit = AsyncMock()

    async def __aenter__(self) -> FakeContext:
        """Start the owned asynchronous context and return its managed value.

        Returns:
            The FakeContext value produced by this operation.
        """
        return await self.start()

    async def __aexit__(self, *exc: Any) -> None:
        """Await owned cleanup when leaving the asynchronous context.

        Args:
            *exc: Fixture or parametrized exc input for this regression.
        """
        await self.quit()


@pytest.mark.asyncio
async def test_complete_quickstart_provisions_then_acquires_offline(
    examples: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify complete quickstart provisions then acquires offline.

    Args:
        examples: Fixture or parametrized examples input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    main = examples["main"]
    field = SimpleNamespace(
        send=AsyncMock(), get_property=AsyncMock(return_value="Hello from Aselenium")
    )

    async def wait_for(predicate: Any, timeout: Any) -> Any:
        """Wait for.

        Args:
            predicate: Fixture or parametrized predicate input for this regression.
            timeout: Fixture or parametrized timeout input for this regression.

        Returns:
            The first truthy predicate result, or a falsey result/None when the deadline expires.
        """
        assert timeout == 5
        return await predicate()

    class TitledSession(SimpleNamespace):
        """Represent TitledSession using the inherited implementation."""

        @property
        async def title(self) -> Any:
            """Title.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            return "Aselenium"

    session = TitledSession(
        load=AsyncMock(), find_element=AsyncMock(return_value=field), wait_for=wait_for
    )
    context = FakeContext(session)
    driver = SimpleNamespace(
        options=SimpleNamespace(
            add_arguments=Mock(), set_timeouts=Mock(), close=Mock()
        ),
        manager=SimpleNamespace(
            install_result=AsyncMock(
                return_value=SimpleNamespace(
                    driver_version="152.0.7977.82", browser_version="152.0.7977.76"
                )
            )
        ),
        acquire=Mock(return_value=context),
    )
    monkeypatch.setitem(main.__globals__, "Chrome", Mock(return_value=driver))
    monkeypatch.chdir(tmp_path)
    await main()
    driver.manager.install_result.assert_awaited_once_with(
        version="build", policy="compatible-build", validate_compatibility=True
    )
    driver.acquire.assert_called_once_with(version="offline")
    field.send.assert_awaited_once_with("Hello from Aselenium")
    assert context.quit.await_count == 1
    driver.options.close.assert_called_once()
    assert (tmp_path / "browser-cache").is_dir()


@pytest.mark.parametrize("failure", [None, "provision", "navigation"])
@pytest.mark.asyncio
async def test_google_quickstart_is_headed_homepage_only_and_owns_cleanup(
    examples: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: Any
) -> None:
    """Verify google quickstart is headed homepage only and owns cleanup.

    Args:
        examples: Fixture or parametrized examples input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.
        failure: Fixture or parametrized failure input for this regression.
    """
    main = examples["google_main"]

    class GoogleSession:
        """Represent GoogleSession using the inherited implementation."""

        load = AsyncMock(
            side_effect=RuntimeError("navigation failed")
            if failure == "navigation"
            else None
        )

        @property
        async def url(self) -> Any:
            """Url.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            return "https://www.google.com/"

        @property
        async def title(self) -> Any:
            """Title.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            return "Google"

    session = GoogleSession()
    context = FakeContext(session)
    driver = SimpleNamespace(
        options=SimpleNamespace(
            set_timeouts=Mock(), close=Mock(), add_arguments=Mock()
        ),
        manager=SimpleNamespace(
            install_result=AsyncMock(
                side_effect=RuntimeError("provision failed")
                if failure == "provision"
                else None,
                return_value=SimpleNamespace(
                    driver_version="152.0.7977.82", browser_version="152.0.7977.76"
                ),
            )
        ),
        acquire=Mock(return_value=context),
    )
    constructor = Mock(return_value=driver)
    pause = AsyncMock()
    monkeypatch.setitem(main.__globals__, "Chrome", constructor)
    monkeypatch.setitem(main.__globals__, "asyncio", SimpleNamespace(sleep=pause))
    monkeypatch.chdir(tmp_path)
    if failure:
        with pytest.raises(RuntimeError, match=failure + " failed"):
            await main()
        pause.assert_not_awaited()
    else:
        await main()
        pause.assert_awaited_once_with(5)
    constructor.assert_called_once_with(directory="browser-cache")
    assert (tmp_path / "browser-cache").is_dir()
    driver.options.add_arguments.assert_not_called()
    driver.options.set_timeouts.assert_called_once_with(
        implicit=0, pageLoad=30, script=5
    )
    assert driver.options.session_timeout == 40
    driver.options.close.assert_called_once()
    driver.manager.install_result.assert_awaited_once_with(
        version="build", policy="compatible-build", validate_compatibility=True
    )
    if failure == "provision":
        driver.acquire.assert_not_called()
        context.quit.assert_not_awaited()
        session.load.assert_not_awaited()
    else:
        driver.acquire.assert_called_once_with(version="offline")
        context.quit.assert_awaited_once()
        session.load.assert_awaited_once_with("https://www.google.com/")


@pytest.mark.asyncio
async def test_manager_recipe_preserves_offline_policy_and_creates_cache(
    examples: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify manager recipe preserves offline policy and creates cache.

    Args:
        examples: Fixture or parametrized examples input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    function = examples["provision_chrome"]
    manager = SimpleNamespace(install_result=AsyncMock(return_value=object()))
    constructor = Mock(return_value=manager)
    monkeypatch.setitem(function.__globals__, "ChromeDriverManager", constructor)
    cache = tmp_path / "new-cache"
    result = await function(str(cache), offline=True)
    assert cache.is_dir()
    assert result is manager.install_result.return_value
    constructor.assert_called_once_with(directory=str(cache))
    manager.install_result.assert_awaited_once_with(
        version="build", policy="offline", validate_compatibility=True
    )


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.asyncio
async def test_lifecycle_recipe_quits_on_success_and_failure(
    examples: Any, failure: Any
) -> None:
    """Verify lifecycle recipe quits on success and failure.

    Args:
        examples: Fixture or parametrized examples input for this regression.
        failure: Fixture or parametrized failure input for this regression.
    """

    class Session:
        """Represent Session using the inherited implementation."""

        load = AsyncMock(side_effect=RuntimeError("load failed") if failure else None)

        @property
        async def title(self) -> Any:
            """Title.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            return "Managed session"

    context = FakeContext(Session())
    driver = SimpleNamespace(acquire=Mock(return_value=context))
    if failure:
        with pytest.raises(RuntimeError, match="load failed"):
            await examples["managed_session"](driver)
    else:
        assert await examples["managed_session"](driver) == "Managed session"
    context.quit.assert_awaited_once()


@pytest.mark.asyncio
async def test_wait_recipe_handles_missing_results(examples: Any) -> None:
    """Verify wait recipe handles missing results.

    Args:
        examples: Fixture or parametrized examples input for this regression.
    """
    session = SimpleNamespace(
        set_timeouts=AsyncMock(), wait_for=AsyncMock(return_value=None)
    )
    with pytest.raises(TimeoutError, match="#name did not appear"):
        await examples["wait_for_input"](session)
    field = SimpleNamespace(wait_until=AsyncMock(return_value=True))
    session.wait_for.return_value = field
    assert await examples["wait_for_input"](session) is field


@pytest.mark.asyncio
async def test_cookie_recipe_reads_real_mapping_and_removes_its_cookie(
    examples: Any,
) -> None:
    """Verify cookie recipe reads real mapping and removes its cookie.

    Args:
        examples: Fixture or parametrized examples input for this regression.
    """
    session = SimpleNamespace(
        add_cookie=AsyncMock(),
        delete_cookie=AsyncMock(),
        get_cookie=AsyncMock(
            return_value=Cookie(name="demo-preference", value="compact")
        ),
    )
    assert await examples["round_trip_cookie"](session) == "compact"
    session.delete_cookie.assert_awaited_once_with("demo-preference")


@pytest.mark.parametrize("unsupported", [False, True])
@pytest.mark.asyncio
async def test_capture_recipe_checks_results_and_creates_output_parent(
    examples: Any, tmp_path: Path, unsupported: Any
) -> None:
    """Verify capture recipe checks results and creates output parent.

    Args:
        examples: Fixture or parametrized examples input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
        unsupported: Fixture or parametrized unsupported input for this regression.
    """
    session = SimpleNamespace(
        save_screenshot=AsyncMock(return_value=True),
        save_page=AsyncMock(return_value=not unsupported),
    )
    output = tmp_path / "captures"
    if unsupported:
        with pytest.raises(RuntimeError, match="PDF was not saved"):
            await examples["capture_page"](session, str(output), pdf=True)
    else:
        await examples["capture_page"](session, str(output), pdf=True)
    assert output.is_dir()
    session.save_screenshot.assert_awaited_once_with(str(output / "page.png"))
    session.save_page.assert_awaited_once_with(
        str(output / "page.pdf"), background=True
    )


@pytest.mark.asyncio
async def test_chromium_recipe_restores_prior_network_conditions(examples: Any) -> None:
    """Verify chromium recipe restores prior network conditions.

    Args:
        examples: Fixture or parametrized examples input for this regression.
    """
    original = Network(
        offline=False, latency=5, upload_throughput=2048, download_throughput=4096
    )

    class Session:
        """Represent Session using the inherited implementation."""

        cache_cdp_cmd = Mock(return_value=object())
        execute_cdp_cmd = AsyncMock(return_value={"product": "local-test"})
        set_network = AsyncMock()
        get_logs = AsyncMock(return_value=[])

        @asynccontextmanager
        async def transaction(self) -> AsyncIterator[Session]:
            """Model the real session transaction used by the README recipe.

            Yields:
                This simulated session while it owns the logical transaction.
            """
            yield self

        @property
        async def network(self) -> Any:
            """Network.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            return original.copy()

        @property
        async def log_types(self) -> Any:
            """Log types.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            return ["browser"]

    session = Session()
    await examples["chromium_diagnostics"](session)
    assert session.set_network.await_args_list[-1].kwargs == original.dict


@pytest.mark.asyncio
async def test_navigation_diagnostics_never_retries_an_ambiguous_timeout(
    examples: Any,
) -> None:
    """Verify navigation diagnostics never retries an ambiguous timeout.

    Args:
        examples: Fixture or parametrized examples input for this regression.
    """
    error = SessionTimeoutError("ambiguous navigation")
    session = SimpleNamespace(load=AsyncMock(side_effect=error))
    with pytest.raises(SessionTimeoutError) as raised:
        await examples["load_with_diagnostics"](session, "http://127.0.0.1/")
    assert raised.value is error
    session.load.assert_awaited_once()


@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.asyncio
async def test_concurrency_recipe_bounds_sessions_and_owns_cleanup(
    examples: Any, fail: Any
) -> None:
    """Verify concurrency recipe bounds sessions and owns cleanup.

    Args:
        examples: Fixture or parametrized examples input for this regression.
        fail: Fixture or parametrized fail input for this regression.
    """
    active = 0
    peak = 0
    closed = 0
    contexts = []

    class Session:
        """Represent Session using the inherited implementation."""

        async def load(self, url: Any) -> None:
            """Load.

            Args:
                url: Fixture or parametrized url input for this regression.
            """
            await asyncio.sleep(0)
            if fail and url.endswith("/fail"):
                raise RuntimeError("load failed")

        @property
        async def title(self) -> Any:
            """Title.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            return "Local title"

    class Context:
        """Represent Context using the inherited implementation."""

        async def __aenter__(self) -> Context:
            """Start the owned asynchronous context and return its managed value.

            Returns:
                A new Session instance constructed from the current values.
            """
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            return Session()

        async def __aexit__(self, *exc: Any) -> None:
            """Await owned cleanup when leaving the asynchronous context.

            Args:
                *exc: Fixture or parametrized exc input for this regression.
            """
            nonlocal active, closed
            active -= 1
            closed += 1

    def acquire(selector: Any) -> Any:
        """Acquire.

        Args:
            selector: Fixture or parametrized selector input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        assert selector == "offline"
        context = Context()
        contexts.append(context)
        return context

    driver = SimpleNamespace(acquire=acquire)
    before = set(asyncio.all_tasks())
    urls = ["http://127.0.0.1/fail", "http://127.0.0.1/a", "http://127.0.0.1/b"]
    if fail:
        with pytest.raises(RuntimeError, match="load failed"):
            await examples["collect_titles"](driver, urls, parallelism=2)
    else:
        assert (
            await examples["collect_titles"](driver, urls, parallelism=2)
            == ["Local title"] * 3
        )
    assert active == 0
    assert closed == len(contexts)
    assert 1 <= peak <= 2
    assert not (set(asyncio.all_tasks()) - before)


def test_documented_element_inspection_members_are_public() -> None:
    """Verify documented element inspection members are public."""
    for name in (
        "text",
        "dom_text",
        "get_property",
        "get_attribute_dom",
        "get_property_css",
        "enabled",
        "selected",
        "in_viewport",
        "unobscured",
        "aria_role",
        "aria_label",
    ):
        assert inspect.getattr_static(Element, name) is not None
