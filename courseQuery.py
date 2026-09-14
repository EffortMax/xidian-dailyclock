# Author: fe1w0
# 生成课程表（可导入 wake up 等课程表 App）
#
# 接口已随选课系统迁移到 https://yjsxk.xidian.edu.cn/yjsxkapp/sys/xsxkapp/，
# 登录方式也从「统一身份认证 SSO + AES 加密密码」改为「选课系统自带登录 + 图片验证码 + DES」，
# 统一由 xidian_login.py 处理（默认无人值守：ddddocr 自动识别验证码，会话过期会自动重登）。
#
# 用法：
#   python courseQuery.py                 # 导出已选课程到 course.csv
#   python courseQuery.py --unattended    # 强制用 ddddocr 自动识别验证码
#   python courseQuery.py --manual        # 临时改回人工输入验证码
#   python courseQuery.py --semester 2026秋   # 只导某个学期的课
#   python courseQuery.py --all            # 连没有固定上课时间的课也一并输出（周数列留空）
#
# 注意（踩过的坑）：
#   1) 课表接口 loadKbxx.do 返回的 xkjgList 里，有些课（如"学术规范与论文写作""科研伦理与学术规范"
#      这类线上/慕课型课程）根本没有排课时间，PKSJDD / PKSJDDMS 都是 null。
#      老代码直接 course["PKSJDD"].split(";")，于是抛 AttributeError: 'NoneType' object has no attribute 'split'。
#   2) PKSJDD 里同一条记录可能含多段，用 ";" 分隔；每段形如
#        "6-17周 星期四[9-11节]J-308" 或 "2-4,6-14周 星期一[5-6节]北校区体育馆"
#      —— 周数可能是 "6周" / "6-17周" / "2-4,6-14周" 三种写法。
#   3) 地点可能缺失，或者写成"北校区体育馆"这种没有楼栋号的；课程名里可能带 "(北校区)" 前缀。
#      这些都不该让脚本崩掉，缺什么就留空/标注"未知"。

import argparse
import csv
import json
import os
import re
import sys
import time

import requests

import xidian_login as xl
password = ""
user_id = ""

BASE = xl.APP            # https://yjsxk.xidian.edu.cn/yjsxkapp/sys/xsxkapp
TIMEOUT = xl.TIMEOUT     # (连接超时, 读取超时)
HERE = os.path.dirname(os.path.abspath(__file__))

try:
    # 可选：在 config.py 里写 xqmc_keyword/... 之外，也读一下无人值守开关与日志设置
    UNATTENDED = False if os.environ.get("XDU_LIBRARY_MODE") else __import__("config").unattended
except ImportError:
    UNATTENDED = False

WEEK_DAYS = ('星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日')

# 默认只导"有排课时间"的课；--all 时把没有时间的课也写进 CSV（周数/星期/节次留空）
INCLUDE_UNSCHEDULED = False
SEMESTER_FILTER = ""


def parse_weeks(week_text):
    """
    把 "6-17周" / "6周" / "2-4,6-14周" 规范化成字符串：
      去掉"周"字，逗号统一成中文顿号（wake up 导入时按此写法识别多段周次）
    """
    return str(week_text).replace("周", "").replace(",", "、").strip()


