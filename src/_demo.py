import asyncio
from aselenium import ChromiumBaseWebDriver, ChromiumBaseSession
from aselenium import Chrome, Edge, Chromium, KeyboardKeys, Session, Proxy


async def test_proxy() -> None:
    print()
    print(" Test Proxy ".center(80, "-"))
    print("DEFAULT Proxy:", Proxy(), "\n")
    print("AUTODETECT Proxy:", Proxy(auto_detect=True), "\n")
    print("PAC Proxy:", Proxy(True, pac_url="http://url_to_pac_server"), "\n")
    print(
        "MANUAL Proxy:",
        proxy := Proxy(
            True,
            pac_url="http://url_to_pac_server",
            ftp_proxy="ftp://ftp_proxy_server:port",
            http_proxy="http://http_proxy_server:port",
            https_proxy="https://https_proxy_server:port",
            socks_proxy="socks5://socks_proxy_server:port",
            socks_username="socks_username",
            socks_password="socks_password",
            no_proxy=["address1", "address2"],
        ),
        "\n",
    )
    proxy.socks_proxy = None
    print("MANUAL Proxy (changed)", proxy, "\n")
    proxy.auto_detect = True
    print("MANUAL Proxy (changed)", proxy, "\n")
    print("-" * 80)
    print()


async def test_edge_options() -> None:
    # Chrome options
    print()
    print(" Chrome Options ".center(80, "-"))
    driver = Edge(
        "/Users/jef/Downloads/msedgedriver-mac-arm64/msedgedriver",
    )
    # . browser version
    driver.options.browser_version = "119.0.2151.58"
    # . platform name
    driver.options.platform_name = "mac"
    # . accept Insecure Certs
    driver.options.accept_insecure_certs = True
    # . page Load Strategy
    driver.options.page_load_strategy = "eager"
    # . proxy
    proxy = Proxy(
        http_proxy="http://127.0.0.1:7890",
        https_proxy="http://127.0.0.1:7890",
        socks_proxy="socks5://127.0.0.1:7890",
    )
    driver.options.proxy = proxy
    # . timeout
    driver.options.set_timeouts(implicit=5, pageLoad=10)
    # . strict file interactability
    driver.options.strict_file_interactability = True
    # . prompt behavior
    driver.options.unhandled_prompt_behavior = "dismiss"
    driver.options.unhandled_prompt_behavior = "dismiss and notify"
    driver.options.unhandled_prompt_behavior = "accept"
    driver.options.unhandled_prompt_behavior = "accept and notify"
    driver.options.unhandled_prompt_behavior = "ignore"
    # . browser binary
    driver.options.binary_location = (
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
    )
    # . arguments
    driver.options.add_arguments("--disable-gpu", "--disable-dev-shm-usage")
    # . experimental options
    driver.options.add_experimental_options(excludeSwitches=["enable-automation"])
    # . webview
    # driver.options.use_webview = True
    # Final options
    print(driver.options)

    # Test driver
    async with driver.acquire() as s:
        await s.load("https://www.baidu.com")
        await s.load("https://whatismyipaddress.com/", retry=True)
        await asyncio.sleep(5)

    # Finished
    print("-" * 80)
    print()


async def test_chrome_options() -> None:
    # Chrome options
    print()
    print(" Chrome Options ".center(80, "-"))
    driver = Chrome(
        "/Users/jef/Downloads/chromedriver-mac-arm64/chromedriver",
    )
    # . browser version
    driver.options.browser_version = "119.0.6045.123"
    # . platform name
    driver.options.platform_name = "mac"
    # . accept Insecure Certs
    driver.options.accept_insecure_certs = True
    # . page Load Strategy
    driver.options.page_load_strategy = "eager"
    # . proxy
    proxy = Proxy(
        http_proxy="http://127.0.0.1:7890",
        https_proxy="http://127.0.0.1:7890",
        socks_proxy="socks5://127.0.0.1:7890",
    )
    driver.options.proxy = proxy
    # . timeout
    driver.options.set_timeouts(implicit=5, pageLoad=10)
    # . strict file interactability
    driver.options.strict_file_interactability = True
    # . prompt behavior
    driver.options.unhandled_prompt_behavior = "dismiss"
    driver.options.unhandled_prompt_behavior = "dismiss and notify"
    driver.options.unhandled_prompt_behavior = "accept"
    driver.options.unhandled_prompt_behavior = "accept and notify"
    driver.options.unhandled_prompt_behavior = "ignore"
    # . browser binary
    driver.options.binary_location = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )
    # . arguments
    driver.options.add_arguments("--disable-gpu", "--disable-dev-shm-usage")
    # . experimental options
    driver.options.add_experimental_options(excludeSwitches=["enable-automation"])
    # Final options
    print(driver.options)

    # Test driver
    async with driver.acquire() as s:
        await s.load("https://www.baidu.com")
        await s.load("https://whatismyipaddress.com/", retry=True)
        await asyncio.sleep(5)

    # Finished
    print("-" * 80)
    print()


