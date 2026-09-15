# Author: sunzy
# 研究生选课系统抢课脚本（按 2026 年现行接口重写）
#
# 相比原版的变化（原版已经跑不通了）：
#   1) 选课系统换了域名/路径：https://yjsxk.xidian.edu.cn/yjsxkapp/sys/xsxkapp/...
#      老的 https://yjspt.xidian.edu.cn/yjsxkapp/... 已被网关废弃：任意子路径都返回
#      400 + 230 字节 HTML，而且每次要卡 25~32 秒 —— 日志里那句
#      json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0) 就是这么来的。
#   2) 登录方式换了：不再走统一身份认证(ids)的 SSO 表单登录 + AES，
#      改成选课系统自带的 login/check/login.do + 图片验证码 + window.DES.strEncSimple 加密密码，
#      实现见 xidian_login.py 与 wisedu_des.py。
#   3) 服务器的 query_keyword 不索引课程代码，所以改成拉全量列表、在本地按 KCDM 匹配。
#   4) 同一门课有几十个教学班，优先挑「还有空位」的班；支持按 教学班名称 / 校区 筛选。
#   5) 所有请求都带超时；响应只看 body 能否解析成 JSON（这套系统会用 text/html 返回 JSON），
#      出错时直接给出 HTTP 状态、URL、响应开头。
#   6) 【重要】选课是"两步式"的，不能只看提交接口的 code：
#        a. POST xsxkCourse/choiceCourse.do（form body: bjdm / lx / csrfToken）
#           code == 0  -> 直接失败，msg 是原因
#           code != 0  -> 只是"请求已受理"，msg 是本次请求的流水号 xid
#        b. POST xsxkCourse/loadXkjgRes.do（body: xid / sfhqdqxkqqs）轮询真正的结果
#           msg 为空   -> 还在处理，继续轮询（官方最多 30 次）
#           msg 是 JSON -> {"code":1,...} 才是真的选课成功
#      以前只做了 a 就报"选课成功"，所以出现了"日志说选上了、系统里却没有"。
#      现在还会去 loadStdCourseInfo.do（已选课程）里复核一遍，复核到才算成功。
#
# 用法：
#   python courseChoose.py                      # 按 config.py 的设置抢课
#   python courseChoose.py --xq 北校区           # 临时只抢北校区的教学班
#   python courseChoose.py --bj 35 --xq 北校区    # 教学班名称含 35 且在北校区
#   python courseChoose.py --list                # 只看有哪些课（不选课）
#   python courseChoose.py --list 英语 --xq 南校区  # 查课时也支持筛选
#   python courseChoose.py --list --chosen        # 看已经选上的课
#   python courseChoose.py --drop X2FL2130        # 退掉某门课（会先让你确认）
#
# 筛选条件也可以写进 config.py：
#   bjmc_keyword = "35"        # 教学班名称必须包含
#   xqmc_keyword = "北校区"     # 校区：北校区 / 南校区（也接受 "北"、"02"；多个用逗号隔开）
#   不写就等于不筛选。命令行 --bj / --xq 的优先级高于 config.py。

import json
import os
import random
import sys
import time

import requests

import xidian_login as xl
password = ""
user_id = ""
course_KCDM = ""
sleep_time = 15

try:
    # 可选：在 config.py 里加一行 bjmc_keyword = "35"，就只考虑名称里带 "35" 的教学班
    BJMC_KEYWORD = "" if os.environ.get("XDU_LIBRARY_MODE") else __import__("config").bjmc_keyword
except ImportError:
    BJMC_KEYWORD = ""

try:
    # 可选：在 config.py 里加一行 xqmc_keyword = "北校区"，就只考虑该校区开的教学班
    XQMC_KEYWORD = "" if os.environ.get("XDU_LIBRARY_MODE") else __import__("config").xqmc_keyword
except ImportError:
    XQMC_KEYWORD = ""

try:
    # 可选：两次轮询之间的最小间隔秒数（默认 1 秒），避免把学校系统刷崩
    POLL_INTERVAL = 1.0 if os.environ.get("XDU_LIBRARY_MODE") else __import__("config").poll_interval
except ImportError:
    POLL_INTERVAL = 1.0

try:
    # 可选：无人值守开关。unattended = True 时用 ddddocr 自动识别图片验证码
    UNATTENDED = False if os.environ.get("XDU_LIBRARY_MODE") else __import__("config").unattended
except ImportError:
    UNATTENDED = False

try:
    # 可选：无人值守时把输出同时写进日志（默认 courseChoose.log；写成 None 可关闭）
    LOG_FILE = "courseChoose.log" if os.environ.get("XDU_LIBRARY_MODE") else __import__("config").log_file
except ImportError:
    LOG_FILE = "courseChoose.log"

LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 5

BASE = xl.APP            # https://yjsxk.xidian.edu.cn/yjsxkapp/sys/xsxkapp
TIMEOUT = xl.TIMEOUT     # (连接超时, 读取超时)


