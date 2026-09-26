#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_replies_others.py —— 抓「他人帖中的 wxmang 答帖」，生成独立页面。

用法：
    python _tools/fetch_replies_others.py --title "中国经济的困境和破局"   # 单篇
    python _tools/fetch_replies_others.py --top 20                       # 回复数前 20
    python _tools/fetch_replies_others.py --all
    python _tools/fetch_replies_others.py --top 5 --dry-run
    python _tools/fetch_replies_others.py --title "…" --audit

输出：
    10-答帖/001-<原帖标题>.md，URL = /wxmang/replies/<slug>/

────────────────────────────────────────────────────────────────
与 fetch_replies.py 的分工
────────────────────────────────────────────────────────────────
fetch_replies.py   处理 corpus 内的 488 篇（页面署名 = wxmang）
                   产物 = 正文附带的「读者问答」页（**附属**，不进列表）
本脚本             处理 corpus 之外的他人帖（页面署名 ≠ wxmang）
                   产物 = **独立**页面「原帖信息 + 配对问答」（进列表）

为什么可以收（归属判据）
────────────────────────────────────────────────────────────────
`REPLY` 块恒为 **wxmang 的发言**，与页面署名无关。他人帖的署名是
**原帖楼主**，`REPLY` 仍是 wxmang —— 三项铁证见 fetch_replies.py
文档串判据 1。实测 594 页 / 5961 块 / 净约 68.7 万字。
⚠️ 原判据曾误为「REPLY 属该页楼主」（反证用的是夏翁帖里那句
   「顾乃杰是我同班同学」，而那句本身就是 wxmang 说的——他中科大出身），
   这个错误结论导致这整类内容被排除在文集之外。

引用剥离（本脚本的生命线）
────────────────────────────────────────────────────────────────
他人帖的引用痕迹远比本人帖重：实测《中国经济的困境和破局（1）》
237 块 REPLY 中 236 块含 <blockquote>，引用尾巴占原始字数的 66%；
剥掉后净发言仅 1.5 万字。**剥离不严就会把网友的话收成他的**——
即 521 条误报的同类错误。复用 wxlib 的三层剥离：
    wxlib.strip_blockquotes  深度配对剥 <blockquote>（支持嵌套）
    wxlib.strip_bbcode_quote 剥 [quote]…[/quote]
    wxlib.clean_reply_text   剔论坛功能行

