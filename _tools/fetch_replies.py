#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_replies.py —— 抓取论坛楼层的读者讨论与 wxmang 回应，生成「问答」配对页。

用法：
    python _tools/fetch_replies.py --series "管理短篇N则"
    python _tools/fetch_replies.py --ids 138,139
    python _tools/fetch_replies.py --all
    python _tools/fetch_replies.py --series "管理短篇N则" --audit    # 附人工核验样本
    python _tools/fetch_replies.py --series "管理短篇N则" --dry-run

输出：
    与正文同目录、同名 + `-qa.md`，URL 为正文 URL + `-qa`。
    e.g. 01-管理学/管理短篇N则/001-管理短篇N则一管理需不需要灵感-qa.md

────────────────────────────────────────────────────────────────
判定规则（三条，全部来自 1421 页实测取证；改动前请先复核样本）
────────────────────────────────────────────────────────────────

1. 归属看「谁是发言人」，不看「谁被引用」。
   普通楼层结构 = USER（网友）/ SAY（网友的话）/ REPLY（楼主的话）。
   实测：REPLY 的归属是**该页楼主**，不是被引用的人。
   反证：作者「夏翁」的页面里，REPLY 是「顾乃杰是我同班同学」——属夏翁。
   所以只有当**楼主是 wxmang** 时，整段 REPLY 才算他的话。

2. 引用以 <blockquote> 包裹，剥掉即可（batch 2 / 3）。
   batch 1 / 4 无 blockquote，REPLY 本身就是纯回复，无需剥离。
   实测：batch1 的 6000 块 REPLY 中仅 1 处出现「写道」字样（且属正文），
   确认无引用混入——这两批的 REPLY 是干净纯回复。

3. 扁平对话流以 `[发言人] (时间)` 标记分句（batch 3 的「淘帖」区）。
   sychaguan 的淘帖区（<div class="REPLY_LI">）把整个讨论压平成一段，
   每段以 <strong>[wxmang] (2011-12-8 11:27:00)</strong> 起头。
   这是**最精确**的归属依据：直接取 name == wxmang 的段。
   实测全库 `[wxmang]` 标记 4073 处——即你所说的「引号标识」。

逐 REPLY 块的最终判定：
   a) 剥 blockquote → 净文本
   b) 净文本**以 `[某人](时间)` 开头** → 按标记切分，只取 wxmang 段（判据 3）
      （必须「开头」，否则会把正文里偶然出现的 `[某某] (日期)` 误当引用切碎）
   c) 否则，若**楼主 == wxmang** → 净文本即他的话（判据 1 + 2）
   d) 否则丢弃（既非楼主、又无标记 → 不是他的话）

跨来源：同一篇在多个论坛批次各有独立讨论串（实测交集为 0），
**全部合并**，并按文本指纹去重。