def parse_one_item(item):
    """
    解析一段上课时间，形如 "6-17周 星期四[9-11节]J-308"。
    返回 dict 或 None（解析不出来时返回 None，交给调用方跳过并记警告）。
    """
    item = str(item).strip()
    if not item:
        return None
    # 周次与"星期几[...]"之间用空格分开，但也有可能用全角空格
    parts = re.split(r"[\s\u3000]+", item, maxsplit=1)
    if len(parts) < 2:
        return None
    week_text, detail = parts[0], parts[1]

    day_match = re.search(r"星期[一二三四五六日天]", detail)
    if not day_match:
        return None
    day_text = day_match.group(0).replace("星期天", "星期日")
    try:
        day = WEEK_DAYS.index(day_text) + 1
    except ValueError:
        return None

    lesson_match = re.search(r"\[(\d+)-(\d+)节\]", detail)
    if lesson_match:
        start_lesson, end_lesson = lesson_match.group(1), lesson_match.group(2)
    else:
        # 有些课只给一个节次，如 [9节]
        single = re.search(r"\[(\d+)节\]", detail)
        if not single:
            return None
        start_lesson = end_lesson = single.group(1)

    # 节次后面剩下的就是地点（可能没有）
    tail = detail[lesson_match.end():] if lesson_match else detail[single.end():]
    classroom = tail.strip(" ]") or ""

    return {"周数": parse_weeks(week_text), "星期": day,
            "开始节数": start_lesson, "结束节数": end_lesson, "地点": classroom}


def parse_PKSJDD(course, warnings=None):
    """
    解析一条课程的 PKSJDD，返回若干条 wake up 记录片段。
    PKSJDD 为 None/空（线上课、慕课等没有排课时间）时返回空列表，不再抛异常。
    多段之间的分隔符见过两种：课表接口用 ";"，课程列表接口用 "<br>"，所以两种都切。
    """
    raw = course.get("PKSJDD")
    if not raw or not str(raw).strip():
        return []
    text = re.sub(r"<br\s*/?>", ";", str(raw), flags=re.I)     # <br> 统一成 ;
    rows = []
    for item in text.split(";"):
        parsed = parse_one_item(item)
        if parsed is None:
            if warnings is not None and str(item).strip():
                warnings.append("无法解析的上课时间片段：{0!r}（课程 {1}）".format(
                    str(item).strip(), course.get("KCMC", "")))
            continue
        parsed["课程名称"] = course.get("课程名称", "")
        parsed["老师"] = course.get("老师", "")
        rows.append(parsed)
    return rows


def fetchChosenCourses(session_client):
    """已选课程（课表接口里的 xkjgList 就是已选结果，loadStdCourseInfo 的 results 同源）"""
    url = BASE + "/xsxkCourse/loadKbxx.do?_={0}".format(int(time.time() * 1000))
    resp = session_client.get(url, verify=False, timeout=TIMEOUT, allow_redirects=False)
    if resp.status_code in (301, 302, 303, 307, 308):
        raise RuntimeError("课表接口被重定向到 {0}，会话已失效".format(resp.headers.get("location")))
    if resp.status_code != 200:
        raise RuntimeError("[x] 取课表失败：HTTP {0}\n  URL={1}\n  响应前 300 字符：{2!r}".format(
            resp.status_code, resp.url, resp.content[:300]))
    # 金智系统常带 UTF-8 BOM，而且会拿 text/html 当 Content-Type 返回 JSON，所以直接看 body
    text = resp.content.decode("utf-8-sig", errors="replace")
    try:
        data = json.loads(text)
    except ValueError as e:
        raise RuntimeError("[x] 课表接口返回的不是 JSON：{0}\n  HTTP {1}，Content-Type={2}\n  URL={3}\n"
                           "  响应前 300 字符：{4!r}".format(
                               e, resp.status_code, resp.headers.get("content-type"), resp.url, text[:300]))
    return data.get("xkjgList") or []


def buildRows(courses, include_unscheduled=False, warnings=None):
    """把课程列表转成 wake up 可导入的行；顺带统计没有排课时间的课"""
    rows = []
    unscheduled = []
    for course in courses:
        name = "({0}){1}".format(course.get("XQMC", ""), course.get("KCMC", ""))
        info = {"课程名称": name, "PKSJDD": course.get("PKSJDD"),
                "老师": course.get("RKJS", ""), "KCMC": course.get("KCMC", "")}
        parsed = parse_PKSJDD(info, warnings)
        if not parsed:
            unscheduled.append(course)
            if include_unscheduled:
                rows.append({"课程名称": name, "星期": "", "开始节数": "", "结束节数": "",
                             "老师": course.get("RKJS", ""), "地点": "", "周数": "",
                             "备注": "无固定上课时间"})
            continue
        for r in parsed:
            rows.append({"课程名称": r["课程名称"], "星期": r["星期"], "开始节数": r["开始节数"],
                         "结束节数": r["结束节数"], "老师": r["老师"], "地点": r["地点"],
                         "周数": r["周数"], "备注": ""})
    return rows, unscheduled


