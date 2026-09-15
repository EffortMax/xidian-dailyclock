# 西安电子科技大学 研究生选课系统（yjsxk.xidian.edu.cn）登录模块
#
# 背景（原来的做法已经失效）：
#   1) 选课系统不在 yjspt.xidian.edu.cn 上了，而是 https://yjsxk.xidian.edu.cn/yjsxkapp/sys/xsxkapp/
#      （老的 /yjsxkapp/... 前缀在 yjspt 上会被网关回 400 + HTML，且每次卡 25~32 秒）
#   2) 它不使用统一身份认证(ids)的 SSO 表单登录了，改成选课系统自带的登录：
#        取验证码 token : GET  {APP}/login/4/vcode.do?timestamp=<毫秒>      -> {"data":{"token":"..."}}
#        取验证码图片   : GET  {APP}/login/vcode/image.do?vtoken=<token>     -> image/jpeg
#        提交登录       : POST {APP}/login/check/login.do?timestrap=<毫秒>
#                         loginName=<学号>&loginPwd=<DES.strEncSimple(密码)>&verifyCode=<验证码>&vtoken=<token>
#                       返回 {"code":"1"} 成功 / "2" 用户名或密码不正确 / "3" 验证码不正确 / "4" 在线人数超过上限
#   3) 密码不是明文提交，也不是标准 DES，而是站点前端 window.DES.strEncSimple()，
#      已按站点 JS 逐行移植到 wisedu_des.py（带实测向量自检）。
#   4) 「登录状态」怎么判断（这点踩过坑，说明一下）：
#      站点自己是用 loadPublicInfo_index.do 里的 loginUserId 字段判断的：
#        loginUserId 非空且不等于 "fail_user"  -> 已登录（index.html 里就是拿它决定显示登录框还是学生信息）
#      loadStdInfo.do 并不返回 loginUserId，它返回的是 {"code": "...", "xs": {...学生信息...}}，
#      code 为 "0" 表示没登录。所以不能拿它去找 loginUserId。
#
# 验证码是图片验证码，脚本没法自动识别（除非另外装 ddddocr 之类的 OCR），
# 所以这里做成「脚本弹图 + 你输入一次验证码」，登录成功后 cookie 存到 cookies.json，
# 后续抢课轮询就不用再输验证码了；会话过期时会再让你输一次。
#
# 单独运行本文件可以只测登录：
#   python xidian_login.py               # 登录并保存 cookies.json
#   python xidian_login.py --force       # 忽略已有 cookies.json，强制重新登录
#   python xidian_login.py --diagnose    # 登录后把各接口的返回打出来（排查用）

import json
import os
import sys
import time

import requests

from wisedu_des import encrypt_password

APP = "https://yjsxk.xidian.edu.cn/yjsxkapp/sys/xsxkapp"
LOGIN_PAGE = APP + "/index.html"
TIMEOUT = (6, 25)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

HERE = os.path.dirname(os.path.abspath(__file__))
COOKIE_FILE = os.path.join(HERE, "cookies.json")
CAPTCHA_FILE = os.path.join(HERE, "captcha.jpg")

# 这套系统里 _WEU 是"记住我"类的持久 cookie。当它失效/过期时，服务端拿它自动登录会抛
# NullPointer，于是所有接口都返回一个 "系统异常" 页面（HTTP 200 + text/html，
# 内容含"稍等~正在紧急修复 / 错误标识 / 出错信息：NullPointer"）。
# 实测：带上 _WEU 就 100% 复现，去掉 _WEU 立刻恢复正常；而正常登录后的请求并不需要它。
# 所以这里主动不保存、不发送 _WEU，并在遇到系统异常页时再去掉它重试一次。
TRANSIENT_COOKIE_NAMES = ("_WEU",)


def strip_transient_cookies(session):
    """去掉会导致服务端 NullPointer 的持久 cookie，返回被去掉的名字列表"""
    removed = []
    jar = session.cookies
    for name in TRANSIENT_COOKIE_NAMES:
        hits = [c for c in jar if c.name == name]
        for c in hits:
            try:
                jar.clear(c.domain, c.path, c.name)
            except KeyError:
                pass
        if hits:
            removed.append(name)
    return removed


def is_server_error_page(text):
    """是不是那个"系统异常"错误页"""
    return ("系统异常" in text and "错误标识" in text) or "出错信息：NullPointer" in text or "NullPointer" in text and "紧急修复" in text