def load_cli_config():
    """仅在命令行入口加载 config.py，库导入时不读取明文凭据。"""
    global password, user_id, course_KCDM, sleep_time
    global BJMC_KEYWORD, XQMC_KEYWORD, POLL_INTERVAL, UNATTENDED, LOG_FILE
    global LOG_MAX_BYTES, LOG_BACKUP_COUNT
    try:
        import config
    except ImportError as exc:
        raise RuntimeError("请在项目目录下准备 config.py") from exc
    password = getattr(config, "password", "")
    user_id = getattr(config, "user_id", "")
    course_KCDM = getattr(config, "course_KCDM", "")
    sleep_time = getattr(config, "sleep_time", 15)
    BJMC_KEYWORD = getattr(config, "bjmc_keyword", "")
    XQMC_KEYWORD = getattr(config, "xqmc_keyword", "")
    POLL_INTERVAL = getattr(config, "poll_interval", 1.0)
    UNATTENDED = getattr(config, "unattended", False)
    LOG_FILE = getattr(config, "log_file", "courseChoose.log")
    LOG_MAX_BYTES = max(0, int(getattr(config, "log_max_bytes", 1_000_000)))
    LOG_BACKUP_COUNT = max(0, int(getattr(config, "log_backup_count", 5)))


class TeeLogger(object):
    """
    无人值守时把控制台输出同时写进日志文件，每行前面加时间戳。
    跑一晚上之后能直接回看什么时候会话过期、什么时候重登、有没有抢到。
    """

    def __init__(self, path, stream, max_bytes=1_000_000, backup_count=5):
        self.stream = stream
        self.path = os.path.abspath(path)
        self.max_bytes = max(0, int(max_bytes or 0))
        self.backup_count = max(0, int(backup_count or 0))
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._rotate_existing_if_needed()
        self.fh = open(self.path, "a", encoding="utf-8")
        self.at_line_start = True

    def _rotate_existing_if_needed(self):
        if not self.max_bytes or not os.path.exists(self.path):
            return
        try:
            if os.path.getsize(self.path) < self.max_bytes:
                return
            if not self.backup_count:
                with open(self.path, "w", encoding="utf-8"):
                    return
            for index in range(self.backup_count - 1, 0, -1):
                source = "{0}.{1}".format(self.path, index)
                destination = "{0}.{1}".format(self.path, index + 1)
                if os.path.exists(source):
                    os.replace(source, destination)
            os.replace(self.path, self.path + ".1")
        except OSError as exc:
            try:
                self.stream.write("[!] 日志轮转失败，将继续追加原文件：{0}\n".format(exc))
            except Exception:
                pass

    def _rotate_during_run_if_needed(self):
        if not self.max_bytes or self.fh.closed:
            return
        try:
            self.fh.flush()
            if os.path.getsize(self.path) < self.max_bytes:
                return
            self.fh.close()
            self._rotate_existing_if_needed()
            self.fh = open(self.path, "a", encoding="utf-8")
        except OSError as exc:
            try:
                self.stream.write("[!] 运行中日志轮转失败：{0}\n".format(exc))
            except Exception:
                pass
            if self.fh.closed:
                self.fh = open(self.path, "a", encoding="utf-8")

    def write(self, data):
        try:
            self.stream.write(data)
        except Exception:
            pass
        if not data or self.fh.closed:
            return
        self._rotate_during_run_if_needed()
        for chunk in data.splitlines(True):
            if self.at_line_start and chunk.strip():
                self.fh.write(time.strftime("[%m-%d %H:%M:%S] "))
            self.fh.write(chunk)
            self.at_line_start = chunk.endswith("\n")
        self.fh.flush()

    def flush(self):
        try:
            self.stream.flush()
        except Exception:
            pass
        if not self.fh.closed:
            try:
                self.fh.flush()
            except Exception:
                pass

    def close(self):
        """关日志文件，并把 sys.stdout 还原，避免解释器退出时再去 flush 已关闭的文件"""
        try:
            self.flush()
        finally:
            try:
                self.fh.close()
            except Exception:
                pass
            if sys.stdout is self:
                sys.stdout = self.stream


class SessionExpired(RuntimeError):
    """会话失效：需要重新登录（继承 RuntimeError，这样顶层兜底也能接住，不会甩一堆 traceback）"""


class ServerError(RuntimeError):
    """选课系统自己抛的内部错误（页面写着"系统异常/NullPointer"），不是我们请求写错"""


def loadJson(resp, what):
    """把响应按 JSON 解析；失败时给出可读原因，而不是让 JSONDecodeError 直接冒出来"""
    ctype = resp.headers.get("content-type", "")
    # 金智(wisedu) 系统常带 UTF-8 BOM，用 utf-8-sig 解码
    text = resp.content.decode("utf-8-sig", errors="replace")

    if resp.status_code != 200:
        raise RuntimeError(
            "{0} 请求失败：HTTP {1}，Content-Type={2}\n  URL={3}\n  响应前 300 字符：{4!r}"
            .format(what, resp.status_code, ctype, resp.url, text[:300]))

    # 注意：这套系统会拿 text/html 当 Content-Type 返回 JSON
    #（loadJhnCourseInfo.do 就是，HTTP 200 + text/html;charset=utf-8，body 却是 {"datas":[...]}），
    # 所以只能看 body 能不能解析，不能拿 Content-Type 当前提。
    try:
        return json.loads(text)
    except ValueError as e:
        if xl.is_server_error_page(text):
            # 学校系统自己抛的异常页（实测：_WEU 这个持久 cookie 失效时会触发 NullPointer）
            raise ServerError("{0} 遇到选课系统的内部错误：{1}\n  URL={2}\n  提示：这是学校系统侧的问题，"
                              "稍后重试即可（脚本会自动去掉 _WEU 重试一次）"
                              .format(what, xl.server_error_brief(text), resp.url)) from e
        hint = ""
        if "pwdEncryptSalt" in text or "loginName" in text or "authserver" in text:
            hint = "\n  -> 返回的是登录页：这次会话并没有登录成功"
        elif "400 Request Header Or Cookie Too Large" in text:
            hint = "\n  -> 网关 400，多半是接口前缀/域名不对"
        raise RuntimeError(
            "{0} 的响应无法按 JSON 解析：{1}\n  HTTP {2}，Content-Type={3}\n  URL={4}{5}\n  响应前 300 字符：{6!r}"
            .format(what, e, resp.status_code, ctype, resp.url, hint, text[:300])) from e


