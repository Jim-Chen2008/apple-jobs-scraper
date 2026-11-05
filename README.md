# Apple 中国区计算机相关岗位爬虫 + 分析报告

逆向 Apple 官方招聘接口，抓取「中国区在招岗位」中**计算机相关**（软件 / ML·AI / 数据算法 / 硬件嵌入式 / 在校实习）的岗位，输出岗位名称、链接、地点、团队，以及每个岗位的最低 / 优先任职要求原文，并生成一份「共同要求 vs 特殊要求 + 什么样的人更有优势」的分析报告。

> 数据快照时间：2026-11-03（Apple 招聘页面为实时数据，重跑脚本会得到最新结果）

## 成果

- **259 个** 计算机相关在招岗位（已剔除销售 / 市场 / 职能 / 零售，以及制造质量工艺等非计算机类）
- 构成：软件 / ML / AI 199、硬件系统 / 嵌入式 49、数据 / 算法 5、在校实习 6
- 城市：深圳、上海、北京、成都为主

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `scrape_apple.py` | 列表爬虫：调用 `/api/v1/search`（需 CSRF token + 会话 cookie），翻页拉取中国区全部岗位并筛选「计算机相关」，结果存 `apple_computer_jobs.json`。支持断点续传。 |
| `analyze_apple.py` | 详情爬虫 + 关键词统计：逐个抓取岗位详情（最低/优先要求原文），写入 `progress_detail.json`（断点续传）。 |
| `make_report.py` | 读取抓取结果，生成 `apple_report.md` 分析报告（岗位清单 + 关键词频率 + 共同/特殊要求 + 优势人群）。 |
| `apple_computer_jobs.json` | 结构化数据：259 个岗位，含 `title` / `link` / `team` / `locations` / `minimumQualifications` / `preferredQualifications` 等字段。 |
| `apple_china_all.json` | **原始全量数据**：中国区全部 556 个在招岗位（未筛选，含非计算机类），作为完整原始快照保留，可在此基础上自行再筛选。 |
| `apple_report.md` | 完整分析报告（含 259 个岗位的名称+链接清单）。 |

## 运行

依赖：Python 3 标准库（无需第三方包）。

```bash
# 1) 抓取中国区计算机相关岗位列表（断点续传）
python scrape_apple.py

# 2) 抓取每个岗位的任职要求详情（断点续传，约几百个请求）
python analyze_apple.py

# 3) 生成分析报告
python make_report.py
```

重跑会自动跳过已完成的页面 / 岗位（基于 `progress_*.json`）。

## 基于原始数据自行筛选

`apple_china_all.json` 是中国区全部 556 个在招岗位的**未筛选原始数据**（列表接口直接返回，不含任职要求详情）。每条记录的顶层字段如下：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `postingTitle` | str | 岗位名称 |
| `positionId` / `jobPositionId` | str/int | 岗位 ID，用于拼接详情链接 |
| `team` | dict | `teamName` / `teamCode` / `teamID`（团队名称与代码） |
| `locations` | list[dict] | 工作地点列表，含 `city` / `stateProvince` / `countryName` / `name` 等 |
| `jobSummary` | str | 岗位简介 |
| `type` | str | 用工类型（如 `Full Time`、`Intern`） |
| `postingDate` / `postDateInGMT` | str | 发布时间 |

详情链接格式：`https://jobs.apple.com/zh-cn/details/{positionId}`

### 示例 1：只看「软件 / ML / 数据」类团队

原始数据中的 `teamCode` 实际取值与分布（共 556 个岗位，2026-11-03 快照）：

| teamCode | 含义 | 数量 |
| --- | --- | --- |
| `SFTWR` | 软件工程 | 177 |
| `HRDWR` | 硬件工程 | 127 |
| `OPMFG` | 运营 / 制造 | 92 |
| `CORSV` | 公司职能 / 服务 | 44 |
| `SLDEV` | 销售 | 43 |
| `MLAI` | 机器学习 / AI | 24 |
| `APPST` | Apple Store 零售 | 18 |
| `MKTG` | 市场 | 15 |
| `STDNT` | 实习 / 在校 | 11 |
| `CUST` | 客户相关 | 5 |

下面示例按团队代码白名单筛选「计算机相关」方向：

```python
import json

data = json.load(open("apple_china_all.json", encoding="utf-8"))

# 只保留软件 / 硬件 / ML·AI / 实习 方向
TEAMS = {"SFTWR", "HRDWR", "MLAI", "STDNT"}
results = [job for job in data
           if (job.get("team") or {}).get("teamCode", "") in TEAMS]

print(f"匹配 {len(results)} 个岗位")
for job in results[:10]:
    code = (job.get("team") or {}).get("teamCode", "")
    pid = job.get("positionId")
    title = job.get("postingTitle")
    link = f"https://jobs.apple.com/zh-cn/details/{pid}"
    print(f"- {title}  [{code}]  {link}")
```

### 示例 2：按城市 + 关键词筛选

```python
import json

data = json.load(open("apple_china_all.json", encoding="utf-8"))

def cities(job):
    return {loc.get("city") or loc.get("name") for loc in job.get("locations", [])}

# 上海 + 标题含 "Machine Learning" 或 "AI"
hits = [
    job for job in data
    if "Shanghai" in cities(job)
    and any(k in (job.get("postingTitle") or "") for k in ("Machine Learning", "AI", "ML"))
]
for job in hits:
    print(job["postingTitle"], "->",
          f"https://jobs.apple.com/zh-cn/details/{job['positionId']}")
```

### 示例 3：导出为 CSV

```python
import json, csv

data = json.load(open("apple_china_all.json", encoding="utf-8"))
with open("jobs.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["title", "team", "teamCode", "city", "link"])
    for job in data:
        code = (job.get("team") or {}).get("teamCode", "")
        city = ",".join({loc.get("city") or loc.get("name") for loc in job.get("locations", [])})
        w.writerow([
            job.get("postingTitle"),
            (job.get("team") or {}).get("teamName", ""),
            code, city,
            f"https://jobs.apple.com/zh-cn/details/{job.get('positionId')}",
        ])
print("已导出 jobs.csv")
```

> 注意：原始列表数据**不含任职要求详情**。若要拿到每个岗位的最低/优先要求，请用 `analyze_apple.py` 抓取（或参考已生成的 `apple_computer_jobs.json`）。

## 接口说明（逆向所得）

- `GET /api/v1/CSRFToken` → 返回 `X-Apple-CSRF-Token` 响应头并设置会话 cookie
- `POST /api/v1/search` → 请求体 `{"query":"","filters":{"locations":["postLocation-CHNC"]},"page":N,"locale":"zh-CN","sort":"relevance",...}`，返回中国区岗位列表
- `GET /api/v1/jobDetails/{positionId}?locale=zh-CN` → 单个岗位完整详情

所有请求需带 `X-Apple-CSRF-Token` 头与同一会话 cookie。

## 免责声明

本仓库仅用于个人学习与技术演示。请遵守 Apple 招聘网站的使用条款，控制请求频率，勿用于商业或批量滥用。`cookies.txt` 等会话文件已在 `.gitignore` 中排除，切勿提交。