组织形态（形式 B）
────────────────────────────────────────────────────────────────
「问」= 网友在 SAY 里的话（**语境**，标明发言人）
「答」= wxmang 的 REPLY
刻意保留「问」：不然「不至于，最极端情况都模拟过」这类回应会失去所指。
"""

import argparse
import glob
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import taxonomy as tx        # noqa: E402
import wxlib                 # noqa: E402
import fetch_replies as fr   # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST_CAT = "10-答帖"
WX = "wxmang"
RE_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')

# 误收自检词：wxmang 不会管自己叫「忙总/忙师」
SELF_WORDS = ["忙总", "忙师", "wxmang 发表于", "wxmang 提到",
              "请教您", "向您请教", "谢谢忙总", "感谢忙总"]


def safe_name(s, limit=60):
    s = RE_ILLEGAL.sub("", s or "")
    s = re.sub(r"\s+", " ", s).strip().rstrip(".")
    return s[:limit].strip() or "untitled"


def others_meta():
    """全部「他人帖且有 REPLY 块」的页面记录（= 收录候选池）。"""
    return [r for r in wxlib.load_meta()
            if (r.get("page_author") or "").strip().lower() != WX
            and int(r.get("n_reply_blocks") or 0) > 0]


def group_hosts(recs):
    """把「同一原帖」的多批次页面归为一组。

    跨 batch 是同一帖在时间分片里的**不同讨论串**（实测交集为 0），
    所以归组后要合并，才是该帖讨论的全貌。
    归组键 =（原帖作者, 净化后的标题）——标题里的「（搬家帖）」等前缀
    由 pretty_title 去掉，避免同一帖因前缀不同被拆开。
    """
    g = {}
    for r in recs:
        key = ((r.get("page_author") or "").strip(), wxlib.pretty_title(r))
        g.setdefault(key, []).append(r)
    out = []
    for (au, ti), arr in g.items():
        arr.sort(key=lambda x: (x.get("page_date") or "", x.get("序号") or 0))
        out.append({"host_author": au, "host_title": ti, "sources": arr})
    out.sort(key=lambda h: (h["sources"][0].get("page_date") or "",
                            h["sources"][0].get("序号") or 0))
    return out


def collect(host):
    """收集一条原帖下的全部发言流（跨来源合并 + 去重 + 回声剔除）。"""
    seen, entries, per_src = set(), [], []
    for r in host["sources"]:
        e = fr.parse_page(r, True)          # 收录开关：REPLY 恒为 wxmang
        per_src.append((r, e))
        for x in e:
            k = wxlib.norm(x["text"])
            if k and k not in seen:
                seen.add(k)
                x["src"] = r.get("batch")
                entries.append(x)
    # 先做回声剔除，再按「有答的轮次优先」稳定排序由 rounds_of 负责
    return fr.strip_quote_echo(entries), per_src


def build_md(host, entries, slug, url, n):
    wx = [e for e in entries if fr.is_wx(e["speaker"])]
    others = [e for e in entries if not fr.is_wx(e["speaker"])]
    wc = sum(len(e["text"]) for e in wx)
    oc = sum(len(e["text"]) for e in others)
    src0 = host["sources"][0]
    speakers = {e["speaker"] for e in others}
    p = []
    p.append("---")
    # 标题不加「（答帖）」后缀：整站只有本栏目产出答帖页，栏目名与页首
    # 原帖信息卡已足够标识性质；594 条列表里逐条缀后缀是纯噪声。
    # 原名保存在 host_title 字段，未丢失。
    p.append(f'title: "{host["host_title"]}"')
    p.append(f'slug: "{slug}"')
    p.append(f'url: "{url}"')
    p.append(f'date: {src0.get("page_date") or "2005-01-01"}')
    p.append('wx_author: "wxmang"')
    p.append('wx_kind: "reply-to-others"   # 本页是他在他人帖下的答帖，非独立文章')
    p.append(f'host_title: "{host["host_title"]}"')
    p.append(f'host_author: "{host["host_author"]}"')
    p.append(f'host_url: "{src0["url"]}"')
    if len(host["sources"]) > 1:
        p.append("host_urls:")
        for r in host["sources"]:
            p.append(f'  - "{r["url"]}"')
    p.append(f'original_date: {src0.get("page_date") or "2005-01-01"}')
    p.append(f'source_count: {len(host["sources"])}')
    p.append(f'reply_count: {len(wx)}       # wxmang 的发言条数')
    p.append(f'reply_chars: {wc}')
    p.append(f'context_count: {len(others)}   # 被回应的读者发言条数（语境）')
    p.append("excludeFromSearch: true   # 隔离：与文集其余部分一致，不进全站搜索")
    p.append("---")
    p.append("")
    # 页头：原帖信息卡 + 收录说明
    hosts = " ｜ ".join(f'[原帖{i + 1}]({r["url"]})' if len(host["sources"]) > 1
                        else f'[原帖]({r["url"]})'
                        for i, r in enumerate(host["sources"]))
    p.append(f'> **原帖**：《{host["host_title"]}》 ｜ 作者：{host["host_author"]}'
             f' ｜ {hosts}')
    p.append(">")
    p.append(f'> 本页收录 **wxmang 在该帖下的答帖 {len(wx)} 条**（约 {wc:,} 字），'
             f'并保留他所回应的读者发言 {len(others)} 条作为语境'
             f'（共 {len(speakers)} 位参与者）。')
    p.append(">")
    p.append("> 说明：`REPLY` 是该站对作者发言的记录方式，与页面署名无关——"
             "这些是 wxmang 的原话，原帖正文版权归原作者。")
    p.append("")
    if not wx:
        p.append("*本主题下暂无可收录的作者答帖。*")
        p.append("")
        return "\n".join(p)

    for i, rd in enumerate(fr.rounds_of(entries), 1):
        if not rd["a"]:
            continue                          # 只收「有答」的轮次
        p.append(f"## {i}")
        p.append("")
        if rd["q"]:
            who = "、".join(dict.fromkeys(e["speaker"] for e in rd["q"]))
            when = rd["q"][0]["time"] or ""
            p.append(f"**问** ｜ {who}" + (f" ｜ {when}" if when else ""))
            p.append("")
            for e in rd["q"]:
                p.append(fr.md_block(e["text"]))
                p.append("")
        else:
            p.append("**问** ｜ *（无前文，作者主动发言）*")
            p.append("")
        when = rd["a"][0]["time"] or ""
        p.append("**答** ｜ wxmang" + (f" ｜ {when}" if when else ""))
        p.append("")
        for e in rd["a"]:
            p.append(fr.md_block(e["text"]))
            p.append("")
    return "\n".join(p)


def audit(host, entries):
    """质量自检：误收率 + 引用残留。"""
    wx = [e for e in entries if fr.is_wx(e["speaker"])]
    ro = [e for e in entries if not fr.is_wx(e["speaker"])]
    print("=" * 78)
    print(f"自检：《{host['host_title']}》")
    print("=" * 78)
    print(f"  来源 {len(host['sources'])} 个：" +
          "、".join(f"b{r.get('batch')}" for r in host["sources"]))
    print(f"  解析条目 {len(entries)}（wxmang {len(wx)} / 读者 {len(ro)}）")
    print(f"  wxmang 净字数 {sum(len(e['text']) for e in wx):,}"
          f" ｜ 读者字数 {sum(len(e['text']) for e in ro):,}")
    bad = []
    for i, e in enumerate(wx, 1):
        hit = [k for k in SELF_WORDS if k in e["text"]]
        if hit:
            bad.append((i, hit, e["text"].replace("\n", " ")[:150]))
    print(f"  误收自检：{len(bad)}/{len(wx)} → {100 * len(bad) / max(len(wx), 1):.2f}%"
          f" {'✅' if not bad else '⚠️'}")
    for i, hit, t in bad[:8]:
        print(f"    第{i}条 {hit}")
        print(f"        {t}")
    sus = [e for e in wx if re.search(r"\[\/?quote|提到[:：]|写道[:：]", e["text"])]
    print(f"  引用残留：{len(sus)} 条 {'✅' if not sus else '⚠️'}")
    for e in sus[:4]:
        print("      ", e["text"].replace("\n", " ")[:140])
    if entries:
        print()
        print("  ── 前 10 条发言（★ = wxmang）──")
        for i, e in enumerate(entries[:10], 1):
            flag = "★" if fr.is_wx(e["speaker"]) else " "
            print(f"  {flag}{i:>2}.[{e['speaker'][:14]}] {e['time']}  "
                  f"{e['text'].replace(chr(10), ' ')[:96]}")


def write_index():
    """维护 `10-答帖/_index.md`（幂等；统计派生自实际文件，不写死数字）。"""
    d = os.path.join(REPO, DEST_CAT)
    files = sorted(glob.glob(os.path.join(d, "[0-9]*.md")))
    chars = 0
    hosts = set()
    for p in files:
        t = io.open(p, encoding="utf-8").read()
        m = re.search(r"reply_chars:\s*(\d+)", t)
        if m:
            chars += int(m.group(1))
        m2 = re.search(r'host_author:\s*"([^"]*)"', t)
        if m2:
            hosts.add(m2.group(1))
    L = ["---",
         'title: "答帖"',
         f'url: "/wxmang/{tx.CATEGORIES[DEST_CAT][1]}/"',
         'description: "wxmang 在他人帖子下的答帖，以「原帖」为单位成页。"',
         "cascade:",
         "  excludeFromSearch: true   # 隔离：与文集其余部分一致，不进全站搜索",
         '  wx_cat: "答帖"',
         # 按年份分节：594 篇跨 2005-2019，且高度不均（2011 占 195、2015 占 134），
         # 平铺无从定位。置 true 后列表按年份出 h2 分组标题，
         # 且 Hugo 分页本就按年份组切（见主题 _default/list.html），分页边界与年份对齐。
         "groupByYear: true",
         # 不显示摘要：答帖正文首块是「原帖信息卡」引用块，Hugo 的 .Summary
         # 取不到段落，声明 true 只会给 200 个列表项各产出一个空 div（实测）。
         "showSummary: false",
         "---",
         "",
         f"**{len(files)} 个原帖**，作者答帖合计约 {chars:,} 字，"
         f"涉及 {len(hosts)} 位原帖作者。",
         "",
         "这里收录的是 **wxmang 在别人帖子下的答帖**——他作为网友参与讨论的发言，",
         "不是他的独立文章。每页对应一个原帖（标明原作者与链接），下挂他的全部回复，",
         "并保留他所回应的读者发言作为语境。",
         "",
         "列表按**年份倒序**排列（同年内按日期倒序）。",
         "",
         "> 本页由 `_tools/fetch_replies_others.py` 自动生成，请勿手工编辑。",
         ""]
    os.makedirs(d, exist_ok=True)
    with io.open(os.path.join(d, "_index.md"), "w",
                 encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L))
    return len(files), chars


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", help="原帖标题（子串匹配）")
    ap.add_argument("--top", type=int, help="按回复数取前 N 条原帖")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--audit", action="store_true")
    args = ap.parse_args()

    cand = others_meta()
    hosts = group_hosts(cand)
    print(f"[others] 候选页面 {len(cand)} 个 → 归并成原帖 {len(hosts)} 条")

    sel = hosts
    if args.title:
        sel = [h for h in hosts if args.title in h["host_title"]]
    elif args.top:
        sel = sorted(hosts,
                     key=lambda h: -sum(int(r.get("n_reply_blocks") or 0)
                                        for r in h["sources"]))[:args.top]
    if not (args.title or args.top or args.all):
        ap.error("请指定 --title / --top / --all 之一")
    if not sel:
        print("!! 没有匹配的原帖")
        return

    used = set()
    written = []
    for n, h in enumerate(sel, 1):
        entries, per_src = collect(h)
        base = tx.slug_name(h["host_title"], 46)
        slug = base
        k = 2
        while slug in used:
            slug = f"{base}-{k}"
            k += 1
        used.add(slug)
        url = f"/wxmang/{tx.CATEGORIES[DEST_CAT][1]}/{slug}/"
        fname = f"{n:03d}-{safe_name(h['host_title'], 50)}.md"
        rel = f"{DEST_CAT}/{fname}"
        md = build_md(h, entries, slug, url, n)
        wx_n = sum(1 for e in entries if fr.is_wx(e["speaker"]))
        if args.audit:
            print()
            audit(h, entries)
        if args.dry_run:
            print(f"[dry-run] {rel}  答 {wx_n} 条 / 上下文 {len(entries) - wx_n} 条  {url}")
        else:
            path = os.path.join(REPO, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with io.open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(md)
        written.append(rel)

    if not args.dry_run:
        print(f"[others] 写出 {len(written)} 个答帖页")
        for w in written[:12]:
            print("   ", w)
        if len(written) > 12:
            print(f"    … 其余 {len(written) - 12} 个")
        n_all, chars = write_index()
        print(f"[others] 栏目页已更新：{n_all} 个原帖 / 约 {chars:,} 字")


if __name__ == "__main__":
    main()
