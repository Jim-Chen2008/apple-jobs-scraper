#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据 apple_computer_jobs.json 生成分析报告 apple_report.md"""
import json
import re
from collections import Counter

DATA = json.load(open("apple_computer_jobs.json", encoding="utf-8"))

CAT_CN = {
    "core": "软件 / 机器学习 / AI（SFTWR + MLAI）",
    "hw_sw": "硬件系统 / 嵌入式 / 射频（HRDWR 软件相关）",
    "data": "数据 / 算法（运营数据类）",
    "intern": "在校实习（软件 / AI 方向）",
}

# ---------- 城市 / 团队 统计 ----------
city_counter = Counter()
team_counter = Counter()
cat_counter = Counter()
for j in DATA:
    cat_counter[j["category"]] += 1
    team_counter[j["team"]] += 1
    for loc in j.get("locations") or []:
        if loc:
            city_counter[loc] += 1

# ---------- 关键词频率（任职要求） ----------
# 中英文关键词 -> 显示名
KW = {
    "计算机科学": ["计算机科学", "computer science", "cs "],
    "软件工程": ["软件工程", "software engineering", "software development"],
    "电子/电气工程": ["电子工程", "电气工程", "electrical engineering", "ee "],
    "相关学位(本科/硕士)": ["bachelor", "master", "学士", "硕士", "学位", "degree"],
    "工作经验(年)": ["年经验", "years", "years of", "experience"],
    "Python": ["python"],
    "Java": ["java"],
    "C/C++": ["c++", "c "],
    "Swift/Objective-C": ["swift", "objective-c"],
    "Go": [" golang", " go "],
    "SQL/数据库": ["sql", "数据库", "database"],
    "机器学习/深度学习": ["machine learning", "深度学习", "deep learning", "ml ", "神经网络"],
    "算法": ["算法", "algorithm"],
    "英语能力": ["英语", "english", "流利"],
    "沟通协作": ["沟通", "communication", "协作", "collaborat"],
    "解决问题": ["解决问题", "problem solving", "problem-solving"],
    "iOS/macOS": ["ios", "macos", "xcode"],
    "云计算/分布式": ["云", "cloud", "分布式", "distributed", "kubernetes", "docker"],
    "前端/Web": ["前端", "frontend", "front-end", "react", "web "],
    "后端/服务": ["后端", "back-end", "backend", "microservice", "微服务"],
    "嵌入式/固件": ["嵌入式", "embedded", "firmware", "rtos"],
    "安全": ["安全", "security"],
    "数据/大数据": ["数据", "data", "pipeline", "hadoop", "spark"],
    "测试/质量": ["测试", "qa", "sdet", "quality"],
    "领导力/管理": ["领导", "lead", "manage", "管理"],
    "项目管理": ["项目管理", "project management", "pmp"],
}

N = len(DATA)
kw_counts = Counter()
for j in DATA:
    text = (j.get("minimumQualifications", "") + " " +
            j.get("preferredQualifications", "")).lower()
    for label, kws in KW.items():
        if any(k in text for k in kws):
            kw_counts[label] += 1

# 高频职位关键词（从标题）
title_words = Counter()
STOP = {"and", "the", "for", "of", "in", "a", "an", "with", "to", "-", "–", "工程师", "eng",
        "intern", "实习", "senior", "staff", "principal", "ii", "iii", "i", "s", "r", "d"}
for j in DATA:
    t = j["title"].lower()
    for w in re.split(r"[^a-z\u4e00-\u9fff]+", t):
        if w and w not in STOP and len(w) > 1:
            title_words[w] += 1

# ---------- 写报告 ----------
L = []
L.append("# Apple 中国区「计算机相关」岗位爬取与分析报告\n")
L.append(f"> 数据来源：https://jobs.apple.com/zh-cn/search?location=china-CHNC  \n"
         f"> 抓取时间口径：2026-11-03  \n"
         f"> 命中岗位数：**{N}** （从 556 条中国区在招岗位中筛选，已剔除销售/市场/职能/零售/"
         f"制造质量工艺等非计算机类）\n")

L.append("## 一、概览\n")
L.append(f"- 计算机相关岗位总数：**{N}**")
for c, n in cat_counter.most_common():
    L.append(f"  - {CAT_CN.get(c,c)}：{n}")
L.append("\n- 团队分布：")
for t, n in team_counter.most_common():
    L.append(f"  - {t}：{n}")
L.append("\n- 工作城市（Top）：")
for c, n in city_counter.most_common(12):
    L.append(f"  - {c}：{n}")

L.append("\n## 二、任职要求关键词频率（基于 {0} 个岗位的「最低要求+优先要求」文本）\n".format(N))
L.append("下表反映**跨岗位共性**——出现比例越高，越属于「通用要求」。\n")
L.append("| 要求维度 | 出现岗位数 | 占比 |")
L.append("|---|---:|---:|")
for label, cnt in kw_counts.most_common():
    L.append(f"| {label} | {cnt} | {cnt*100//N}% |")

L.append("\n## 三、全部岗位清单（名称 + 链接）\n")
L.append("> 按类别分组。链接指向 Apple 官方招聘页（含完整 JD）。\n")
for c in ["core", "hw_sw", "data", "intern"]:
    items = [j for j in DATA if j["category"] == c]
    if not items:
        continue
    L.append(f"### {CAT_CN.get(c,c)}（{len(items)}）\n")
    L.append("| # | 职位名称 | 团队 | 地点 | 发布日期 | 链接 |")
    L.append("|---|---|---|---|---|---|")
    for i, j in enumerate(items, 1):
        loc = "、".join([x for x in (j.get("locations") or []) if x]) or "-"
        date = j.get("postingDate") or "-"
        title = j["title"].replace("|", "/")
        link = j["link"]
        L.append(f"| {i} | {title} | {j['team']} | {loc} | {date} | [查看]({link}) |")

