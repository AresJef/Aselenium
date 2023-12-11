## Asyncronous implementation of web browser automation for Python.

Created to be used in a project, this package is published to github for ease of management and installation across different modules.

### Features
- **Asynchronous Execution**: Aselenium is inspired by the [HENNGE/arsenic](https://github.com/HENNGE/arsenic) project, enabling multiple browser sessions to run concurrently. This allows Python to execute other async tasks without being blocked by time-consuming browser actions.

- **Webdriver Management**: Aselenium integrates the webdriver installation and management, taking inspiration from the [SergeyPirogov/webdriver_manager](https://github.com/SergeyPirogov/webdriver_manager) project. It provides a simple interface for user to install the proper/desired webdriver for different browsers cross platforms.

- **Browser Support**: Aselenium supports popular browsers such as Chrome, Chromium, Edge, Firefox, and Safari.

### Installation
Install from `PyPi`
``` bash
pip install aselenium
```

Install from `github`
``` bash
pip install git+https://github.com/AresJef/Aselenium.git
```

### Compatibility
Only support for python 3.10 and above.

### Chrome Automation
``` python
from aselenium import Chrome
driver = Chrome(
    # optional: the directory to store the webdrivers.
    directory="/path/to/driver/cache/directory"
    # optional: the maximum amount of webdrivers (and CTF browsers) to maintain.
    max_cache_size=10
)

# Set options
driver.options.add_arguments('--headless', '--disable-gpu')
...

# Acquire a chrome session
async with driver.acquire("build", "dev") as session
    # explain: install webdriver that has the same major & build
    # version as the Chrome [dev] browser installed in the system,
    # and start a new session with the dev browser.
    await session.load("https://www.google.com")
    # . do some automated tasks
    ...

# Acquire a CFT [Chrome for Testing] session
async with driver.acquire("119.0.6045", "cft") as session:
    # explain: install both the webdriver and CFT browser with the 
    # same build version '119.0.6045', and start a new session with 
    # the CFT browser.
    await session.load("https://www.google.com")
    # . do some automated tasks
    ...
```

### Edge Automation
``` python
from aselenium import Edge
driver = Edge()

# Set options
driver.options.add_arguments('--headless', '--disable-gpu')
...

# Acquire an edge session
async with driver.acquire("build", "stable") as session:
    # explain: install webdriver that has the same major & build
    # version as the Edge [stable] browser installed in the system,
    # and start a new session with the stable Edge browser.
    await session.load("https://www.google.com")
    # . do some automated tasks
    ...
```

### Firefox Automation
``` python
from aselenium import Firefox
driver = Firefox()

# Set options
driver.options.add_arguments('--headless', '--disable-gpu')
...

# Acquire a firefox session
async with driver.acquire("latest") as session:
    # explain: install the latest geckodriver available at
    # [Mozilla Github] repository that is compatible with
    # the installed Firefox browser, and start a new session.
    await session.load("https://www.google.com")
    # . do some automated tasks
    ...
```

### Options configuration
Setting options for aselenium drivers does not require to import an Options class. Instead, the options can be accessed directly from the driver instance. The following example shows how to set options for Chrome, but the same method (if applicable) can also apply to other browsers.

``` python
from aselenium import Chrome, Proxy
driver = Chrome()
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
# . arguments
driver.options.add_arguments("--disable-gpu", "--disable-dev-shm-usage")
# . preferences [Keywork Arguments]
driver.options.set_preferences(
    **{
        "download.default_directory": "/path/to/download/directory",
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
)
# . experimental options [Keywork Arguments]
driver.options.add_experimental_options(
    excludeSwitches=["enable-automation", "enable-logging"]
)
...
```

### Profile configuration
The options of aselenium drivers provides the 'set_profile' method to configure the profile of the browser. By using this method, a cloned temporary profile will be created based on the specified profile directory, leaving the original profile untouched. When the driver is no longer in use, the temporary profile will be deleted automatically. The following example shows how to set profile for Chrome, but the same method (if applicable) can also apply to other browsers.
``` python
from aselenium import Chrome
driver = Chrome()
driver.options.set_profile(
    # . the default profile directory for Chrome on MacOS
    directory="~/Library/Application Support/Google/Chrome", 
    profile="Default",
)
```

### Navigation
``` python
from aselenium import Chrome
driver = Chrome()
async with driver.acquire() as session:
    # . load a url
    await session.load("https://www.google.com")
    # . explicitly wait for page loading: url
    res = await session.wait_until_url("contains", "google", timeout=10)  # True / False
    # . explicitly wait for page loading: title
    res = await session.wait_until_title("startswith", "Google", timeout=10)  # True / False
    # . backward
    await session.backward()
    # . forward
    await session.forward()
    # . refresh
    await session.refresh()
```

### Page Information
``` python
from aselenium import Chrome
driver = Chrome()
async with driver.acquire() as session:
    await session.load("https://www.google.com")
    # . access page url [property]
    url = await session.url  # https://www.google.com
    # . access page title [property]
    title = await session.title  # Google
    # . access page viewport [property]
    viewport = await session.viewport  # <Viewport (width=1200, height=776, x=0, y=2143)>
    # . access page width [property]
    width = await session.width  # 1200
    # . access page height [property]
    height = await session.height  # 776
    # . access page source [property]
    source = await session.source  # <!DOCTYPE html><html itemscope="" itemtype="http://...
    # . take screenshot
    data = await session.screenshot()  # b'\x89PNG\r\n\x1a\n\x00\x00\x00\...
    # . save screenshot
    await session.save_screenshot("~/path/to/screenshot.png")  # True / False
    # . print page
    data = await session.print_page()  # b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1...
    # . save page
    await session.save_page("~/path/to/page.pdf")  # True / False
```

### Session Timeouts
``` python
from aselenium import Chrome
driver = Chrome()
async with driver.acquire() as session:
    # . access timeouts of the session [property]
    timeouts = await options.timeouts
    # <Timeouts (implicity=0, pageLoad=300000, script=30000, unit='ms')>

    # . set timeouts of the session
    timeouts = await session.set_timeouts(implicit=0.1, pageLoad=30, script=3)
    # <Timeouts (implicity=100, pageLoad=30000, script=3000, unit='ms')>

    # . reset timeouts of the session
    timeouts = await session.reset_timeouts()
    # <Timeouts (implicity=0, pageLoad=300000, script=30000, unit='ms')>
```

### Session Windows
``` python
from aselenium import Chrome
driver = Chrome()
async with driver.acquire() as session:
    await session.load("https://www.google.com")
    # . access the active window [property]
    win = await session.active_window
    # <Window (name='default', handle='CCEF49C484842CFE1AB855ECCA164858')>

    # . rename a window
    win = await session.rename_window("default", "google")
    # <Window (name='google', handle='CCEF49C484842CFE1AB855ECCA164858')>

    # . open a new window
    win = await session.new_window("baidu", "tab")
    # <Window (name='baidu', handle='B89293FA79B6389AF1657B972FBD6B26')>
    await session.load("https://www.baidu.com")

    # . access all opened windows [property]
    wins = await session.windows
    # [
    #    <Window (name='google', handle='CCEF49C484842CFE1AB855ECCA164858')>
    #    <Window (name='baidu', handle='B89293FA79B6389AF1657B972FBD6B26')>
    # ]

    # . close current window
    await session.close_window(switch_to="google")
    # <Window (name='google', handle='CCEF49C484842CFE1AB855ECCA164858')>

    # . access window rect [property]
    rect = await session.window_rect
    # <WindowRect (width=1200, height=900, x=22, y=60)>

    # . set window rect
    rect = await session.set_window_rect(800, 500)
    # <WindowRect (width=800, height=500, x=22, y=60)>

    # . maximize window
    await session.maximize_window()

    # . minimize window
    await session.minimize_window()

    # . fullscreen window
    await session.fullscreen_window()
```

### Active Window Cookies
``` python
from aselenium import Chrome, Cookie
driver = Chrome()
async with driver.acquire() as session:
    await session.load("https://www.baidu.com")

    # . access all cookies [property]
    cookies = await session.cookies
    # [
    #    <Cookie (name='ZFY', data={'domain': '.baidu.com', 'expiry': 1720493275, ...})>
    #    <Cookie (name='ZFK', data={'domain': '.baidu.com', 'expiry': 1720493275, ...})>
    #    ...
    # ]

    # . get a cookie
    cookie = await session.get_cookie("ZFY")
    # <Cookie (name='ZFY', data={'domain': '.baidu.com', 'expiry': 1720493275, ...})>

    # . add a cookie
    await session.add_cookie({"name": "test_cookie2", "value": "123456", "domain": ".baidu.com"})
    # // or //
    test_cookie2 = Cookie(name="test_cookie1", value="123456", domain=".baidu.com")
    await session.add_cookie(test_cookie2)

    # . delete a cookie
    await session.delete_cookie("test_cookie1")
    # // or //
    await session.delete_cookie(test_cookie2)
```

### JavaScript Execution
Notice that some of the following methods are not async functions, therefore should not be awaited.

``` python
from aselenium import Chrome
driver = Chrome()
async with driver.acquire() as session:
    await session.load("https://www.google.com")
    # . execute a raw javascript
    res = await session.execute_script("return document.title;")  # Google

    # . cache a javascript
    js = session.cache_script("get_title", "return document.title;")
    # <JavaScript (name='get_title', script='return document.title;', args=[])>

    # . access all cached javascripts
    scripts = session.scripts
    # [<JavaScript (name='get_title', script='return document.title;', args=[])>]

    # . get a cached javascript
    js = session.get_script("get_title")
    # <JavaScript (name='get_title', script='return document.title;', args=[])>

    # . execute cached javascript
    res = await session.execute_script(js)  # Google
    # // or //
    res = await session.execute_script("get_title")  # Google

    # . rename cached javascript
    js = session.rename_script("get_title", "access_title")
    # // or //
    js = session.rename_script(js, "access_title")
    # <JavaScript (name='access_title', script='return document.title;', args=[])>

    # . remove cached javascript
    session.remove_script(js)
    # // or //
    session.remove_script("access_title")
```

### Element Interaction
``` python
from aselenium import Chrome
driver = Chrome()
async with driver.acquire() as session:
    await session.load("https://www.baidu.com")
    # . find element
    element = await session.find_element("#kw", by="css")
    # <Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_1', session='1e78...', service='http://...')>

    # . find elements
    elements = await session.find_elements(".s_ipt", by="css")
    # [
    #       <Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_2', session='1e78...', service='http://...')>
    #       <Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_3', session='1e78...', service='http://...')>
    #       ...
    # ]

    # . find the 1st located element among selectors
    element = await session.find_1st_element("#kw", ".s_ipt", by="css")
    # <Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_1', session='1e78...', service='http://...')>
    
    # . explicit wait for element
    res = await session.wait_until_element("visible", "#kw", by="css", timeout=10)  # True
    res = await session.wait_until_element("gone", "#kw", by="css", timeout=10) # False

    # . explicit wait for elements
    res = await session.wait_until_elements(
        "exist", "#kw", ".s_ipt", by="css", all_=True, timeout=10
    )  # True
    res = await session.wait_until_elements(
        "selected", "#kw", ".s_ipt", by="css", all_=True, timeout=10
    )  # False

    # . access element properties
    exists = await element.exists  # True
    visible = await element.visible  # True
    viewable = await element.viewable  # True
    enabled = await element.enabled  # True
    selected = await element.selected  # False
    tag = await element.tag  # input
    text = await element.text  # None
    rect = await element.rect  # <ElementRect (width=500, height=22, x=522, y=217)>
    aria_role = await element.aria_role  # None
    aria_label = await element.aria_label  # None
    ...

    # . element interaction
    await element.click()
    await element.send("Hello World!")
    await element.clear()
    await element.upload("~/path/to/file.png")
    await element.scroll_into_view()
    ...
```

### Actions Chain
Actions chain allows the browser to perform a series of low-level interactions such as mouse movements, key presses, and wheel scrolls.

- For Chromium-based browsers like Chrome, Chromium, and Edge, the actions chain execution passes most tests, including 'drag_and_drop'.
- For Firefox, the actions chain execution fails the 'drag_and_drop' test. Additionally, user must explicitly block the code execution until all actions are completed. This is because geckodriver returns a response immediately after receiving the actions command (where chromedriver only returns a response when all actions are completed). To do so, user can choose to use the 'explicit_wait' argument in the 'perform()' method to wait the specified amount of seconds, or implement a custom logic right after the actions chain execution.
``` python
from aselenium import Chrome, KeyboardKeys
driver = Chrome()
async with driver.acquire() as session:
    # Actions chain
    await session.load("https://www.baidu.com")
    search_button = await session.find_element("#su", by="css")
    (
        await session.actions()
        # . move mouse to the element
        .move_to(element=search_button)
        # . click the element
        .click(pause=1)
        # . send text
        .send_keys("Hello World!", pause=1)
        # . select all (control + a)
        .send_key_combo(KeyboardKeys.CONTROL, "a", pause=1)
        # . cut (control + x)
        .send_key_combo(KeyboardKeys.CONTROL, "x", pause=1)
        # . paste (control + v)
        .send_key_combo(KeyboardKeys.CONTROL, "v", pause=1)
        # . enter
        .send_keys(KeyboardKeys.ENTER, pause=1)
        # . scroll wheel
        .scroll_by(y=500, pause=1)
        # . execute the actions chain
        .perform()  
        # For Firefox, specify an explicit wait time to wait for the 
        # actions to complete: `.perform(explicit_wait=20)`.
    )

    # Drag and drop
    await session.load("https://www.w3schools.com/html/html5_draganddrop.asp")
    l_element = await session.find_element("#div1", by="css")
    r_element = await session.find_element("#div2", by="css")
    (
        await session.actions()
        # . drag and drop: left -> right
        .drag_and_drop(drag=l_element, drop=r_element, pause=1)
        # . drag and drop: right -> left
        .drag_and_drop(drag=r_element, drop=l_element, pause=1)
        # . execute the actions chain
        .perform()
        # For Firefox, `drag_and_drop` is not supported.
    )
```

### Known Issues
- For Linux users, browsers installed through 'snap store' will failed due to the 'snap' sandbox. Snap version of the browsers lack the permissions to create and access a temporary profile out side of snap, which is required by the webdriver to start the browser. The most straight forward solution is to uninstall the snap version and re-install the browser through the official website.
- For Firefox, the actions chain does not work quite as expected. If actions chain is important for the project, consider using Chromium-based browsers instead.
- Safari is supported by aselenium, but limited to some basic functionalities, and not recommended to use for critical automations. The webdriver for Safari yeilds many unexpected errors and sometimes even crashes the browser and program.

### Acknowledgements
aselenium is based on several open-source repositories.
- [aiohttp](https://github.com/aio-libs/aiohttp)
- [psutil](https://github.com/giampaolo/psutil)
- [orjson](https://github.com/ijl/orjson)

aselenium is inspired from and makes modifications of the following open-source repositories:
- [arsenic](https://github.com/HENNGE/arsenic)
- [selenium](https://github.com/SeleniumHQ/selenium)
- [webdriver-manager](https://github.com/SergeyPirogov/webdriver_manager)