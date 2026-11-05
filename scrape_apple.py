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


INCLUDE_KW = [
    "engineer", "engineering", "工程师",
    "developer", "development", "开发", "开发工程师",
    "software", "软件",
    "data", "数据", "data scientist", "数据科学家", "data engineer", "数据工程师",
    "machine learning", "ml", "机器学习", "深度学习", "deep learning",
    "人工智能", " ai", "a.i.",
    "algorithm", "算法",
    "ios", "android", "移动",
    "sdet", "qa", "test", "测试", "quality",
    "architect", "架构",
    "infrastructure", "基础设施", "platform", "平台",
    "backend", "back-end", "后端", "frontend", "front-end", "前端",
    "full stack", "全栈",
    "devops", "sre", "运维",
    "security", "安全",
    "database", "数据库",
    "network", "网络",
    "system", "systems", "系统",
    "researcher", "research scientist", "研究员",
    "programmer", "程序员",
    "information technology", "信息技术",
    "firmware", "固件", "embedded", "嵌入式",
    "computer vision", "cv ", "nlp",
    "cloud", "云",
    "technical", "技术",
]
COMPUTER_TEAMS = {"SFTWR", "HRDWR"}  # Software and Services / Hardware


def is_computer(job):
    title = (job.get("postingTitle") or "").lower()
    team_name = ""
    t = job.get("team") or {}
    if isinstance(t, dict):
        team_name = (t.get("teamName") or "").lower()
    blob = title + " " + team_name
    team_code = (t.get("teamCode") or "").upper() if isinstance(t, dict) else ""

    for kw in ("retail", "store leader", "specialist", "genius", "零售", "销售代表", "店经理"):
        if kw in blob:
            return False

    if team_code in COMPUTER_TEAMS:
        if any(k in title for k in ("retail", "store", "specialist", "genius", "销售", "零售")):
            return False
        return True

    hit = any(kw in blob for kw in INCLUDE_KW)
    if not hit:
        return False
    for kw in ("sales", "marketing", "brand", "pr ", "communications", "finance", "legal", "hr ", "招聘", "人力"):
        if kw in title:
            return False
    return True


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
        if not pid or pid in done:
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

    comp = [j for j in all_jobs if is_computer(j)]
    print(f"\n==> 计算机相关岗位命中: {len(comp)}", flush=True)
    for j in comp:
        t = j.get("team") or {}
        print(f"  - {j.get('postingTitle')}  [{t.get('teamCode')}]", flush=True)

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