L.append("\n## 四、共同要求 vs 特殊要求\n")
L.append("### 4.1 共同要求（绝大多数岗位都具备）\n")
L.append("综合 {0} 份 JD，以下属于「计算机相关岗位的通用门槛」：\n".format(N))
common = [k for k, v in kw_counts.most_common() if v * 100 // N >= 30]
for k in common:
    L.append(f"- **{k}**（约 {kw_counts[k]*100//N}% 的岗位提及）")
L.append("\n归纳起来，Apple 对中国区计算机岗位的「共同画像」是：")
L.append("- 具备**计算机科学 / 软件工程 / 电子工程**等相关专业的学士或更高学位；")
L.append("- 拥有 **2–5 年以上**对应方向的工程经验（实习岗除外）；")
L.append("- 扎实的**编程能力**（Python / C / C++ / Java 等至少一门，且能写生产级代码）；")
L.append("- 良好的**英语读写与跨文化沟通**（JD 普遍写明需与全球团队协作用英语）；")
L.append("- 强的**问题解决 / 系统性思维**与**团队协作**意识。\n")

L.append("### 4.2 特殊要求（仅特定方向/团队才有）\n")
L.append("这些要求只在部分岗位出现，是区分度所在：\n")
special_notes = [
    ("机器学习 / AI 岗（MLAI + 部分 SFTWR）", "深度学习框架（PyTorch/TensorFlow）、大模型/ foundation model 经验、NLP/CV、推荐系统、MLSys；多要求顶会论文或研究实习。"),
    ("iOS / 客户端软件岗", "Swift / Objective-C、Xcode、Apple 平台生态（iOS/macOS/watchOS）、UIKit/SwiftUI。"),
    ("后端 / 服务端岗", "分布式系统、微服务、Go/Java、Kubernetes/Docker、高并发与海量数据处理。"),
    ("数据 / 算法岗", "SQL/NoSQL、Spark/Hadoop、数据管道、统计建模、A/B 实验。"),
    ("硬件系统 / 嵌入式岗（HRDWR 软件相关）", "嵌入式 C/C++、RTOS、固件、底层驱动、数字/RF 电路理解、硅验证、自动化测试脚本。"),
    ("安全岗", "应用/系统安全、密码学、威胁建模、合规（如 GDPR/等保）。"),
    ("云 / 基础设施岗", "AWS/GCP/Azure、Terraform、CI/CD、SRE/可观测性。"),
    ("测试 / 质量岗（SDET/QA）", "自动化测试框架、持续集成、测试策略。"),
    ("高级 / 管理岗", "团队管理、跨职能项目管理（PMP 加分）、技术路线图规划。"),
]
for title, desc in special_notes:
    L.append(f"- **{title}**：{desc}")

L.append("\n## 五、什么样的人更有优势？\n")
L.append("结合 JD 文本与 Apple 的用人偏好，以下几类候选人优势明显：\n")
adv = [
    "**科班底色 + 真刀真枪的工程能力**：计算机/软件/电子相关学位是门票，但 Apple 更看重「做过什么」——有可演示的项目、开源贡献、或实习产出，比 GPA 更有说服力。",
    "**英语好、能和全球团队协同**：中国区很多岗位向美国总部/跨国团队汇报，JD 普遍把英文沟通列为硬要求，双语（中英）是显著加分。",
    "**某方向的深度专精**：Apple 岗位细分极强（如『iPhone System HW Electrical Engineer』『AIML - Machine Learning Engineer, Data & ML Innovation』），在一个垂直领域有 2–3 年深耕 + 代表作，远胜于泛泛的「全栈都会一点」。",
    "**系统思维与极致打磨**：Apple 强调『细节、质量、用户体验』，能在简历/面试中体现对性能、可靠性、隐私、可维护性的执着者更受青睐。",
    "**研究/算法背景（AI 岗）**：ML/AI 岗明显偏好有论文、竞赛（Kaggle/ICPC）、或大模型实战经验的人；实习岗也偏爱有科研经历的在校生。",
    "**文化契合与协作力**：JD 反复出现『collaboration / 跨职能 / 包容』，能证明自己擅长在大型跨团队项目中推动落地的人更有优势。",
]
for a in adv:
    L.append(f"- {a}")

L.append("\n## 六、说明与局限\n")
L.append("- 范围：本爬取以「团队代码 + 标题关键词」判定「计算机相关」，已剔除销售(SLDEV)、市场(MKTG)、"
         "公司职能(CORSV)、零售(APPST) 及制造/质量/工艺类岗位；硬件岗仅保留软件/嵌入式/系统/射频等方向。")
L.append("- 数据来自 Apple 官方招聘 API 的当前快照，岗位会动态增减；链接可能随岗位下线失效。")
L.append("- 原始结构化数据见同目录 `apple_computer_jobs.json`（含每个岗位的完整任职要求文本）。")

open("apple_report.md", "w", encoding="utf-8").write("\n".join(L))
print("报告已生成 apple_report.md，共", len(L), "行；命中岗位", N)
print("关键词 Top:", kw_counts.most_common(8))
