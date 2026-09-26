#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
taxonomy.py —— 文集目录 → ASCII URL 的映射表。

为什么单独放一张表：
    目录名用中文（仓库里可读性最好），URL 用 ASCII（分享出去、粘到别处都干净）。
    两者解耦，改映射不影响已有目录。**没登记的系列回落到中文目录名做 URL。**

新增系列时在这里补一行即可；不需要动任何模板。
"""

import re

# 大类：目录名 → (显示名, URL slug)
CATEGORIES = {
    "01-管理学":   ("管理学",     "management"),
    "02-经济与金融": ("经济与金融", "economics"),
    "03-传统文化":  ("传统文化",   "classics"),
    "04-国际与地缘": ("国际与地缘", "geopolitics"),
    "05-产业与技术": ("产业与技术", "industry"),
    "06-社会与时政": ("社会与时政", "society"),
    "07-回忆与随笔": ("回忆与随笔", "memoir"),
    "08-生活与美食": ("生活与美食", "life"),
    "09-其他":     ("其他",       "misc"),
    # 10 与其他九类性质不同：里面是「他在别人帖子下的答帖」，
    # 不是他的独立文章。以「原帖」为单位成页（见 fetch_replies_others.py）。
    "10-答帖":     ("答帖",       "replies"),
}

# 原清单的「主题分类」→ 大类目录
CATEGORY_MAP = {
    "管理与职场":       "01-管理学",
    "经济与金融":       "02-经济与金融",
    "传统文化与经典":    "03-传统文化",
    "国际与地缘":       "04-国际与地缘",
    "技术与工程":       "05-产业与技术",
    "时政与社会":       "06-社会与时政",
    "人生与随笔":       "07-回忆与随笔",
    "美食与生活":       "08-生活与美食",
    "文化与娱乐":       "09-其他",
    "未分类":          "09-其他",
}

# 系列名 → URL slug（未登记则用中文目录名）
SERIES_SLUG = {
    "职业经理人工作笔记":   "notes-of-a-manager",
    "管理短篇N则":         "management-essays",
    "春节菜单":           "spring-festival-menu",
    "标准化菜谱":          "standard-recipes",
    "中国重型机械":         "heavy-machinery",
    "读《易经》心得":       "i-ching",
    "遵义名小吃":          "zunyi-snacks",
    "我的司机/身边人":      "people-around-me",
    "货币政策回顾":         "monetary-policy",
    "读报读资料笔记":       "reading-notes",
    "读书笔记":           "book-notes",
    "中国农村改革":         "rural-reform",
    "供应链管理SCM":       "scm",
    "管理科学简介":         "management-science",
    "滞胀与反通胀":         "stagflation",
    "项目管理":           "project-management",
    "海外投资":           "overseas-investment",
    "管理案例分析":         "case-studies",
    "我经济政策分析的方法":    "economic-analysis-method",
    "民工荒与用工":         "labor-shortage",
    "童年碎影":           "childhood",
    "遵义地域文化":         "zunyi-culture",
    "贵州地域":           "guizhou",
}

# 系列名 → 所属大类目录（人工登记，可复核）
#
# 为什么不从文章自带的「主题分类」投票得出：
#     那个字段与作者归属一样，是按**标题关键词**猜的，同样不可靠——
#     实测投票会把「标准化菜谱」投进管理学、「我的司机/身边人」投进管理学。
#     系列是文集的骨干，归属必须由人定，再由脚本执行。
SERIES_CAT = {
    # 01 管理学
    "职业经理人工作笔记":   "01-管理学",
    "管理短篇N则":         "01-管理学",
    "管理案例分析":         "01-管理学",
    "管理科学简介":         "01-管理学",
    "项目管理":           "01-管理学",
    "供应链管理SCM":       "01-管理学",
    "民工荒与用工":         "01-管理学",
    # 02 经济与金融
    "货币政策回顾":         "02-经济与金融",
    "滞胀与反通胀":         "02-经济与金融",
    "海外投资":           "02-经济与金融",
    "我经济政策分析的方法":    "02-经济与金融",
    # 03 传统文化
    "读《易经》心得":       "03-传统文化",
    # 05 产业与技术
    "中国重型机械":         "05-产业与技术",
    # 06 社会与时政
    "中国农村改革":         "06-社会与时政",
    # 07 回忆与随笔
    "我的司机/身边人":      "07-回忆与随笔",
    "童年碎影":           "07-回忆与随笔",
    "读书笔记":           "07-回忆与随笔",
    "读报读资料笔记":       "07-回忆与随笔",
    # 08 生活与美食
    "标准化菜谱":          "08-生活与美食",
    "春节菜单":           "08-生活与美食",
    "遵义名小吃":          "08-生活与美食",
    # 09 其他
    "贵州地域":           "09-其他",
    "遵义地域文化":         "09-其他",
}

# 只有达到这个篇数的系列才单独建目录；其余留在所属大类根目录
SERIES_MIN = 3


def slug_for_series(name, fallback=None):
    return SERIES_SLUG.get(name) or fallback or name


def article_url(cat_dir, series_slug, article_slug):
    """文章页的 ASCII URL，与栏目页同源（大类 slug / 系列 slug）。

    为什么文章也要显式写 url：
        §2 的「仓库=中文目录 / URL=ASCII」只覆盖了 `_index.md`。文章若不写，
        物理目录名会直接进 URL —— 正文链接变成
        /wxmang/08-%E7%94%9F%E6%B4%BB%E4%B8%8E%E7%BE%8E%E9%A3%9F/%E6%A0%87...
        读者从系列页点进去，URL 会突然从 /wxmang/life/standard-recipes/ 跳成
        编码串。文章级 url 把这一层补上，两级链接就对齐了。
        （article_slug 是中文标题，Hugo 会做 percent-encoding；中段全 ASCII，
         分享出去至少是「可读的中文尾巴」，而非「一长串 %E5…」。）
    """
    _, cslug = CATEGORIES[cat_dir]
    parts = ["wxmang", cslug]
    if series_slug:
        parts.append(series_slug)
    parts.append(article_slug)
    return "/" + "/".join(parts) + "/"


def dir_safe(name):
    """系列名可能含 / 或 \\（如「我的司机/身边人」），做目录名时必须替换，
    否则会凭空多出一层目录。"""
    return name.replace("/", "·").replace("\\", "·").strip().rstrip(".")


# URL slug：只留字母数字与汉字。
#
# 为什么与文件名分开：中文标题里的全角标点（？：、，。）进了 slug 会被
# percent-encode 成一串 %EF%BC%9F，分享出去很难看；且全角「？」在某些
# 解析器里可能被误当查询串分隔符。文件名保留标点（可读性好），URL 只留实词。
#
# ⚠️ fetch_articles.py 与 fetch_replies.py 必须共用本函数——两边各自实现过
#    一次，一次改动就会让正文与问答页的 URL 分叉。
RE_SLUG_KEEP = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")


def slug_name(s, limit=50):
    s = RE_SLUG_KEEP.sub("", s or "")
    return s[:limit] or "untitled"