async def test_chromium_options() -> None:
    # Chrome options
    print()
    print(" Chrome Options ".center(80, "-"))
    driver = Chromium(
        "/Users/jef/Downloads/chromiumdriver_mac64/chromedriver",
    )
    # . browser version
    driver.options.browser_version = "119.0.6045.123"
    # . platform name
    driver.options.platform_name = "mac"
    # . accept Insecure Certs
    driver.options.accept_insecure_certs = True
    # . page Load Strategy
    driver.options.page_load_strategy = "eager"
    # . proxy
    proxy = Proxy(
        http_proxy="http://127.0.0.1:7890",
        https_proxy="http://127.0.0.1:7890",
        socks_proxy="socks5://127.0.0.1:7890",
    )
    driver.options.proxy = proxy
    # . timeout
    driver.options.set_timeouts(implicit=5, pageLoad=10)
    # . strict file interactability
    driver.options.strict_file_interactability = True
    # . prompt behavior
    driver.options.unhandled_prompt_behavior = "dismiss"
    driver.options.unhandled_prompt_behavior = "dismiss and notify"
    driver.options.unhandled_prompt_behavior = "accept"
    driver.options.unhandled_prompt_behavior = "accept and notify"
    driver.options.unhandled_prompt_behavior = "ignore"
    # . browser binary
    driver.options.binary_location = (
        "/Applications/Chromium.app/Contents/MacOS/Chromium"
    )
    # . arguments
    driver.options.add_arguments("--disable-gpu", "--disable-dev-shm-usage")
    # . experimental options
    driver.options.add_experimental_options(excludeSwitches=["enable-automation"])
    # Final options
    print(driver.options)

    # Test driver
    async with driver.acquire() as s:
        await s.load("https://www.baidu.com")
        await s.load("https://whatismyipaddress.com/", retry=True)
        await asyncio.sleep(5)

    # Finished
    print("-" * 80)
    print()