def request_json(session_client, method, url, what, **kwargs):
    """统一发请求：带超时、不自动跟随跳转（302 说明会话失效），再做 JSON 校验。
    遇到"系统异常"页时先去掉 _WEU 重试一次（实测那就是 _WEU 引起的服务端 NullPointer）。"""
    for attempt in (1, 2):
        resp = session_client.request(method, url, verify=False, timeout=TIMEOUT,
                                      allow_redirects=False, **kwargs)
        if resp.status_code in (301, 302, 303, 307, 308):
            raise SessionExpired("{0} 被重定向到 {1}（会话已失效）"
                                 .format(what, resp.headers.get("location")))
        try:
            return loadJson(resp, what)
        except ServerError:
            text = resp.content.decode("utf-8-sig", errors="replace")
            if attempt == 1 and xl.strip_transient_cookies(session_client):
                print("[!] 遇到系统异常页（{0}），已去掉 _WEU 后重试".format(xl.server_error_brief(text)))
                continue
            raise


def printCourseInfo(course):
    print("[+] 课程名称:", course.get("BJMC", course.get("KCMC", "")))
    print("[+] 校区:", course.get("XQMC", ""))
    print("[+] 上课时间和地点:", course.get("PKSJDDMS", course.get("PKSJDD", "")))
    print("[+] 任课教师:", course.get("RKJS", ""))


def getPublicInfo(session_client):
    """选课公共信息：未登录时 loginUserId 为空；若接口返回 csrfToken 就带上"""
    return request_json(session_client, "GET", BASE + "/xsxkHome/loadPublicInfo_course.do",
                        "获取选课公共信息(loadPublicInfo_course)")


# 选课页的各个课程来源（标签页）。第二个元素是列表接口，第三个是提交选课时必须带的 lx 参数。
# 实测：方案内课程 = loadJhnCourseInfo + lx 0；公选课 = loadGxkCourseInfo + lx 1；
#       方案外课程 = loadFanCourseInfo + lx 2；跨学科专业课 = loadKxkzykCourseInfo + lx 3。
# 提交选课时带错 lx 会被系统当成另一种选课方式处理，所以 lx 必须跟课程来源配套。
COURSE_SOURCES = (
    ("方案内课程", "/xsxkCourse/loadJhnCourseInfo.do", "0"),
    ("公选课", "/xsxkCourse/loadGxkCourseInfo.do", "1"),
    ("方案外课程", "/xsxkCourse/loadFanCourseInfo.do", "2"),
    ("跨学科专业课", "/xsxkCourse/loadKxkzykCourseInfo.do", "3"),
)


def queryCourseList(session_client, keyword="", page_size=200, retries=5, pause=15,
                    sources=None):
    """
    取课程列表。默认把上面几个来源都拉一遍（每条记录会打上 _lx / _source 两个内部字段，
    提交选课时要用 _lx）。
    实测：服务器端的 query_keyword 并不索引课程代码 —— 搜 "X1PE2070" / "X1MX0040"
    这种 KCDM 一律 total=0，所以关键字只用于列出时的本地过滤。
    遇到学校系统的"系统异常"错误页时等一会儿重试（那是它自己的 NullPointer）。
    """
    all_courses = []
    seen_bjdm = set()
    for source_name, path, lx in (sources or COURSE_SOURCES):
        page = 1
        while True:
            url = (BASE + path + "?query_keyword={0}&pageIndex={1}&pageSize={2}&_={3}"
                   .format(requests.utils.quote(keyword), page, page_size, int(time.time() * 1000)))
            for attempt in range(1, retries + 1):
                try:
                    data = request_json(session_client, "POST", url,
                                        "查询课程({0})".format(source_name))
                    break
                except ServerError as exc:
                    print("[!] {0}".format(exc))
                    if attempt >= retries:
                        raise
                    print("    {0}s 后重试（第 {1}/{2} 次）".format(pause, attempt, retries))
                    time.sleep(pause)
            datas = data.get("datas") or []
            for rec in datas:
                bjdm = rec.get("BJDM")
                if bjdm and bjdm in seen_bjdm:      # 同一教学班可能在多个来源里出现，只留第一次
                    continue
                if bjdm:
                    seen_bjdm.add(bjdm)
                rec["_lx"] = lx                     # 提交选课必须带的来源参数
                rec["_source"] = source_name
                all_courses.append(rec)
            total = data.get("total") or 0
            if not datas or len(datas) < page_size or page * page_size >= total or page >= 50:
                break
            page += 1
    return all_courses


