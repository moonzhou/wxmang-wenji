#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wxlib —— wxmang 文集整理的公共库。

三条硬规则（来源于实测，改动请先复核样本）：
  1. 署名以页面 <p class="author"> 为准，**不用**标题关键词猜测。
     实测：120 篇随机样本中真实署名 wxmang 仅 52.5%，而标题猜测口径为 89.5%。
  2. 正文只取 <div class="POST"> 内、首个 <div class="LI"> 之前的内容（留言区必须剔除）。
  3. 正文尾部混有论坛元数据（关键词(Tags)/管理推/通宝推/N 条留言），
     **必须剔除后再比对**，否则同一篇的搬家版本会因留言数不同而被判为不同文章。
"""

import collections
import difflib
import html as htmllib
import io
import json
import os
import re

ROOT = "D:/个人网站"
WORK = os.path.join(ROOT, "wxmang-梳理")
RAW = os.path.join(WORK, "raw")
META_JSON = os.path.join(WORK, "wxmang-权威元数据.json")

RE_POST = re.compile(r'<div class="POST">', re.I)
RE_LI = re.compile(r'<div class="LI"', re.I)
RE_BACK = re.compile(r'<div class="BACK"', re.I)

# 论坛元数据行：出现在正文尾部，非作者原文
RE_FORUM_META = re.compile(
    r"^\s*(关键词\(Tags\)|关键词|Tags|管理推|通宝推|花\s*\(\d+\)|\d+\s*条留言)\s*[:：]?.*$"
)

# 标题里的搬运/来源前缀，仅用于生成干净的展示标题，不改动原文
RE_TITLE_PREFIX = re.compile(r"^\s*(【[^】]{0,8}】|（搬家帖?）|\(搬家帖?\)|转[:：]?|\[[^\]]{0,8}\])\s*")


def load_meta(path=META_JSON):
    return json.load(io.open(path, encoding="utf-8"))


def raw_html(rec):
    m = re.search(r"/(\d+)_(\d+)\.html", rec["url"])
    p = os.path.join(RAW, f"{m.group(1)}_{m.group(2)}.html")
    return io.open(p, encoding="utf-8", errors="ignore").read()


def body_html(rec):
    """切出正文区 HTML（剔除留言楼层）。"""
    h = raw_html(rec)
    m = RE_POST.search(h)
    if not m:
        return ""
    s = m.end()
    li = RE_LI.search(h, s)
    bk = RE_BACK.search(h, s)
    ends = [x.start() for x in (li, bk) if x]
    return h[s:min(ends)] if ends else h[s:]


def html_to_text(fragment):
    t = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    t = re.sub(r"</p>", "\n", t, flags=re.I)
    t = re.sub(r"</div>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = htmllib.unescape(t)
    return "\n".join(ln.strip() for ln in t.splitlines() if ln.strip())


def clean_body(rec):
    """正文 → 纯文本，并剔除论坛元数据行。"""
    return "\n".join(
        ln for ln in html_to_text(body_html(rec)).splitlines()
        if not RE_FORUM_META.match(ln)
    ).strip()


def norm(t):
    """去重指纹：去空白。"""
    return re.sub(r"\s+", "", t)


def pretty_title(rec):
    """展示用标题：去掉【原创】/（搬家帖）这类前缀。"""
    t = RE_TITLE_PREFIX.sub("", rec["page_title"] or rec["list_title"]).strip()
    return t or rec["page_title"] or rec["list_title"]


def is_wxmang(rec):
    return (rec.get("page_author") or "").strip() == "wxmang"


def dedup(records, threshold=0.97, contain=0.95, progress=None):
    """
    两级去重：
      1. 精确：正文指纹完全相同
      2. 近似：按长度排序 + 滑动窗口比对
         a) 整体相似度 ≥ threshold → 同一篇的搬家版本
            （如「1、原材料」→「一、原材料」这类一两行差异）
         b) **包含关系**：短文有 ≥ contain 的比例被长文覆盖 → 同一篇的不同版本
            （实测案例：「八宝饭」早期版比搬家版多出 3 条"技术控制要点"，
              相似度只有 0.907 抓不到，但短的那份几乎整篇都在长的里面）

    为什么按长度排序而不是按「前 N 字」分桶：
        实测踩过坑——按前 60 字分桶时，一处差异正好落在第 41 字，
        于是同一篇的两个版本被分进不同桶、**永远不会被比对**（相似度实为 0.9994）。

    返回：[[成员, …], …]，每组是一次"同一篇文章"，成员按日期升序。
    """
    exact = collections.OrderedDict()
    for r in records:
        key = norm(r["_clean"])
        if not key:
            continue
        exact.setdefault(key, []).append(r)

    firsts = list(exact.values())
    keys = [norm(v[0]["_clean"]) for v in firsts]
    order = sorted(range(len(firsts)), key=lambda i: len(keys[i]))
    n = len(keys)

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    done = 0
    for pos in range(n):
        i = order[pos]
        a = keys[i]
        window = max(0.30 * len(a), 80)
        for q in range(pos + 1, n):
            j = order[q]
            b = keys[j]
            if len(b) - len(a) > window:
                break
            sm = difflib.SequenceMatcher(None, a, b)
            if sm.quick_ratio() < 0.85:
                continue
            if sm.ratio() >= threshold:
                union(i, j)
                continue
            short = min(len(a), len(b))
            if short < 200:
                continue
            covered = sum(bl.size for bl in sm.get_matching_blocks())
            if covered / short >= contain:
                union(i, j)
        done += 1
        if progress and (done % 50 == 0 or done == n):
            progress(done, n)

    grouped = collections.defaultdict(list)
    for i in range(n):
        grouped[find(i)] += firsts[i]

    out = []
    for grp in grouped.values():
        grp.sort(key=lambda r: (r["page_date"], r["序号"]))
        out.append(grp)
    out.sort(key=lambda g: (g[0]["page_date"], g[0]["序号"]))
    return out


def build_corpus(meta=None, threshold=0.97, progress=None):
    """产出权威文集：只收真实署名 wxmang、去重后的唯一篇目。"""
    meta = meta if meta is not None else load_meta()
    wx = [dict(r) for r in meta if is_wxmang(r)]
    for r in wx:
        r["_clean"] = clean_body(r)
    groups = dedup(wx, threshold=threshold, progress=progress)
    corpus = []
    for i, grp in enumerate(groups, 1):
        head = grp[0]                       # 最早的一条 → 归属与日期
        body_src = max(grp, key=lambda r: len(r["_clean"]))   # 最完整的一条 → 正文
        corpus.append({
            "id": i,
            "title": pretty_title(head),
            "date": head["page_date"],
            "author": "wxmang",
            "category": head["list_cat"] or "未分类",
            "series": head["list_series"] or "",
            "body_chars": len(body_src["_clean"]),
            "body_from": body_src["url"],
            "sources": [{"url": g["url"], "date": g["page_date"],
                         "raw_title": g["page_title"], "batch": g["batch"]} for g in grp],
            "dup_count": len(grp),
            "body_clean": body_src["_clean"],
        })
    return corpus


def summarize(corpus):
    lines = []
    tot = len(corpus)
    lines.append(f"唯一篇目：{tot}")
    dups = sum(c["dup_count"] - 1 for c in corpus)
    lines.append(f"合并掉的重复条：{dups}")
    lines.append("")
    lines.append("主题大类：")
    c = collections.Counter(x["category"] for x in corpus)
    for k, v in c.most_common():
        lines.append(f"  {v:4d}  {v/tot*100:5.1f}%  {k}")
    lines.append("")
    lines.append("系列（≥3 篇）：")
    s = collections.Counter(x["series"] for x in corpus if x["series"])
    for k, v in s.most_common():
        if v >= 3:
            lines.append(f"  {v:4d}  {k}")
    lines.append(f"  （成系列 {sum(s.values())} 篇，散篇 {tot-sum(s.values())} 篇）")
    lines.append("")
    lines.append("年份：")
    y = collections.Counter(x["date"][:4] for x in corpus)
    for k in sorted(y):
        lines.append(f"  {k}  {y[k]:4d}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summarize(build_corpus()))
