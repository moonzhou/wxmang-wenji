#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scaffold.py —— 生成文集的目录骨架与各级 _index.md。

为什么用脚本而不是手写：
    各级 _index.md 里要展示篇数、系列清单、时间跨度。手写必然随入库进度失真，
    而全量规模下没人会记得去改。**计数由 corpus.json 派生，永远是准的。**

生成物：
    _index.md                    文集总入口（大类导览 + 统计 + 版权摘要）
    <大类>/_index.md             大类页（系列清单 + cascade 注入 wx_cat）
    <大类>/<系列>/_index.md      系列页（cascade 注入 wx_series + 顺序阅读开关）

本脚本可重复执行（幂等）：只重写自己生成的 _index.md，绝不触碰文章文件。

用法：python _tools/scaffold.py
"""

import collections
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import taxonomy as tx  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META = os.path.join(REPO, "_meta")


def esc(s):
    """转义 Markdown 列表里会误触语法的字符。"""
    for a, b in (("[", "\\["), ("]", "\\]"), ("*", "\\*"), ("`", "\\`")):
        s = s.replace(a, b)
    return s


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def dir_safe(name):
    return tx.dir_safe(name)


def year_hist_of(dirpath):
    """扫描目录下 md 的 date 字段，返回 (年份直方图, 有日期的篇数)。

    专给答帖（10-答帖/）用：答帖以「原帖」为单位，不属于 corpus
    （corpus 只收 wxmang 的独立文章），但其年份分布要并进首页的
    「文章年份分布」表，故单独扫目录取，而不是硬编码。
    """
    hist = collections.Counter()
    if not os.path.isdir(dirpath):
        return (hist, 0)
    for f in sorted(os.listdir(dirpath)):
        if not f.endswith(".md") or f == "_index.md":
            continue
        try:
            head = io.open(os.path.join(dirpath, f), encoding="utf-8").read(600)
        except OSError:
            continue
        m = re.search(r'^date:\s*["\']?(\d{4})', head, re.M)
        if m:
            hist[m.group(1)] += 1
    return (hist, sum(hist.values()))


def main():
    corpus = json.load(io.open(os.path.join(META, "corpus.json"), encoding="utf-8"))
    total = len(corpus)

    # 答帖不属于 corpus，其年份分布单独扫目录取
    rep_hist, rep_n = year_hist_of(os.path.join(REPO, "10-答帖"))

    # ---- 先定系列归属 ----
    # 系列归属由 taxonomy.SERIES_CAT 人工登记；未登记的系列回落为该系列
    # 多数成员所在的分类（仍属启发式，发现不对就往 SERIES_CAT 补一行）。
    # 一个系列只挂一个大类，否则同一系列会被拆成两个同名目录、无法顺序通读。
    members = collections.defaultdict(list)
    for c in corpus:
        if c["series"]:
            members[c["series"]].append(c)
    series_home = {}
    for s, arr in members.items():
        if len(arr) < tx.SERIES_MIN:
            continue
        if s in tx.SERIES_CAT:
            series_home[s] = tx.SERIES_CAT[s]
        else:
            vote = collections.Counter(
                tx.CATEGORY_MAP.get(x["category"], "09-其他") for x in arr)
            series_home[s] = vote.most_common(1)[0][0]
            print(f"   ! 系列「{s}」未在 SERIES_CAT 登记，按出现最多的分类"
                  f"落入 {series_home[s]}，建议人工确认")

    # ---- 归拢成树 ----
    tree = collections.OrderedDict()
    for c in corpus:
        s = c["series"]
        cat_dir = series_home.get(s) or tx.CATEGORY_MAP.get(c["category"], "09-其他")
        key = s if s in series_home else ""
        tree.setdefault(cat_dir, collections.OrderedDict()).setdefault(key, []).append(c)

    # ---------- 文集总入口 ----------
    # 首页只做导览（正文已有「按主题浏览 / 系列 / 文章年份分布」三块），
    # 不再附加 Hugo 自动生成的子页面列表——那一层列的是「栏目」而非文章，
    # 还会把答帖、整理原则与 9 大类混在一起按年分组。故改用专用 layout 渲染。
    dates = sorted(c["date"] for c in corpus)
    # 年份并集（独立文章 ∪ 答帖）——简介区间与年份表共用这个全集
    year_hist = collections.Counter(c["date"][:4] for c in corpus)
    years_all = sorted(set(year_hist) | set(rep_hist))
    span_lo, span_hi = years_all[0], years_all[-1]

    L = []
    L.append("---")
    L.append('title: "wxmang 文集"')
    L.append(f'description: "{span_lo}–{span_hi} 年 wxmang 公开的文字整理，'
             f'含独立文章与答帖。非商业公益整理，版权归原作者所有。"')
    L.append("cascade:")
    L.append('  wx_author: "wxmang"')
    L.append("showTableOfContents: true")
    L.append('layout: "no-list"   # 走 zmsite 的 layouts/_default/no-list.html：只渲染正文')
    L.append("---")
    L.append("")
    rep_yr = f"{min(rep_hist)}–{max(rep_hist)}" if rep_hist else "无"
    L.append(f"这里收录 **{span_lo}–{span_hi}** 年间 wxmang 公开的文字："
             f"独立文章 **{total}** 篇（{dates[0][:4]}–{dates[-1][:4]}），"
             f"另有 **{rep_n}** 个原帖下的答帖（{rep_yr}）。")
    L.append("")
    L.append("## 说明")
    L.append("")
    L.append("- **非商业公益整理**，仅用于阅读与检索便利；**文章著作权归原作者所有**。")
    L.append("- 每篇正文开头保留原始署名、首发日期与原文链接；相关权利人的下架请求会在 48 小时内处理。")
    L.append("- 详见《[整理原则与版权说明](/wxmang/about/)》。")
    L.append("")
    L.append("## 按主题浏览")
    L.append("")
    L.append("| 大类 | 篇数 | 成系列 |")
    L.append("| --- | --- | --- |")
    for cat_dir in sorted(tree):
        name, slug = tx.CATEGORIES[cat_dir]
        arr = [c for v in tree[cat_dir].values() for c in v]
        ser = sum(1 for s, v in tree[cat_dir].items() if s and len(v) >= tx.SERIES_MIN)
        L.append(f"| [{name}](/wxmang/{slug}/) | {len(arr)} | {ser} 个 |")
    L.append("")
    L.append("## 回其他网友答帖")
    L.append("")
    L.append("与上面 9 个大类**性质不同**，故单列：上面 9 类是 wxmang **自己署名发表的独立文章**；"
             "本类是他作为网友，**在其他网友所发主题帖下的回帖**，并非他的独立文章。")
    L.append("")
    rep_span = f"{min(rep_hist)}–{max(rep_hist)}" if rep_hist else "无"
    L.append(f"- [回其他网友答帖](/wxmang/replies/) ｜ {rep_n} 个原帖 · {rep_span}")
    L.append("")
    L.append("每页对应一个原帖（标明原作者与原帖链接），下挂 wxmang 在该帖下的全部回复，"
             "并保留他所回应的读者发言作为语境。")
    L.append("")
    L.append("## 系列")
    L.append("")
    series_all = sorted(
        ((cat_dir, s, v) for cat_dir in tree for s, v in tree[cat_dir].items()
         if s and len(v) >= tx.SERIES_MIN),
        key=lambda x: -len(x[2]))
    for cat_dir, s, v in series_all:
        _, cslug = tx.CATEGORIES[cat_dir]
        sslug = tx.slug_for_series(s)
        first = min(x["date"] for x in v)
        L.append(f"- [{s}](/wxmang/{cslug}/{sslug}/)（{len(v)} 篇，始于 {first[:4]}）")
    L.append("")
    L.append("## 年份分布")
    L.append("")
    L.append(f"下表并列 **{total}** 篇独立文章与 **{rep_n}** 个答帖页。"
             f"答帖以原帖为单位，年份取自原帖首发日期；「—」表示该年无内容。")
    L.append("")
    L.append("| 年份 | 独立文章 | 答帖 |")
    L.append("| --- | --- | --- |")
    for k in years_all:
        a = year_hist.get(k)
        b = rep_hist.get(k)
        L.append(f"| {k} | {a or '—'} | {b or '—'} |")
    L.append(f"| **合计** | **{total}** | **{rep_n}** |")
    L.append("")
    L.append("> 本页由 `_tools/scaffold.py` 依据 `_meta/corpus.json` 自动生成，请勿手工编辑。")
    write(os.path.join(REPO, "_index.md"), "\n".join(L))

    # ---------- 大类页 / 系列页 ----------
    n_files = 1
    for cat_dir in sorted(tree):
        name, cslug = tx.CATEGORIES[cat_dir]
        arr = [c for v in tree[cat_dir].values() for c in v]
        dates = sorted(c["date"] for c in arr)
        series_here = {s: v for s, v in tree[cat_dir].items()
                       if s and len(v) >= tx.SERIES_MIN}
        loose = {s: v for s, v in tree[cat_dir].items()
                 if not s or len(v) < tx.SERIES_MIN}
        n_loose = sum(len(v) for v in loose.values())

        L = []
        L.append("---")
        L.append(f'title: "{name}"')
        L.append(f'url: "/wxmang/{cslug}/"')
        L.append('cascade:')
        L.append("  excludeFromSearch: true   # 隔离：文集全文不进全站搜索索引")
        L.append(f'  wx_cat: "{name}"')
        L.append("groupByYear: false")
        L.append("showSummary: true")
        # 同系列页：分页大小见 zmsite 的 config/_default/hugo.toml [pagination]。
        L.append("---")
        L.append("")
        L.append(f"**{len(arr)} 篇**，{dates[0][:10]} 至 {dates[-1][:10]}。")
        L.append("")
        if series_here:
            L.append("## 系列")
            L.append("")
            for s, v in sorted(series_here.items(), key=lambda x: -len(x[1])):
                sslug = tx.slug_for_series(s)
                ds = sorted(x["date"] for x in v)
                L.append(f"- [{s}](/wxmang/{cslug}/{sslug}/)"
                         f"（{len(v)} 篇，{ds[0][:4]}–{ds[-1][:4]}）")
            L.append("")
        if n_loose:
            L.append(f"## 散篇（{n_loose} 篇）")
            L.append("")
            L.append("未归入系列的文章，按时间倒序列在下方。")
            L.append("")
        L.append("> 本页由 `_tools/scaffold.py` 自动生成，请勿手工编辑。")
        write(os.path.join(REPO, cat_dir, "_index.md"), "\n".join(L))
        n_files += 1

        for s, v in sorted(series_here.items(), key=lambda x: -len(x[1])):
            sslug = tx.slug_for_series(s)
            ds = sorted(x["date"] for x in v)
            L = []
            L.append("---")
            L.append(f'title: "{s}"')
            L.append(f'url: "/wxmang/{cslug}/{sslug}/"')
            L.append('cascade:')
            L.append(f'  wx_series: "{s}"')
            L.append("groupByYear: false")
            L.append("orderByWeight: true   # 系列按顺序读，不按年份分组")
            # ⚠️ 分页**不能**在 front matter 里覆盖：`pagination.pagerSize` 是
            #    站点配置键，写在这里只会被当成自定义参数（实测 Hugo 0.166
            #    下 18 篇的系列仍按全站 pagerSize=10 切成 2 页）。
            #    系列「一次列全」靠 zmsite 侧把 [pagination] pagerSize 调大。
            L.append("---")
            L.append("")
            L.append(f"**{len(v)} 篇**，{ds[0][:10]} 至 {ds[-1][:10]}，"
                     f"属[《{name}》](/wxmang/{cslug}/)大类。")
            L.append("")
            L.append("> 本页由 `_tools/scaffold.py` 自动生成，请勿手工编辑。")
            write(os.path.join(REPO, cat_dir, dir_safe(s), "_index.md"), "\n".join(L))
            n_files += 1

    print(f"[scaffold] 文集总入口 + {len(tree)} 个大类 + "
          f"{sum(1 for cd in tree for s, v in tree[cd].items() if s and len(v) >= tx.SERIES_MIN)}"
          f" 个系列 = 共 {n_files} 个 _index.md")
    for cat_dir in sorted(tree):
        name, _ = tx.CATEGORIES[cat_dir]
        arr = [c for v in tree[cat_dir].values() for c in v]
        ns = sum(1 for s, v in tree[cat_dir].items() if s and len(v) >= tx.SERIES_MIN)
        print(f"   {cat_dir:12s} {len(arr):4d} 篇  {ns} 个系列")


if __name__ == "__main__":
    main()