def server_error_brief(text):
    """从错误页里抠出错误标识/出错信息，便于反馈给学校（原文里这些值常被标签包着）"""
    import re as _re
    mark = _re.search(r"错误标识[：:]\s*(?:<[^>]*>\s*)*([A-Za-z0-9]+)", text)
    info = _re.search(r"出错信息[：:]\s*(?:<[^>]*>\s*)*([^\s<]+)", text)
    parts = []
    if mark:
        parts.append("错误标识 " + mark.group(1))
    if info:
        parts.append("出错信息 " + info.group(1))
    return "，".join(parts) if parts else "服务端内部错误（页面写着 系统异常）"


def _url(path):
    return APP + path


def vcode_token_url():
    return _url("/login/4/vcode.do?timestamp={0}".format(int(time.time() * 1000)))


def vcode_image_url(token):
    return _url("/login/vcode/image.do?vtoken={0}".format(token))


def login_url():
    return _url("/login/check/login.do?timestrap={0}".format(int(time.time() * 1000)))


def login_state_url():
    """站点用这个接口的 loginUserId 判断登录状态"""
    return _url("/xsxkHome/loadPublicInfo_index.do?_={0}".format(int(time.time() * 1000)))


def std_info_url():
    """学生信息：{"code": "...", "xs": {...}}，code == "0" 表示未登录"""
    return _url("/xsxkHome/loadStdInfo.do?_={0}".format(int(time.time() * 1000)))


class LoginError(RuntimeError):
    pass


def new_session():
    session = requests.Session()
    requests.packages.urllib3.disable_warnings()
    session.headers.update({
        "User-Agent": UA,
        "Referer": LOGIN_PAGE,
        "Origin": "https://yjsxk.xidian.edu.cn",
    })
    return session


def get_json(session, url, timeout=TIMEOUT, allow_retry=True):
    """拿一个 JSON 响应；拿不到（非 200 / 解析失败 / 系统异常页）返回 None"""
    for attempt in (1, 2) if allow_retry else (1,):
        try:
            resp = session.get(url, verify=False, timeout=timeout, allow_redirects=False)
        except requests.RequestException:
            return None
        text = resp.content.decode("utf-8-sig", errors="replace")
        if is_server_error_page(text):
            # 多半是 _WEU 引起的服务端 NullPointer：去掉它再试一次
            if attempt == 1 and strip_transient_cookies(session):
                print("[!] 遇到系统异常页（{0}），已去掉 _WEU 后重试".format(server_error_brief(text)))
                continue
            return None
        if resp.status_code != 200:
            return None
        # 这套系统会拿 text/html 当 Content-Type 返回 JSON，所以只看 body 能不能解析
        try:
            return json.loads(text)
        except ValueError:
            return None
    return None


def login_state(session):
    """
    判断当前会话是否已登录，返回 (状态, 说明)：
      True  = 确定已登录（站点依据：loginUserId 非空且不是 "fail_user"）
      False = 确定没登录（拿到空值 / fail_user / loadStdInfo 的 code == "0"）
      None  = 拿不准（接口没返回 JSON，比如网关拦截、系统异常页），此时不要贸然重新登录
    """
    data = get_json(session, login_state_url())
    if isinstance(data, dict) and "loginUserId" in data:
        uid = str(data.get("loginUserId") or "").strip()
        if uid and uid != "fail_user":
            return True, "loadPublicInfo_index: loginUserId={0}".format(uid)
        return False, "loadPublicInfo_index: loginUserId={0!r}（空或 fail_user 都算未登录）".format(
            data.get("loginUserId"))

    # 兜底：loadPublicInfo_index 不可用时看 loadStdInfo 的 code（"0" = 未登录）
    std = get_json(session, std_info_url())
    if isinstance(std, dict):
        code = str(std.get("code"))
        if code not in ("0", "", "None"):
            return True, "loadStdInfo: code={0}（已登录）".format(code)
        return False, "loadStdInfo: code={0}（未登录）".format(code)
    return None, "两个状态接口都没能返回 JSON（可能被网关拦了或系统异常）"


def is_logged_in(session):
    """只有明确判定为已登录才返回 True；拿不准时返回 False（调用方请用 login_state 区分）"""
    return login_state(session)[0] is True


