#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_articles.py —— 抓正文并渲染为 Hugo 可读的 Markdown。

用法：
    python _tools/fetch_articles.py --series "标准化菜谱"      # 单个系列
    python _tools/fetch_articles.py --cat "生活与美食"          # 整个大类
    python _tools/fetch_articles.py --ids 1,2,3                # 指定序号
    python _tools/fetch_articles.py --all                      # 全量（562 篇）
    python _tools/fetch_articles.py --series "标准化菜谱" --dry-run

输出：
    <大类>/[<系列>/]NNN-<标题>.md     一篇一个文件（幂等，重跑覆盖）

两个必须知道的处理：
  1. 段落是**重建**出来的。源站的 <p> 是原论坛按 ~40 字折行的产物，
     真正的段落结构在源头就已丢失。这里用「编号行独立成段 + 上句以句末标点
     结尾则另起段」的规则合并回去，比逐行成段可读得多，但不是原文分段。
  2. 正文首行注入固定格式的溯源行（作者/首发/原文链接）。写成正文而不是模板，
     是为了让溯源跟着内容走——换主题、导出 PDF 都不会丢。
"""

import argparse
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import taxonomy as tx  # noqa: E402
import wxlib  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 编号行：1、/ 1. / 一、/ 第3、/（一）——这类行独立成段，且强制其后另起一段
RE_ITEM = re.compile(
    r"^\s*(?:[0-9]{1,3}\s*[、.．)）]"
    r"|[一二三四五六七八九十百]+[、.．]"
    r"|第[一二三四五六七八九十百千]+[、.．]?"
    r"|[（(]\s*[0-9一二三四五六七八九十]+\s*[）)])"
)
# 句末标点：以这些结尾说明一句话说完了，下一行另起段
RE_SENT_END = re.compile(r"[。！？…：][\u201d\u2019\u300d\u300f\uff09\u3011]?$")
RE_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')
RE_MULTISPACE = re.compile(r"\s+")
RE_MD_LEAD = re.compile(r"^(\s*)([#>+\-]|(?:\d+)[.](?=\s|$))")


def safe_name(s, limit=60):
    s = RE_ILLEGAL.sub("", s)
    s = RE_MULTISPACE.sub(" ", s).strip().rstrip(".")
    return s[:limit].strip() or "untitled"


def escape_md(line):
    """转义行首会被 Markdown 当成语法的字符。"""
    return RE_MD_LEAD.sub(lambda m: m.group(1) + "\\" + m.group(2), line)


def rebuild_paragraphs(text):
    """把源站按行折行的文本重新合并成段落。"""
    paras, cur, standalone_prev = [], "", False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if RE_ITEM.match(line):
            if cur:
                paras.append(cur)
                cur = ""
            paras.append(line)
            standalone_prev = True
            continue
        if cur and (standalone_prev or RE_SENT_END.search(cur)):
            paras.append(cur)
            cur = ""
        cur = line if not cur else cur + line   # 中文段内直接拼接，不加空格
        standalone_prev = False
    if cur:
        paras.append(cur)
    return [escape_md(p) for p in paras if p.strip()]


def build_md(entry, series_dir):
    p = []
    p.append("---")
    p.append(f'title: "{entry["title"]}"')
    p.append(f'slug: "{entry["slug"]}"')
    p.append(f'date: {entry["date"]}')
    if series_dir:
        p.append(f'weight: {entry["weight"]}   # 系列内阅读顺序')
    p.append(f'wx_author: "wxmang"')
    p.append(f'wx_cat: "{entry["cat_name"]}"')
    if entry["series"]:
        p.append(f'wx_series: "{entry["series"]}"')
    p.append(f'original_date: {entry["date"]}')
    p.append(f'source_url: "{entry["sources"][0]["url"]}"')
    if len(entry["sources"]) > 1:
        p.append("source_urls:   # 同一篇在多个论坛批次重复发布，全部留档")
        for s in entry["sources"]:
            p.append(f'  - "{s["url"]}"')
    p.append(f'source_count: {len(entry["sources"])}')
    p.append("excludeFromSearch: true   # 隔离：不进全站搜索索引")
    p.append("---")
    p.append("")

    # 溯源行
    urls = " ｜ ".join(f'[原文链接{i + 1}]({s["url"]})' if len(entry["sources"]) > 1
                       else f'[原文链接]({s["url"]})'
                       for i, s in enumerate(entry["sources"]))
    p.append(f"> 作者：wxmang ｜ 首发：{entry['date']} ｜ {urls}")
    p.append("")
    # ⚠️ 段落之间必须留空行：Markdown 把连续非空行视为同一段，
    #    漏掉空行会让整篇正文塌成一大坨（实测踩过）。
    p.append("\n\n".join(rebuild_paragraphs(entry["body_clean"])))
    p.append("")
    return "\n".join(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", help="只处理某个系列")
    ap.add_argument("--cat", help="只处理某个大类（按 corpus 的分类名）")
    ap.add_argument("--ids", help="只处理指定序号，逗号分隔")
    ap.add_argument("--all", action="store_true", help="全量")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    corpus = wxlib.load_meta(os.path.join(REPO, "_meta", "corpus.json"))
    # corpus.json 不含正文，这里现取。
    # 注意取的是 body_from（**最完整**的那一版），不是 sources[0]（最早的那一版）——
    # 搬家版常常丢掉尾部段落，用最早版会把内容截短。
    for c in corpus:
        src = next((s for s in c["sources"] if s["url"] == c.get("body_from")),
                   c["sources"][0])
        c["body_clean"] = wxlib.clean_body(
            {"url": src["url"], "batch": src["batch"], "page_date": src["date"]})

    sel = corpus
    if args.series:
        sel = [c for c in sel if c["series"] == args.series]
    if args.cat:
        sel = [c for c in sel if c["category"] == args.cat]
    if args.ids:
        want = {int(x) for x in args.ids.split(",")}
        sel = [c for c in sel if c["id"] in want]
    if not (args.series or args.cat or args.ids or args.all):
        ap.error("请指定 --series / --cat / --ids / --all 之一")

    # 系列归属与序号
    members = {}
    for c in corpus:
        if c["series"]:
            members.setdefault(c["series"], []).append(c)
    series_dir_of, order_of = {}, {}
    for s, arr in members.items():
        if len(arr) < tx.SERIES_MIN:
            continue
        arr2 = sorted(arr, key=lambda x: (x["date"], x["id"]))
        for i, x in enumerate(arr2, 1):
            series_dir_of[s] = tx.dir_safe(s)
            order_of[x["id"]] = i

    written, used = [], set()
    for c in sorted(sel, key=lambda x: (x["date"], x["id"])):
        cat_dir = (tx.SERIES_CAT.get(c["series"])
                   or tx.CATEGORY_MAP.get(c["category"], "09-其他"))
        cat_name = tx.CATEGORIES[cat_dir][0]
        sd = series_dir_of.get(c["series"]) if c["series"] in series_dir_of else None
        c["cat_name"] = cat_name
        c["weight"] = order_of.get(c["id"], c["id"])
        c["slug"] = safe_name(c["title"], 50)

        # 同目录内 slug 去重
        key = (cat_dir, sd, c["slug"])
        n = 2
        while key in used:
            c["slug"] = f"{safe_name(c['title'], 45)}-{n}"
            key = (cat_dir, sd, c["slug"])
            n += 1
        used.add(key)

        rel_dir = os.path.join(cat_dir, sd) if sd else cat_dir
        fname = f"{c['weight']:03d}-{safe_name(c['title'], 50)}.md"
        path = os.path.join(REPO, rel_dir, fname)
        md = build_md(c, sd)
        if args.dry_run:
            print(f"[dry-run] {rel_dir}/{fname}  ({len(c['body_clean'])} 字)")
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with io.open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(md)
        written.append(os.path.join(rel_dir, fname).replace("\\", "/"))

    print(f"[fetch_articles] 选中 {len(sel)} 篇，"
          f"{'预演' if args.dry_run else '写出'} {len(written)} 个文件")
    for w in written[:12]:
        print("   ", w)
    if len(written) > 12:
        print(f"    … 其余 {len(written) - 12} 个")


if __name__ == "__main__":
    main()