def fetchChosenCourses(session_client):
    """已选课程（选课页"已选课程"标签的数据源）：返回 results 列表"""
    data = request_json(session_client, "GET",
                        BASE + "/xsxkCourse/loadStdCourseInfo.do?_={0}".format(int(time.time() * 1000)),
                        "查询已选课程(loadStdCourseInfo)")
    return data.get("results") or []


def formatChosen(course):
    return "{0} {1}（{2}）".format(course.get("KCDM", ""), course.get("KCMC", ""), course.get("BJMC", ""))


def verifyChosen(session_client, bjdm, tries=8, pause=2.0):
    """
    复核：到"已选课程"里确认这个教学班真的选上了。
    提交接口说成功不一定真成功，所以成功与否以这里为准。
    """
    for i in range(1, tries + 1):
        try:
            chosen = fetchChosenCourses(session_client)
        except (SessionExpired, ServerError, RuntimeError, requests.RequestException) as exc:
            print("[!] 复核已选课程时出错（{0}/{1}）：{2}".format(i, tries, exc))
            chosen = None
        if chosen is not None:
            for c in chosen:
                if c.get("BJDM") == bjdm:
                    return True, c
        if i < tries:
            time.sleep(pause)
    return False, None


def hasFreeSeat(course):
    """这个教学班还有空位吗（已选人数 < 容量）"""
    try:
        return int(course.get("DQRS") or 0) < int(course.get("KXRS") or 0)
    except (TypeError, ValueError):
        return False


def matchCampus(course, xqmc_keyword):
    """
    校区匹配：支持「北校区」「北」这种包含匹配，也支持用校区代码（01 南校区 / 02 北校区）；
    多个条件用 逗号/顿号/空格 分隔，任意命中即可（例如 "北校区,南校区"）。
    空条件表示不筛选。
    """
    keyword = str(xqmc_keyword or "").strip()
    if not keyword:
        return True
    xqmc = str(course.get("XQMC") or "")
    xqdm = str(course.get("XQDM") or "")
    for part in [p for p in keyword.replace("，", ",").replace("、", ",").replace(" ", ",").split(",") if p]:
        if part in xqmc:
            return True
        if part.isdigit() and xqdm.lstrip("0") == part.lstrip("0"):
            return True
    return False


def filterClasses(courses, course_KCDM, bjmc_keyword="", xqmc_keyword=""):
    """从本轮课程列表里挑出这个 KCDM 的教学班，并按 教学班名称 / 校区 过滤"""
    matched = [c for c in courses if course_KCDM == c.get("KCDM")]
    if bjmc_keyword:
        matched = [c for c in matched if bjmc_keyword in str(c.get("BJMC", ""))]
    if xqmc_keyword:
        matched = [c for c in matched if matchCampus(c, xqmc_keyword)]
    return matched


def pickClass(classes):
    """优先挑还有空位的教学班；全满时返回第一个（仅用于显示容量状态）"""
    if not classes:
        return None
    free = [c for c in classes if hasFreeSeat(c)]
    return free[0] if free else classes[0]


def campusesOf(courses, course_KCDM=None):
    """统计出现过的校区（可按课程代码过滤），用于提示可选值"""
    subset = [c for c in courses if course_KCDM is None or course_KCDM == c.get("KCDM")]
    stat = {}
    for c in subset:
        name = str(c.get("XQMC") or "")
        stat.setdefault(name, {"total": 0, "free": 0})
        stat[name]["total"] += 1
        if hasFreeSeat(c):
            stat[name]["free"] += 1
    return stat


def describeFilters(bjmc_keyword="", xqmc_keyword=""):
    parts = []
    if xqmc_keyword:
        parts.append("校区={0}".format(xqmc_keyword))
    if bjmc_keyword:
        parts.append("教学班名称含 {0}".format(bjmc_keyword))
    return "、".join(parts) if parts else "无"


def getCourseInfo(session_client, course_KCDM, bjmc_keyword="", xqmc_keyword="", verbose=False):
    """
    按课程代码 KCDM 找到要抢的教学班（可选按教学班名称 / 校区筛选）。
    同一门课通常有几十个教学班，优先返回「还有空位」的那个。
    """
    courses = queryCourseList(session_client)
    matched = filterClasses(courses, course_KCDM, bjmc_keyword, xqmc_keyword)
    if verbose:
        print("[*] 本轮次开放课程共 {0} 个教学班；课程 {1} 在筛选条件（{2}）下匹配 {3} 个"
              .format(len(courses), course_KCDM, describeFilters(bjmc_keyword, xqmc_keyword), len(matched)))
    return pickClass(matched)