def describe_session(session):
    """排查用：把会话状态相关的接口逐个打出来"""
    print("--- 会话诊断 ---")
    print("cookies:", requests.utils.dict_from_cookiejar(session.cookies))
    for name, url in (("loadPublicInfo_index", login_state_url()),
                      ("loadStdInfo", std_info_url()),
                      ("loadPublicInfo_course", _url("/xsxkHome/loadPublicInfo_course.do")),
                      ("loadJhnCourseInfo(测试课程)", _url("/xsxkCourse/loadJhnCourseInfo.do?query_keyword=1"))):
        try:
            resp = session.get(url, verify=False, timeout=TIMEOUT, allow_redirects=False)
            body = resp.content.decode("utf-8-sig", errors="replace")
            print("[{0}] HTTP {1} {2} -> {3!r}".format(
                name, resp.status_code, resp.headers.get("content-type"), body[:300]))
        except requests.RequestException as exc:
            print("[{0}] 请求异常：{1}".format(name, exc))
    ok, why = login_state(session)
    label = "已登录" if ok is True else ("未登录" if ok is False else "状态不明")
    print("结论：", label, "|", why)
    print("--- 诊断结束 ---")


def fetch_captcha(session):
    """取一个验证码：返回 (vtoken, 图片字节)"""
    resp = session.get(vcode_token_url(), verify=False, timeout=TIMEOUT)
    data = json.loads(resp.content.decode("utf-8-sig"))
    if str(data.get("code")) != "1":
        raise LoginError("获取验证码 token 失败：{0}".format(data))
    token = (data.get("data") or {}).get("token")
    if not token:
        raise LoginError("验证码 token 为空：{0}".format(data))
    img = session.get(vcode_image_url(token), verify=False, timeout=TIMEOUT)
    if img.status_code != 200 or not img.content:
        raise LoginError("下载验证码图片失败：HTTP {0}".format(img.status_code))
    return token, img.content


def ask_captcha(image_bytes, attempt=1):
    """把验证码图片落到本地并打开，让用户输入；非交互场景可用环境变量 XDU_CAPTCHA"""
    preset = os.environ.get("XDU_CAPTCHA")
    if preset:
        return preset.strip()
    with open(CAPTCHA_FILE, "wb") as fh:
        fh.write(image_bytes)
    print("[*] 验证码图片已保存：{0}".format(CAPTCHA_FILE))
    try:
        if sys.platform.startswith("win"):
            os.startfile(CAPTCHA_FILE)          # 自动用系统看图工具打开
        else:
            print("[*] 请手动打开上面的文件查看验证码")
    except Exception:
        pass
    try:
        return input("[?] 请输入图片里的验证码（第 {0} 次尝试）：".format(attempt)).strip()
    except EOFError:
        # 挂机场景下 stdin 可能不可交互，别让它抛一堆 traceback
        raise LoginError("需要手动输入验证码，但当前终端不可交互；请在终端里运行，或用 XDU_CAPTCHA 指定")


def make_ddddocr_provider(verbose=True):
    """
    用 ddddocr 做无人值守验证码识别，返回回调 (image_bytes, attempt) -> 验证码字符串。
    没装 ddddocr 时返回 None（调用方回退到人工输入）。
    """
    from app.services.ocr_compat import ensure_opencv_module

    ensure_opencv_module()
    try:
        import ddddocr
    except ImportError:
        return None
    try:
        ocr = ddddocr.DdddOcr(show_ad=False)       # 新版支持关广告
    except TypeError:
        ocr = ddddocr.DdddOcr()

    def provider(image_bytes, attempt=1):
        try:
            code = (ocr.classification(image_bytes) or "").strip().replace(" ", "")
        except Exception as exc:                   # 识别本身出问题也不能把挂机搞崩
            print("[!] ddddocr 识别失败：{0}".format(exc))
            return ""
        if verbose:
            print("[*] ddddocr 识别验证码 -> {0!r}（第 {1} 次尝试）".format(code, attempt))
        return code

    return provider


def make_captcha_provider(unattended=True, verbose=True):
    """
    按需给出验证码回调：
      unattended=True  -> 优先用 ddddocr 自动识别（识别错了 login() 会自动换一张重试）
      unattended=False -> 手动输入（弹出 captcha.jpg）
    """
    if not unattended:
        return ask_captcha
    provider = make_ddddocr_provider(verbose=verbose)
    if provider is None:
        print("[!] 没有安装 ddddocr，回退为手动输入验证码；想无人值守请先 pip install ddddocr")
        return ask_captcha
    return provider


