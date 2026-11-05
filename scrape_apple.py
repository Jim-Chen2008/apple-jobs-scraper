#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apple 中国区「计算机相关」岗位爬虫 + 分析报告生成器（健壮版：自动重试 + 断点续传）

工作方式：
  1. GET /api/v1/CSRFToken 取 CSRF token + 会话 cookie（Apple 必须）
  2. POST /api/v1/search 用 postLocation-CHNC 分页拉取中国区全部岗位
  3. 按标题/团队关键词过滤出「计算机相关专业」岗位
  4. 对命中岗位逐个 GET /api/v1/jobDetails/{positionId} 取任职要求
  5. 输出 JSON 数据 + Markdown 分析报告

用法：
  python3 scrape_apple.py             # 全流程
  python3 scrape_apple.py --no-detail # 只抓列表不抓详情（快）
支持断点续传：中断后重跑会自动跳过已抓取的页/岗位。
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error
import http.cookiejar
from collections import Counter

BASE = "https://jobs.apple.com"
API = BASE + "/api/v1"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
REF = BASE + "/zh-cn/search"
LOCALE = "zh-CN"
CHINA_FILTER = {"locations": ["postLocation-CHNC"]}
PROGRESS_LIST = "progress_china.json"
PROGRESS_DETAIL = "progress_detail.json"


# ===== 精细化「计算机相关」分类（口径与 analyze_apple.py 一致，产出 ~259 条）=====
# 明确属于计算机/软件/数据/AI 的团队
CORE_TEAMS = {"SFTWR", "MLAI"}

# HRDWR(硬件) 中偏「计算机/软件/嵌入式/系统」的关键词 -> 纳入
HW_INCLUDE = [
    "software", "embedded", "firmware", "silicon", "soc ", "rtos", "driver",
    "machine learning", "ml ", "deep learning", "validation", "automation",
    "wireless", "rf", "network", "security", "system", "algorithm",
    "computer vision", "ai ", "data", "infrastructure", "platform", "backend",
    "cloud", "devops", "sre", " sdet", "qa", "test", "camera", "signal",
    "digital", "fpga", "verification", "architect", "建模", "仿真",
]
# HRDWR 中偏「制造/质量/工艺/材料/结构」的关键词 -> 排除
HW_EXCLUDE = [
    "manufacturing", "mechanical", "display", "material", "molding",
    "failure analysis", "quality", "process", "supplier", "optical",
    "packaging", "enclosure", "product design", "dfm", "thermal", "acoustic",
    "battery", "magnet", "magnetics", "ink", "coating", "metrology", "speaker",
    "天线", "antenna", "lens", "注塑", "layout", "cad",
]
# 完全排除的团队（销售/市场/职能/零售等）
EXCLUDE_TEAMS = {"SLDEV", "MKTG", "CORSV", "APPST"}
# 即便在软件/ML 团队内，以下明显非工程类标题也排除
EXCLUDE_TITLE = ["marketing", "recruit", "business manager", "communications",
                 "公关", "人力", "sales", "account", "evangelist"]
# OPMFG 中仅保留明显数据/算法/自动化岗
OPMFG_INCLUDE = ["data", "机器学习", "算法", "automation", "python", "软件", "ml ", "ai "]


def classify(job):
    """返回岗位分类：core / hw_sw / data / intern，非计算机相关返回 None。"""
    t = job.get("team") or {}
    code = (t.get("teamCode") or "").upper() if isinstance(t, dict) else ""
    title = (job.get("postingTitle") or "").lower()
    if code in EXCLUDE_TEAMS:
        return None
    if code in CORE_TEAMS:
        if any(k in title for k in EXCLUDE_TITLE):
            return None
        return "core"
    if code == "HRDWR":
        if any(k in title for k in HW_EXCLUDE):
            return None
        if any(k in title for k in HW_INCLUDE):
            return "hw_sw"
        return None
    if code == "OPMFG":
        if any(k in title for k in OPMFG_INCLUDE):
            return "data"
        return None
    if code == "STDNT":
        # 仅保留软件/数据/ML 实习
        if any(k in title for k in ["software", "data", "ml ", "machine learning",
                                    "算法", "机器学习", "开发", "embedded", "ai "]):
            return "intern"
        return None
    return None


class Session:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj))
        self.token = None
        self.refresh()

    def refresh(self):
        for _ in range(3):
            try:
                req = urllib.request.Request(API + "/CSRFToken", headers={"User-Agent": UA})
                resp = self.opener.open(req, timeout=20)
                self.token = resp.headers.get("X-Apple-CSRF-Token")
                if self.token:
                    return self.token
            except Exception as e:
                print("  CSRF retry:", e, file=sys.stderr)
                time.sleep(1.5)
        return None

    def _request(self, url, method, data=None):
        last = None
        for attempt in range(5):
            try:
                req = urllib.request.Request(url, data=data, method=method)
                req.add_header("User-Agent", UA)
                req.add_header("X-Apple-CSRF-Token", self.token or "")
                req.add_header("Referer", REF)
                if data is not None:
                    req.add_header("Content-Type", "application/json")
                resp = self.opener.open(req, timeout=25)
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 401:
                    self.refresh()
                    continue
                time.sleep(1.5)
            except Exception as e:
                last = e
                time.sleep(1.5 + attempt)
        print(f"  !! request failed after retries: {url} -> {last}", file=sys.stderr)
        return None

    def post(self, url, body):
        return self._request(url, "POST", json.dumps(body).encode("utf-8"))

    def get(self, url):
        return self._request(url, "GET")