def listCourses(session_client, keyword="", bjmc_keyword="", xqmc_keyword=""):
    """把本轮次的课程打出来，方便挑课程代码（python courseChoose.py --list 关键字）"""
    # 注意：关键字的过滤一律在本地做。服务器端的 query_keyword 只模糊匹配课程名，
    # 搜"羽毛球"这种班名返回 0 条（实测），交给它过滤会导致什么都看不到。
    courses = queryCourseList(session_client)
    if keyword:
        kk = keyword.strip().lower()
        courses = [c for c in courses
                   if kk in str(c.get("KCDM", "")).lower()
                   or keyword in str(c.get("KCMC", ""))
                   or keyword in str(c.get("BJMC", ""))
                   or keyword in str(c.get("RKJS", ""))
                   or kk in str(c.get("KCMCYW", "")).lower()]
    if bjmc_keyword:
        courses = [c for c in courses if bjmc_keyword in str(c.get("BJMC", ""))]
    if xqmc_keyword:
        courses = [c for c in courses if matchCampus(c, xqmc_keyword)]

    stat = campusesOf(courses)
    print("[*] 筛选条件：{0}；共 {1} 个教学班".format(
        describeFilters(bjmc_keyword, xqmc_keyword), len(courses)))
    if stat:
        print("[*] 校区分布：" + "，".join(
            "{0} {1} 个班（有空位 {2}）".format(name or "未知", v["total"], v["free"])
            for name, v in sorted(stat.items())))
    print("{0:<12} {1:<10} {2:<14} {3:<18} {4:<32} {5:>5} {6:>5}  {7}".format(
        "课程代码KCDM", "校区", "来源", "课程名称KCMC", "教学班BJMC", "容量", "已选", "时间地点"))
    for c in courses:
        print("{0:<12} {1:<10} {2:<14} {3:<18} {4:<32} {5:>5} {6:>5}  {7}{8}".format(
            str(c.get("KCDM", ""))[:12], str(c.get("XQMC", ""))[:10],
            str(c.get("_source", ""))[:14], str(c.get("KCMC", ""))[:18],
            str(c.get("BJMC", ""))[:32], c.get("KXRS", ""), c.get("DQRS", ""),
            str(c.get("PKSJDDMS", ""))[:36], "  ★" if hasFreeSeat(c) else ""))
    return courses


def listChosen(session_client, keyword=""):
    """打印已经选上的课程（python courseChoose.py --list --chosen）"""
    chosen = fetchChosenCourses(session_client)
    if keyword:
        chosen = [c for c in chosen
                  if keyword in str(c.get("KCDM", "")) or keyword in str(c.get("KCMC", ""))
                  or keyword in str(c.get("BJMC", "")) or keyword in str(c.get("RKJS", ""))]
    print("[*] 已选课程共 {0} 门：".format(len(chosen)))
    print("{0:<12} {1:<10} {2:<18} {3:<32} {4:>4}  {5}".format(
        "课程代码KCDM", "校区", "课程名称KCMC", "教学班BJMC", "学分", "时间地点"))
    for c in chosen:
        print("{0:<12} {1:<10} {2:<18} {3:<32} {4:>4}  {5}".format(
            str(c.get("KCDM", ""))[:12], str(c.get("XQMC", ""))[:10], str(c.get("KCMC", ""))[:18],
            str(c.get("BJMC", ""))[:32], c.get("XF", ""), str(c.get("PKSJDDMS", ""))[:40]))
    return chosen


def dropCourse(session_client, target, assume_yes=False):
    """
    退课：target 可以是课程代码 KCDM（退掉该课所有教学班）或教学班代码 BJDM。
    会先列出将要退的课程让你确认（--yes 可跳过确认）。
    """
    chosen = fetchChosenCourses(session_client)
    hits = [c for c in chosen if c.get("BJDM") == target or c.get("KCDM") == target]
    if not hits:
        print("[!] 已选课程里没有匹配 {0!r} 的记录".format(target))
        print("    可先跑 python courseChoose.py --list --chosen 看看已选课程")
        return False
    print("[*] 将要退掉以下 {0} 门课程：".format(len(hits)))
    for c in hits:
        print("    {0}".format(formatChosen(c)))
    if not assume_yes:
        answer = input("[?] 确认退课请输入 yes：").strip().lower()
        if answer != "yes":
            print("[*] 已取消")
            return False
    public_info = getPublicInfo(session_client)
    csrf_token = public_info.get("csrfToken") if isinstance(public_info, dict) else None
    all_ok = True
    for c in hits:
        ok, why = cancelCourse(session_client, c.get("BJDM"), csrf_token)
        print("{0} {1} {2}".format("[+]" if ok else "[x]", formatChosen(c), why or ""))
        all_ok = all_ok and ok
    return all_ok


def chooseCourse(session_client, course_BJDM, csrf_token=None, lx="0", max_polls=30,
                 verbose=True):
    """
    提交选课，并等出真正的结果（两步式协议，见文件头说明）。
    :param course_BJDM: 教学班代码（列表接口里的 BJDM）
    :param csrf_token:  选课公共信息里的 csrfToken
    :param lx:          课程来源，必须和列表来源配套（方案内=0 / 公选=1 / 方案外=2 / 跨学科=3）
    :return: (是否真的选上, 说明信息)
    """
    # ---- 第一步：提交选课请求 ----
    submit_url = BASE + "/xsxkCourse/choiceCourse.do?_={0}".format(int(time.time() * 1000))
    body = {"bjdm": course_BJDM, "lx": lx, "csrfToken": csrf_token or ""}
    data = request_json(session_client, "POST", submit_url, "提交选课(choiceCourse)", data=body)

    code = str(data.get("code"))
    msg = data.get("msg") or data.get("message") or ""
    if code == "0":
        # 提交阶段就被拒：容量/时间冲突/学分上限/不在可选范围等，msg 里写着原因
        return False, "提交被拒绝：{0}".format(msg or "（接口未给出原因）")
    if not msg:
        return False, "提交后没有拿到流水号（xid），响应：{0}".format(str(data)[:200])
    if verbose:
        print("[*] 选课请求已受理（xid={0}），正在查询处理结果…".format(str(msg)[:60]))

    # ---- 第二步：轮询 loadXkjgRes 拿真正的结果 ----
    for i in range(1, max_polls + 1):
        time.sleep(0.5 if i == 1 else random.uniform(0.8, 2.0))
        try:
            res = request_json(session_client, "POST",
                               BASE + "/xsxkCourse/loadXkjgRes.do?_={0}".format(int(time.time() * 1000)),
                               "查询选课结果(loadXkjgRes)",
                               data={"xid": msg, "sfhqdqxkqqs": 1 if i == 1 else 0})
        except (SessionExpired, ServerError):
            raise
        except RuntimeError as exc:
            if verbose:
                print("[!] 查结果出错（{0}/{1}）：{2}".format(i, max_polls, exc))
            continue

        dqxkqqs = res.get("dqxkqqs")
        if dqxkqqs and str(dqxkqqs).isdigit() and int(dqxkqqs) >= 200 and verbose:
            print("[*] 系统高峰期：当前有 {0} 个选课请求在处理中…".format(dqxkqqs))

        payload = res.get("msg")
        if payload in (None, ""):
            if verbose and i % 5 == 0:
                print("[*] 结果还没出来（已等 {0} 次）…".format(i))
            continue

        result = payload if isinstance(payload, dict) else json.loads(payload)
        ok = str(result.get("code")) == "1"
        return ok, "{0}".format(result.get("msg") or ("选课成功" if ok else "接口未给出原因"))

    return False, "轮询 {0} 次仍没有结果（系统太忙），请稍后在\"已选课程\"里确认".format(max_polls)