def login(session, user_id, password, max_attempts=3, captcha_provider=None):
    """
    用选课系统自带登录接口登录。
    captcha_provider: 可选，签名 (image_bytes, attempt) -> 验证码字符串；
                      不传就是人工输入；传 ddddocr 的回调即无人值守。
    """
    encrypted = encrypt_password(password)
    for attempt in range(1, max_attempts + 1):
        token, image = fetch_captcha(session)
        code_text = (captcha_provider or ask_captcha)(image, attempt)
        if not code_text:
            print("[!] 没有输入验证码，重新获取")
            continue

        resp = session.post(
            login_url(),
            data={"loginName": user_id, "loginPwd": encrypted,
                  "verifyCode": code_text, "vtoken": token},
            headers={"X-Requested-With": "XMLHttpRequest"},
            verify=False, timeout=TIMEOUT)
        try:
            result = json.loads(resp.content.decode("utf-8-sig"))
        except ValueError:
            raise LoginError("登录接口返回的不是 JSON：HTTP {0}，前 200 字符 {1!r}".format(
                resp.status_code, resp.content[:200]))
        code = str(result.get("code"))
        msg = result.get("msg") or ""
        if code == "1":
            strip_transient_cookies(session)     # 登录响应可能又把 _WEU 塞回来，去掉它
            print("[+] 登录成功（{0}）".format(msg or "登录成功"))
            return session
        if code == "3":
            print("[!] 验证码不正确，换一张重试")
            continue
        if code == "4":
            print("[!] 在线人数超过上限，5 秒后重试")
            time.sleep(5)
            continue
        raise LoginError("登录失败：code={0} msg={1}".format(code, msg))
    raise LoginError("连续 {0} 次登录都没成功（多半是验证码输错），请重跑".format(max_attempts))


def save_cookies(session, path=COOKIE_FILE):
    """
    保存登录态。**连同 domain/path 一起存**：
    JSON 里如果只存 "名字: 值"，再 load 回来时 requests 会把 cookie 挂到空 domain（any-domain），
    登录后新的 JSESSIONID 是挂在 domain=yjsxk.xidian.edu.cn 上的，于是 jar 里会同时存在两个
    同名 JSESSIONID，请求时旧的那个（值已失效）反而可能被发出去 —— 表现就是
    "登录提示成功，但紧接着所有接口都 302 回登录页"。
    """
    try:
        jar = []
        for c in session.cookies:
            if c.name in TRANSIENT_COOKIE_NAMES:     # 不保存 _WEU：失效时会让服务端 NPE
                continue
            jar.append({"name": c.name, "value": c.value,
                        "domain": c.domain, "path": c.path or "/",
                        "secure": bool(c.secure), "expires": c.expires})
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"version": 2, "cookies": jar}, fh, ensure_ascii=False)
        print("[*] 已保存登录状态到 {0}".format(path))
    except OSError as exc:
        print("[!] 保存 cookie 失败：{0}".format(exc))


def load_cookies(session, path=COOKIE_FILE):
    """
    读回登录态。先清空 jar（很重要：别让上一次请求残留的旧 cookie 混进来），再按 domain/path 装回。
    兼容老版本只存 "名字: 值" 的格式（那种格式下 domain 会挂成空，容易出问题，读到就提示重登）。
    """
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False

    session.cookies.clear()
    if isinstance(data, dict) and data.get("version") == 2 and isinstance(data.get("cookies"), list):
        for item in data["cookies"]:
            if not isinstance(item, dict) or item.get("name") in TRANSIENT_COOKIE_NAMES:
                continue
            try:
                expires = item.get("expires")
                session.cookies.set(item["name"], item["value"], domain=item.get("domain") or "",
                                     path=item.get("path") or "/", secure=bool(item.get("secure")),
                                     expires=expires)
            except Exception:
                continue
        return True

    # 老格式（v1）：只有名字和值，domain 会是空的 —— 这会引发同名 cookie 冲突，所以直接不采用
    print("[!] {0} 是旧格式（没有记录 domain/path），已忽略并重新登录".format(os.path.basename(path)))
    return False