async def test_cancellation() -> None:
    print()
    print(" Edge Cancellation ".center(80, "-"))
    task = asyncio.create_task(test_edge_options())
    await asyncio.sleep(2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        print("-" * 80)
        print("Cancelled Successfully")
    print("-" * 80)
    print()

    print()
    print(" Chrome Cancellation ".center(80, "-"))
    task = asyncio.create_task(test_chrome_options())
    await asyncio.sleep(2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        print("-" * 80)
        print("Cancelled Successfully")
    print("-" * 80)
    print()

    print()
    print(" Chromium Cancellation ".center(80, "-"))
    task = asyncio.create_task(test_chromium_options())
    await asyncio.sleep(2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        print("-" * 80)
        print("Cancelled Successfully")
    print("-" * 80)
    print()


async def test_driver(browser: str = "chrome") -> None:
    async def session_info(s: Session) -> None:
        print(" Session Info ".center(80, "-"))
        # fmt: off
        print("Session:", s)
        print("Service Port:", s.service.port)
        print("Session Url:", s.base_url)
        print("Timeouts:", await s.timeouts)
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        # fmt: on
        print("-" * 80)
        print()

    async def navigate(s: Session) -> None:
        print(" Navigate Commands ".center(80, "-"))
        # fmt: off
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("get: taobao:", await s.load("https://www.taobao.com", timeout=FORCE_TIMEOUT, retry=True))
        await asyncio.sleep(pause)
        print("backward:", await s.backward(timeout=FORCE_TIMEOUT))
        await asyncio.sleep(pause)
        print("forward:", await s.forward(timeout=FORCE_TIMEOUT))
        await asyncio.sleep(pause)
        print("backward:", await s.backward(timeout=FORCE_TIMEOUT))
        await asyncio.sleep(pause)
        print("refresh:", await s.refresh(timeout=FORCE_TIMEOUT, retry=True))
        await asyncio.sleep(pause)
        # fmt: on
        print("-" * 80)
        print()

    async def information(s: Session) -> None:
        print(" Information Commands ".center(80, "-"))
        # fmt: off
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("url:", x := await s.url, type(x))
        print("title:", x := await s.title, type(x))
        print("viewport:", x := await s.viewport, type(x))
        print("page_width:", x := await s.page_width, type(x))
        print("page_height:", x := await s.page_height, type(x))
        print("page_source:", x := await s.page_source, type(x))
        print("take_screenshot:", x := await s.take_screenshot(), type(x))
        # print("save_screenshot:", await s.save_screenshot(image))
        print("print_pdf:", await s.print_pdf())
        # print("save_pdf:", await s.save_pdf(image))
        # fmt: on
        print("-" * 80)
        print()

    async def timeouts(s: Session) -> None:
        print(" Timeout Commands ".center(80, "-"))
        # fmt: off
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("orig_timeouts", await s.timeouts)
        print("set_timeouts", await s.set_timeouts(implicit=0, pageLoad=300))
        print("set_timeouts", await s.set_timeouts(implicit=0.1, script=30))
        print("reset_timeouts", await s.reset_timeouts())
        # fmt: on
        print("-" * 80)
        print()

    async def cookies(s: Session) -> None:
        print(" Cookies Commands ".center(80, "-"))
        # fmt: off
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("cookies:", (cookies := await s.cookies))
        print("delete_cookies:", await s.delete_cookies())
        print("cookies:", await s.cookies)
        print()
        for cookie in cookies:
            print("add_cookie:", await s.add_cookie(cookie))
        print("cookies:", await s.cookies)
        print()
        cookie = await s.get_cookie("ZFY")
        cookie.name = "test"
        print("add_cookie:", await s.add_cookie(cookie))
        print("get_cookie:", await s.get_cookie(cookie))
        print("delete_cookie:", await s.delete_cookie("test"))
        print("get_cookie:", await s.get_cookie("test"))
        print("cookies:", await s.cookies)
        # fmt: on
        print("-" * 80)
        print()

    async def network(s: Session) -> None:
        print(" Network Commands ".center(80, "-"))
        # fmt: off
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("network:", await s.network)
        print("set_network:", await s.set_network(latency=10, upload_throughput=1000))
        print("reset_network:", await s.reset_network())
        # fmt: on
        print("-" * 80)
        print()

    async def permission(s: Session) -> None:
        print(" Permission Commands ".center(80, "-"))
        # fmt: off
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("permissions:", await s.permissions)
        print("get_permission:", await s.get_permission("camera"))
        print("set_permission:", await s.set_permission("camera", "denied"))
        print("set_permission:", await s.set_permission("camera", "granted"))
        print("set_permission:", await s.set_permission("camera", "prompt"))
        # fmt: on
        print("-" * 80)
        print()

    async def window(s: Session) -> None:
        print(" Window Commands ".center(80, "-"))
        # fmt: off
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("new_window:", await s.new_window("new"))
        await asyncio.sleep(pause)
        print("all_windows:", await s.windows)
        await asyncio.sleep(pause)
        print("switch_window:", await s.switch_window("default"))
        await asyncio.sleep(pause)
        print("switch_window:", await s.switch_window("new"))
        await asyncio.sleep(pause)
        print("rename_window", await s.rename_window("new", "new2"))
        await asyncio.sleep(pause)
        print("all_windows:", await s.windows)
        await asyncio.sleep(pause)
        print("close_window:", await s.close_window())
        await asyncio.sleep(pause)
        print("all_windows:", await s.windows)
        await asyncio.sleep(pause)
        print("new_window:", await s.new_window("new"))
        await asyncio.sleep(pause)
        print("all_windows:", await s.windows)
        await asyncio.sleep(pause)
        print("window_rect", await s.window_rect)
        await asyncio.sleep(pause)
        print("maximize_window", await s.maximize_window())
        await asyncio.sleep(pause)
        print("minimize_window", await s.minimize_window())
        await asyncio.sleep(pause)
        print("fullscreen_window", await s.fullscreen_window())
        await asyncio.sleep(pause)
        print("set_window_rect", await s.set_window_rect(1200, 900, 0, 0))
        await asyncio.sleep(pause)
        print("close_window:", await s.close_window())
        await asyncio.sleep(pause)
        print("all_windows:", await s.windows)
        await asyncio.sleep(pause)
        print("new_window:", await s.new_window("new1"))
        await asyncio.sleep(pause)
        print("new_window:", await s.new_window("new2"))
        await asyncio.sleep(pause)
        print("close_window:", await s.close_window("new1"))
        await asyncio.sleep(pause)
        print("close_window:", await s.close_window())
        print("close_window:", await s.close_window())
        print("close_window:", await s.close_window())
        await asyncio.sleep(pause)
        print("all_windows:", await s.windows)
        await asyncio.sleep(pause)
        print("new_window:", await s.new_window("new1"))
        await asyncio.sleep(pause)
        print("all_windows:", await s.windows)
        await asyncio.sleep(pause)
        # fmt: on
        print("-" * 80)
        print()

    async def scroll(s: Session) -> None:
        print(" Scroll Commands ".center(80, "-"))
        # fmt: off
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        rect = await s.window_rect
        await s.set_window_rect(800, 3000, 0, 0)
        print("scroll_to", await s.scroll_to(1000, 0))
        print("scroll_to_left", await s.scroll_to_left(60, by="pixels"))
        print("scroll_to_right", await s.scroll_to_right(6))
        el1 = await s.find_element("#kw", by="css")  # search input box
        await el1.send("Hello world!", pause=0.5)
        await s.actions().key_down(KeyboardKeys.ENTER).key_up(KeyboardKeys.ENTER).perform()
        await asyncio.sleep(1)
        print("scroll_by", await s.scroll_by(0, 300, pause))
        print("scroll_to", await s.scroll_to(0, 3000, pause))
        print("scroll_to_top", await s.scroll_to_top(500, "pixels"))
        print("scroll_to_bottom", await s.scroll_to_bottom(5, "steps"))
        print("scroll_into_view", await s.scroll_into_view(el1))
        print("scroll_into_view", await s.scroll_into_view("#tsn_inner", "css"))
        await s.set_window_rect(width=rect.width, height=rect.height, x=rect.x, y=rect.y)
        # fmt: on
        print("-" * 80)
        print()

    async def alert(s: Session) -> None:
        print(" Alert Commands ".center(80, "-"))
        # fmt: off
        await s.load("https://demo.guru99.com/test/delete_customer.php", timeout=FORCE_TIMEOUT, retry=True)
        print("alert:", (al := await s.alert))
        el1 = await s.find_element("input[name='cusid']")
        await el1.send("123456")
        el2 = await s.find_element("input[name='submit']")
        await el2.click()
        print("alert:", (al := await s.alert))
        print("alert.text:", await al.text)
        # await asyncio.sleep(1)
        print("alert.dismiss:", await al.dismiss(pause=0.5))
        await el2.click()
        print("alert:", (al := await s.alert))
        print("alert.text:", await al.text)
        # await asyncio.sleep(1)
        print("alert.accept:", await al.accept(pause=0.5))
        print("alert:", (al := await s.alert))
        print("alert.text:", await al.text)
        # await asyncio.sleep(1)
        print("alert.accept:", await al.accept(pause=0.5))
        # fmt: on
        print("-" * 80)
        print()

    async def frame(s: Session) -> None:
        print(" Frame Commands ".center(80, "-"))
        # fmt: off
        await s.load("https://web.dev/shadowdom-v1/", timeout=FORCE_TIMEOUT, retry=True)
        # . switch by element
        css = "figure.demoarea > iframe"
        el = await s.find_element(css)
        if el is not None:
            print("switch_frame (by element):", await s.switch_frame(el))
            print("varify: ", (await (await s.find_element("body")).text).replace("\n", " ")[:30])
            print("default_frame:", await s.default_frame())
            print("default_frame:", await s.default_frame())
            print("varify: ", (await (await s.find_element("body")).text).replace("\n", " ")[:30])
            print()

            # . switch by element locator
            print("switch_frame (by locator):", await s.switch_frame(css))
            print("varify: ", (await (await s.find_element("body")).text).replace("\n", " ")[:30])
            print("parent_frame:", await s.parent_frame())
            print("parent_frame:", await s.parent_frame())
            print("varify: ", (await (await s.find_element("body")).text).replace("\n", " ")[:30])
            print()

            # . switch by index
            print("switch_frame (by index):", await s.switch_frame(0, by="index"))
            print("varify: ", (await (await s.find_element("body")).text).replace("\n", " ")[:30])
            print("default_frame:", await s.default_frame())
            print("varify: ", (await (await s.find_element("body")).text).replace("\n", " ")[:30])
            print()
        else:
            print("Test webpage not loaded properly")
        # fmt: on
        print("-" * 80)
        print()

    async def element(s: Session) -> None:
        print(" Element Commands ".center(80, "-"))
        # fmt: off
        css1, css2, css3, css4 = "#kw", "#kw1", "#su", "#su1"
        xpath1, xpath2 = ".//input[@id='kw']", ".//input[@id='kw1']"
        xpath3, xpath4 = ".//input[@id='su']", ".//input[@id='su1']"
        csss1, csss2 = [css1, css3], [css2, css4]
        csss3, csss4 = [css1, "span.soutu-btn"], [css2, "span.soutu-btn1"]
        xps1, xps2 = [xpath1, xpath3], [xpath2, xpath4]
        xps3 = [xpath1, ".//span[@class='soutu-btn']"]
        xps4 = [xpath2, ".//span[@class='soutu-btn1']"]
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("active_el", await s.active_element)
        print("find_el_css:", await s.find_element(css1, by="css"))
        print("find_els_css:", await s.find_elements(css3, by="css"))
        print("find_el_xp:", await s.find_element(xpath1, by="xpath"))
        print("find_els_xp:", await s.find_elements(xpath3, by="xpath"))
        print("find_1st_el_css:", await s.find_1st_element(css1, css2, by="css"))
        print("find_1st_el_xp:", await s.find_1st_element(xpath1, xpath2, by="xpath"))
        print()

        print("el_ext_css:", await s.exists_element(css1, by="css"))
        print("el_ext_css:", await s.exists_element(css2, by="css"))
        print("el_ext_xp:", await s.exists_element(xpath1, by="xpath"))
        print("el_ext_xp:", await s.exists_element(xpath2, by="xpath"))
        print("el_exts_css:", await s.exist_elements(*csss3, by="css"))
        print("el_exts_css:", await s.exist_elements(*csss4, by="css"))
        print("el_exts_xp:", await s.exist_elements(*xps3, by="xpath"))
        print("el_exts_xp:", await s.exist_elements(*xps4, by="xpath"))
        print("el_exts_css_f:", await s.exist_elements(*csss1, by="css", all_=False))
        print("el_exts_css_f:", await s.exist_elements(*csss2, by="css", all_=False))
        print("el_exts_xp_f:", await s.exist_elements(*xps1, by="xpath", all_=False))
        print("el_exts_xp_f:", await s.exist_elements(*xps2, by="xpath", all_=False))
        print("wf_el_gone_css:", await s.wait_element_gone(css1, by="css", timeout=1))
        print("wf_el_gone_css:", await s.wait_element_gone(css2, by="css", timeout=1))
        print("wf_el_gone_xp:", await s.wait_element_gone(xpath1, by="xpath", timeout=1))
        print("wf_el_gone_xp:", await s.wait_element_gone(xpath2, by="xpath", timeout=1))
        print("wf_els_gone_css:", await s.wait_elements_gone(*csss1, by="css", timeout=1))
        print("wf_els_gone_css:", await s.wait_elements_gone(*csss2, by="css", timeout=1))
        print("wf_els_gone_xp:", await s.wait_elements_gone(*xps1, by="xpath", timeout=1))
        print("wf_els_gone_xp:", await s.wait_elements_gone(*xps2, by="xpath", timeout=1))
        print("wf_gone_css:", await s.wait_elements_gone(*csss1, by="css", all_=False, timeout=1))
        print("wf_gone_css:", await s.wait_elements_gone(*csss2, by="css", all_=False, timeout=1))
        print("wf_gone_xp:", await s.wait_elements_gone(*xps1, by="xpath", all_=False, timeout=1))
        print("wf_gone_xp:", await s.wait_elements_gone(*xps2, by="xpath", all_=False, timeout=1))

        el0 = await s.find_element("span.bg.s_ipt_wr", by="css")
        print("el.el_ext_css:", await el0.exists_element(css1, by="css"), "<-:", el0)
        print("el.el_ext_css:", await el0.exists_element(css2, by="css"), "<-:", el0)
        print("el.el_ext_css:", await el0.exists_element(css3, by="css"), "<-:", el0)
        print("el.el_ext_css:", await el0.exists_element(css4, by="css"), "<-:", el0)
        print("el.el_ext_xp:", await el0.exists_element(xpath1, by="xpath"), "<-:", el0)
        print("el.el_ext_xp:", await el0.exists_element(xpath2, by="xpath"), "<-:", el0)
        print("el.el_ext_xp:", await el0.exists_element(xpath3, by="xpath"), "<-:", el0)
        print("el.el_ext_xp:", await el0.exists_element(xpath4, by="xpath"), "<-:", el0)
        print("el.el_exs_css:", await el0.exist_elements(*csss3, by="css"), "<-:", el0)
        print("el.el_exs_css:", await el0.exist_elements(*csss4, by="css"), "<-:", el0)
        print("el.el_exs_xp:", await el0.exist_elements(*xps3, by="xpath"), "<-:", el0)
        print("el.el_exs_xp:", await el0.exist_elements(*xps4, by="xpath"), "<-:", el0)
        val = await el0.exist_elements(*csss1, by="css", all_=False)
        print("el.el_exs_css:", val, "<-:", el0)
        val = await el0.exist_elements(*csss2, by="css", all_=False)
        print("el.el_exs_css:", val, "<-:", el0)
        val = await el0.exist_elements(*xps3, by="xpath", all_=False)
        print("el.el_exs_xp:", val, "<-:", el0)
        val = await el0.exist_elements(*xps4, by="xpath", all_=False)
        print("el.el_exs_xp:", val, "<-:", el0)
        print("el.wgc:", await el0.wait_element_gone(css1, by="css", timeout=1), "<-:", el0)
        print("el.wgc:", await el0.wait_element_gone(css2, by="css", timeout=1), "<-:", el0)
        print("el.wgc:", await el0.wait_element_gone(css3, by="css", timeout=1), "<-:", el0)
        print("el.wgc:", await el0.wait_element_gone(css4, by="css", timeout=1), "<-:", el0)
        print("el.wgx:", await el0.wait_element_gone(xpath1, by="xpath", timeout=1), "<-:", el0)
        print("el.wgx:", await el0.wait_element_gone(xpath2, by="xpath", timeout=1), "<-:", el0)
        print("el.wgx:", await el0.wait_element_gone(xpath3, by="xpath", timeout=1), "<-:", el0)
        print("el.wgx:", await el0.wait_element_gone(xpath4, by="xpath", timeout=1), "<-:", el0)
        print("el.wgsc:", await el0.wait_elements_gone(*csss1, by="css", timeout=1), "<-:", el0)
        print("el.wgsc:", await el0.wait_elements_gone(*csss2, by="css", timeout=1), "<-:", el0)
        print("el.wgsx:", await el0.wait_elements_gone(*xps1, by="xpath", timeout=1), "<-:", el0)
        print("el.wgsx:", await el0.wait_elements_gone(*xps2, by="xpath", timeout=1), "<-:", el0)
        print("el.wgsc_f:", val := await el0.wait_elements_gone(*csss1, by="css", timeout=1), "<-:", el0)
        print("el.wgsc_f:", val := await el0.wait_elements_gone(*csss2, by="css", timeout=1), "<-:", el0)
        print("el.wgsx_f:", val := await el0.wait_elements_gone(*xps1, by="xpath", timeout=1), "<-:", el0)
        print("el.wgsx_f:", val := await el0.wait_elements_gone(*xps2, by="xpath", timeout=1), "<-:", el0)
        print("el.find_1st_el_css:", val := await el0.find_1st_element(css3, css1, by="css"), "<-:", el0)
        print("el.find_1st_el_xp:", val := await el0.find_1st_element(xpath3, xpath1, by="xpath"), "<-:", el0)

        el1 = await s.find_element("a[href='http://image.baidu.com/']", by="css")
        print("el.tag:", await el1.tag, "<-:", el1)
        print("el.text:", await el1.text, "<-:", el1)
        print("el.rect:", await el1.rect, "<-:", el1)

        el2 = await s.find_element("div.title-text.c-color-t", by="css")
        print("el.aria_role:", await el2.aria_role, "<-:", el2)
        print("el.aria_label:", await el2.aria_label, "<-:", el2)
        print("el.properties:", await el2.properties, "<-:", el2)
        print("el.get_property:", await el2.get_property("clientHeight"), "<-:", el2)
        print("el.css_properties:", await el2.properties_css, "<-:", el2)
        print("el.get_css_property:", await el2.get_property_css("cursor"), "<-:", el2)
        print("el.attributes:", await el2.attributes, "<-:", el2)
        print("el.get_attribute_dom:", await el2.get_attribute_dom("class"), "<-:", el2)

        el3 = await s.find_element(css3, by="css")
        print("el.take_screenshot", await el3.take_screenshot(), "<-:", el3)
        # print("el.save_screenshot", await el3.save_screenshot(image), "<-:", el3)

        el4 = await s.find_element("#form", by="css")
        xpath = xpath3
        print("el.find_el_css:", await el4.find_element(css3, by="css"), "<-:", el4)
        print("el.find_el_xp:", await el4.find_element(xpath, by="xpath"), "<-:", el4)
        print("el.find_els_css:", await el4.find_elements(css3, by="css"), "<-:", el4)
        print("el.find_els_xp:", await el4.find_elements(xpath, by="xpath"), "<-:", el4)

        # Control
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        el1 = await s.find_element(css1, by="css")
        print("el.visible:", await el1.visible, "<-:", el1)
        print("el.viewable:", await el1.viewable, "<-:", el1)
        print("el.enabled:", await el1.enabled, "<-:", el1)
        print("el.selected:", await el1.selected, "<-:", el1)
        print("el.click:", await el1.click(pause=0.5), "<-:", el1)
        el_c = await s.find_element("i.quickdelete-line")
        print("el.get_attr:", await el_c.get_attribute_dom("style"), "<-:", el_c)
        print("el.get_attr_dom:", await el_c.get_attribute_dom("style"), "<-:", el_c)
        print()

        print("el.sent_text:", await el1.send("Hello world!", pause=0.5), "<-:", el1)
        el_c = await s.find_element("i.quickdelete-line")
        print("el.get_attr:", await el_c.get_attribute_dom("style"), "<-:", el_c)
        print("el.get_attr_dom:", await el_c.get_attribute_dom("style"), "<-:", el_c)
        print()

        print("el.sent_ctla:", await el1.send(KeyboardKeys.COMMAND, "a", pause=0.5), "<-:", el1)
        print("el.sent_ctlc:", await el1.send(KeyboardKeys.COMMAND, "c", pause=0.5), "<-:", el1)
        print("el.sent_del:", await el1.send(KeyboardKeys.DELETE, pause=0.5), "<-:", el1)
        print("el.sent_ctlv:", await el1.send(KeyboardKeys.COMMAND, "v", pause=0.5), "<-:", el1)
        print("el.sent_ent:", await el1.send(KeyboardKeys.ENTER, pause=0.5), "<-:", el1)
        try:
            print("el.clear:", await el1.clear(pause=0.5), "<-:", el1)
        except Exception:
            pass
        el2 = await s.find_element("#help", by="css")
        print("el.scroll_into_view", await el2.scroll_into_view(), "<-:", el2)
        print()

        # Upload
        await s.load("https://image.baidu.com/", timeout=FORCE_TIMEOUT, retry=True)
        el1 = await s.find_element("#stcontent > a.sttb")
        print("el.click:", await el1.click(pause=0.5), "<-:", el1)
        el2 = await s.find_element("#stfile")
        path = "/Users/jef/Pwork/Github_Repo/Simple_Toolbox/src/captcha-test.png"
        print("el.upload:", await el2.upload(path, pause=1), "<-:", el2)
        # fmt: on
        print("-" * 80)
        print()

    async def shadow(s: Session) -> None:
        print(" Shadow Commands ".center(80, "-"))
        # fmt: off
        await s.load("https://www.htmlelements.com/demos/menu/shadow-dom/index.htm", timeout=FORCE_TIMEOUT, retry=True)
        el0 = await s.find_element("smart-ui-menu.smart-ui-component", by="css")
        while el0 is None:
            el0 = await s.find_element("smart-ui-menu.smart-ui-component", by="css")
        print("el.shadow:", (sh := await el0.shadow), "<-:", el0)
        css1 = "div[smart-id='container']"
        css2 = "div[smart-id='containe']"
        css3 = "div[smart-id='container'] > div.smart-header"
        css4 = "div[smart-id='container'] > div.smart-heade"
        csss1 = [css1, css3]
        csss2 = [css2, css4]
        csss3 = [css1, css2]
        csss4 = [css3, css4]
        csss5 = [css1, css2, css3, css4]
        print("sh.ext_el:", await sh.exists_element(css1), "<-:", sh)
        print("sh.ext_el:", await sh.exists_element(css2), "<-:", sh)
        print("sh.ext_el:", await sh.exists_element(css3), "<-:", sh)
        print("sh.ext_el:", await sh.exists_element(css4), "<-:", sh)
        print("sh.ext_els_t:", await sh.exist_elements(*csss1), "<-:", sh)
        print("sh.ext_els_f:", await sh.exist_elements(*csss2), "<-:", sh)
        print("sh.ext_els_f:", await sh.exist_elements(*csss3), "<-:", sh)
        print("sh.ext_els_f:", await sh.exist_elements(*csss4), "<-:", sh)
        print("sh.ext_els_f:", await sh.exist_elements(*csss5), "<-:", sh)
        print("sh.ext_els_f:", await sh.exist_elements(*csss5, all_=False), "<-:", sh)
        print("sh.find_el:", await sh.find_element(css1), "<-:", sh)
        print("sh.find_el:", await sh.find_element(css3), "<-:", sh)
        print("sh.find_els:", await sh.find_elements(css1), "<-:", sh)
        print("sh.find_els:", await sh.find_elements(css3), "<-:", sh)
        print("sh.find_1st_el:", await sh.find_1st_element(*csss5), "<-:", sh)
        print("sh.w_elg:", await sh.wait_element_gone(css1, timeout=1), "<-:", sh)
        print("sh.w_elg:", await sh.wait_element_gone(css2, timeout=1), "<-:", sh)
        print("sh.w_elsg:", await sh.wait_elements_gone(*csss5, timeout=1), "<-:", sh)
        print("sh.w_elsg:", await sh.wait_elements_gone(*csss5, timeout=1, all_=False), "<-:", sh)
        # fmt: on
        print("-" * 80)
        print()

    async def javascript(s: Session) -> None:
        print(" Javascript Commands ".center(80, "-"))
        # fmt: off
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("scripts:", s.scripts)
        print("cache_script:", s.cache_script("get_title", "return document.title;"))
        print("scripts:", s.scripts)
        print("remove_script:", s.remove_script("get_title"))
        print("scripts:", s.scripts)
        print("cache_script:", s.cache_script("get_title_x", "return document.title;"))
        print("rename_script:", s.rename_script("get_title_x", "get_title"))
        print("scripts:", s.scripts)
        print("cache_script (args):", s.cache_script("get_args", "return arguments[0];", "Hello world! cached"))
        print("get_script:", s.get_script("get_title"))
        print("scripts:", s.scripts)
        print()

        print("execute_script (raw):", await s.execute_script("return document.title;"))
        print("execute_script (cached name):", await s.execute_script("get_title"))
        print("execute_script (cached instance):", await s.execute_script(s.get_script("get_title")))
        print("execute_script (raw args):", await s.execute_script("return arguments[0];", "Hello world!"))
        print("execute_script (cached args):", await s.execute_script("get_args"))
        print("execute_script (overwrite args):", await s.execute_script("get_args", "Hello world! overwrite"))
        # fmt: on
        print("-" * 80)
        print()

    async def actions(s: Session) -> None:
        print(" Actions Commands ".center(80, "-"))
        # fmt: off

        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("image button:", el1 := await s.find_element("span.soutu-btn"))
        print("image button rect:", rect1 := await el1.rect)
        print("move_to (x, y) & click", await s.actions().move_to(x=rect1.x, y=rect1.y, pause=0.5).click().perform())
        print("search button:", el2 := await s.find_element("#su"))
        print("search button rect:", rect2 := await el2.rect)
        print("move_to (x, y) & click", await s.actions().move_to(x=rect2.x, y=rect2.y, pause=0.5).click().perform())
        await asyncio.sleep(1)
        print()

        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("image button:", el1 := await s.find_element("span.soutu-btn"))
        print("move_to (element)", await s.actions().move_to(element=el1, pause=0.5).click().perform())
        print("search button:", el2 := await s.find_element("#su"))
        print("move_to (element)", await s.actions().move_to(element=el2, pause=0.5).click().perform())
        await asyncio.sleep(1)
        print()

        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("image button:", el1 := await s.find_element("span.soutu-btn"))
        print("image button rect:", rect1 := await el1.rect)
        print("move_to (element) offset on target", 
              await s.actions().move_to(el1, rect1.width / 2 - 1, rect1.height / 2 - 1, pause=0.5)
              .click().perform())
        await asyncio.sleep(1)
        print()

        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("image button:", el1 := await s.find_element("span.soutu-btn"))
        print("image button rect:", rect1 := await el1.rect)
        print("move_to (element) offset off target", 
              await s.actions().move_to(el1, rect1.width / 2, rect1.height / 2, pause=0.5)
              .click().perform())
        await asyncio.sleep(1)
        print()

        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("image button:", el1 := await s.find_element("span.soutu-btn"))
        print("image button rect:", rect1 := await el1.rect)
        print("move_by (x, y)", 
              await s.actions().move_to(0, 0).move_by(x=rect1.x, y=rect1.y, pause=0.5)
              .click().perform())
        print("search button:", el2 := await s.find_element("#su"))
        print("search button rect:", rect2 := await el2.rect)
        print("move_by (x, y)",
                await s.actions().move_by(rect2.x - rect1.x, pause=0.5)
                .click().perform())
        await asyncio.sleep(1)
        print()
        
        await s.load("https://www.w3schools.com/html/html5_draganddrop.asp", timeout=FORCE_TIMEOUT, retry=True)
        print("left element:", el1 := await s.find_element("#div1"))
        print("right element:", el2 := await s.find_element("#div2"))
        print("drag & drop (left to right):", 
              await s.actions().drop_and_drop(src_element=el1, dst_element=el2, pause=1).perform())
        print("drag & drop (right to left):", 
              await s.actions().drop_and_drop(src_element=el2, dst_element=el1, pause=1).perform())
        await asyncio.sleep(1)
        print()

        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("search input:", el1 := await s.find_element("#kw"))
        print("keys_combo:", 
              await s.actions().move_to(element=el1).click().send_keys("hellow world!", pause=1)
              .key_down(KeyboardKeys.COMMAND).key_down("a")
              .key_up("a").key_up(KeyboardKeys.COMMAND, pause=1)
              .send_keys(KeyboardKeys.DELETE, pause=0.5)
              .send_keys("Hello World!", KeyboardKeys.ENTER)
              .perform())
        await asyncio.sleep(1)
        print()

        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("search input:", el1 := await s.find_element("#kw"))
        print("keys_combo:", 
              await s.actions().move_to(element=el1).click()
              .send_keys("hellow world!", KeyboardKeys.ENTER, pause=1).perform())
        print(el1 := await s.find_element("#help"))
        print("scroll_to (element)", await s.actions().scroll_to(el1).perform())
        await asyncio.sleep(1)
        print("scroll_to (element) offset", await s.actions().scroll_to(el1, y=-500).perform())
        await asyncio.sleep(1)
        print("scroll_by", await s.actions().scroll_by(y=500).perform())
        await asyncio.sleep(1)
        print("scroll_by", await s.actions().scroll_by(y=-500).perform())
        await asyncio.sleep(1)
        # fmt: on
        print("-" * 80)
        print()

    async def logs(s: Session) -> None:
        print(" Logs Commands ".center(80, "-"))
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("logs:", await s.log_types)
        print("get_logs:", await s.get_logs("browser"))
        print("get_logs:", await s.get_logs("driver"))
        print("get_logs:", await s.get_logs("apple"))
        print("-" * 80)
        print()

    async def chromium_casting(s: ChromiumBaseSession) -> None:
        print(" Chromium Casting Commands ".center(80, "-"))
        # fmt: off
        await s.load("https://www.baidu.com", timeout=FORCE_TIMEOUT, retry=True)
        print("cast_sinks:", await s.cast_sinks)
        print("cast_issue:", await s.cast_issue)
        print("set_cast_sink:", await s.set_cast_sink("local"))
        # print("start_casting:", await s.start_casting("local"))
        # print("stop_casting:", await s.stop_casting("local"))
        # fmt: on
        print("-" * 80)
        print()

    async def chromium_cdp_cmds(s: ChromiumBaseSession) -> None:
        print(" Chromium DevTools Protocol Commands ".center(80, "-"))
        # fmt: off
        await s.load("https://www.baidu.com/", timeout=FORCE_TIMEOUT, retry=True)
        print("cdp_cmds:", s.cdp_cmds)
        print("cache_cdp_cmd:", s.cache_cdp_cmd("get_v", "Browser.getVersion"))
        print("cdp_cmds:", s.cdp_cmds)
        print("remove_cdp_cmd:", s.remove_cdp_cmd("random"))
        print("cdp_cmds:", s.cdp_cmds)
        print("remove_cdp_cmd:", s.remove_cdp_cmd("get_v"))
        print("cdp_cmds:", s.cdp_cmds)
        print("cache_cdp_cmd:", s.cache_cdp_cmd("get_v", "Browser.getVersion"))
        print("cdp_cmds:", s.cdp_cmds)
        print("rename_cdp_cmd:", s.rename_cdp_cmd("get_v", "get_version"))
        print("cdp_cmds:", s.cdp_cmds)
        print("cache_cdp_cmd:", s.cache_cdp_cmd("get_url", "Runtime.evaluate", expression="window.location.href",))
        print("cdp_cmds:", s.cdp_cmds)
        print()

        print("execute_cdp_cmd (frin cmd line):", await s.execute_cdp_cmd("Browser.getVersion"))
        print("execute_cdp_cmd (from cache name):", await s.execute_cdp_cmd("get_version"))
        print("execute_cdp_cmd (from cache instance):", await s.execute_cdp_cmd(s.get_cdp_cmd("get_version")))
        print("execute_cdp_cmd (frin cmd line):", await s.execute_cdp_cmd("get_url"))
        # fmt: on
        print("-" * 80)
        print()

    # fmt: off
    if browser == "edge":
        driver = Edge("/Users/jef/Downloads/msedgedriver-mac-arm64/msedgedriver")
    elif browser == "chrome":
        driver = Chrome("/Users/jef/Downloads/chromedriver-mac-arm64/chromedriver")
    elif browser == "chromium":
        driver = Chromium("/Users/jef/Downloads/chromiumdriver_mac64/chromedriver")
    else:
        raise ValueError(f"Browser not supported: '{browser}'")
    # fmt: on
    driver.options.set_timeouts(implicit=10, pageLoad=20)
    driver.options.add_arguments("--disable-gpu", "--disable-dev-shm-usage")
    print(driver.options)
    FORCE_TIMEOUT = 30

    pause = 0.5
    image = "/Users/jef/Desktop/image"
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
        # Network commands
        await network(s)
        # Permission commands
        await permission(s)
        # Window commands
        await window(s)
        # Scroll commands
        await scroll(s)
        # Alert commands
        await alert(s)
        # Frame commands
        # await frame(s)
        # Element commands
        await element(s)
        # Shadow commands
        await shadow(s)
        # Javascript commands
        await javascript(s)
        # Action commands
        await actions(s)
        # Logs commands
        await logs(s)
        # Chromium special commands
        if isinstance(driver, ChromiumBaseWebDriver):
            # Casting commands
            await chromium_casting(s)
            # DevTools commands
            await chromium_cdp_cmds(s)

        # Ended
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(test_proxy())
    asyncio.run(test_edge_options())
    asyncio.run(test_chrome_options())
    asyncio.run(test_chromium_options())
    asyncio.run(test_cancellation())
    asyncio.run(test_driver("edge"))
    asyncio.run(test_driver("chrome"))
    asyncio.run(test_driver("chromium"))
