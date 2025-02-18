from typing import Literal
import asyncio, platform, os
from time import perf_counter
from aselenium import Chrome, Firefox, Chromium, Edge, Safari
from aselenium import IncompatibleWebdriverError, Proxy, Session
from aselenium import ChromeSession, FirefoxSession, SafariSession
from aselenium import KeyboardKeys

T = Literal["chrome", "chromium", "edge", "firefox", "safari"]
SYSTEM = platform.system()
cancell_switch = False


async def test_driver_manager(browser: T) -> None:
    async def manager_test(driver_cls: type[Edge], **kwargs) -> None:
        print("-" * 80)
        driver = driver_cls()
        print(f"{driver.__class__.__name__} Driver Manager Test: {kwargs}")
        print("- " * 40)
        t1 = perf_counter()
        async with driver.acquire(**kwargs) as session:
            t2 = perf_counter()
            print(session.driver_version, session.driver_location)
            print(session.browser_version, session.browser_location)
            await session.load("https://www.baidu.com")
        print("- " * 40)
        print("Driver Manager Test Success:", t2 - t1)
        print("-" * 80)
        print()

    # Chrome Test
    if browser == "chrome":
        await manager_test(Chrome, version="build", channel="stable")
        await manager_test(Chrome, version="build", channel="beta")
        await manager_test(Chrome, version="build", channel="dev")
        await manager_test(Chrome, version="patch", channel="dev")
        try:
            await manager_test(Chrome, version="110", channel="stable")
        except IncompatibleWebdriverError:
            print("-" * 80)
            print("Chrome IncompatibleWebdriver Test Success")
            print("-" * 80)
            print()
        await manager_test(Chrome, version="114", channel="cft")
        await manager_test(Chrome, version="115.0.5763", channel="cft")
        await manager_test(Chrome, version="113.0.5672", channel="cft")
        await manager_test(Chrome, version="119.0.6045", channel="cft")

    # Chromium Test
    if browser == "chromium":
        if SYSTEM == "Linux":
            return None
        await manager_test(Chromium, version="build")
        await manager_test(Chromium, version="major")
        await manager_test(Chromium, version="patch")
        try:
            await manager_test(Chromium, version="110")
        except IncompatibleWebdriverError:
            print("-" * 80)
            print("Chromium IncompatibleWebdriver Test Success")
            print("-" * 80)
            print()

    # Edge Test
    if browser == "edge":
        await manager_test(Edge, version="build", channel="stable")
        await manager_test(Edge, version="build", channel="beta")
        await manager_test(Edge, version="build", channel="dev")
        await manager_test(Edge, version="patch", channel="dev")
        try:
            await manager_test(Edge, version="110", channel="stable")
        except IncompatibleWebdriverError:
            print("-" * 80)
            print("Edge IncompatibleWebdriver Test Success")
            print("-" * 80)
            print()

    # Firefox Test
    if browser == "firefox":
        await manager_test(Firefox, version="auto")
        await manager_test(Firefox, version="latest")
        driver = Firefox()
        for version in list(driver.manager._GECKODRIVER_TABLE.keys())[:-1]:
            await manager_test(Firefox, version=version)
        await manager_test(Firefox, version="0.30")
        await manager_test(Firefox, version="0")

    # Safari Test
    if browser == "safari" and SYSTEM == "Darwin":
        await manager_test(Safari, channel="stable")
        await manager_test(Safari, channel="dev")


async def test_driver_options(browser: T) -> None:
    async def options_test(driver_cls: type[Edge], **kwargs) -> None:
        print("-" * 80)
        driver = driver_cls()
        print(f"{driver.__class__.__name__} Options Test: {kwargs}")
        print("- " * 40)
        # . accept Insecure Certs
        driver.options.accept_insecure_certs = True
        # . page Load Strategy
        driver.options.page_load_strategy = "eager"
        # . proxy
        proxy = Proxy(
            http_proxy=f"http://{PROXY_SERVER}",
            https_proxy=f"http://{PROXY_SERVER}",
            socks_proxy=f"socks5://{PROXY_SERVER}",
        )
        if SYSTEM == "Darwin":
            driver.options.proxy = proxy
        # . timeout
        driver.options.set_timeouts(implicit=5, pageLoad=10)
        # . strict file interactability
        driver.options.strict_file_interactability = True
        # . prompt behavior
        driver.options.unhandled_prompt_behavior = "dismiss"
        # . arguments
        driver.options.add_arguments("--disable-gpu", "--disable-dev-shm-usage")
        # . experimental options
        if browser != "firefox":
            driver.options.add_experimental_options(
                excludeSwitches=["enable-automation", "enable-logging"]
            )
        # Final options
        print()
        print(driver.options)
        print()

        # Test driver
        async with driver.acquire(**kwargs) as session:
            await session.load("https://www.baidu.com")
            await session.load("https://whatismyipaddress.com/", retry=10)

        # Finished
        print("- " * 40)
        print(f"Options Test Success: {kwargs}")
        print("-" * 80)
        print()

    # Chrome Test
    if browser == "chrome":
        await options_test(Chrome, version="build", channel="stable")
        await options_test(Chrome, version="build", channel="beta")
        await options_test(Chrome, version="build", channel="dev")
        await options_test(Chrome, version="115", channel="cft")
    # Chromium Test
    if browser == "chromium":
        if SYSTEM == "Linux":
            return None
        await options_test(Chromium, version="build")
        await options_test(Chromium, version="major")
        await options_test(Chromium, version="patch")
    # Edge Test
    if browser == "edge":
        await options_test(Edge, version="build", channel="stable")
        await options_test(Edge, version="build", channel="beta")
        await options_test(Edge, version="build", channel="dev")
    # Firefox Test
    if browser == "firefox":
        await options_test(Firefox, version="auto")
        await options_test(Firefox, version="latest")
    # Safari Test
    if browser == "safari" and SYSTEM == "Darwin":
        await options_test(Safari, channel="stable")
        await options_test(Safari, channel="dev")


async def test_driver_profile(browser: T) -> None:
    def get_profile_dir(browser: T) -> str | None:
        if SYSTEM == "Darwin":
            if browser == "chrome":
                return "~/Library/Application Support/Google/Chrome"
            elif browser == "chromium":
                return "~/Library/Application Support/Chromium"
            elif browser == "edge":
                return "~/Library/Application Support/Microsoft Edge"
            elif browser == "firefox":
                return "~/Library/Application Support/Firefox/Profiles/684o1n0x.default-release-1700386926530"
        elif SYSTEM == "Windows":
            if browser == "chrome":
                return r"C:\Users\jef\AppData\Local\Google\Chrome\User Data"
            elif browser == "chromium":
                return r"C:\Users\jef\AppData\Local\Chromium\User Data"
            elif browser == "edge":
                return r"C:\Users\jef\AppData\Local\Microsoft\Edge Beta\User Data"
            elif browser == "firefox":
                return r"C:\Users\jef\AppData\Roaming\Mozilla\Firefox\Profiles\bestyaik.default-release"
        elif SYSTEM == "Linux":
            if browser == "chrome":
                return "~/.config/google-chrome"
            elif browser == "chromium":
                return None
            elif browser == "edge":
                return "~/.config/microsoft-edge"
            elif browser == "firefox":
                return "~/.mozilla/firefox/a9epssnc.default-release"
        return None

    profile_dir = get_profile_dir(browser)
    if profile_dir is None or not os.path.isdir(profile_dir):
        return None

    elif browser == "firefox":
        driver = Firefox()
        driver.options.set_profile(profile_dir)

    else:
        if browser == "chrome":
            driver = Chrome()
        elif browser == "chromium":
            driver = Chromium()
        else:
            driver = Edge()
        driver.options.set_profile(profile_dir, "Default")
        driver.options.add_experimental_options(
            excludeSwitches=["enable-automation", "enable-logging"]
        )

    print("-" * 80)
    print(f"{driver.__class__.__name__} Profile Test")
    print("- " * 40)
    async with driver.acquire() as session:
        print(driver.options.profile)
        await session.load("https://www.baidu.com")
        await session.load("https://whatismyipaddress.com/", retry=10)
        await asyncio.sleep(5)
    print("- " * 40)
    print("Profile Test Success")
    print("-" * 80)
    print()


async def test_driver_cancellation(browser: T) -> None:
    async def test_cancellation(driver_cls: type[Edge], **kwargs) -> None:
        global cancell_switch

        async def acquire_session(driver, **kwargs) -> None:
            global cancell_switch

            async with driver.acquire(**kwargs) as session:
                cancell_switch = True
                while True:
                    await session.load("https://whatismyipaddress.com/", retry=10)

        print("-" * 80)
        driver = driver_cls()
        print(f"{driver.__class__.__name__} Cancellation Test: {kwargs}")
        t1 = perf_counter()
        cancell_switch = False
        task = asyncio.create_task(acquire_session(driver, **kwargs))
        while not cancell_switch:
            await asyncio.sleep(0.5)
        await asyncio.sleep(2)
        task.cancel()
        cancell_switch = False
        try:
            await task
        except asyncio.CancelledError:
            t2 = perf_counter()
            print(f"{driver.__class__.__name__} Cancelled Successfully: {t2 - t1}")
        print("-" * 80)
        print()

    # Chrome Test
    if browser == "chrome":
        await test_cancellation(Chrome, version="build", channel="stable")
        await test_cancellation(Chrome, version="build", channel="beta")
        await test_cancellation(Chrome, version="build", channel="dev")
        await test_cancellation(Chrome, version="115", channel="cft")

    # Chromium Test
    if browser == "chromium":
        if SYSTEM == "Linux":
            return None
        await test_cancellation(Chromium, version="build")
        await test_cancellation(Chromium, version="major")
        await test_cancellation(Chromium, version="patch")

    # Edge Test
    if browser == "edge":
        await test_cancellation(Edge, version="build", channel="stable")
        await test_cancellation(Edge, version="build", channel="beta")
        await test_cancellation(Edge, version="build", channel="dev")

    # Firefox Test
    if browser == "firefox":
        await test_cancellation(Firefox, version="auto")
        await test_cancellation(Firefox, version="latest")

    # Safari Test
    if browser == "safari" and SYSTEM == "Darwin":
        await test_cancellation(Safari, channel="stable")
        await test_cancellation(Safari, channel="dev")