def ensure_session(user_id, password, cookie_file=COOKIE_FILE, force_login=False,
                   captcha_provider=None, strict=False, max_attempts=3):
    """
    拿一个已登录的 session：优先复用 cookies.json，失效了再走一次登录。
    captcha_provider 传 ddddocr 的回调即无人值守；登录接口返回 code=1 即视为成功并立刻保存 cookies；
    状态复核不通过只提示、不抛异常（避免验证码白输），strict=True 时才抛。
    """
    session = new_session()
    if not force_login and load_cookies(session, cookie_file):
        ok, why = login_state(session)
        if ok is True:
            print("[+] 复用了 {0} 里的登录状态（{1}）".format(os.path.basename(cookie_file), why))
            return session
        if ok is None:
            # 拿不准（网关拦截 / 系统异常页）时不要贸然重新登录，否则白白要一次验证码
            print("[!] 暂时无法确认登录状态（{0}），先按可用处理".format(why))
            return session
        print("[*] {0} 里的登录状态已失效（{1}），需要重新登录"
              .format(os.path.basename(cookie_file), why))

    print("[*] 需要登录选课系统（{0}）".format(LOGIN_PAGE))
    session.cookies.clear()      # 关键：登录前清干净，免得旧的 JSESSIONID 混进请求把新会话顶掉
    login(session, user_id, password, captcha_provider=captcha_provider, max_attempts=max_attempts)
    save_cookies(session, cookie_file)          # 先存下来，别让验证码白输

    ok, why = login_state(session)
    if ok is True:
        print("[+] 会话复核通过（{0}）".format(why))
    elif ok is None:
        print("[!] 会话复核拿不准（{0}）；cookies.json 已保存，先直接跑 courseChoose.py 试试".format(why))
    else:
        # 复核没过：用干净会话再登录一次（不清 jar 的重试没意义，问题往往就在旧 cookie 上）
        print("[!] 会话复核没通过（{0}），用干净会话重登一次".format(why))
        for attempt in range(1, 3):
            session.cookies.clear()
            try:
                login(session, user_id, password, captcha_provider=captcha_provider,
                      max_attempts=max_attempts)
            except LoginError as exc:
                print("[x] 重登失败（{0}/2）：{1}".format(attempt, exc))
                continue
            ok, why = login_state(session)
            if ok is True:
                print("[+] 会话复核通过（{0}）".format(why))
                save_cookies(session, cookie_file)
                return session
            print("[!] 仍然复核不过（{0}）".format(why))
            time.sleep(2)
        message = ("登录接口一直返回成功，但会话复核始终不通过：{0}\n"
                   "    可能是同一账号在别处登录把会话顶掉了、或学校系统正忙/异常。\n"
                   "    请稍等一会儿重跑；若持续如此，执行 python xidian_login.py --diagnose 看细节"
                   .format(why))
        if strict:
            raise LoginError(message)
        print("[!] " + message)
    return session


def relogin(session, user_id, password, cookie_file=COOKIE_FILE, captcha_provider=None,
            max_attempts=5):
    """
    会话过期后重新登录。captcha_provider 传 ddddocr 的回调即无人值守；
    max_attempts 默认给到 5，因为自动识别的验证码偶尔会认错，多试几张就稳了。
    """
    print("[!] 登录状态已失效，需要重新登录")
    session.cookies.clear()
    login(session, user_id, password, captcha_provider=captcha_provider, max_attempts=max_attempts)
    save_cookies(session, cookie_file)
    return session


if __name__ == "__main__":
    # 直接跑本文件：只做登录并保存 cookie，方便先验证账号/验证码流程是否通
    #   python xidian_login.py              复用 cookies.json，失效则重新登录
    #   python xidian_login.py --force      忽略 cookies.json，强制重新登录
    #   python xidian_login.py --unattended 用 ddddocr 自动识别验证码（无人值守）
    #   python xidian_login.py --diagnose   打印各接口返回，排查用
    sys.path.insert(0, HERE)
    try:
        from config import user_id, password
    except ImportError:
        raise SystemExit("请在项目目录下运行，或先准备好 config.py（user_id / password）")

    unattended = "--unattended" in sys.argv
    if not unattended:
        try:                                     # 也读 config.py 里的开关
            from config import unattended as unattended
        except ImportError:
            unattended = False

    provider = make_captcha_provider(unattended=unattended) if unattended else None
    sess = ensure_session(user_id, password, force_login="--force" in sys.argv,
                          captcha_provider=provider)
    if "--diagnose" in sys.argv:
        describe_session(sess)
    else:
        ok, why = login_state(sess)
        label = "已登录" if ok is True else ("未登录" if ok is False else "状态不明")
        print("[+] 会话状态：{0}（{1}）".format(label, why))
