"""登录态管理（对应 DM.md D1.2 买家账号池登录态）。

拼多多没有独立网页版APP，但 mobile.yangkeduo.com 这个移动端网页本身可以单独登录
（手机号+验证码，跟APP是同一套账号体系，登录动作不依赖装没装APP）。

这里用 Playwright 打开一个真实浏览器窗口，人工完成一次登录，把登录后的 Cookie 存成本地文件，
后续 importer.py 直接复用这份 Cookie 发普通 HTTP 请求，不用每次都开浏览器、也不用每次重新登录。

这份登录态本质上就是买家账号池的登录态，Module 01（商品导入）和以后的 Module 09（采购履约）
应该共用同一套账号 + 登录态管理逻辑，不是两套互不相干的东西。
"""

from __future__ import annotations

import json
import os

MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36 Edg/152.0.0.0"
)


def new_stealth_context(playwright, cookies: list[dict], headless: bool = False):
    """开一个尽量不带自动化痕迹的浏览器上下文，商家后台/以后买家账号自动化都用这个。

    2026-08-13实测教训：headless=True + 默认的navigator.webdriver=true这个组合，
    在商家后台"发布商品"这种敏感页面上会直接触发滑块验证码；换成 headless=False（真实弹窗口）
    +抹掉navigator.webdriver+真实桌面UA之后，同样的操作（搜索类目）就没有再触发。
    这不是研究怎么绕过验证码本身，只是让自动化的浏览器环境更接近一个真实浏览器该有的样子，
    真遇到验证码还是要转人工，不会在这个函数里加任何"识别/跳过验证码"的逻辑。

    返回 (browser, context)，调用方用完记得 browser.close()。
    """
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context(viewport={"width": 1400, "height": 1000}, user_agent=DESKTOP_USER_AGENT)
    context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    context.add_cookies(cookies)
    return browser, context


def save_login_state(state_path: str, start_url: str = "https://mobile.yangkeduo.com/goods.html") -> None:
    from playwright.sync_api import sync_playwright  # 延迟导入，避免没装playwright时其他模块也导入失败

    os.makedirs(os.path.dirname(os.path.abspath(state_path)) or ".", exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(user_agent=MOBILE_USER_AGENT)
        # 同样的伪装补丁（见 new_stealth_context 的说明）：默认 navigator.webdriver=true 会被
        # 拼多多风控识别成自动化环境，直接拦掉验证码发送，之前只给商家后台那边打了这个补丁，
        # 买家登录这边一直没加，2026-08-15实测验证码发送失败就是这个原因。
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()
        page.goto(start_url)
        input(
            "\n浏览器已经打开拼多多的移动端网页。请在这个窗口里手动登录你的账号"
            "（一般是点右上角/我的，走手机号+验证码登录，跟登App是同一套账号，"
            "网页登录不需要装App）。登录完成、能看到个人信息之后，"
            "回到这个终端窗口按回车键继续...\n"
        )
        context.storage_state(path=state_path)
        browser.close()
    print(f"登录态已保存到 {state_path}")


def _parse_netscape_cookie_txt(text: str) -> dict[str, str]:
    """解析经典的 Netscape cookies.txt 格式（"Get cookies.txt LOCALLY"这类扩展导出的就是这个格式）。

    每行7个字段，用制表符分隔：domain, include_subdomains, path, secure, expiration, name, value。
    以 `#` 开头的是注释，空行跳过。
    """
    cookies: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        name, value = fields[5], fields[6]
        cookies[name] = value
    return cookies


def load_cookies_for_requests(state_path: str) -> dict[str, str]:
    """把登录态文件转成 requests 能直接用的 cookie 字典。

    兼容三种来源：
    1. Playwright 的 storage_state.json —— 顶层是 {"cookies": [...], "origins": [...]}
    2. 浏览器扩展（比如 Cookie-Editor）导出的JSON —— 顶层直接是一个 [{"name":..,"value":..}, ...] 数组，
       字段名可能是 name/value 或 Name/Value，大小写不完全统一，所以两种都兼容一下。
    3. 经典 Netscape cookies.txt 格式（"Get cookies.txt LOCALLY"这类扩展导出的就是这种，纯文本、制表符分隔）。

    Playwright 自动化窗口登录时如果被拼多多的反自动化风控拦了（比如验证码发不出去），
    改用人工在正常浏览器里登录、再用扩展导出cookie这条路，这里就是接那份导出文件用的。
    """
    with open(state_path, encoding="utf-8") as f:
        raw_text = f.read()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        return _parse_netscape_cookie_txt(raw_text)

    if isinstance(data, dict) and "cookies" in data:
        raw_cookies = data["cookies"]
    elif isinstance(data, list):
        raw_cookies = data
    else:
        raise ValueError(
            f"{state_path} 的格式认不出来，既不是Playwright的storage_state，也不是常见的cookie导出格式。"
        )

    cookies: dict[str, str] = {}
    for c in raw_cookies:
        name = c.get("name") or c.get("Name")
        value = c.get("value") or c.get("Value")
        if name is not None and value is not None:
            cookies[name] = value
    return cookies


def _parse_netscape_cookie_txt_full(text: str) -> list[dict]:
    """跟 _parse_netscape_cookie_txt 是同一份文件格式，但这个不丢domain/path信息——
    requests只需要name:value就够用，但Playwright的 context.add_cookies() 要求每条cookie
    必须带domain+path（否则不知道这条cookie该套用到哪个网站上），所以这里单独留一份不裁剪的解析。
    """
    cookies: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        domain, _include_sub, path, secure, expiration, name, value = fields
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path or "/",
                "secure": secure.upper() == "TRUE",
                "expires": float(expiration) if expiration.isdigit() else -1,
            }
        )
    return cookies


def load_playwright_cookies(state_path: str, default_domain: str = ".pinduoduo.com") -> list[dict]:
    """把登录态文件转成 Playwright context.add_cookies() 能直接用的cookie列表（带domain/path），
    不是 load_cookies_for_requests() 那种裁剪成 name:value 的简化字典——那个给requests发裸请求够用，
    但装进真实浏览器上下文里必须带上domain/path，浏览器才知道这条cookie该在哪个网站生效。

    同样兼容 Netscape cookies.txt / storage_state.json / 扩展导出JSON数组 三种格式；
    JSON来源如果没带domain（比如某些精简版的Cookie-Editor导出），用 default_domain 兜底。
    """
    with open(state_path, encoding="utf-8") as f:
        raw_text = f.read()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        return _parse_netscape_cookie_txt_full(raw_text)

    if isinstance(data, dict) and "cookies" in data:
        raw_cookies = data["cookies"]
    elif isinstance(data, list):
        raw_cookies = data
    else:
        raise ValueError(
            f"{state_path} 的格式认不出来，既不是Playwright的storage_state，也不是常见的cookie导出格式。"
        )

    cookies: list[dict] = []
    for c in raw_cookies:
        name = c.get("name") or c.get("Name")
        value = c.get("value") or c.get("Value")
        if name is None or value is None:
            continue
        domain = c.get("domain") or c.get("Domain") or default_domain
        path = c.get("path") or c.get("Path") or "/"
        expires = c.get("expires") or c.get("expirationDate") or -1
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "expires": expires,
            }
        )
    return cookies