async def test_driver_automation(browser: T) -> None:
    async def session_info(s: Session) -> None:
        print(" Session Info ".center(80, "-"))

        print("Session", s, sep="\t")
        print("Service port", s.service.port, sep="\t")
        print("Session url", s.base_url, sep="\t")
        print("Timeouts", await s.timeouts, sep="\t")
        print("Load 'www.baidu.com'")
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)

        print("-" * 80)
        print()

    async def navigate(s: Session) -> None:
        print(" Navigate Commands ".center(80, "-"))
        print("Load 'www.baidu.com'")
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)

        print("Load 'www.taobao.com'")
        await s.load("https://www.taobao.com", timeout=FORCE_TIMEOUT, retry=10)
        print("Verify url", (await s.url) == "https://www.taobao.com/", sep="\t")

        print("Backward")
        await s.backward(timeout=FORCE_TIMEOUT)
        print("Verify url", (await s.url) == "https://www.baidu.com/", sep="\t")

        print("Forward")
        await s.forward(timeout=FORCE_TIMEOUT)
        print("Verify url", (await s.url) == "https://www.taobao.com/", sep="\t")

        print("Backward")
        await s.backward(timeout=FORCE_TIMEOUT)
        print("Verify url", (await s.url) == "https://www.baidu.com/", sep="\t")

        print("Refresh")
        await s.refresh(timeout=FORCE_TIMEOUT, retry=10)
        print("Verify url", (await s.url) == "https://www.baidu.com/", sep="\t")

        print("-" * 80)
        print()

    async def information(s: Session) -> None:
        print(" Information Commands ".center(80, "-"))
        print("Load 'www.baidu.com'")
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)

        url = await s.url
        print("url:\t\t\t", url == "https://www.baidu.com/", url, sep="\t")
        res = await s.wait_until_url("equals", "https://www.baidu.com/", 1)
        print("wait_until_url (equals):", res is True, res, sep="\t")
        res = await s.wait_until_url("contains", "baidu", 1)
        print("wait_until_url (contains):", res is True, res, sep="\t")
        res = await s.wait_until_url("startswith", "xxx", 1)
        print("wait_until_url (startswith):", res is False, res, sep="\t")
        res = await s.wait_until_url("endswith", "xxx", 1)
        print("wait_until_url (endswith):", res is False, res, sep="\t")
        print()

        title = await s.title
        print("title:\t\t\t", title == "百度一下，你就知道", title, sep="\t")
        res = await s.wait_until_title("equals", "xxx", 1)
        print("wait_until_title (equals):", res is False, res, sep="\t")
        res = await s.wait_until_title("contains", "xxx", 1)
        print("wait_until_title (contains):", res is False, res, sep="\t")
        res = await s.wait_until_title("startswith", "百度一下", 1)
        print("wait_until_title (startswith):", res is True, res, sep="\t")
        res = await s.wait_until_title("endswith", "你就知道", 1)
        print("wait_until_title (endswith):", res is True, res, sep="\t")
        print()

        viewport = await s.viewport
        print("viewport:", viewport is not None, viewport, sep="\t")
        page_width = await s.page_width
        print("page_width:", isinstance(page_width, int), page_width, sep="\t")
        page_height = await s.page_height
        print("page_height:", isinstance(page_height, int), page_height, sep="\t")
        page_source = await s.page_source
        print("page_source:", bool(page_source), page_source[:50] + "...", sep="\t")
        screenshot = await s.take_screenshot()
        print("screenshot:", bool(screenshot), screenshot[:30], sep="\t")
        path = os.path.join(TEST_FOLDER, "screenshot")
        print("save_screenshot:", await s.save_screenshot(path), sep="\t")

        pdf = await s.print_page()
        if pdf is not None:
            print("print_page:", bool(pdf), pdf[:30], sep="\t")
            path = os.path.join(TEST_FOLDER, "save_pdf")
            print("save_page:", await s.save_page(path), sep="\t")

        if isinstance(s, FirefoxSession):
            sch_bar = await s.find_element("#kw", by="css")
            await sch_bar.send("Hello world!", pause=0.5)
            sch_btn = await s.find_element("#su", by="css")
            await sch_btn.click()
            await s.wait_until_title("startswith", "Hello", 10)

            full_st = await s.take_full_screenshot()
            print("take_full_screenshot:", bool(full_st), full_st[:30], sep="\t")
            path = os.path.join(TEST_FOLDER, "full_screenshot")
            print("save_full_screenshot:", await s.save_full_screenshot(path), sep="\t")

        print("-" * 80)
        print()

    async def timeouts(s: Session) -> None:
        print(" Timeout Commands ".center(80, "-"))
        print("Load 'www.baidu.com'")
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)

        # fmt: off
        init_timeouts = await s.timeouts
        print("timeouts:", init_timeouts, sep="\t")

        implicit, pageLoad, script = 0, 300, 30
        timeouts = await s.set_timeouts(implicit=implicit, pageLoad=pageLoad, script=script)
        print("set_timeouts:", 
              (implicit, pageLoad, script) == (timeouts.implicit, timeouts.pageLoad, timeouts.script), 
              timeouts, sep="\t")
        
        implicit, pageLoad, script = 0.1, 200.1, 20.1
        timeouts = await s.set_timeouts(implicit=implicit, pageLoad=pageLoad, script=script)
        print("set_timeouts:", 
              (implicit, pageLoad, script) == (timeouts.implicit, timeouts.pageLoad, timeouts.script), 
              timeouts, sep="\t")

        rest_timeouts = await s.reset_timeouts()
        print("reset_timeouts:", 
              (init_timeouts.implicit, init_timeouts.pageLoad, init_timeouts.script) == 
              (rest_timeouts.implicit, rest_timeouts.pageLoad, rest_timeouts.script),
              rest_timeouts, sep="\t")
        # fmt: on

        print("-" * 80)
        print()

    async def cookies(s: Session) -> None:
        print(" Cookies Commands ".center(80, "-"))
        print("Load 'www.baidu.com'")
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)
        # fmt: off

        cookies = await s.cookies
        print("cookies:", *cookies, sep="\n")
        await s.delete_cookies()
        print("delete_cookies:", not bool(x := await s.cookies), x, sep="\t")
        print()

        for cookie in cookies:
            print("add_cookie:", await s.add_cookie(cookie), sep="\t")
        print("cookies:", bool(x := await s.cookies), sep="\t")
        print()

        cookie = await s.get_cookie("BAIDUID")
        print("get_cookie:", cookie.name == "BAIDUID", cookie, sep="\t")
        cookie.name = "test"
        await s.add_cookie(cookie)
        cookie = await s.get_cookie("test")
        print("new_cookie:", cookie.name == "test", cookie, sep="\t")
        await s.delete_cookie("test")
        cookie = await s.get_cookie("test")
        print("delete_cookie:", cookie is None, 
              not bool([i for i in await s.cookies if i.name == "test"]), sep="\t")
        print()

        # fmt: on
        print("-" * 80)
        print()

    async def window(s: Session) -> None:
        print(" Window Commands ".center(80, "-"))
        print("Load 'www.baidu.com'")
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)

        window = await s.new_window("new")
        print("new_window:", window.name == "new", window, sep="\t")
        windows = await s.windows
        print("windows:", len(windows) == 2, sep="\t")
        print(*windows, sep="\n")
        print()

        window = await s.switch_window("default")
        print("switch_window:", window.name == "default", window, sep="\t")
        window = await s.switch_window("new")
        print("switch_window:", window.name == "new", window, sep="\t")
        window = await s.rename_window("new", "new2")
        print("rename_window:", window.name == "new2", window, sep="\t")
        windows = await s.windows
        print("windows:", len(windows) == 2, sep="\t")
        print(*windows, sep="\n")
        print()

        await s.close_window()
        print("close_window:", len(await s.windows) == 1, sep="\t")
        windows = await s.windows
        print("windows:", len(windows) == 1, sep="\t")
        print(*windows, sep="\n")
        print()

        print("window_rect:", await s.window_rect, sep="\t")
        print("maximize:", await s.maximize_window(), sep="\t")
        print("minimize:", (await s.minimize_window()) is None, sep="\t")
        print("fullscreen", (await s.fullscreen_window()) is None, sep="\t")
        print("set_win_rect", await s.set_window_rect(1200, 900, 0, 0), sep="\t")
        print()

        window = await s.new_window("new1")
        print("new_window:", window.name == "new1", window, sep="\t")
        window = await s.new_window("new2")
        print("new_window:", window.name == "new2", window, sep="\t")
        await s.close_window("new1")
        windows = await s.windows
        print("close_window:", "default" in windows and "new1" in windows, sep="\t")
        await s.close_window()
        windows = await s.windows
        print("close_window:", "default" in windows, sep="\t")
        await s.close_window()
        await s.close_window()
        print("closed_all:", len(await s.windows) == 0, sep="\t")
        window = await s.new_window("new")
        print("new_window:", window.name == "new", window, sep="\t")
        windows = await s.windows
        print("windows:", len(windows) == 1, sep="\t")
        print(*windows, sep="\n")

        print("-" * 80)
        print()

    async def scroll(s: Session) -> None:
        print(" Scroll Commands ".center(80, "-"))
        print("Load 'www.baidu.com'")
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)

        rect = await s.window_rect
        await s.set_window_rect(800, 900, 0, 0)

        print("scroll_to:", await s.scroll_to(1000, 0) is None, sep="\t")
        print("scroll_left:", await s.scroll_to_left(60, by="pixels") is None, sep="\t")
        print("scroll_right:", await s.scroll_to_right(6) is None, sep="\t")
        print()

        el1 = await s.find_element("#kw", by="css")  # search input box
        await el1.send("Hello world!", pause=0.5)
        el2 = await s.find_element("#su", by="css")  # search button
        await el2.click()
        await asyncio.sleep(2)
        print("scroll_by:", await s.scroll_by(0, 300, 0.5) is None, sep="\t")
        print("scroll_to:", await s.scroll_to(0, 3000, 0.5) is None, sep="\t")
        print("scroll_top:", await s.scroll_to_top(500, "pixels") is None, sep="\t")
        print("scroll_bot:", await s.scroll_to_bottom(5, "steps") is None, sep="\t")
        print()

        print("into_view:", await s.scroll_into_view(el1), sep="\t")
        print("into_view:", await s.scroll_into_view("#tsn_inner", "css"), sep="\t")
        await s.set_window_rect(
            width=rect.width, height=rect.height, x=rect.x, y=rect.y
        )
        # fmt: on
        print("-" * 80)
        print()

    async def alert(s: Session) -> None:
        # Skip Safari
        if browser == "safari":
            return None

        print(" Alert Commands ".center(80, "-"))
        print("Load 'demo.guru99.com/")
        url = "https://demo.guru99.com/test/delete_customer.php"
        await s.load(url, timeout=FORCE_TIMEOUT, retry=10)
        PAUSE = 3

        print("nill alert:", await s.get_alert(1) is None, sep="\t")
        el1 = await s.find_element("input[name='cusid']")
        await el1.send("123456")
        el2 = await s.find_element("input[name='submit']")
        await el2.click(PAUSE)

        alert = await s.get_alert()
        print("with alert:", alert is not None, alert, sep="\t")
        text = await alert.text
        print("alert text:", text.startswith("Do you"), text, sep="\t")
        print("dismiss alert:", await alert.dismiss(PAUSE) is None, sep="\t")
        print()

        await el2.click(PAUSE)
        alert = await s.get_alert()
        print("with alert:", alert is not None, alert, sep="\t")
        text = await alert.text
        print("alert text:", text.startswith("Do you"), text, sep="\t")
        print("accept alert:", await alert.accept(PAUSE) is None, sep="\t")
        print()

        alert = await s.get_alert()
        print("next alert:", alert is not None, alert, sep="\t")
        text = await alert.text
        print("alert text:", text.startswith("Customer"), text, sep="\t")
        print("accept alert:", await alert.accept(PAUSE) is None, sep="\t")

        print("-" * 80)
        print()

    async def frame(s: Session) -> None:
        # Skip Safari
        if browser == "safari":
            return None

        print(" Frame Commands ".center(80, "-"))
        print("Load 'web.dev/'")
        await s.load("https://web.dev/shadowdom-v1/", timeout=FORCE_TIMEOUT, retry=10)

        # Verify default frame
        els = await s.find_elements("button")
        text = " ".join([await i.text for i in els]).strip()
        print("default_frame:", text == "", text, sep="\t")
        frame_css = "figure.demoarea > iframe"
        print()

        # . switch by element locator
        print("switch_frame:", switch := await s.switch_frame(frame_css), sep="\t")
        if switch:
            els = await s.find_elements("button")
            text = " ".join([await i.text for i in els]).strip()
            print("sub_frame", text != "", text, sep="\t")
            await s.default_frame()
            await s.default_frame()
            els = await s.find_elements("button")
            text = " ".join([await i.text for i in els]).strip()
            print("default_frame:", text == "", text, sep="\t")
        print()

        # . switch by element
        frame = await s.find_element(frame_css)
        print("switch_frame:", switch := await s.switch_frame(frame), sep="\t")
        if switch:
            els = await s.find_elements("button")
            text = " ".join([await i.text for i in els]).strip()
            print("sub_frame", text != "", text, sep="\t")
            await s.default_frame()
            await s.default_frame()
            els = await s.find_elements("button")
            text = " ".join([await i.text for i in els]).strip()
            print("default_frame:", text == "", text, sep="\t")
        print()

        # . switch by index
        print("switch_frame:", switch := await s.switch_frame(0, by="index"), sep="\t")
        if switch:
            els = await s.find_elements("button")
            text = " ".join([await i.text for i in els]).strip()
            print("sub_frame", text != "", text, sep="\t")
            await s.default_frame()
            await s.default_frame()
            els = await s.find_elements("button")
            text = " ".join([await i.text for i in els]).strip()
            print("default_frame:", text == "", text, sep="\t")
        # fmt: on

        print("-" * 80)
        print()

    async def element(s: Session) -> None:
        print(" Element Commands ".center(80, "-"))
        print("Load 'www.baidu.com'")
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)
        await s.maximize_window()

        # fmt: off
        # css
        if 1:
            vil_css1, vil_css2, vil_css3 = "#kw", "#su", "span.soutu-btn"
            nil_css1, nil_css2, nil_css3 = "#kw1", "#su1", "span.soutu-btn1"
            vil_csses = [vil_css1, vil_css2, vil_css3]
            nil_csses = [nil_css1, nil_css2, nil_css3]
            mix_csses = [nil_css1, vil_css2, nil_css3]

            exists = await s.element_exists(vil_css1, by="css")
            print("element_exists (css):\t", exists is True, exists, sep="\t")
            exists = await s.element_exists(nil_css1, by="css")
            print("element_exists (css):\t", exists is False, exists, sep="\t")
            exist = await s.elements_exist(*vil_csses, by="css")
            print("elements_exist (css):\t", exist is True, exist, sep="\t")
            exist = await s.elements_exist(*nil_csses, by="css")
            print("elements_exist (css):\t", exist is False, exist, sep="\t")
            exist = await s.elements_exist(*mix_csses, by="css", all_=False)
            print("elements_exist (css):\t", exist is True, exist, sep="\t")
            exist = await s.elements_exist(*mix_csses, by="css", all_=True)
            print("elements_exist (css):\t", exist is False, exist, sep="\t")
            print()

            el = await s.active_element
            print("active_element:\t\t", el is not None, el, sep="\t")
            el1 = await s.find_element(vil_css1, by="css")
            print("find_element (css):\t", el1 is not None, el1, sep="\t")
            el2 = await s.find_element(vil_css2, by="css")
            print("find_element (css):\t", el2 is not None, el2, sep="\t")
            el3 = await s.find_element(vil_css3, by="css")
            print("find_element (css):\t", el3 is not None, el3, sep="\t")
            els = await s.find_elements(vil_css2, by="css")
            print("find_elements (css):\t", els[0] == el2, els, sep="\t")
            el = await s.find_1st_element(*vil_csses, by="css")
            print("find_1st_element (css):\t", el == el1, el, sep="\t")
            el = await s.find_1st_element(*mix_csses, by="css")
            print("find_1st_element (css):\t", el == el2, el, sep="\t")
            el = await s.find_1st_element(*nil_csses, by="css")
            print("find_1st_element (css):\t", el is None, el, sep="\t")
            print()

            res = await s.wait_until_element("exist", vil_css1, timeout=1)
            print("wait_until_element [exist] (css):", res is True, res, sep="\t")
            res = await s.wait_until_element("exist", nil_css1, timeout=1)
            print("wait_until_element [exist] (css):", res is False, res, sep="\t")
            res = await s.wait_until_element("gone", nil_css1, timeout=1)
            print("wait_until_element [gone] (css):", res is True, res, sep="\t")
            res = await s.wait_until_element("gone", vil_css1, timeout=1)
            print("wait_until_element [gone] (css):", res is False, res, sep="\t")
            if not isinstance(s, SafariSession):
                res = await s.wait_until_element("visible", vil_css1, timeout=1)
                print("wait_until_element [visible] (css):", res is True, res, sep="\t")
                res = await s.wait_until_element("selected", vil_css1, timeout=1)
                print("wait_until_element [selected] (css):", res is False, res, sep="\t")
            print()

            res = await s.wait_until_elements("exist", *vil_csses, timeout=1)
            print("wait_until_elements [exist] (css):", res is True, res, sep="\t")
            res = await s.wait_until_elements("exist", *nil_csses, timeout=1)
            print("wait_until_elements [exist] (css):", res is False, res, sep="\t")
            res = await s.wait_until_elements("exist", *mix_csses, all_=False, timeout=1)
            print("wait_until_elements [exist] (css):", res is True, res, sep="\t")
            res = await s.wait_until_elements("exist", *mix_csses, all_=True, timeout=1)
            print("wait_until_elements [exist] (css):", res is False, res, sep="\t")
            res = await s.wait_until_elements("gone", *nil_csses, timeout=1)
            print("wait_until_elements [gone] (css):", res is True, res, sep="\t")
            res = await s.wait_until_elements("gone", *vil_csses, timeout=1)
            print("wait_until_elements [gone] (css):", res is False, res, sep="\t")
            res = await s.wait_until_elements("gone", *mix_csses, all_=False, timeout=1)
            print("wait_until_elements [gone] (css):", res is True, res, sep="\t")
            res = await s.wait_until_elements("gone", *mix_csses, all_=True, timeout=1)
            print("wait_until_elements [gone] (css):", res is False, res, sep="\t")
            if not isinstance(s, SafariSession):
                res = await s.wait_until_elements("visible", *vil_csses, timeout=1)
                print("wait_until_elements [visible] (css):", res is True, res, sep="\t")
                res = await s.wait_until_elements("visible", *mix_csses, all_=False, timeout=1)
                print("wait_until_elements [visible] (css):", res is True, res, sep="\t")
                res = await s.wait_until_elements("visible", *mix_csses, all_=True, timeout=1)
                print("wait_until_elements [visible] (css):", res is False, res, sep="\t")
                res = await s.wait_until_elements("selected", *vil_csses, timeout=1)
                print("wait_until_elements [selected] (css):", res is False, res, sep="\t")
                res = await s.wait_until_elements("selected", *mix_csses, all_=False, timeout=1)
                print("wait_until_elements [selected] (css):", res is False, res, sep="\t")
                res = await s.wait_until_elements("selected", *mix_csses, all_=True, timeout=1)
                print("wait_until_elements [selected] (css):", res is False, res, sep="\t")
            print()

            vil_csses = [vil_css1, vil_css3]
            nil_csses = [nil_css1, nil_css3]
            mix_csses = [vil_css3, nil_css3]
            sb = await s.find_element("span.bg.s_ipt_wr", by="css")
            print("search_bar:", sb, sep="\t")
            exists = await sb.element_exists(vil_css1, by="css")
            print("[el] element_exists (css):", exists is True, exists, sep="\t")
            exists = await sb.element_exists(nil_css1, by="css")
            print("[el] element_exists (css):", exists is False, exists, sep="\t")
            exist = await sb.elements_exist(*vil_csses, by="css")
            print("[el] elements_exist (css):", exist is True, exist, sep="\t")
            exist = await sb.elements_exist(*nil_csses, by="css")
            print("[el] elements_exist (css):", exist is False, exist, sep="\t")
            exist = await sb.elements_exist(*mix_csses, by="css", all_=False)
            print("[el] elements_exist (css):", exist is True, exist, sep="\t")
            exist = await sb.elements_exist(*mix_csses, by="css", all_=True)
            print("[el] elements_exist (css):", exist is False, exist, sep="\t")
            print()

            el1 = await sb.find_element(vil_css1, by="css")
            print("[el] find_element (css):", el1 is not None, el1, sep="\t")
            el2 = await sb.find_element(vil_css3, by="css")
            print("[el] find_element (css):", el2 is not None, el2, sep="\t")
            els = await sb.find_elements(vil_css1, by="css")
            print("[el] find_elements (css):", els[0] == el1, els, sep="\t")
            el = await sb.find_1st_element(*vil_csses, by="css")
            print("[el] find_1st_element (css):", el == el1, el, sep="\t")
            el = await sb.find_1st_element(*mix_csses, by="css")
            print("[el] find_1st_element (css):", el == el2, el, sep="\t")
            el = await sb.find_1st_element(*nil_csses, by="css")
            print("[el] find_1st_element (css):", el is None, el, sep="\t")
            print()

            res = await sb.wait_until_element("exist", vil_css1, timeout=1)
            print("[el] wait_until_element [exist] (css):\t", res is True, res, sep="\t")
            res = await sb.wait_until_element("exist", nil_css1, timeout=1)
            print("[el] wait_until_element [exist] (css):\t", res is False, res, sep="\t")
            res = await sb.wait_until_element("gone", nil_css1, timeout=1)
            print("[el] wait_until_element [gone] (css):\t", res is True, res, sep="\t")
            res = await sb.wait_until_element("gone", vil_css1, timeout=1)
            print("[el] wait_until_element [gone] (css):\t", res is False, res, sep="\t")
            if not isinstance(s, SafariSession):
                res = await sb.wait_until_element("visible", vil_css1, timeout=1)
                print("[el] wait_until_element [visible] (css):", res is True, res, sep="\t")
                res = await sb.wait_until_element("selected", vil_css1, timeout=1)
                print("[el] wait_until_element [selected] (css):", res is False, res, sep="\t")
            print()

            res = await sb.wait_until_elements("exist", *vil_csses, timeout=1)
            print("[el] wait_until_elements [exist] (css):\t", res is True, res, sep="\t")
            res = await sb.wait_until_elements("exist", *nil_csses, timeout=1)
            print("[el] wait_until_elements [exist] (css):\t", res is False, res, sep="\t")
            res = await sb.wait_until_elements("exist", *mix_csses, all_=False, timeout=1)
            print("[el] wait_until_elements [exist] (css):\t", res is True, res, sep="\t")
            res = await sb.wait_until_elements("exist", *mix_csses, all_=True, timeout=1)
            print("[el] wait_until_elements [exist] (css):\t", res is False, res, sep="\t")
            res = await sb.wait_until_elements("gone", *nil_csses, timeout=1)
            print("[el] wait_until_elements [gone] (css):\t", res is True, res, sep="\t")
            res = await sb.wait_until_elements("gone", *vil_csses, timeout=1)
            print("[el] wait_until_elements [gone] (css):\t", res is False, res, sep="\t")
            res = await sb.wait_until_elements("gone", *mix_csses, all_=False, timeout=1)
            print("[el] wait_until_elements [gone] (css):\t", res is True, res, sep="\t")
            res = await sb.wait_until_elements("gone", *mix_csses, all_=True, timeout=1)
            print("[el] wait_until_elements [gone] (css):\t", res is False, res, sep="\t")
            if not isinstance(s, SafariSession):
                res = await sb.wait_until_elements("visible", *vil_csses, timeout=1)
                print("[el] wait_until_elements [visible] (css):", res is True, res, sep="\t")
                res = await sb.wait_until_elements("visible", *mix_csses, all_=False, timeout=1)
                print("[el] wait_until_elements [visible] (css):", res is True, res, sep="\t")
                res = await sb.wait_until_elements("visible", *mix_csses, all_=True, timeout=1)
                print("[el] wait_until_elements [visible] (css):", res is False, res, sep="\t")
                res = await sb.wait_until_elements("selected", *vil_csses, timeout=1)
                print("[el] wait_until_elements [selected] (css):", res is False, res, sep="\t")
                res = await sb.wait_until_elements("selected", *mix_csses, all_=False, timeout=1)
                print("[el] wait_until_elements [selected] (css):", res is False, res, sep="\t")
                res = await sb.wait_until_elements("selected", *mix_csses, all_=True, timeout=1)
                print("[el] wait_until_elements [selected] (css):", res is False, res, sep="\t")
            print()

        # xpath
        if 1:
            vil_xp1, vil_xp2 = ".//input[@id='kw']", ".//input[@id='su']"
            vil_xp3 = ".//span[@class='soutu-btn']"
            nil_xp1, nil_xp2 = ".//input[@id='kw1']", ".//input[@id='su1']"
            nil_xp3 = ".//span[@class='soutu-btn1']"
            vil_xps = [vil_xp1, vil_xp2, vil_xp3]
            nil_xps = [nil_xp1, nil_xp2, nil_xp3]
            mix_xps = [nil_xp1, vil_xp2, nil_xp3]

            exists = await s.element_exists(vil_xp1, by="xpath")
            print("element_exists (xpath):\t", exists is True, exists, sep="\t")
            exists = await s.element_exists(nil_xp1, by="xpath")
            print("element_exists (xpath):\t", exists is False, exists, sep="\t")
            exist = await s.elements_exist(*vil_xps, by="xpath")
            print("elements_exist (xpath):\t", exist is True, exist, sep="\t")
            exist = await s.elements_exist(*nil_xps, by="xpath")
            print("elements_exist (xpath):\t", exist is False, exist, sep="\t")
            exist = await s.elements_exist(*mix_xps, by="xpath", all_=False)
            print("elements_exist (xpath):\t", exist is True, exist, sep="\t")
            exist = await s.elements_exist(*mix_xps, by="xpath", all_=True)
            print("elements_exist (xpath):\t", exist is False, exist, sep="\t")
            print()

            el1 = await s.find_element(vil_xp1, by="xpath")
            print("find_element (xpath):\t", el1 is not None, el1, sep="\t")
            el2 = await s.find_element(vil_xp2, by="xpath")
            print("find_element (xpath):\t", el2 is not None, el2, sep="\t")
            el3 = await s.find_element(vil_xp3, by="xpath")
            print("find_element (xpath):\t", el3 is not None, el3, sep="\t")
            els = await s.find_elements(vil_xp2, by="xpath")
            print("find_elements (xpath):\t", els[0] == el2, els, sep="\t")
            el = await s.find_1st_element(*vil_xps, by="xpath")
            print("find_1st_element (xpath):", el == el1, el, sep="\t")
            el = await s.find_1st_element(*mix_xps, by="xpath")
            print("find_1st_element (xpath):", el == el2, el, sep="\t")
            el = await s.find_1st_element(*nil_xps, by="xpath")
            print("find_1st_element (xpath):", el is None, el, sep="\t")
            print()

            res = await s.wait_until_element("exist", vil_xp1, by="xpath", timeout=1)
            print("wait_until_element [exist] (xpath):", res is True, res, sep="\t")
            res = await s.wait_until_element("exist", nil_xp1, by="xpath", timeout=1)
            print("wait_until_element [exist] (xpath):", res is False, res, sep="\t")
            res = await s.wait_until_element("gone", nil_xp1, by="xpath", timeout=1)
            print("wait_until_element [gone] (xpath):", res is True, res, sep="\t")
            res = await s.wait_until_element("gone", vil_xp1, by="xpath", timeout=1)
            print("wait_until_element [gone] (xpath):", res is False, res, sep="\t")
            if not isinstance(s, SafariSession):
                res = await s.wait_until_element("visible", vil_xp1, by="xpath", timeout=1)
                print("wait_until_element [visible] (xpath):", res is True, res, sep="\t")
                res = await s.wait_until_element("selected", vil_xp1, by="xpath", timeout=1)
                print("wait_until_element [selected] (xpath):", res is False, res, sep="\t")
            print()

            res = await s.wait_until_elements("exist", *vil_xps, by="xpath", timeout=1)
            print("wait_until_elements [exist] (xpath):", res is True, res, sep="\t")
            res = await s.wait_until_elements("exist", *nil_xps, by="xpath", timeout=1)
            print("wait_until_elements [exist] (xpath):", res is False, res, sep="\t")
            res = await s.wait_until_elements("exist", *mix_xps, by="xpath", all_=False, timeout=1)
            print("wait_until_elements [exist] (xpath):", res is True, res, sep="\t")
            res = await s.wait_until_elements("exist", *mix_xps, by="xpath", all_=True, timeout=1)
            print("wait_until_elements [exist] (xpath):", res is False, res, sep="\t")
            res = await s.wait_until_elements("gone", *nil_xps, by="xpath", timeout=1)
            print("wait_until_elements [gone] (xpath):", res is True, res, sep="\t")
            res = await s.wait_until_elements("gone", *vil_xps, by="xpath", timeout=1)
            print("wait_until_elements [gone] (xpath):", res is False, res, sep="\t")
            res = await s.wait_until_elements("gone", *mix_xps, by="xpath", all_=False, timeout=1)
            print("wait_until_elements [gone] (xpath):", res is True, res, sep="\t")
            res = await s.wait_until_elements("gone", *mix_xps, by="xpath", all_=True, timeout=1)
            print("wait_until_elements [gone] (xpath):", res is False, res, sep="\t")
            if not isinstance(s, SafariSession):
                res = await s.wait_until_elements("visible", *vil_xps, by="xpath", timeout=1)
                print("wait_until_elements [visible] (xpath):", res is True, res, sep="\t")
                res = await s.wait_until_elements("visible", *mix_xps, by="xpath", all_=False, timeout=1)
                print("wait_until_elements [visible] (xpath):", res is True, res, sep="\t")
                res = await s.wait_until_elements("visible", *mix_xps, by="xpath", all_=True, timeout=1)
                print("wait_until_elements [visible] (xpath):", res is False, res, sep="\t")
                res = await s.wait_until_elements("selected", *vil_xps, by="xpath", timeout=1)
                print("wait_until_elements [selected] (xpath):", res is False, res, sep="\t")
                res = await s.wait_until_elements("selected", *mix_xps, by="xpath", all_=False, timeout=1)
                print("wait_until_elements [selected] (xpath):", res is False, res, sep="\t")
                res = await s.wait_until_elements("selected", *mix_xps, by="xpath", all_=True, timeout=1)
                print("wait_until_elements [selected] (xpath):", res is False, res, sep="\t")
            print()

            vil_xps = [vil_xp1, vil_xp3]
            nil_xps = [nil_xp1, nil_xp3]
            mix_xps = [vil_xp3, nil_xp3]
            sb = await s.find_element("span.bg.s_ipt_wr", by="css")
            print("search_bar:", sb, sep="\t")
            exists = await sb.element_exists(vil_xp1, by="xpath")
            print("[el] element_exists (xpath):", exists is True, exists, sep="\t")
            exists = await sb.element_exists(nil_xp1, by="xpath")
            print("[el] element_exists (xpath):", exists is False, exists, sep="\t")
            exist = await sb.elements_exist(*vil_xps, by="xpath")
            print("[el] elements_exist (xpath):", exist is True, exist, sep="\t")
            exist = await sb.elements_exist(*nil_xps, by="xpath")
            print("[el] elements_exist (xpath):", exist is False, exist, sep="\t")
            exist = await sb.elements_exist(*mix_xps, by="xpath", all_=False)
            print("[el] elements_exist (xpath):", exist is True, exist, sep="\t")
            exist = await sb.elements_exist(*mix_xps, by="xpath", all_=True)
            print("[el] elements_exist (xpath):", exist is False, exist, sep="\t")
            print()

            el1 = await sb.find_element(vil_xp1, by="xpath")
            print("[el] find_element (xpath):", el1 is not None, el1, sep="\t")
            el2 = await sb.find_element(vil_xp3, by="xpath")
            print("[el] find_element (xpath):", el2 is not None, el2, sep="\t")
            els = await sb.find_elements(vil_xp1, by="xpath")
            print("[el] find_elements (xpath):", els[0] == el1, els, sep="\t")
            el = await sb.find_1st_element(*vil_xps, by="xpath")
            print("[el] find_1st_element (xpath):", el == el1, el, sep="\t")
            el = await sb.find_1st_element(*mix_xps, by="xpath")
            print("[el] find_1st_element (xpath):", el == el2, el, sep="\t")
            el = await sb.find_1st_element(*nil_xps, by="xpath")
            print("[el] find_1st_element (xpath):", el is None, el, sep="\t")
            print()

            res = await sb.wait_until_element("exist", vil_xp1, by="xpath", timeout=1)
            print("[el] wait_until_element [exist] (xpath):", res is True, res, sep="\t")
            res = await sb.wait_until_element("exist", nil_xp1, by="xpath", timeout=1)
            print("[el] wait_until_element [exist] (xpath):", res is False, res, sep="\t")
            res = await sb.wait_until_element("gone", nil_xp1, by="xpath", timeout=1)
            print("[el] wait_until_element [gone] (xpath):\t", res is True, res, sep="\t")
            res = await sb.wait_until_element("gone", vil_xp1, by="xpath", timeout=1)
            print("[el] wait_until_element [gone] (xpath):\t", res is False, res, sep="\t")
            if not isinstance(s, SafariSession):
                res = await sb.wait_until_element("visible", vil_xp1, by="xpath", timeout=1)
                print("[el] wait_until_element [visible] (xpath):", res is True, res, sep="\t")
                res = await sb.wait_until_element("selected", vil_xp1, by="xpath", timeout=1)
                print("[el] wait_until_element [selected] (xpath):", res is False, res, sep="\t")
            print()

            res = await sb.wait_until_elements("exist", *vil_xps, by="xpath", timeout=1)
            print("[el] wait_until_elements [exist] (xpath):", res is True, res, sep="\t")
            res = await sb.wait_until_elements("exist", *nil_xps, by="xpath", timeout=1)
            print("[el] wait_until_elements [exist] (xpath):", res is False, res, sep="\t")
            res = await sb.wait_until_elements("exist", *mix_xps, by="xpath", all_=False, timeout=1)
            print("[el] wait_until_elements [exist] (xpath):", res is True, res, sep="\t")
            res = await sb.wait_until_elements("exist", *mix_xps, by="xpath", all_=True, timeout=1)
            print("[el] wait_until_elements [exist] (xpath):", res is False, res, sep="\t")
            res = await sb.wait_until_elements("gone", *nil_xps, by="xpath", timeout=1)
            print("[el] wait_until_elements [gone] (xpath):", res is True, res, sep="\t")
            res = await sb.wait_until_elements("gone", *vil_xps, by="xpath", timeout=1)
            print("[el] wait_until_elements [gone] (xpath):", res is False, res, sep="\t")
            res = await sb.wait_until_elements("gone", *mix_xps, by="xpath", all_=False, timeout=1)
            print("[el] wait_until_elements [gone] (xpath):", res is True, res, sep="\t")
            res = await sb.wait_until_elements("gone", *mix_xps, by="xpath", all_=True, timeout=1)
            print("[el] wait_until_elements [gone] (xpath):", res is False, res, sep="\t")
            if not isinstance(s, SafariSession):
                res = await sb.wait_until_elements("visible", *vil_xps, by="xpath", timeout=1)
                print("[el] wait_until_elements [visible] (xpath):", res is True, res, sep="\t")
                res = await sb.wait_until_elements("visible", *mix_xps, by="xpath", all_=False, timeout=1)
                print("[el] wait_until_elements [visible] (xpath):", res is True, res, sep="\t")
                res = await sb.wait_until_elements("visible", *mix_xps, by="xpath", all_=True, timeout=1)
                print("[el] wait_until_elements [visible] (xpath):", res is False, res, sep="\t")
                res = await sb.wait_until_elements("selected", *vil_xps, by="xpath", timeout=1)
                print("[el] wait_until_elements [selected] (xpath):", res is False, res, sep="\t")
                res = await sb.wait_until_elements("selected", *mix_xps, by="xpath", all_=False, timeout=1)
                print("[el] wait_until_elements [selected] (xpath):", res is False, res, sep="\t")
                res = await sb.wait_until_elements("selected", *mix_xps, by="xpath", all_=True, timeout=1)
                print("[el] wait_until_elements [selected] (xpath):", res is False, res, sep="\t")
            print()

        # Skip safari
        if not isinstance(s, SafariSession):
            print("Load 'image.baidu.com/'")
            await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)

            el = await s.find_element("a[href='http://image.baidu.com/']")
            tag = await el.tag
            print("[el] tag:\t", tag == "a", tag, sep="\t")
            res = await el.wait_until_tag("equals", "a", timeout=1)
            print("[el] wait_until_tag:", res is True, res, sep="\t")
            res = await el.wait_until_tag("contains", "a", timeout=1)
            print("[el] wait_until_tag:", res is True, res, sep="\t")
            res = await el.wait_until_tag("startswith", "a", timeout=1)
            print("[el] wait_until_tag:", res is True, res, sep="\t")
            res = await el.wait_until_tag("endswith", "a", timeout=1)
            print("[el] wait_until_tag:", res is True, res, sep="\t")
            res = await el.wait_until_tag("endswith", "div", timeout=1)
            print("[el] wait_until_tag:", res is False, res, sep="\t")

            text = await el.text
            print("[el] text:\t", text == "图片", text, sep="\t")
            res = await el.wait_until_text("equals", "图片", timeout=1)
            print("[el] wait_until_text:", res is True, res, sep="\t")
            res = await el.wait_until_text("contains", "图", timeout=1)
            print("[el] wait_until_text:", res is True, res, sep="\t")
            res = await el.wait_until_text("startswith", "图", timeout=1)
            print("[el] wait_until_text:", res is True, res, sep="\t")
            res = await el.wait_until_text("endswith", "片", timeout=1)
            print("[el] wait_until_text:", res is True, res, sep="\t")
            res = await el.wait_until_text("endswith", "1", timeout=1)
            print("[el] wait_until_text:", res is False, res, sep="\t")

            rect = await el.rect
            print("[el] rect:\t", rect is not None, rect, sep="\t")

            el = await s.find_element("div.title-text.c-color-t", by="css")
            aria_role = await el.aria_role
            print("[el] aria_role:\t", aria_role == "generic", aria_role, sep="\t")
            aria_label = await el.aria_label
            print("[el] aria_label:", aria_label == "百度热搜", aria_label, sep="\t")
            props = await el.properties
            print("[el] properties:", bool(props), props[:5], sep="\t")
            prop = await el.get_property("clientHeight")
            print("[el] get_property:", isinstance(prop, int), prop, sep="\t")
            props_css = await el.properties_css
            print("[el] properties_css:", bool(props_css), str(props_css)[:50], sep="\t")
            prop_css = await el.get_property_css("cursor")
            print("[el] get_property_css:", prop_css == "pointer", prop_css, sep="\t")
            attrs = await el.attributes
            print("[el] attributes:", bool(attrs), attrs, sep="\t")
            attr = await el.get_attribute("aria-label")
            print("[el] get_attribute:", attr == "百度热搜", attr, sep="\t")
            attr_dom = await el.get_attribute_dom("aria-label")
            print("[el] get_attribute_dom:", attr_dom == "百度热搜", attr_dom, sep="\t")

            el = await s.find_element("span.soutu-btn", by="css")
            screenshot = await el.take_screenshot()
            print("[el] take_screenshot", bool(screenshot), screenshot[:30], sep="\t")
            path = os.path.join(TEST_FOLDER, "screenshot_button")
            print("[el] save_screenshot", await el.save_screenshot(path), sep="\t")
            print()

        # Control
        print("Load 'image.baidu.com/'")
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)
        el = await s.find_element("#kw", by="css")
        visible = await el.visible
        print("[el] visible:\t\t", visible is True, visible, sep="\t")
        res = await el.wait_until("visible", timeout=1)
        print("[el] wait_until [visible]:", res is True, res, sep="\t")
        viewable = await el.viewable
        print("[el] viewable:\t\t", viewable is True, viewable, sep="\t")
        res = await el.wait_until("viewable", timeout=1)
        print("[el] wait_until [viewable]:", res is True, res, sep="\t")
        enabled = await el.enabled
        print("[el] enabled:\t\t", enabled is True, enabled, sep="\t")
        res = await el.wait_until("enabled", timeout=1)
        print("[el] wait_until [enabled]:", res is True, res, sep="\t")
        selected = await el.selected
        print("[el] selected:\t\t", selected is False, selected, sep="\t")
        res = await el.wait_until("selected", timeout=1)
        print("[el] wait_until [selected]:", res is False, res, sep="\t")
        res = await el.wait_until("gone", timeout=1)
        print("[el] wait_until [gone]:\t", res is False, res, sep="\t")
        print()

        print("[el] send (text):", await el.send("Hello world!", pause=0.5), sep="\t")
        print("[el] send (ctl + a):", await el.send(CONTROL_KEY, "a", pause=0.5), sep="\t")
        print("[el] send (ctl + c):", await el.send(CONTROL_KEY, "c", pause=0.5), sep="\t")
        print("[el] send (del):", await el.send(KeyboardKeys.DELETE, pause=0.5), sep="\t")
        print("[el] send (ctl + v):", await el.send(CONTROL_KEY, "v", pause=0.5), sep="\t")
        print("[el] send (enter):", await el.send(KeyboardKeys.ENTER, pause=0.5), sep="\t")
        el = await s.find_element("#kw", by="css")
        print("[el] clear:\t", await el.clear(pause=0.5), sep="\t")
        el = await s.find_element("#help", by="css")
        print("[el] scroll_into_view:", await el.scroll_into_view(), sep="\t")
        print()

        # Upload
        print("Load 'www.baidu.com/'")
        await s.load("https://www.baidu.com/", timeout=FORCE_TIMEOUT, retry=10)
        el = await s.find_element("span.soutu-btn")
        await el.click(pause=0.5)
        el = await s.find_element("input.upload-pic")
        await el.upload(os.path.join(TEST_FOLDER, "captcha-test.png"))
        await s.wait_until_url("startswith", "https://graph.baidu.com/", timeout=20)
        print("[el] upload:\t", True, sep="\t")
        await asyncio.sleep(2)

        # fmt: on
        print("-" * 80)
        print()

    async def shadow(s: Session) -> None:
        # Skip Safari
        if browser == "safari":
            return None

        print(" Shadow Commands ".center(80, "-"))
        print("Load 'www.htmlelements.com'")
        url = "https://www.htmlelements.com/demos/menu/shadow-dom/index.htm"
        await s.load(url, timeout=FORCE_TIMEOUT, retry=10)
        shadow_css = "smart-ui-menu.smart-ui-component"
        await s.wait_until_element("exist", shadow_css, timeout=100)
        sd = await s.get_shadow(shadow_css)
        print("shadow root:", sd is not None, sd, sep="\t")
        vil_css1 = "div[smart-id='container']"
        vil_css2 = "div[smart-id='container'] > div.smart-header"
        nil_css1 = "div[smart-id='containe']"
        nil_css2 = "div[smart-id='container'] > div.smart-heade"
        vil_csses = [vil_css1, vil_css2]
        nil_csses = [nil_css1, nil_css2]
        mix_csses = [nil_css1, vil_css2]
        print()

        exists = await sd.element_exists(vil_css1)
        print("[sd] element_exists (css):", exists is True, exists, sep="\t")
        exists = await sd.element_exists(nil_css1)
        print("[sd] element_exists (css):", exists is False, exists, sep="\t")
        exist = await sd.elements_exist(*vil_csses)
        print("[sd] elements_exist (css):", exist is True, exist, sep="\t")
        exist = await sd.elements_exist(*nil_csses)
        print("[sd] elements_exist (css):", exist is False, exist, sep="\t")
        exist = await sd.elements_exist(*mix_csses, all_=False)
        print("[sd] elements_exist (css):", exist is True, exist, sep="\t")
        exist = await sd.elements_exist(*mix_csses, all_=True)
        print("[sd] elements_exist (css):", exist is False, exist, sep="\t")
        print()

        el1 = await sd.find_element(vil_css1)
        print("[sd] find_element (css):", el1 is not None, el1, sep="\t")
        el2 = await sd.find_element(vil_css2)
        print("[sd] find_element (css):", el2 is not None, el2, sep="\t")
        els = await sd.find_elements(vil_css1)
        print("[sd] find_elements (css):", els[0] == el1, els, sep="\t")
        el = await sd.find_1st_element(*vil_csses)
        print("[sd] find_1st_element (css):", el == el1, el, sep="\t")
        el = await sd.find_1st_element(*mix_csses)
        print("[sd] find_1st_element (css):", el == el2, el, sep="\t")
        el = await sd.find_1st_element(*nil_csses)
        print("[sd] find_1st_element (css):", el is None, el, sep="\t")
        print()

        res = await sd.wait_until_element("exist", vil_css1, timeout=1)
        print("[sd] wait_until_element [exist] (css):\t", res is True, res, sep="\t")
        res = await sd.wait_until_element("exist", nil_css1, timeout=1)
        print("[sd] wait_until_element [exist] (css):\t", res is False, res, sep="\t")
        res = await sd.wait_until_element("gone", nil_css1, timeout=1)
        print("[sd] wait_until_element [gone] (css):\t", res is True, res, sep="\t")
        res = await sd.wait_until_element("gone", vil_css1, timeout=1)
        print("[sd] wait_until_element [gone] (css):\t", res is False, res, sep="\t")
        res = await sd.wait_until_element("visible", vil_css1, timeout=1)
        print("[sd] wait_until_element [visible] (css):", res is True, res, sep="\t")
        res = await sd.wait_until_element("selected", vil_css1, timeout=1)
        print("[sd] wait_until_element [selected] (css):", res is False, res, sep="\t")
        print()

        # fmt: off
        res = await sd.wait_until_elements("exist", *vil_csses, timeout=1)
        print("[sd] wait_until_elements [exist] (css):\t", res is True, res, sep="\t")
        res = await sd.wait_until_elements("exist", *nil_csses, timeout=1)
        print("[sd] wait_until_elements [exist] (css):\t", res is False, res, sep="\t")
        res = await sd.wait_until_elements("exist", *mix_csses, all_=False, timeout=1)
        print("[sd] wait_until_elements [exist] (css):\t", res is True, res, sep="\t")
        res = await sd.wait_until_elements("exist", *mix_csses, all_=True, timeout=1)
        print("[sd] wait_until_elements [exist] (css):\t", res is False, res, sep="\t")
        res = await sd.wait_until_elements("gone", *nil_csses, timeout=1)
        print("[sd] wait_until_elements [gone] (css):\t", res is True, res, sep="\t")
        res = await sd.wait_until_elements("gone", *vil_csses, timeout=1)
        print("[sd] wait_until_elements [gone] (css):\t", res is False, res, sep="\t")
        res = await sd.wait_until_elements("gone", *mix_csses, all_=False, timeout=1)
        print("[sd] wait_until_elements [gone] (css):\t", res is True, res, sep="\t")
        res = await sd.wait_until_elements("gone", *mix_csses, all_=True, timeout=1)
        print("[sd] wait_until_elements [gone] (css):\t", res is False, res, sep="\t")
        res = await sd.wait_until_elements("visible", *vil_csses, timeout=1)
        print("[sd] wait_until_elements [visible] (css):", res is True, res, sep="\t")
        res = await sd.wait_until_elements("visible", *mix_csses, all_=False, timeout=1)
        print("[sd] wait_until_elements [visible] (css):", res is True, res, sep="\t")
        res = await sd.wait_until_elements("visible", *mix_csses, all_=True, timeout=1)
        print("[sd] wait_until_elements [visible] (css):", res is False, res, sep="\t")
        res = await sd.wait_until_elements("selected", *vil_csses, timeout=1)
        print("[sd] wait_until_elements [selected] (css):", res is False, res, sep="\t")
        res = await sd.wait_until_elements("selected", *mix_csses, all_=False, timeout=1)
        print("[sd] wait_until_elements [selected] (css):", res is False, res, sep="\t")
        res = await sd.wait_until_elements("selected", *mix_csses, all_=True, timeout=1)
        print("[sd] wait_until_elements [selected] (css):", res is False, res, sep="\t")
        # fmt: on

        print("-" * 80)
        print()

    async def javascript(s: Session) -> None:
        print(" Javascript Commands ".center(80, "-"))
        print("Load 'www.baidu.com'")
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)
        js1 = "return document.title;"
        js2 = "return arguments[0];"
        args1 = "Hello world!"
        args2 = "Hello world! overwrite"

        scripts = s.scripts
        print("scripts:", len(scripts) == 0, scripts, sep="\t")
        sp1 = s.cache_script("get_title", js1)
        print("cache_script:", sp1.name == "get_title", sp1, sep="\t")
        res = s.remove_script("get_title")
        print("remove_script:", res is True and not s.scripts, res, sep="\t")
        sp1 = s.cache_script("get_title", js1)
        print("cache_script:", sp1.name == "get_title", sp1, sep="\t")
        res = s.remove_script(sp1)
        print("remove_script:", res is True and not s.scripts, res, sep="\t")
        print()

        sp1 = s.cache_script("get_title_2", js1)
        print("cache_script:", sp1.name == "get_title_2", sp1, sep="\t")
        sp1 = s.rename_script("get_title_2", "get_title_1")
        print("rename_script:", sp1.name == "get_title_1", sp1, sep="\t")
        sp1 = s.rename_script(sp1, "get_title")
        print("rename_script:", sp1.name == "get_title", sp1, sep="\t")
        scripts = s.scripts
        print("scripts:", len(scripts) == 1, scripts, sep="\t")
        sp2 = s.cache_script("return", js2, args1)
        print("cache_script:", sp2.name == "return", sp2, sep="\t")
        print()

        sp1 = s.get_script("get_title")
        print("get_script:", sp1.name == "get_title", sp1, sep="\t")
        sp1 = s.get_script(sp1)
        print("get_script:", sp1.name == "get_title", sp1, sep="\t")
        sp2 = s.get_script("random_name")
        print("get_script:", sp2 is None, sp2, sep="\t")
        sp2 = s.get_script("return")
        print("get_script:", sp2.name == "return", sp2, sep="\t")
        print()

        res = await s.execute_script(js1)
        print("execute_script [nill args] (code):\t", bool(res), res, sep="\t")
        res = await s.execute_script("get_title")
        print("execute_script [nill args] (cached name):", bool(res), res, sep="\t")
        res = await s.execute_script(sp1)
        print("execute_script [nill args] (cached inst):", bool(res), res, sep="\t")
        print()

        res = await s.execute_script(js2, args1)
        print("execute_script [with args] (code):\t", res == args1, res, sep="\t")
        res = await s.execute_script("return")
        print("execute_script [cache args] (cached name):", res == args1, res, sep="\t")
        res = await s.execute_script("return", args2)
        print("execute_script [new args] (cached name)::", res == args2, res, sep="\t")
        res = await s.execute_script(sp2)
        print("execute_script [cache args] (cached inst):", res == args1, res, sep="\t")
        res = await s.execute_script(sp2, args2)
        print("execute_script [new args] (cached inst):", res == args2, res, sep="\t")

        print("-" * 80)
        print()

    async def actions(s: Session) -> None:
        # Skip Safari
        if browser == "safari":
            return None

        print(" Actions Commands ".center(80, "-"))
        img_btn_css = "span.soutu-btn"
        sch_btn_css = "#su"
        verify_css1 = "input.upload-pic"
        verify_css2 = "span.soutu-url-error"

        if 1:
            # Move to (x, y) center-coordiantes
            print("Load 'www.baidu.com'")
            await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)
            img_btn = await s.find_element(img_btn_css)
            print("image button:\t", img_btn is not None, img_btn, sep="\t")
            rect1 = await img_btn.rect
            x, y = rect1.center_x, rect1.center_y
            await s.actions().move_to(x=x, y=y, pause=0.5).click().perform()
            verify = await s.find_element(verify_css1)
            print("[AC] move_to (x, y):", verify is not None, sep="\t")
            sch_btn = await s.find_element(sch_btn_css)
            print("search button:\t", sch_btn is not None, sch_btn, sep="\t")
            rect2 = await sch_btn.rect
            x, y = rect2.center_x, rect2.center_y
            await s.actions().move_to(x=x, y=y, pause=0.5).click().perform()
            verify = await s.find_element(verify_css2)
            print("[AC] move_to (x, y):", verify is not None, sep="\t")
            print()

            # Move to (x, y) offset-coordiantes hit
            print("Load 'www.baidu.com'")
            await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)
            img_btn = await s.find_element(img_btn_css)
            print("image button:\t", img_btn is not None, img_btn, sep="\t")
            rect1 = await img_btn.rect
            x, y = rect1.x + 10, rect1.y + 10
            await s.actions().move_to(x=x, y=y, pause=0.5).click().perform()
            verify = await s.find_element(verify_css1)
            print("[AC] move_to (x, y) offset hit:", verify is not None, sep="\t")
            sch_btn = await s.find_element(sch_btn_css)
            print("search button:\t", sch_btn is not None, sch_btn, sep="\t")
            rect2 = await sch_btn.rect
            x, y = rect2.x + 10, rect2.y + 10
            await s.actions().move_to(x=x, y=y, pause=0.5).click().perform()
            verify = await s.find_element(verify_css2)
            print("[AC] move_to (x, y) offset hit:", verify is not None, sep="\t")
            print()

            # Move to (x, y) offset-coordiantes miss
            print("Load 'www.baidu.com'")
            await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)
            img_btn = await s.find_element(img_btn_css)
            print("image button:\t", img_btn is not None, img_btn, sep="\t")
            rect1 = await img_btn.rect
            x, y = rect1.x + rect1.width, rect1.y + rect1.height
            await s.actions().move_to(x=x, y=y, pause=0.5).click().perform()
            verify = await s.find_element(verify_css1)
            print("[AC] move_to (x, y) offset miss:", verify is None, sep="\t")
            print()

        if 1:
            # Move to (element) center-coordiantes
            print("Load 'www.baidu.com'")
            await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)
            img_btn = await s.find_element(img_btn_css)
            print("image button:\t", img_btn is not None, img_btn, sep="\t")
            await s.actions().move_to(element=img_btn, pause=0.5).click().perform()
            verify = await s.find_element(verify_css1)
            print("[AC] move_to (element):", verify is not None, sep="\t")
            sch_btn = await s.find_element(sch_btn_css)
            print("search button:\t", sch_btn is not None, sch_btn, sep="\t")
            await s.actions().move_to(element=sch_btn, pause=0.5).click().perform()
            verify = await s.find_element(verify_css2)
            print("[AC] move_to (element):", verify is not None, sep="\t")
            print()

            # Move to (element) offset hit
            print("Load 'www.baidu.com'")
            await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)
            x, y = 1, 1
            img_btn = await s.find_element(img_btn_css)
            print("image button:\t", img_btn is not None, img_btn, sep="\t")
            await s.actions().move_to(img_btn, x, y, pause=0.5).click().perform()
            verify = await s.find_element(verify_css1)
            print("[AC] move_to (element) offset hit:", verify is not None, sep="\t")
            sch_btn = await s.find_element(sch_btn_css)
            print("search button:\t", sch_btn is not None, sch_btn, sep="\t")
            await s.actions().move_to(sch_btn, x, y, pause=0.5).click().perform()
            verify = await s.find_element(verify_css2)
            print("[AC] move_to (element) offset hit:", verify is not None, sep="\t")
            print()

            # Move to (element) offset miss
            print("Load 'www.baidu.com'")
            await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)
            x, y = 30, 30
            img_btn = await s.find_element(img_btn_css)
            print("image button:\t", img_btn is not None, img_btn, sep="\t")
            await s.actions().move_to(img_btn, x, y, pause=0.5).click().perform()
            verify = await s.find_element(verify_css1)
            print("[AC] move_to (element) offset miss:", verify is None, sep="\t")
            print()

        if 1:
            # Move by (x, y)
            print("Load 'www.baidu.com'")
            await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)
            img_btn = await s.find_element(img_btn_css)
            print("image button:\t", img_btn is not None, img_btn, sep="\t")
            rect1 = await img_btn.rect
            x, y = rect1.center_x, rect1.center_y
            await s.actions().move_to(x=0, y=0).perform()
            await s.actions().move_by(x, y, pause=0.5).click().perform()
            verify = await s.find_element(verify_css1)
            print("[AC] move_by (x, y):", verify is not None, sep="\t")
            sch_btn = await s.find_element(sch_btn_css)
            print("search button:\t", sch_btn is not None, sch_btn, sep="\t")
            rect2 = await sch_btn.rect
            x, y = rect2.x - rect1.x, 0
            await s.actions().move_by(x, y, pause=0.5).click().perform()
            verify = await s.find_element(verify_css2)
            print("[AC] move_by (x, y):", verify is not None, sep="\t")
            print()

        if 1:
            # Drag & Drop (element)
            print("Load 'https://www.w3schools.com'")
            url = "https://www.w3schools.com/html/html5_draganddrop.asp"
            await s.load(url, timeout=FORCE_TIMEOUT, retry=10)
            print("left element:", l_el := await s.find_element("#div1"))
            print("right element:", r_el := await s.find_element("#div2"))
            await s.actions().drag_and_drop(drag=l_el, drop=r_el, pause=1).perform()
            l_verify = await s.element_exists("#div1 > img")
            r_verify = await s.element_exists("#div2 > img")
            print("[AC] drag_and_drop (element):", not l_verify and r_verify, sep="\t")
            await s.actions().drag_and_drop(drag=r_el, drop=l_el, pause=1).perform()
            l_verify = await s.element_exists("#div1 > img")
            r_verify = await s.element_exists("#div2 > img")
            print("[AC] drag_and_drop (element):", l_verify and not r_verify, sep="\t")
            print()

        if 1:
            # Keyboards
            print("Load 'www.baidu.com'")
            await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)
            sch_btn = await s.find_element(sch_btn_css)
            (
                await s.actions()
                .move_to(element=sch_btn)
                .click(pause=1)
                .send_keys("hellow world!", pause=1)
                .send_key_combo(CONTROL_KEY, "a", pause=1)
                .send_keys(KeyboardKeys.DELETE, pause=1)
                .send_keys("Hello World!", pause=1)
                .send_keys(KeyboardKeys.ENTER, pause=1)
                .perform("10" if isinstance(s, FirefoxSession) else None)
            )
            title = await s.title
            print("[AC] keyboards:\t\t", title.startswith("Hello World!"), sep="\t")
            print()

        if 1:
            # Wheel
            print("Load 'www.baidu.com'")
            await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)
            sch_btn = await s.find_element(sch_btn_css)
            (
                await s.actions()
                .move_to(element=sch_btn)
                .click(pause=1)
                .send_keys("hellow world!", pause=1)
                .send_keys(KeyboardKeys.ENTER, pause=1)
                .perform()
            )
            if isinstance(s, FirefoxSession):
                await asyncio.sleep(5)

            await s.actions().scroll_by(y=500, pause=1).perform()
            viewport = await s.viewport
            print("[AC] scroll_by (x, y):\t", viewport.y == 500, sep="\t")
            await s.actions().scroll_by(y=-500, pause=1).perform()
            viewport = await s.viewport
            print("[AC] scroll_by (x, y):\t", viewport.y == 0, sep="\t")

            if browser != "firefox":
                hlp_el = await s.find_element("#help")
                await s.actions().scroll_to(element=hlp_el, pause=1).perform()
                viewport1 = await s.viewport
                await s.actions().scroll_to(element=hlp_el, y=-500, pause=1).perform()
                viewport2 = await s.viewport
                success = viewport1.y - viewport2.y == 500
                print("[AC] scroll_to (element):", success, sep="\t")

        # fmt: on
        print("-" * 80)
        print()

    async def permission(s: ChromeSession) -> None:
        # Skip Firefox
        if browser == "firefox":
            return None

        print(" Permission Commands ".center(80, "-"))
        print("Load 'www.baidu.com'")
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)

        if isinstance(s, SafariSession):
            permissions = await s.permissions
            print("permissions:", bool(permissions), permissions, sep="\t")
            p = await s.get_permission("getUserMedia")
            print("get_permission:", p is True, p, sep="\t")
            await s.set_permission("getUserMedia", False)
            p = await s.get_permission("getUserMedia")
            print("set_permission:", p is False, p, sep="\t")
            permissions = await s.permissions
            print("permissions:", bool(permissions), permissions, sep="\t")
        else:
            permissions = await s.permissions
            print("permissions:", bool(permissions), sep="\t")
            print(*permissions, sep="\n\t")
            p = await s.get_permission("camera")
            print("get_permission:", p is not None, p, sep="\t")
            p = await s.set_permission("camera", "denied")
            print("set_permission:", p.state == "denied", p, sep="\t")
            p = await s.set_permission("camera", "granted")
            print("set_permission:", p.state == "granted", p, sep="\t")
            p = await s.set_permission("camera", "prompt")
            print("set_permission:", p.state == "prompt", p, sep="\t")

        print("-" * 80)
        print()

    async def network(s: ChromeSession) -> None:
        # Chromium only
        if browser not in ("chrome", "edge", "chromium"):
            return None

        print(" Network Commands ".center(80, "-"))
        print("Load 'www.baidu.com'")
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)

        network = await s.network
        print("network:", network is not None, network, sep="\t")
        latency, upload = 10, 1000
        n = await s.set_network(latency=10, upload_throughput=1000)
        success = n.latency == latency and n.upload_throughput == upload
        print("set_network:", success, n, sep="\t")
        n = await s.reset_network()
        success = n.latency == 0 and n.upload_throughput == -1
        print("reset_network:", success, n, sep="\t")

        print("-" * 80)
        print()

    async def chromium_casting(s: ChromeSession) -> None:
        # Chromium only
        if browser not in ("chrome", "edge", "chromium"):
            return None

        print(" Chromium Casting Commands ".center(80, "-"))
        print("Load 'www.baidu.com'")
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)

        print("cast_sinks:", await s.cast_sinks)
        print("cast_issue:", await s.cast_issue)
        print("set_cast_sink:", await s.set_cast_sink("local"))
        # print("start_casting:", await s.start_casting("local"))
        # print("stop_casting:", await s.stop_casting("local"))

        print("-" * 80)
        print()

    async def chromium_cdp_cmds(s: ChromeSession) -> None:
        # Chromium only
        if browser not in ("chrome", "edge", "chromium"):
            return None

        print(" Chromium DevTools Protocol Commands ".center(80, "-"))
        print("Load 'www.baidu.com'")
        await s.load("https://www.baidu.com/", timeout=FORCE_TIMEOUT, retry=10)

        cmd1 = "Browser.getVersion"
        cmd2 = "Runtime.evaluate"

        cmds = s.cdp_cmds
        print("cdp_cmds:", len(cmds) == 0, cmds, sep="\t")
        c1 = s.cache_cdp_cmd("get_version", cmd1)
        print("cache_cdp_cmd:", c1.name == "get_version", c1, sep="\t")
        res = s.remove_cdp_cmd("get_version")
        print("remove_cdp_cmd:", res is True and not s.cdp_cmds, res, sep="\t")
        c1 = s.cache_cdp_cmd("get_version", cmd1)
        print("cache_cdp_cmd:", c1.name == "get_version", c1, sep="\t")
        res = s.remove_cdp_cmd(c1)
        print("remove_cdp_cmd:", res is True and not s.cdp_cmds, res, sep="\t")
        print()

        c1 = s.cache_cdp_cmd("get_version_2", cmd1)
        print("cache_cdp_cmd:", c1.name == "get_version_2", c1, sep="\t")
        c1 = s.rename_cdp_cmd("get_version_2", "get_version_1")
        print("rename_cdp_cmd:", c1.name == "get_version_1", c1, sep="\t")
        c1 = s.rename_cdp_cmd(c1, "get_version")
        print("rename_cdp_cmd:", c1.name == "get_version", c1, sep="\t")
        cmds = s.cdp_cmds
        print("cdp_cmds:", len(cmds) == 1, cmds, sep="\t")
        c2 = s.cache_cdp_cmd("get_url", cmd2, expression="window.location.href")
        print("cache_cdp_cmd:", c2.name == "get_url", c2, sep="\t")
        print()

        c1 = s.get_cdp_cmd("get_version")
        print("get_cdp_cmd:", c1.name == "get_version", c1, sep="\t")
        c1 = s.get_cdp_cmd(c1)
        print("get_cdp_cmd:", c1.name == "get_version", c1, sep="\t")
        c2 = s.get_cdp_cmd("random_name")
        print("get_cdp_cmd:", c2 is None, c2, sep="\t")
        c2 = s.get_cdp_cmd("get_url")
        print("get_cdp_cmd:", c2.name == "get_url", c2, sep="\t")
        print()

        # fmt: off
        res = await s.execute_cdp_cmd(cmd1)
        print("execute_cdp_cmd [nill kwargs] (code):]\t", bool(res), str(res)[:50], sep="\t")
        res = await s.execute_cdp_cmd("get_version")
        print("execute_cdp_cmd [nill kwargs] (cached name):", bool(res), str(res)[:50], sep="\t")
        res = await s.execute_cdp_cmd(c1)
        print("execute_cdp_cmd [nill kwargs] (cached inst):", bool(res), str(res)[:50], sep="\t")
        # fmt: on
        print()

        res = await s.execute_cdp_cmd(cmd2, expression="window.location.href")
        print("execute_cdp_cmd [with kwargs] (code):]\t", bool(res), res, sep="\t")
        res = await s.execute_cdp_cmd("get_url")
        print("execute_cdp_cmd [cache kwargs] (cached name):", bool(res), res, sep="\t")
        res = await s.execute_cdp_cmd("get_url", expression="window.title")
        print("execute_cdp_cmd [new kwargs] (cached name):", bool(res), res, sep="\t")
        res = await s.execute_cdp_cmd(c2)
        print("execute_cdp_cmd [cache kwargs] (cached inst):", bool(res), res, sep="\t")
        res = await s.execute_cdp_cmd(c2, expression="window.title")
        print("execute_cdp_cmd [new kwargs] (cached inst):", bool(res), res, sep="\t")

        print("-" * 80)
        print()

    async def logs(s: ChromeSession) -> None:
        # Chromium only
        if browser not in ("chrome", "edge", "chromium"):
            return None
        print(" Logs Commands ".center(80, "-"))
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)
        print("logs:", await s.log_types)
        print("get_logs:", await s.get_logs("browser"))
        print("get_logs:", await s.get_logs("driver"))
        print("get_logs:", await s.get_logs("apple"))
        print("-" * 80)
        print()

    async def firefox_context(s: FirefoxSession) -> None:
        # Firefox only
        if browser != "firefox":
            return None

        print(" Firefox Context Commands ".center(80, "-"))
        print("Load 'www.baidu.com'")
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)

        res = await s.context
        print("context\t", res == "content", res, sep="\t")
        res = await s.set_context("chrome")
        print("set_context", res == "chrome", res, sep="\t")
        res = await s.reset_context()
        print("reset_context", res == "content", res, sep="\t")

        print("-" * 80)
        print()

    async def firefox_addon(s: FirefoxSession) -> None:
        # Firefox only
        if browser != "firefox":
            return None

        print(" Firefox Addon Commands ".center(80, "-"))
        print("Load 'www.baidu.com'")
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=10)

        addons = [
            os.path.join(TEST_FOLDER, file)
            for file in os.listdir(TEST_FOLDER)
            if file.endswith("xpi")
        ]
        await s.install_addons(*addons)
        print("install_addons:\t", len(s.addons) == 2, s.addons, sep="\t")
        await asyncio.sleep(5)

        await s.uninstall_addon(s.addons[0].id)
        print("uninstall_addon:", len(s.addons) == 1, s.addons, sep="\t")

        await s.uninstall_addon(s.addons[0])
        print("uninstall_addon:", not s.addons, s.addons, sep="\t")
        await asyncio.sleep(5)
        print("-" * 80)
        print()

    # fmt: off
    if browser == "chrome":
        driver = Chrome()
    elif browser == "chromium":
        if SYSTEM == "Linux":
            return None
        driver = Chromium()
    elif browser == "edge":
        driver = Edge()
    elif browser == "firefox":
        driver = Firefox()
    elif browser == "safari" and SYSTEM == "Darwin":
        driver = Safari()
    else:
        return None
    # fmt: on
    driver.options.session_timeout = 120
    driver.options.set_timeouts(implicit=2, pageLoad=20)
    if browser in ("chrome", "chromium", "edge"):
        driver.options.add_experimental_options(
            excludeSwitches=["enable-automation", "enable-logging"]
        )
    driver.options.add_arguments("--disable-gpu", "--disable-dev-shm-usage")
    FORCE_TIMEOUT = 30
    if SYSTEM == "Darwin":
        CONTROL_KEY = KeyboardKeys.COMMAND
    else:
        CONTROL_KEY = KeyboardKeys.CONTROL

    async with driver.acquire() as s:
        # Base info
        await session_info(s)

        # Navigate commands
        await navigate(s)
        # Info commands
        await information(s)
        # Timeout commands
        await timeouts(s)
        # Cookie commands
        await cookies(s)
        # Window commands
        await window(s)
        # Scroll commands
        await scroll(s)
        # Alert commands
        await alert(s)
        # Frame commands
        await frame(s)
        # Element commands
        await element(s)
        # Shadow commands
        await shadow(s)
        # Javascript commands
        await javascript(s)
        # Action commands
        await actions(s)
        # Permission commands
        await permission(s)
        # Network commands
        await network(s)
        # Casting commands
        await chromium_casting(s)
        # DevTools commands
        await chromium_cdp_cmds(s)
        # Logs commands
        await logs(s)
        # Firefox context commands
        await firefox_context(s)
        # Firefox addon commands
        await firefox_addon(s)

        # Ended
        await asyncio.sleep(5)