def main():
    session_client = xl.ensure_session(
        user_id, password, captcha_provider=CAPTCHA_PROVIDER)

    courses = fetchChosenCourses(session_client)
    print("[*] 共取到 {0} 条课程记录".format(len(courses)))

    if SEMESTER_FILTER:
        kept = [c for c in courses if str(c.get("XNXQMC") or "") == SEMESTER_FILTER]
        print("[*] 学期过滤 {0!r}：{1} -> {2} 条".format(SEMESTER_FILTER, len(courses), len(kept)))
        courses = kept

    warnings = []
    rows, unscheduled = buildRows(courses, INCLUDE_UNSCHEDULED, warnings)

    for w in warnings:
        print("[!] {0}".format(w))
    if unscheduled:
        print("[*] 其中 {0} 门课没有排课时间（线上课/慕课，课表接口里 PKSJDD 为 null），已跳过："
              .format(len(unscheduled)))
        for c in unscheduled:
            print("      {0} {1}（{2}）".format(c.get("KCDM", ""), c.get("KCMC", ""),
                                               "已选" if c.get("BJMC") is None else c.get("BJMC", "")))
        print("    想把这些课也写进 CSV（周数/星期/节次留空），加参数 --all")

    dict_info = ["课程名称", "星期", "开始节数", "结束节数", "老师", "地点", "周数", "备注"]
    out_path = os.path.join(HERE, "course.csv")
    with open(out_path, "w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=dict_info)
        writer.writeheader()
        writer.writerows({k: row.get(k, "") for k in dict_info} for row in rows)

    print("[*] 解析出 {0} 条上课安排：".format(len(rows)))
    for row in rows:
        print("    周{0} 第{1}-{2}节 {3} | {4} | {5}".format(
            row["星期"], row["开始节数"], row["结束节数"],
            row["地点"] or "地点未知", row["课程名称"], row["周数"] or ""))
    print("[+] 已写入 {0}，共 {1} 条".format(out_path, len(rows)))
    print("[+] Finish")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="导出已选课程到 course.csv（wake up 可导入）")
    parser.add_argument("--unattended", action="store_true", help="用 ddddocr 自动识别验证码")
    parser.add_argument("--manual", action="store_true", help="人工输入验证码")
    parser.add_argument("--all", action="store_true", help="连没有排课时间的课也写进 CSV")
    parser.add_argument("--semester", default="", help="只导该学期，例如 2026秋")
    return parser.parse_args(argv)


if __name__ == '__main__':
    try:
        import config
    except ImportError as exc:
        raise SystemExit("请在项目目录下准备 config.py（user_id / password）") from exc
    user_id = getattr(config, "user_id", "")
    password = getattr(config, "password", "")
    UNATTENDED = getattr(config, "unattended", False)
    args = parse_args(sys.argv[1:])
    INCLUDE_UNSCHEDULED = args.all
    SEMESTER_FILTER = args.semester
    UNATTENDED = False if args.manual else (True if args.unattended else UNATTENDED)
    CAPTCHA_PROVIDER = xl.make_captcha_provider(unattended=UNATTENDED) if UNATTENDED else None
    try:
        main()
    except KeyboardInterrupt:
        print("\n[+] 已手动停止")
        raise SystemExit(0)
    except (RuntimeError, requests.RequestException) as e:
        print("[x] {0}".format(e))
        raise SystemExit(1)
