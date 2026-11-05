#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于已抓取的 apple_china_all.json，做「计算机相关」精细化过滤 + 详情抓取 + 报告生成。
不会再拉列表，只抓命中岗位的详情（支持断点续传）。
"""
import json
import sys
import time
import re
import threading
import urllib.request
import urllib.error
import http.cookiejar
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

BASE = "https://jobs.apple.com"
API = BASE + "/api/v1"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
REF = BASE + "/zh-cn/search"
LOCALE = "zh-CN"
PROGRESS_DETAIL = "progress_detail.json"
_tls = threading.local()


def get_session():
    if not hasattr(_tls, "sess"):
        _tls.sess = Session()
    return _tls.sess

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
                print("  CSRF retry:", e, file=sys.stderr); time.sleep(1.5)
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
                return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 401:
                    self.refresh(); continue
                time.sleep(1.5)
            except Exception as e:
                last = e; time.sleep(1.5 + attempt)
        print(f"  !! request failed: {url} -> {last}", file=sys.stderr)
        return None

    def get(self, url):
        return self._request(url, "GET")


def build_link(job):
    pid = job.get("positionId") or job.get("id")
    slug = job.get("transformedPostingTitle") or ""
    return f"{BASE}/zh-cn/details/{pid}/{slug}"


def main():
    all_jobs = json.load(open("apple_china_all.json", encoding="utf-8"))
    refined = []
    for j in all_jobs:
        cat = classify(j)
        if cat:
            j["_cat"] = cat
            refined.append(j)
    print(f"精细化后计算机相关岗位: {len(refined)} (总抓取 {len(all_jobs)})", flush=True)

    # 分类统计
    cat_counter = Counter(j["_cat"] for j in refined)
    print("分类:", dict(cat_counter), flush=True)

    # 抓取详情（断点续传 + 多线程）
    prog = json.load(open(PROGRESS_DETAIL, encoding="utf-8")) if __import__("os").path.exists(PROGRESS_DETAIL) else {"done": []}
    done = set(prog.get("done", []))
    sess = Session()
    assert sess.token, "CSRF 失败"
    n = len(refined)
    lock = threading.Lock()

    def fetch_one(job):
        pid = job.get("positionId")
        if not pid:
            return
        s = get_session()
        d = s.get(f"{API}/jobDetails/{pid}?locale={LOCALE}")
        if d is None:
            return
        res = d.get("res", {})
        job["detail"] = {
            "minimumQualifications": res.get("minimumQualifications", ""),
            "preferredQualifications": res.get("preferredQualifications", ""),
            "description": res.get("description", ""),
            "jobSummary": res.get("jobSummary", ""),
            "teamNames": res.get("teamNames", []),
            "locations": res.get("locations", []),
        }
        with lock:
            done.add(pid)
            if len(done) % 10 == 0:
                json.dump({"done": list(done)}, open(PROGRESS_DETAIL, "w", encoding="utf-8"))
                print(f"  details done {len(done)}/{n}", flush=True)

    pending = [j for j in refined if j.get("positionId") and j["positionId"] not in done]
    print(f"  待抓取详情: {len(pending)} (已缓存 {len(done)})", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(fetch_one, pending))
    json.dump({"done": list(done)}, open(PROGRESS_DETAIL, "w", encoding="utf-8"))
    print(f"  详情抓取完成: {len(done)}/{n}", flush=True)

    # 写出结构化数据
    out = []
    for j in refined:
        t = j.get("team") or {}
        locs = j.get("detail", {}).get("locations", []) if j.get("detail") else (j.get("locations") or [])
        if not locs and j.get("detail"):
            locs = j["detail"].get("locations", [])
        out.append({
            "title": j.get("postingTitle"),
            "team": t.get("teamName"),
            "teamCode": t.get("teamCode"),
            "category": j.get("_cat"),
            "positionId": j.get("positionId"),
            "postingDate": j.get("postingDate"),
            "locations": [ (l.get("name") or l.get("countryName") or "") for l in locs if isinstance(l, dict)],
            "link": build_link(j),
            "minimumQualifications": (j.get("detail") or {}).get("minimumQualifications", ""),
            "preferredQualifications": (j.get("detail") or {}).get("preferredQualifications", ""),
            "description": (j.get("detail") or {}).get("description", ""),
        })
    json.dump(out, open("apple_computer_jobs.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"已写出 apple_computer_jobs.json ({len(out)} 条)", flush=True)


if __name__ == "__main__":
    main()