def cancelCourse(session_client, course_BJDM, csrf_token=None):
    """退课（POST cancelCourse.do，form body: bjdm / csrfToken）。返回 (是否成功, 说明)"""
    url = BASE + "/xsxkCourse/cancelCourse.do?_={0}".format(int(time.time() * 1000))
    data = request_json(session_client, "POST", url, "退课(cancelCourse)",
                        data={"bjdm": course_BJDM, "csrfToken": csrf_token or ""})
    ok = str(data.get("code")) == "1"
    return ok, "{0}".format(data.get("msg") or "")


def try_relogin(session_client, captcha_provider=None, attempts=3, pause=20):
    """
    重新登录。captcha_provider 传 ddddocr 的回调即无人值守（不用人守验证码）。
    失败也不抛出去，交给主循环稍后再试，这样长时间挂机不会因为一次登录失败就整个脚本崩掉。
    """
    for i in range(1, attempts + 1):
        try:
            xl.relogin(session_client, user_id, password, captcha_provider=captcha_provider)
            return True
        except xl.LoginError as exc:
            print("[x] 重新登录失败（{0}/{1}）：{2}".format(i, attempts, exc))
            if i < attempts:
                time.sleep(pause)
    print("[!] 这次没能重新登录成功，{0}s 后主循环会再试".format(sleep_time))
    return False


def recover_session(session_client, reason, captcha_provider=None):
    """
    出错后的自愈：先确认会话真实状态，真的失效了才重新登录（避免白输验证码）。
    返回 True 表示可以继续跑。
    """
    print("[!] {0}".format(reason))
    ok, why = xl.login_state(session_client)
    if ok is True:
        print("[*] 会话其实还有效（{0}），继续".format(why))
        return True
    print("[*] 会话状态：{0}".format(why))
    return try_relogin(session_client, captcha_provider=captcha_provider)


