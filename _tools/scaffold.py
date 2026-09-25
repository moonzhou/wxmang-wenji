#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scaffold.py —— 生成文集的目录骨架与各级 _index.md。

为什么用脚本而不是手写：
    各级 _index.md 里要展示篇数、系列清单、时间跨度。手写必然随入库进度失真，
    而 562 篇的规模下没人会记得去改。**计数由 corpus.json 派生，永远是准的。**

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
    """系列名可能含 / 或 \\（如「我的司机/身边人」），做目录名时必须替换，
    否则会凭空多出一层目录。"""
    return name.replace("/", "·").replace("\\", "·").strip().rstrip(".")


def main():
    corpus = json.load(io.open(os.path.join(META, "corpus.json"), encoding="utf-8"))
    total = len(corpus)

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
    L = []
    L.append("---")
    L.append('title: "wxmang 文集"')
    L.append('description: "2009–2022 年 wxmang 公开发表的文章整理。非商业公益整理，'
             '版权归原作者所有。"')
    L.append("cascade:")
    L.append("  excludeFromSearch: true   # 不进全站搜索索引（否则索引会被 562 篇全文撑爆）")
    L.append('  wx_author: "wxmang"')
    L.append("excludeFromSearch: false     # 文集入口页本身要能被搜到，否则读者找不到这一栏")
    L.append("showTableOfContents: true")
    L.append("---")
    L.append("")
    dates = sorted(c["date"] for c in corpus)
    L.append(f"这里收录 **{dates[0][:4]}–{dates[-1][:4]}** 年间 wxmang 公开发表的文章，"
             f"经整理与去重后共 **{total}** 篇。")
    L.append("")
    L.append("## 说明")
    L.append("")
    L.append("- **非商业公益整理**，仅用于阅读与检索便利；**文章著作权归原作者所有**。")
    L.append("- 每篇正文开头保留原始署名、首发日期与原文链接；权利人的下架请求会在 48 小时内处理。")
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
    L.append(f"逐篇清单（含每篇的全部原始链接）见仓库内 `_meta/SOURCES.csv`，"
             f"按系列分组的完整目录见 `_meta/文集总目录.md`。")
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
    L.append("## 数据")
    L.append("")
    y = collections.Counter(c["date"][:4] for c in corpus)
    L.append("| 年份 | 篇数 |")
    L.append("| --- | --- |")
    for k in sorted(y):
        L.append(f"| {k} | {y[k]} |")
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
        L.append(f'  wx_cat: "{name}"')
        L.append("groupByYear: false")
        L.append("showSummary: true")
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