if __name__ == "__main__":
    ABS_PATH = os.path.abspath(os.path.dirname(__file__))
    TEST_FOLDER = os.path.join(ABS_PATH, "test_files")
    PROXY_SERVER = "127.0.0.1:7898"

    asyncio.run(test_driver_manager("chrome"))
    asyncio.run(test_driver_manager("chromium"))
    asyncio.run(test_driver_manager("edge"))
    asyncio.run(test_driver_manager("firefox"))
    asyncio.run(test_driver_manager("safari"))

    asyncio.run(test_driver_options("chrome"))
    asyncio.run(test_driver_options("chromium"))
    asyncio.run(test_driver_options("edge"))
    asyncio.run(test_driver_options("firefox"))
    asyncio.run(test_driver_options("safari"))

    asyncio.run(test_driver_profile("chrome"))
    asyncio.run(test_driver_profile("chromium"))
    asyncio.run(test_driver_profile("edge"))
    asyncio.run(test_driver_profile("firefox"))

    asyncio.run(test_driver_cancellation("chrome"))
    asyncio.run(test_driver_cancellation("chromium"))
    asyncio.run(test_driver_cancellation("edge"))
    asyncio.run(test_driver_cancellation("firefox"))
    asyncio.run(test_driver_cancellation("safari"))

    asyncio.run(test_driver_automation("chrome"))
    asyncio.run(test_driver_automation("chromium"))
    asyncio.run(test_driver_automation("edge"))
    asyncio.run(test_driver_automation("firefox"))
    asyncio.run(test_driver_automation("safari"))
