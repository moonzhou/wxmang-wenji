#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_corpus.py —— 生成权威文集口径。

输入：wxmang-梳理/wxmang-权威元数据.json（由 fetch_meta.py 产出）+ raw/ 原始 HTML
输出：_meta/SOURCES.csv        全量来源清单（含每篇的全部原始链接）
      _meta/corpus.json       结构化文集（供 fetch_articles.py 消费）
      _meta/文集总目录.md      按大类/系列分组的可读目录

用法：python _tools/build_corpus.py
"""

import csv
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wxlib  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META_DIR = os.path.join(REPO, "_meta")


def main():
    os.makedirs(META_DIR, exist_ok=True)

    def prog(done, total):
        if done % 100 == 0 or done == total:
            print(f"  去重比对 … {done}/{total}", flush=True)

    meta = wxlib.load_meta()
    print(f"[build_corpus] 元数据 {len(meta)} 条；候选池 = 本人署名 + 代发帖 + 转载页")
    print("                （判据见 wxlib.page_kind：署名 / 标题声明 / 正文作者元信息）")
    corpus = wxlib.build_corpus(meta, progress=prog)
    import collections as _c
    kk = _c.Counter(c["page_kind"] for c in corpus)
    print(f"[build_corpus] 去重后 {len(corpus)} 篇；来源构成 "
          f"{dict(kk)}；转载页剔除 {len(wxlib.LAST_DROPPED_REPOST)} / "
          f"合并 {len(wxlib.LAST_MERGED_REPOST) + len(wxlib.LAST_MERGED_TITLE)}")

    # ---- SOURCES.csv ----
    p = os.path.join(META_DIR, "SOURCES.csv")
    with io.open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["序号", "标题", "首发日期", "主题分类", "系列",
                    "合并条数", "全部原始链接", "正文长度"])
        for c in corpus:
            w.writerow([c["id"], c["title"], c["date"], c["category"], c["series"],
                        c["dup_count"],
                        " | ".join(s["url"] for s in c["sources"]),
                        c["body_chars"]])

    # ---- corpus.json（不含正文，正文由 fetch_articles 现取）----
    light = [{k: v for k, v in c.items() if k != "body_clean"} for c in corpus]
    p2 = os.path.join(META_DIR, "corpus.json")
    import json
    with io.open(p2, "w", encoding="utf-8", newline="\n") as f:
        json.dump(light, f, ensure_ascii=False, indent=1)

    # ---- 文集总目录.md ----
    import collections
    by_cat = collections.OrderedDict()
    for c in corpus:
        by_cat.setdefault(c["category"], []).append(c)

    L = []
    L.append("# wxmang 文集 · 总目录")
    L.append("")
    L.append(f"> 收录 **{len(corpus)}** 篇（按页面真实署名筛选、并合并搬家重复帖后的唯一篇目）")
    L.append(f"> 时间跨度 {corpus[0]['date']} ~ {corpus[-1]['date']}")
    L.append("> 本目录由 `_tools/build_corpus.py` 自动生成，请勿手工编辑")
    L.append("")
    L.append("## 主题大类")
    L.append("")
    L.append("| 大类 | 篇数 |")
    L.append("| --- | --- |")
    for k, v in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        L.append(f"| {k} | {len(v)} |")
    L.append("")
    for k, arr in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        L.append(f"## {k}（{len(arr)} 篇）")
        L.append("")
        ser = collections.OrderedDict()
        for c in arr:
            ser.setdefault(c["series"] or "", []).append(c)
        for sname in sorted(ser, key=lambda s: (s == "", -len(ser[s]))):
            items = ser[sname]
            L.append(f"### {sname}（{len(items)} 篇）" if sname else f"### 散篇（{len(items)} 篇）")
            L.append("")
            for c in sorted(items, key=lambda x: x["date"]):
                mark = f" ×{c['dup_count']}" if c["dup_count"] > 1 else ""
                L.append(f"- [{c['date']}] {c['title']}{mark}")
            L.append("")
    p3 = os.path.join(META_DIR, "文集总目录.md")
    with io.open(p3, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L))

    print()
    print(wxlib.summarize(corpus))
    print()
    print(f"[build_corpus] 已写出：{p}")
    print(f"[build_corpus] 已写出：{p2}")
    print(f"[build_corpus] 已写出：{p3}")


if __name__ == "__main__":
    main()