另有一条**回声剔除**（见 drop_echo）：源站淘帖区偶发把网友的整段话
重复挂在 wxmang 名下，若某 wxmang 段与紧邻的前一条非 wxmang 发言
相似度 ≥0.95 则丢弃——实测样本 3_2969.html。
"""

import argparse
import difflib
import html as htmllib
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import taxonomy as tx  # noqa: E402
import wxlib  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RE_LI = re.compile(r'<div class="LI">(.*?)(?=<div class="LI">|$)', re.S)
RE_USER = re.compile(r'<span class="NAME"[^>]*>(.*?)</span>', re.S)
RE_SAY = re.compile(r'<div class="SAY">(.*?)(?=<div class="REPLY">|$)', re.S)
RE_REPLY = re.compile(r'<div class="REPLY">(.*?)(?=<div class="LI">|$)', re.S)
RE_BQ = re.compile(r"<blockquote>.*?</blockquote>", re.S | re.I)
RE_TIME = re.compile(r'<div class="TIME">(.*?)</div>', re.S)
# 扁平对话流的发言人标记：[wxmang] (2011-12-8 11:27:00)
RE_SPK = re.compile(r"\[([^\]\[\n]{1,24})\]\s*\((\d{4}-\d{1,2}-\d{1,2}[^)]*)\)")
WX = "wxmang"
RE_MD_LEAD = re.compile(r"^(\s*)([#>+\-]|(?:\d+)[.](?=\s|$))")
RE_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')


def totext(s):
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s)
    return re.sub(r"[ \t\u3000]+", " ", s).strip()


def ntime(s):
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s or "")
    return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3))) if m else ""


def is_wx(name):
    return (name or "").strip().lower() == WX


def split_flat(text):
    """文本若**以** `[某人](时间)` 开头 → 拆成 [(name, time, body), …]；否则 None。"""
    ms = list(RE_SPK.finditer(text))
    if not ms:
        return None
    if text[:ms[0].start()].strip():      # 第一个标记前有实质内容 → 不是扁平流
        return None
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        body = text[m.end():end].strip()
        out.append((m.group(1).strip(), ntime(m.group(2)), body))
    return out


def parse_page(rec, page_author):
    """把一页的楼层解析成按 DOM 顺序排列的发言流。

    返回 [{speaker, time, text, kind}]，kind ∈ {'say', 'reply'}。
    """
    h = wxlib.raw_html(rec)
    entries = []
    for li in RE_LI.findall(h):
        nu = RE_USER.search(li)
        uname = totext(nu.group(1)) if nu else ""

        # ---- SAY：网友的话（剥嵌套 blockquote + BBCode 引用 + 论坛功能行）----
        say = RE_SAY.search(li)
        if say:
            st = wxlib.clean_reply_text(totext(wxlib.strip_blockquotes(say.group(1))))
            if st:
                flat = split_flat(st)
                if flat:
                    for nm, tm, bd in flat:
                        if bd:
                            entries.append({"speaker": nm, "time": tm,
                                            "text": bd, "kind": "say"})
                else:
                    stm = RE_TIME.search(li)      # LI 里第一个 TIME = 网友发言时间
                    entries.append({"speaker": uname or "（匿名）",
                                    "time": ntime(totext(stm.group(1))) if stm else "",
                                    "text": st, "kind": "say"})

        # ---- REPLY：楼主的话（剥掉 blockquote 引用 + 楼层时间）----
        rep = RE_REPLY.search(li)
        if rep:
            seg = rep.group(1)
            tm = RE_TIME.search(seg)
            rtime = ntime(totext(tm.group(1))) if tm else ""
            net = wxlib.clean_reply_text(
                totext(RE_TIME.sub("", wxlib.strip_blockquotes(seg))))
            if net:
                flat = split_flat(net)
                if flat:                          # 判据 3：扁平流，按标记取
                    for nm, t2, bd in flat:
                        if bd:
                            entries.append({"speaker": nm, "time": t2,
                                            "text": bd, "kind": "reply"})
                elif is_wx(page_author):          # 判据 1+2：整段是楼主的
                    entries.append({"speaker": WX, "time": rtime,
                                    "text": net, "kind": "reply"})
    return entries


def rounds_of(entries):
    """把发言流聚成「轮次」：连续的非 wxmang 发言 = 问，紧随的 wxmang 发言 = 答。"""
    rounds, i = [], 0
    while i < len(entries):
        q = []
        while i < len(entries) and not is_wx(entries[i]["speaker"]):
            q.append(entries[i])
            i += 1
        a = []
        while i < len(entries) and is_wx(entries[i]["speaker"]):
            a.append(entries[i])
            i += 1
        if q or a:
            rounds.append({"q": q, "a": a})
    return rounds


def esc(line):
    return RE_MD_LEAD.sub(lambda m: m.group(1) + "\\" + m.group(2), line)


def md_block(text):
    """把一段发言渲染为 Markdown 段落（保持原有换行结构）。"""
    lines = [esc(x.strip()) for x in text.splitlines() if x.strip()]
    return "\n\n".join(lines)


def strip_leading_echo(text, other, min_len=40):
    """若 text 的前若干「行」与 other 整段一致，剥掉这些行，返回剩余部分。

    按行累积比对（而不是字符串切片），因为要剥的长度必须映射回**原文**位置，
    而去空白归一化后的长度不能直接换算。逐行累积到刚好等于 other 的归一化
    文本即命中——比模糊相似度更严格，不会误剥「恰巧有点像」的回复。
    """
    a = wxlib.norm(other)
    if len(a) < min_len:
        return text
    lines = text.split("\n")
    acc = ""
    for i, ln in enumerate(lines):
        acc += wxlib.norm(ln)
        if acc == a:
            return "\n".join(lines[i + 1:]).strip()
        if len(acc) > len(a):
            return text
    return text


def strip_quote_echo(entries, min_len=40):
    """剔除源站淘帖区的「引用回声」错挂——两种形态一并处理。

    实测样本 batch3 / 3_2969.html 里两种都出现了：
      a) 把网友的**整段话**重复挂在 `[wxmang] (时间)` 名下
         （剥完前缀为空 → 整条丢弃）
      b) 把「网友的问 + wxmang 的答」**合并成一整段**挂在 `[wxmang]` 名下
         （剥掉问的前缀 → 留下他真正的回复）

    这是源站数据的问题，不是解析的问题；但照单全收就会把网友的话收成
    wxmang 的——同类错误的又一次翻版。

    判据是**逐行精确前缀匹配**前文任何一条非 wxmang 发言，而不是模糊相似度：
    后者容易误伤「wxmang 引述网友原话再回应」的正常写法。min_len 门槛
    则避免「谢谢，谢谢支持」这类短回应偶然撞车时被误剥。
    """
    others, out = [], []
    for e in entries:
        if not is_wx(e["speaker"]):
            others.append(e)
            out.append(e)
            continue
        t = e["text"]
        for o in others:
            nt = strip_leading_echo(t, o["text"], min_len)
            if nt != t:
                t = nt
                break
        if t.strip():
            out.append(dict(e, text=t))
    return out


def collect(c):
    """收集一篇的全部发言流（跨来源合并 + 去重 + 引用回声剔除）。

    去重指纹用**完整文本**（去掉所有空白后逐字比对），不用前 N 字截断——
    截断会把「谢谢，谢谢支持」和「谢谢，谢谢支持。慢慢来」误判成同一条。
    宁可留下细微重复（可复核），也不能悄悄删掉一句真实发言。
    """
    seen, entries, per_src = set(), [], []
    for s in c["sources"]:
        e = parse_page(s, c["author"])
        per_src.append((s, e))
        for x in e:
            k = wxlib.norm(x["text"])
            if k and k not in seen:
                seen.add(k)
                x["src"] = s["batch"]
                entries.append(x)
    return strip_quote_echo(entries), per_src


def build_md(c, entries, qa_url, body_url):
    wx_n = sum(1 for e in entries if is_wx(e["speaker"]))
    spk = len({e["speaker"] for e in entries})
    p = []
    p.append("---")
    p.append(f'title: "{c["title"]}（读者问答）"')
    p.append(f'slug: "{c["slug"]}-qa"')
    p.append(f'url: "{qa_url}"')
    p.append(f'date: {c["date"]}')
    p.append('wx_author: "wxmang"')
    p.append(f'wx_cat: "{c["cat_name"]}"')
    if c["series"]:
        p.append(f'wx_series: "{c["series"]}"')
    p.append('wx_kind: "qa"        # 本篇是正文的配套问答集，非独立文章')
    p.append(f'qa_of: "{body_url}"')
    p.append(f'original_date: {c["date"]}')
    p.append(f'source_url: "{c["sources"][0]["url"]}"')
    if len(c["sources"]) > 1:
        p.append("source_urls:")
        for s in c["sources"]:
            p.append(f'  - "{s["url"]}"')
    p.append(f'source_count: {len(c["sources"])}')
    p.append(f'qa_comments: {len(entries)}')
    p.append(f'qa_wxmang: {wx_n}')
    p.append("excludeFromSearch: true   # 隔离：不进全站搜索索引")
    # ⚠️ 只加 excludeFromSearch 是不够的——Hugo 的 `.Pages` 仍会包含 QA 页，
    #    系列页用 `.Paginate (.Pages.ByWeight)` 分页时，QA 页会**占掉分页配额**
    #    却因为它们不是正文而显示为空档（实测：18 篇正文被切成 4 页，
    #    page/1 只排出 1 篇，page/3 反而列出 10 个 QA 链接）。
    #    `build.list: never` 让 QA 页彻底退出列表集合，`render: always`
    #    保证它仍照常生成 URL（正文页的「读者问答」入口要靠它）。
    # ⚠️ 键名是 `build`，不是 `_build`——Hugo 0.145 起把 `_build` 改名了，
    #    旧名会直接让构建报错退出（实测 Hugo 0.166 报 deprecated 并中止）。
    p.append("build:")
    p.append("  list: never       # 不进任何列表，不占系列页分页配额")
    p.append("  render: always    # 但仍生成页面（正文页要链过来）")
    p.append("---")
    p.append("")
    p.append(f'> 作者：wxmang ｜ 本文正文：[《{c["title"]}》]({body_url}) ｜ '
             f'收录读者讨论 {len(entries)} 条，其中作者回应 {wx_n} 条'
             f'（共 {spk} 位参与者）。')
    p.append("")
    if not entries:
        p.append("*本主题下暂无可收录的读者讨论。*")
        p.append("")
        return "\n".join(p)

    for n, rd in enumerate(rounds_of(entries), 1):
        p.append(f"## {n}")
        p.append("")
        if rd["q"]:
            who = "、".join(dict.fromkeys(e["speaker"] for e in rd["q"]))
            when = rd["q"][0]["time"] or ""
            head = f"**问** ｜ {who}" + (f" ｜ {when}" if when else "")
            p.append(head)
            p.append("")
            for e in rd["q"]:
                p.append(md_block(e["text"]))
                p.append("")
        else:
            p.append("**问** ｜ *（无前文，作者主动补充）*")
            p.append("")
        if rd["a"]:
            when = rd["a"][0]["time"] or ""
            p.append("**答** ｜ wxmang" + (f" ｜ {when}" if when else ""))
            p.append("")
            for e in rd["a"]:
                p.append(md_block(e["text"]))
                p.append("")
    return "\n".join(p)


def safe_name(s, limit=60):
    s = RE_ILLEGAL.sub("", s)
    s = re.sub(r"\s+", " ", s).strip().rstrip(".")
    return s[:limit].strip() or "untitled"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series")
    ap.add_argument("--cat")
    ap.add_argument("--ids")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--audit", action="store_true", help="打印人工核验样本")
    ap.add_argument("--audit-n", type=int, default=6, help="核验样本条数")
    args = ap.parse_args()

    corpus = json.load(io.open(os.path.join(REPO, "_meta", "corpus.json"),
                               encoding="utf-8"))

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

    # 与 fetch_articles 一致的系列序号 / slug（保证 -qa 与正文对齐）
    members = {}
    for c in corpus:
        if c["series"]:
            members.setdefault(c["series"], []).append(c)
    order_of = {}
    for s, arr in members.items():
        if len(arr) < tx.SERIES_MIN:
            continue
        for i, x in enumerate(sorted(arr, key=lambda y: (y["date"], y["id"])), 1):
            order_of[x["id"]] = i

    written, empty = [], []
    audit_pool = []
    for c in sorted(sel, key=lambda x: (x["date"], x["id"])):
        cat_dir = (tx.SERIES_CAT.get(c["series"])
                   or tx.CATEGORY_MAP.get(c["category"], "09-其他"))
        c["cat_name"] = tx.CATEGORIES[cat_dir][0]
        c["weight"] = order_of.get(c["id"], c["id"])
        # slug 必须与 fetch_articles.py 同源（都走 taxonomy.slug_name），
        # 否则问答页 URL 会与正文的 -qa 后缀对不上。
        c["slug"] = tx.slug_name(c["title"], 50)
        series_slug = tx.slug_for_series(c["series"]) if c["series"] else None
        sd = tx.dir_safe(c["series"]) if (c["series"] and len(members.get(c["series"], [])) >= tx.SERIES_MIN) else None

        body_url = tx.article_url(cat_dir, series_slug, c["slug"])
        qa_url = tx.article_url(cat_dir, series_slug, c["slug"] + "-qa")
        rel_dir = os.path.join(cat_dir, sd) if sd else cat_dir
        fname = f"{c['weight']:03d}-{safe_name(c['title'], 50)}-qa.md"
        path = os.path.join(REPO, rel_dir, fname)

        entries, per_src = collect(c)
        wx_n = sum(1 for e in entries if is_wx(e["speaker"]))
        if not entries:
            empty.append(c["title"])
        md = build_md(c, entries, qa_url, body_url)

        if args.audit and len(audit_pool) < args.audit_n:
            audit_pool.append((c, per_src, entries))

        if args.dry_run:
            print(f"[dry-run] {rel_dir}/{fname}  讨论 {len(entries)} 条 / 作者 {wx_n} 条")
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with io.open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(md)
        written.append(os.path.join(rel_dir, fname).replace("\\", "/"))

    print(f"[fetch_replies] 选中 {len(sel)} 篇，"
          f"{'预演' if args.dry_run else '写出'} {len(written)} 个问答页")
    for w in written[:12]:
        print("   ", w)
    if len(written) > 12:
        print(f"    … 其余 {len(written) - 12} 个")
    if empty:
        print(f"[提示] {len(empty)} 篇无可收录讨论：{'、'.join(empty[:5])}"
              + ("…" if len(empty) > 5 else ""))

    if args.audit:
        print()
        print("=" * 78)
        print("人工核验样本（原页结构 → 提取结果）")
        print("=" * 78)
        for c, per_src, entries in audit_pool:
            print()
            print(f"### {c['title']}")
            print(f"    来源 {len(per_src)} 个：" +
                  "、".join(f"batch{s['batch']}({len(e)}条)" for s, e in per_src))
            show = entries if len(entries) <= 40 else entries[:40]
            for i, e in enumerate(show, 1):
                flag = "★" if is_wx(e["speaker"]) else " "
                print(f"  {flag}{i:>2}.[{e['speaker']}|b{e.get('src', '?')}] {e['time']}  "
                      f"{e['text'].replace(chr(10), ' ')[:110]}")
            if len(entries) > len(show):
                print(f"      … 余 {len(entries) - len(show)} 条")


if __name__ == "__main__":
    main()