def search_china(sess, page):
    body = {
        "query": "",
        "filters": CHINA_FILTER,
        "page": page,
        "locale": LOCALE,
        "sort": "relevance",
        "format": {"longDate": "MMMM D, YYYY", "mediumDate": "MMM D, YYYY"},
    }
    return sess.post(API + "/search", body)


def load_progress(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_progress(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def fetch_all_china(sess):
    prog = load_progress(PROGRESS_LIST, {"next_page": 1, "jobs": []})
    jobs = prog.get("jobs", [])
    page = prog.get("next_page", 1)
    seen = {j.get("positionId") for j in jobs}
    while True:
        d = search_china(sess, page)
        if d is None:
            print(f"  page {page} 失败，稍后重试", flush=True)
            time.sleep(3)
            continue
        res = d.get("res", {})
        results = res.get("searchResults", [])
        total = res.get("totalRecords", 0)
        for r in results:
            if r.get("positionId") not in seen:
                jobs.append(r)
                seen.add(r.get("positionId"))
        print(f"  page {page}: +{len(results)} (累计 {len(jobs)}/{total})", flush=True)
        save_progress(PROGRESS_LIST, {"next_page": page + 1, "jobs": jobs})
        if len(results) < 20 or len(jobs) >= total:
            break
        page += 1
        time.sleep(0.2)
    return jobs


def build_link(job):
    pid = job.get("positionId") or job.get("id")
    slug = job.get("transformedPostingTitle") or ""
    return f"{BASE}/zh-cn/details/{pid}/{slug}"


def fetch_details(sess, jobs):
    prog = load_progress(PROGRESS_DETAIL, {"done": []})
    done = set(prog.get("done", []))
    total = len(jobs)
    for i, job in enumerate(jobs, 1):
        pid = job.get("positionId")
        # 若 pid 已抓过且本次内存中确有详情，则跳过；否则（如从上次残留进度恢复）重新抓取
        if not pid or (pid in done and job.get("detail")):
            continue
        d = sess.get(f"{API}/jobDetails/{pid}?locale={LOCALE}")
        if d is None:
            time.sleep(2)
            continue
        res = d.get("res", {})
        job["detail"] = {
            "minimumQualifications": res.get("minimumQualifications", ""),
            "preferredQualifications": res.get("preferredQualifications", ""),
            "description": res.get("description", ""),
            "jobSummary": res.get("jobSummary", ""),
            "teamNames": res.get("teamNames", []),
            "locations": res.get("locations", []),
        }
        done.add(pid)
        if len(done) % 10 == 0:
            save_progress(PROGRESS_DETAIL, {"done": list(done)})
            print(f"  details {i}/{total} (done {len(done)})", flush=True)
        time.sleep(0.15)
    save_progress(PROGRESS_DETAIL, {"done": list(done)})
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-detail", action="store_true", help="只抓列表，不抓岗位详情")
    args = ap.parse_args()

    print("==> 初始化会话 / 取 CSRF token ...", flush=True)
    sess = Session()
    if not sess.token:
        print("无法获取 CSRF token，退出。", file=sys.stderr)
        sys.exit(1)

    print("==> 拉取中国区全部岗位 (postLocation-CHNC) ...", flush=True)
    all_jobs = fetch_all_china(sess)
    with open("apple_china_all.json", "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=1)
    print(f"  中国区岗位总数: {len(all_jobs)}", flush=True)

    team_counter = Counter()
    for j in all_jobs:
        t = j.get("team") or {}
        if isinstance(t, dict):
            team_counter[(t.get("teamName"), t.get("teamCode"))] += 1
    print("\n==> 团队分布 (Top 20):", flush=True)
    for (name, code), c in team_counter.most_common(20):
        print(f"  {c:4d}  {name} ({code})", flush=True)

    comp = []
    for j in all_jobs:
        cat = classify(j)
        if cat:
            j["_cat"] = cat
            comp.append(j)
    print(f"\n==> 计算机相关岗位命中: {len(comp)}", flush=True)
    for j in comp:
        t = j.get("team") or {}
        print(f"  - {j.get('postingTitle')}  [{t.get('teamCode')}] {j.get('_cat')}", flush=True)

    if not args.no_detail:
        print("\n==> 抓取岗位详情(任职要求) ...", flush=True)
        comp = fetch_details(sess, comp)

    out = []
    for j in comp:
        t = j.get("team") or {}
        locs = j.get("locations") or []
        loc_names = []
        for l in locs:
            if isinstance(l, dict):
                loc_names.append(l.get("name") or l.get("countryName") or "")
        item = {
            "title": j.get("postingTitle"),
            "team": t.get("teamName"),
            "teamCode": t.get("teamCode"),
            "category": j.get("_cat"),
            "positionId": j.get("positionId"),
            "postingDate": j.get("postingDate"),
            "locations": loc_names,
            "link": build_link(j),
        }
        if not args.no_detail:
            det = j.get("detail", {})
            item["minimumQualifications"] = det.get("minimumQualifications", "")
            item["preferredQualifications"] = det.get("preferredQualifications", "")
            item["description"] = det.get("description", "")
        out.append(item)

    with open("apple_computer_jobs.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n==> 已写出 apple_computer_jobs.json ({len(out)} 条)", flush=True)


if __name__ == "__main__":
    main()