def main(bjmc_keyword=BJMC_KEYWORD, xqmc_keyword=XQMC_KEYWORD, session_client=None,
         captcha_provider=None):
    KCDM = course_KCDM
    if session_client is None:            # 也可以在外部先建好 session 再传进来，避免重复登录
        session_client = xl.ensure_session(user_id, password, captcha_provider=captcha_provider)

    public_info = getPublicInfo(session_client)
    csrf_token = public_info.get("csrfToken") if isinstance(public_info, dict) else None
    if csrf_token:
        print("[*] 拿到 csrfToken")
    if not str((public_info or {}).get("loginUserId") or "").strip():
        print("[!] 警告：公共信息里 loginUserId 还是空的，可能没真正登录")

    print("[*] 目标课程代码：{0}；筛选条件：{1}".format(KCDM, describeFilters(bjmc_keyword, xqmc_keyword)))
    try:
        courses = queryCourseList(session_client)
    except SessionExpired as exc:
        # 启动阶段也可能撞上会话过期，这里同样自愈一次，别让脚本一上来就退出
        if not recover_session(session_client, "{0}".format(exc), captcha_provider):
            raise
        courses = queryCourseList(session_client)
    classes = filterClasses(courses, KCDM, bjmc_keyword, xqmc_keyword)
    print("[*] 本轮次开放课程共 {0} 个教学班；课程 {1} 在筛选条件（{2}）下匹配 {3} 个"
          .format(len(courses), KCDM, describeFilters(bjmc_keyword, xqmc_keyword), len(classes)))

    if not classes:
        same_kcdm = filterClasses(courses, KCDM)      # 不加筛选，看看这门课本身在不在
        if same_kcdm:
            stat = campusesOf(courses, KCDM)
            print("[+] 课程 {0} 本轮有 {1} 个教学班，但都被筛选条件排除了。".format(KCDM, len(same_kcdm)))
            print("    它的校区分布：" + "，".join(
                "{0} {1} 个班（有空位 {2}）".format(n or "未知", v["total"], v["free"])
                for n, v in sorted(stat.items())))
            print("    把 xqmc_keyword / bjmc_keyword 放宽或去掉再试（命令行可用 --xq / --bj 临时指定）")
        else:
            print("[+] 本轮次里没有找到课程代码 {0}。".format(KCDM))
            print("    可能的原因：代码写错、这门课本轮没开放、或它不在你这次可选范围内。")
            print("    本轮开放的全部校区：" + "，".join(
                "{0} {1} 个班".format(n or "未知", v["total"]) for n, v in sorted(campusesOf(courses).items())))
            print("    想看本轮到底有哪些课（含课程代码），执行：")
            print("      python courseChoose.py --list                 # 全部")
            print("      python courseChoose.py --list 英语 --xq 南校区  # 按关键字 + 校区过滤")
        return

    course_info = pickClass(classes)
    course_KXRS = course_info["KXRS"]  # 课程总容量
    course_DQRS = course_info["DQRS"]  # 当前选课人数
    print("[*] 选中教学班：{0}（{1}，容量 {2}，已选 {3}）{4}"
          .format(course_info.get("BJMC", KCDM), course_info.get("XQMC", ""), course_KXRS, course_DQRS,
                  "  ★还有空位" if hasFreeSeat(course_info) else "  （已满，等别人退课）"))
    print("[*] 上课时间地点：{0}".format(course_info.get("PKSJDDMS", "")))
    last_bjdm = course_info.get("BJDM")

    while True:
        started = time.time()
        try:
            # ---- 1) 有空位就下单，满了就等 ----
            if course_DQRS < course_KXRS:
                ok, why = chooseCourse(session_client, course_info["BJDM"], csrf_token,
                                       lx=course_info.get("_lx", "0"))
                if ok:
                    # 关键：提交接口说成功不算数，要去"已选课程"里复核到才算选上
                    print("[*] 接口表示选课成功（{0}），正在\"已选课程\"里复核…".format(why))
                    verified, entry = verifyChosen(session_client, course_info["BJDM"])
                    if verified:
                        print("[+] 选课成功（已在已选课程中确认）!")
                        print("[+] 课程信息如下:")
                        printCourseInfo(entry or course_info)
                        return
                    print("[!] 接口说成功，但\"已选课程\"里暂时没看到这个教学班。")
                    print("    常见原因：系统正在排队处理、或该轮次需要后续确认。")
                    print("    脚本不会退出，会继续盯这门课；你也可以随时用")
                    print("      python courseChoose.py --list --chosen   # 查看已选课程")
                    print("    确认一下。")
                else:
                    print("[!] 本次选课未成功：{0}".format(why))
            else:
                print("[+] 当前课程容量已满!")
                time.sleep(sleep_time)    # 每 sleep_time 秒查询一次

            # ---- 2) 监控选课人数的变化（选课失败后立即重试，保持抢课原有的节奏）----
            course_info = getCourseInfo(session_client, KCDM, bjmc_keyword, xqmc_keyword)
            if course_info is None:
                # 课程从可选列表里消失有两种可能：已经选上了（系统会把已选课程从可选列表移除），
                # 或者轮次变了/不在范围内。先查"已选课程"确认一下，别傻等。
                chosen = fetchChosenCourses(session_client)
                already = [c for c in chosen if c.get("KCDM") == KCDM]
                if already:
                    print("[+] 课程 {0} 已经在\"已选课程\"里了，说明已经选上：".format(KCDM))
                    for c in already:
                        print("    {0}".format(formatChosen(c)))
                    printCourseInfo(already[0])
                    return
                print("[!] 暂时查不到满足筛选条件的教学班，{0}s 后重试".format(sleep_time))
                time.sleep(sleep_time)
                continue
            if course_info.get("BJDM") != last_bjdm:
                last_bjdm = course_info.get("BJDM")
                print("[*] 换到这个教学班：{0}（{1}，{2}/{3}）{4}".format(
                    course_info.get("BJMC", ""), course_info.get("XQMC", ""),
                    course_info.get("DQRS", ""), course_info.get("KXRS", ""),
                    course_info.get("PKSJDDMS", "")))
            course_KXRS = course_info["KXRS"]  # 课程总容量
            course_DQRS = course_info["DQRS"]  # 当前选课人数

        except SessionExpired as exc:
            # 会话失效可能出现在任何一步（下单、查询、监控），这里统一处理，不再让脚本崩掉
            if recover_session(session_client, "{0}".format(exc), captcha_provider):
                try:
                    public_info = getPublicInfo(session_client)
                    csrf_token = public_info.get("csrfToken") if isinstance(public_info, dict) else None
                    refreshed = getCourseInfo(session_client, KCDM, bjmc_keyword, xqmc_keyword)
                    if refreshed:
                        course_info = refreshed
                        last_bjdm = course_info.get("BJDM")
                        course_KXRS = course_info["KXRS"]     # 同步刷新容量，避免打印陈旧的"已满"
                        course_DQRS = course_info["DQRS"]
                        print("[*] 重登后继续盯：{0}（{1}，{2}/{3}）"
                              .format(course_info.get("BJMC", ""), course_info.get("XQMC", ""),
                                      course_DQRS, course_KXRS))
                except (SessionExpired, ServerError, requests.RequestException) as inner:
                    # 自愈过程中再出错也不能把整个脚本带崩，下一轮继续
                    print("[!] 重登后刷新课程信息失败：{0}".format(inner))
                    time.sleep(15)
            else:
                time.sleep(sleep_time)
        except ServerError as exc:
            # 学校系统自己的 NullPointer：先确认是不是会话过期引起的，再决定是否重登
            recover_session(session_client, "{0}".format(exc), captcha_provider)
            time.sleep(15)
        except requests.RequestException as exc:
            # 网络抖动也别让长跑的脚本退出
            print("[!] 网络异常：{0}，{1}s 后继续".format(exc, 15))
            time.sleep(15)
        finally:
            # 两次轮询之间至少间隔 POLL_INTERVAL，避免把学校系统刷崩（拉的是整份课程列表）
            elapsed = time.time() - started
            if elapsed < POLL_INTERVAL:
                time.sleep(POLL_INTERVAL - elapsed)


def parse_args(argv):
    """很简单的参数解析：
       --list [关键字]     只看课程，不选课
       --xq 校区           校区筛选（北校区 / 南校区 / 北 / 02，多个用逗号）
       --bj 片段           教学班名称筛选
       --unattended        无人值守：用 ddddocr 自动识别验证码（等价于 config.py 里 unattended = True）
       --manual            强制人工输入验证码（覆盖 config.py 的 unattended）
       --log 文件          把输出同时写进日志文件（--unattended 时默认写 courseChoose.log）
       --no-log            不写日志文件
    """
    args = {"list": False, "keyword": "", "xqmc_keyword": XQMC_KEYWORD, "bjmc_keyword": BJMC_KEYWORD,
            "unattended": None, "log": None, "chosen": False, "drop": None, "yes": False}
    rest = list(argv)
    for flag, key in (("--xq", "xqmc_keyword"), ("--bj", "bjmc_keyword"), ("--log", "log")):
        if flag in rest:
            i = rest.index(flag)
            if len(rest) > i + 1:
                value = rest[i + 1]
                # --xq all / --bj 不限 ：用来临时取消 config.py 里配的筛选条件
                if key != "log" and value.strip().lower() in ("all", "*", "-", "全部", "不限", "none"):
                    value = ""
                args[key] = value
                del rest[i:i + 2]
            else:
                del rest[i]
    if "--unattended" in rest:
        args["unattended"] = True
        rest.remove("--unattended")
    if "--manual" in rest:
        args["unattended"] = False
        rest.remove("--manual")
    if "--no-log" in rest:
        args["log"] = ""
        rest.remove("--no-log")
    if "--list" in rest:
        i = rest.index("--list")
        args["list"] = True
        remaining = [a for a in rest[i + 1:] if not a.startswith("--")]
        args["keyword"] = remaining[0] if remaining else ""
    if "--chosen" in rest:
        args["chosen"] = True
        rest.remove("--chosen")
    if "--yes" in rest:
        args["yes"] = True
        rest.remove("--yes")
    if "--drop" in rest:
        i = rest.index("--drop")
        if len(rest) > i + 1:
            args["drop"] = rest[i + 1]
            del rest[i:i + 2]
        else:
            del rest[i]
    return args


if __name__ == '__main__':
    logger = None
    try:
        load_cli_config()
        opts = parse_args(sys.argv[1:])
        # 无人值守 = 命令行开关 > config.py 里的 unattended
        unattended = UNATTENDED if opts["unattended"] is None else opts["unattended"]
        captcha_provider = xl.make_captcha_provider(unattended=unattended) if unattended else None

        # 日志：默认给无人值守配上，方便跑一晚上后回看
        log_path = opts["log"]
        if log_path is None:
            log_path = LOG_FILE if (unattended and LOG_FILE) else ""
        if log_path:
            if not os.path.isabs(log_path):      # 相对路径按脚本所在目录算，别受当前工作目录影响
                log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), log_path)
            logger = TeeLogger(
                log_path,
                sys.stdout,
                max_bytes=LOG_MAX_BYTES,
                backup_count=LOG_BACKUP_COUNT,
            )
            sys.stdout = logger
            print("[*] 已开启日志：{0}".format(log_path))
        if unattended:
            print("[*] 无人值守模式：验证码由 ddddocr 自动识别")

        session = xl.ensure_session(user_id, password, captcha_provider=captcha_provider)
        if opts.get("drop"):
            # python courseChoose.py --drop <KCDM 或 BJDM> [--yes] ：退课
            ok = dropCourse(session, opts["drop"], assume_yes=opts.get("yes", False))
            if not ok:
                raise SystemExit(1)
        elif opts.get("chosen"):
            # python courseChoose.py --list --chosen [关键字] ：看已选课程
            listChosen(session, opts["keyword"])
        elif opts["list"]:
            # python courseChoose.py --list [关键字] [--xq 北校区] [--bj 35]  ：只看课程，不选课
            listCourses(session, opts["keyword"], opts["bjmc_keyword"], opts["xqmc_keyword"])
        else:
            main(opts["bjmc_keyword"], opts["xqmc_keyword"], session, captcha_provider)
    except KeyboardInterrupt:
        print("\n[+] 已手动停止")
        raise SystemExit(0)
    except (RuntimeError, requests.RequestException) as e:
        # 这些异常里已经写清了 HTTP 状态码、URL 和响应开头，直接看这一段就够了
        print("[x] {0}".format(e))
        raise SystemExit(1)
    finally:
        print("[+] Finish")
        if logger is not None:
            logger.close()
