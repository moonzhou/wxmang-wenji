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

# ─────────────────────────────────────────────────────────────
# 候选池扩展：署名不是 wxmang、但正文是他的页面（实测两类，判据分明）
# ─────────────────────────────────────────────────────────────
# 一、「代发帖」：他人代为转发，标题直接写明
#     实测 48 页全部署名「思炎」，标题形如
#       「代wxmang发帖【读易经心得】颐卦：如何益寿延年」
#       「【代wxmang发帖】读《资治通鉴》心得：新君登基（一）」
#       「代wxmang发帖—读《易经》心得—涣卦」
#     内容为《读易经》心得系列 43 卦 + 《资治通鉴》新君登基 5 篇，约 55 万字。
#     这批此前被「署名必须等于 wxmang」的判据整类挡在文集之外。
RE_DAIFA_TITLE = re.compile(
    r"代\s*(?:wxmang|忙总|文小芒)\s*发(?:帖|贴)|受.{0,6}委托.{0,4}发(?:帖|贴)")
# ⚠️ 刻意不含「代wxmang发**图**」——实测该页（【代wxmang发图】配合中国重型机械…）
#    正文是代发者写的配图说明（「这里的图片是忙总收集的…」），不是他的原文。

# 二、「转载汇编页」：转载账号把「原文 + 该帖问答录」打包成一页
#     实测 20 页全部署名「CleanRobot.A」，正文首行带作者元信息：
#       「作者: wxmang    时间: 2012-2-19 21:52」
#       「作者: 文小芒（wxmang）  发表时间: 2013/1/19 11:12:21」
#     ⚠️ 整页正文 = 原文 + 网友问答录，直接入 corpus 会造出巨型重复篇，
#        必须先由 slice_repost_body() 切掉问答录（见下）。
RE_AUTH_HEAD = re.compile(
    r"^\s*作者\s*[:：]\s*(?:文小芒\s*[（(]\s*)?wxmang\b", re.I)
RE_META_LINE = re.compile(
    r"^\s*(?:作者|标题|发表时间|时间)\s*[:：].*$|^\s*[-—–－=]{6,}\s*$")

# 扁平对话流的发言人标记（与 fetch_replies 的 RE_SPK 同构，此处只需判界）
RE_SPK_LINE = re.compile(r"^\s*\[[^\]\[\n]{1,24}\]\s*\(\s*\d{4}-\d{1,2}-\d{1,2}")
RE_SPK_ANY = re.compile(r"\[[^\]\[\n]{1,24}\]\s*\(\s*\d{4}-\d{1,2}-\d{1,2}[^)]*\)")

# 「作者: 某人    时间: …」——转载汇编页的**第二种**发言人标记
# （与扁平流的 `[某人] (时间)` 并存；实测「懒人版蹄髈」页有 41 处）
RE_AUTH_ANY = re.compile(
    r"^\s*作者\s*[:：]?\s*[^\s:：]{1,20}\s*(?:发表?)?时间\s*[:：]", re.I)
# 「网友问答录」分隔标签（实测「当务之急…」「什么因素会影响我们的智力」两页用它）
RE_QA_LABEL = re.compile(
    r"^\s*[-—–－=]{0,}\s*(?:网友问答录|网友问答|问答录|读者问答录)\s*[:：]?\s*$")
# 一篇正文的结束边界（按实测的三种形态统一判界）
RE_ARTICLE_END = re.compile(
    r"^(?:\s*\[[^\]\[\n]{1,24}\]\s*\(\s*\d{4}-\d{1,2}-\d{1,2}"      # [某人] (时间)
    r"|\s*作者\s*[:：]?\s*[^\s:：]{1,20}\s*(?:发表?)?时间\s*[:：]"      # 作者: 某人 时间:
    r"|\s*[-—–－=]*\s*(?:网友问答录|网友问答|问答录|读者问答录)\s*[:：]?\s*$"  # 问答录标签
    r")", re.I)


# 「作者: 某人 时间: …」的作者名（用于区分 wxmang 本人的段与他人发言）
RE_AUTH_NAME = re.compile(
    r"^\s*作者\s*[:：]?\s*([^\s:：]{1,20})\s*(?:发表?)?时间\s*[:：]", re.I)
WX_NAME_HINT = re.compile(r"wxmang|文小芒", re.I)


def _is_wx_name(name):
    return bool(WX_NAME_HINT.search(name or ""))


def split_repost_articles(rec, min_chars=300):
    """转载汇编页 → 拆成若干「候选正文」（每篇一段）。

    实测结构（CleanRobot.A 20 页，三种形态并存）：
      · 单篇页   `作者: wxmang  时间: …` → 正文 → 尾部问答录
                 （问答录用 `[某人] (时间)` 或 `作者: 某人  时间: …` 或 `网友问答录：`）
      · 合集页   多个 `作者: 文小芒（wxmang）发表时间: …` 标记，每标记起一篇
                 （如「中国农村改革的几个瞬间系列 共7篇」）
      · 混排页   正文之后紧跟问答录，两者**同用一种标记**（如「懒人版蹄髈」页
                 正文与网友问答都用 `作者: 名字  时间: …`）

    切分三步：
      ① 按「作者元信息行」切段，每段记下署名；
      ② 从第一个 **wxmang 署名**的段开始连续收集，**一旦遇到非 wxmang 署名的段即停**
         —— 这就是「混排页」正/答的天然分界（网友一出现，正文即结束）；
      ③ 段内再切掉 `[某人] (时间)` / `网友问答录：` 之后的内容。

    ⚠️ 不切的后果：整页 2.7 万字入 corpus，与已有的 3111 字原篇构成包含关系，
       dedup 取最长者作正文 → 原篇正文被替换成带问答录的大杂烩。
    """
    lines = clean_body(rec).splitlines()
    marks = []
    for i, ln in enumerate(lines):
        m = RE_AUTH_NAME.match(ln)
        if m:
            marks.append((i, m.group(1).strip()))
    if not marks:
        marks = [(0, "")]

    # 定位第一个 wxmang 署名段
    start_k = next((k for k, (_, nm) in enumerate(marks) if _is_wx_name(nm)), 0)
    segs, k = [], start_k
    while k < len(marks):
        if k > start_k and not _is_wx_name(marks[k][1]):
            break                          # 非 wxmang 署名出现 → 问答录开始，停止
        s = marks[k][0]
        e = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
        seg = lines[s:e]
        j = 0
        while j < len(seg) and (not seg[j].strip() or RE_META_LINE.match(seg[j])):
            j += 1
        out = []
        for ln in seg[j:]:
            if RE_ARTICLE_END.match(ln):
                break
            out.append(ln)
        t = "\n".join(out).strip()
        if len(t) >= min_chars:
            segs.append(t)
        k += 1
    return segs


def slice_repost_body(rec):
    """兼容入口：转载汇编页取最长的一篇候选正文（单篇页即全文）。"""
    b = split_repost_articles(rec)
    return max(b, key=len) if b else ""


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


# 代发/转载的标题前缀（可能叠加出现，如「代wxmang发帖-读《易经》心得—涣卦」）
RE_DAIFA_LEAD = re.compile(
    r"^\s*(?:【[^】]{0,20}代\s*(?:wxmang|忙总|文小芒)\s*发[帖贴图][^】]{0,20}】"
    r"|代\s*(?:wxmang|忙总|文小芒)\s*发[帖贴图])\s*[-—–－~～:：]?\s*")
RE_REPOST_LEAD = re.compile(r"^\s*wxmang\s*[-—–－]\s*", re.I)


def pretty_title(rec):
    """展示用标题：去掉【原创】/（搬家帖）/「代wxmang发帖」这类前缀。"""
    t = rec["page_title"] or rec["list_title"]
    for _ in range(4):
        before = t
        t = RE_DAIFA_LEAD.sub("", t)
        t = RE_REPOST_LEAD.sub("", t)
        t = RE_TITLE_PREFIX.sub("", t)
        t = t.strip()
        if t == before:
            break
    return t or rec["page_title"] or rec["list_title"]


def is_wxmang(rec):
    return (rec.get("page_author") or "").strip() == "wxmang"


def page_kind(rec):
    """判断该页承载的是不是 wxmang 的正文，以及属于哪一类。

    'self'   页面署名就是 wxmang（773 页）
    'daifa'  标题写明「代wxmang发帖」，内容是他的（实测 48 页，署名思炎）
    'repost' 转载账号的汇编页，正文首行带「作者: wxmang」元信息（实测 20 页，署名 CleanRobot.A）
    None     不属于以上任何一类

    ⚠️ 判据只用**页面自带的结构性证据**（署名 / 标题声明 / 正文内的作者元信息），
       不靠标题关键词猜内容——后者实测准确率仅 52.5%（见 fetch_meta.py 文档串）。
    """
    if is_wxmang(rec):
        return "self"
    t = (rec.get("page_title") or "") + " " + (rec.get("list_title") or "")
    if RE_DAIFA_TITLE.search(t):
        return "daifa"
    if RE_AUTH_HEAD.search(clean_body(rec)[:400]):
        return "repost"
    return None


def article_text(rec):
    """该页承载的「正文」，按页类型选路。"""
    return slice_repost_body(rec) if page_kind(rec) == "repost" else clean_body(rec)


# ─────────────────────────────────────────────────────────────
# 回复区专用净化（正文的 clean_body 不够用，回复里混的东西更多）
# 全部来自 28355 个 REPLY 块的实测统计，不是拍脑袋列的。
# ─────────────────────────────────────────────────────────────

# 论坛功能行 / 导航行：混在回复文本里，不是作者原话。
#   返回索引页 665 次、链接出处 258 次、通宝推：… 、关键词(Tags): … 、删除
#   编辑标记（postbit_editedby）1077 处，全库形态唯一：
#     `(这个帖子最后修改于: 10-08-2011 05:25 PM by wxmang.)`
#     它落在 REPLY 块内部（</blockquote> 之后、TIME 之前），不过滤就会
#     出现在「答」的正文里——实测原型 31 处。
REPLY_JUNK_LINE = re.compile(
    r"^\s*(?:返回索引页|返回列表|链接出处|删除删除|删除"
    r"|通宝推\s*[:：].*|关键词\(Tags\)\s*[:：].*|\[/?quote[^\]]*\]"
    r"|\(这个帖子最后修改于[:：].*\)|\(本帖最后由.*\))\s*$"
)

# BBCode 引用：部分老帖的引用没被转成 <blockquote>，原文留下了 [quote]…[/quote]。
# 实测样本：`[quote …[/quote] 1、臀尖肉就是猪屁股…` ← 前段是网友的话，后段才是 wxmang 的。
RE_BBQ_PAIR = re.compile(r"\[quote[^\]]*\].*?\[/quote\]", re.S | re.I)
RE_BBQ_CLOSE = re.compile(r"\[/quote\]", re.I)
RE_BBQ_OPEN = re.compile(r"\[quote[^\]]*\]?", re.I)
RE_BBQ_ANY = re.compile(r"\[/?quote", re.I)


def strip_bbcode_quote(text):
    """剥掉 BBCode 形式的引用。

    为什么要单独处理：<blockquote> 只覆盖了一部分引用，另一部分老帖
    留下的是 BBCode 原文。不剥就会把网友的话当成 wxmang 的收进来——
    正是 521 条误报的同类错误。

    边界判断（依据实测样本，引用总是出现在回复**开头**）：
      - 成对的 `[quote]…[/quote]` → 整块删除，保留两侧文字
      - 只剩孤立的 `[/quote]`  → 它之前是被引用的，丢弃之前
      - 只剩孤立的 `[quote]`   → 它之后是被引用的，丢弃之后

    ⚠️ 守卫必须同时认 `[quote` 与 `[/quote]`。曾写成 `"[quote" not in text`，
       而 `[/quote]` 里并**不**含子串 `[quote`（中间隔着 `/`），于是含 `[/quote]`
       的文本被原样放行——实测导致 002/014 两篇把网友的话收成了 wxmang 的答。
    """
    if not RE_BBQ_ANY.search(text):
        return text
    t = RE_BBQ_PAIR.sub(" ", text)
    low = t.lower()
    if "[/quote]" in low:
        t = t[low.rfind("[/quote]") + len("[/quote]"):]
    m = RE_BBQ_OPEN.search(t)
    if m:
        t = t[:m.start()]
    return t


def clean_reply_text(text):
    """回复文本 → 剥 BBCode 引用 + 剔除论坛功能行。"""
    t = strip_bbcode_quote(text)
    return "\n".join(
        ln for ln in t.splitlines()
        if ln.strip() and not REPLY_JUNK_LINE.match(ln)
    ).strip()


# ── <blockquote> 的剥离必须支持嵌套 ───────────────────────────
# 踩过的坑：用非贪婪正则 `<blockquote>.*?</blockquote>` 时，遇到嵌套
#     <blockquote>外 <blockquote>内</blockquote> 中间</blockquote> 真实内容
# 只会匹配到**内层**的闭合，剥完剩下 `中间</blockquote> 真实内容` ——
# 而「中间」那截是**引用的尾巴**（往往是 wxmang 自己的话），
# 于是它会被当成网友的发言收进"问"，或反过来混进"答"。
# 实测样本：ashok 的 SAY 里混入了 wxmang 上一轮的回复文字。
# 因此改用**标签配对计数**，一次剥掉整个最外层块，循环到没有为止。
RE_BQ_OPEN = re.compile(r"<blockquote[^>]*>", re.I)
RE_BQ_CLOSE = re.compile(r"</blockquote\s*>", re.I)


def strip_blockquotes(html, rounds=6):
    """删除所有最外层的 <blockquote>…</blockquote>（正确处理嵌套）。"""
    for _ in range(rounds):
        if not RE_BQ_OPEN.search(html):
            break
        out, pos = [], 0
        while True:
            m = RE_BQ_OPEN.search(html, pos)
            if not m:
                out.append(html[pos:])
                break
            out.append(html[pos:m.start()])
            depth, q = 1, m.end()
            while depth > 0:
                no = RE_BQ_OPEN.search(html, q)
                nc = RE_BQ_CLOSE.search(html, q)
                if not nc:
                    q = len(html)
                    break
                if no and no.start() < nc.start():
                    depth += 1
                    q = no.end()
                else:
                    depth -= 1
                    q = nc.end()
            pos = q
        html = "".join(out)
    return html


# 签名档：网友的固定尾签，每帖都带。实测全库 391 处，**全部落在 SAY（网友段）**，
# 0 处落进 REPLY——即不会污染「答」，但会让「问」显得臃肿（同一网友每帖重复一遍）。
# 有明确的 HTML 注释标记，可精确剥离，零误伤。
RE_SIGNATURE = re.compile(
    r"<!--\s*start:\s*postbit_signature\s*-->.*?<!--\s*end:\s*postbit_signature\s*-->",
    re.S | re.I)


def strip_signature(html):
    """剥掉网友的固定签名档（位于 SAY 内）。"""
    return RE_SIGNATURE.sub(" ", html)


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


LAST_DROPPED_REPOST = []
LAST_MERGED_REPOST = []
LAST_MERGED_TITLE = []


def _title_sim(a, b):
    return difflib.SequenceMatcher(None, a or "", b or "").ratio()


def _ngram_set(texts, n=16):
    """把若干正文压成 n-gram 集合（用于覆盖检测）。

    ⚠️ 必须 **step=1**（每个位置都取）。曾用 step=3 省内存，结果与
       `_cover_ratio` 的 step=2 扫描叠加，再加上两段文本本身存在偏移
       （实测「新君登基」页与思炎版正文偏 34 字），大量 gram 落在
       错位的采样点上——真实命中率 0.971 被算成 0.325。
       改为全位置取样 + 哈希存储，内存约 150MB，可接受。
    """
    g = set()
    for t in texts:
        s = norm(t)
        for i in range(len(s) - n + 1):
            g.add(hash(s[i:i + n]))
    return g


def _cover_ratio(text, grams, n=16, step=2):
    """text 有多少比例的内容能在 grams 里找到。"""
    s = norm(text)
    if len(s) < n:
        return 0.0
    hit = tot = 0
    for i in range(0, len(s) - n + 1, step):
        tot += 1
        if hash(s[i:i + n]) in grams:
            hit += 1
    return hit / tot if tot else 0.0


def drop_covered(cands, refs, thresh=0.90, progress=None):
    """剔除「已被参照篇目覆盖」的候选。

    为什么需要：dedup 的近似比对带**长度窗口**（`window = 30% 长度`，为控制
    O(n²) 成本），于是「一篇 2.1 万字的合集」与「构成它的 5 篇 2 千字单篇」
    因长度差超窗而**从不比对**，重复篇照样进 corpus。实测样本：
    「读《资治通鉴》心得：新君登基」——思炎代发的 5 篇（合计 2.24 万字）
    与 CleanRobot.A 的合集页（2.14 万字）本是一回事，却各占一条。
    这里用与长度无关的 n-gram 覆盖率兜底，只作用于转载页（数量少、成本低）。
    """
    grams = _ngram_set([r["_clean"] for r in refs])
    out, dropped = [], []
    for i, c in enumerate(cands):
        r = _cover_ratio(c["_clean"], grams)
        (dropped if r >= thresh else out).append((c, r))
        if progress and (i % 5 == 0 or i == len(cands) - 1):
            progress(i + 1, len(cands))
    return [c for c, _ in out], [(c, r) for c, r in dropped]


def _title_key(rec):
    """标题归一化键：剥离前缀、括注序号与全部标点，用于「同题」归组。"""
    t = pretty_title(rec)
    t = re.sub(r"[（(]\s*[一二三四五六七八九十百\d]+\s*[)）]", "", t)
    t = re.sub(r"[《》【】（）()\[\]「」『』：:，,。、·\-—–－~～\s]", "", t)
    return t


def _group_by_title(cands):
    """按标题归组：归一化键**相同**，或一键**包含**另一键（短键 ≥5 字）。

    为什么要包含匹配：同一篇在不同来源的标题常差一个系列前缀——
    「屯卦：创业的故事」（2011 原发）与「读《易经》心得：屯卦：创业的故事」
    （2011-07 搬家版），归一化键不同却指同一篇。按长度降序遍历 + 单次归组，
    保证每篇只进一个组，且短键依附于最长的父键。
    """
    ks = sorted(((c, _title_key(c)) for c in cands), key=lambda x: -len(x[1]))
    groups, assigned = [], set()
    for c, k in ks:
        if id(c) in assigned or not k:
            continue
        grp = [c]
        assigned.add(id(c))
        for c2, k2 in ks:
            if id(c2) in assigned or len(k2) < 5:
                continue
            if k2 in k or k in k2:
                grp.append(c2)
                assigned.add(id(c2))
        groups.append(grp)
    return groups


def merge_same_title(cands, cover_th=0.90):
    """同标题的「长版 ⊃ 短版」强制合并。

    为什么 dedup 不够：dedup 的近似比对带**长度窗口**（`window = 30% 长度`，
    为控制 O(n²) 成本），长度差超窗的对**从不比对**。实测漏网样本：
      「屯卦：创业的故事」2011 版 5601 字 与 2012 代发版 10144 字，
      标题逐字相同、后者完整包含前者，却因长度差 4543 > 1680 各占一条。
    这里只对**同标题**组做与长度无关的 n-gram 覆盖检测，成本可控。

    合并方向：正文取长版（更完整），元数据（标题/日期/分类）仍取原短版——
    转载/代发页的日期是**搬运日**，不是写作日，不该覆盖原始发表日。
    """
    drop_ids, merged = set(), []
    for arr in _group_by_title(cands):
        if len(arr) < 2:
            continue
        # 键完全相同（同题，仅编号/前缀不同）→ 总是合并；
        # 键只是包含关系（如「童年碎影」与其分篇）→ 只在涉及转载/代发页时处理，
        # 旧 corpus 内部既有的合集结构不在本次口径变更范围。
        same_key = len({_title_key(c) for c in arr}) == 1
        if not same_key and not any(c["_kind"] != "self" for c in arr):
            continue
        arr = sorted(arr, key=lambda r: len(r["_clean"]))
        for i in range(len(arr) - 1, 0, -1):
            big = arr[i]
            if id(big) in drop_ids:
                continue
            gb = _ngram_set([big["_clean"]])
            for j in range(i - 1, -1, -1):
                small = arr[j]
                if id(small) in drop_ids:
                    continue
                if len(big["_clean"]) < len(small["_clean"]) * 1.05:
                    continue
                if _cover_ratio(small["_clean"], gb) >= cover_th:
                    small["_extra_sources"] = small.get("_extra_sources", []) + [big["url"]]
                    small["_clean"] = big["_clean"]
                    drop_ids.add(id(big))
                    merged.append((small, big))
                    break
    return [c for c in cands if id(c) not in drop_ids], merged


def build_corpus(meta=None, threshold=0.97, progress=None, expand=True):
    """产出权威文集：去重后的唯一篇目。

    expand=True（默认）时候选池为三类页面之并：
        self   773 页本人署名
        daifa   48 页「代wxmang发帖」（思炎代发，《读易经》心得 43 卦等）
        repost  20 页转载汇编页（CleanRobot.A；正文先切掉其后的问答录）
    三类之间靠 dedup 的精确/近似/包含三重判据合并——即「用正文去重」，
    同一篇的新旧版本（如屯卦 2011 版与 2012 代发版）归并为一条。
    """
    meta = meta if meta is not None else load_meta()
    wx = []
    for m in meta:
        k = page_kind(m)
        if not k or (k != "self" and not expand):
            continue
        if k == "repost":
            # 汇编页可能承载多篇原文（如「张厂长的故事123」= 3 篇）
            for j, txt in enumerate(split_repost_articles(m), 1):
                if not txt:
                    continue
                d = dict(m)
                d["_kind"], d["_part"], d["_clean"] = k, j, txt
                wx.append(d)
        else:
            d = dict(m)
            d["_kind"], d["_part"], d["_clean"] = k, 0, clean_body(m)
            if d["_clean"]:
                wx.append(d)
    if expand:
        # 转载页（repost）先与本人署名/代发篇目做覆盖比对，剔掉整段重复的
        refs = [d for d in wx if d["_kind"] in ("self", "daifa")]
        reps = [d for d in wx if d["_kind"] == "repost"]
        if reps:
            kept, dropped = drop_covered(reps, refs)
            del LAST_DROPPED_REPOST[:]
            LAST_DROPPED_REPOST.extend(dropped)
            del LAST_MERGED_REPOST[:]
            rest = []
            for c in kept:
                # 「合集页 vs 单篇」：repost 比某篇 ref 更长、且完整包含它 →
                # 同一篇的不同版本，正文换成更全的 repost 版，元数据仍取原篇。
                # 实测「一篇可以用来观察中国民营企业发展的研究报告」页
                # = 报告1（9353 字，已收）+ 报告 2/3（约 1.6 万字，未收）。
                cand = [r for r in refs
                        if len(r["_clean"]) <= len(c["_clean"])
                        and _title_sim(r["page_title"], c["page_title"]) >= 0.45]
                cg = _ngram_set([c["_clean"]]) if cand else None
                subs = [(r, _cover_ratio(r["_clean"], cg)) for r in cand]
                subs = [(r, v) for r, v in subs if v >= 0.90]
                if len(subs) == 1:
                    r = subs[0][0]
                    r["_extra_sources"] = r.get("_extra_sources", []) + [c["url"]]
                    r["_clean"] = c["_clean"]
                    LAST_MERGED_REPOST.append((r, c, subs[0][1]))
                    continue
                rest.append(c)
            wx = [d for d in wx if d["_kind"] != "repost"] + rest
    # 同标题的长短版本合并（dedup 的长度窗口会漏掉这类）
    wx, same_title_merged = merge_same_title(wx)
    del LAST_MERGED_TITLE[:]
    LAST_MERGED_TITLE.extend(same_title_merged)
    groups = dedup(wx, threshold=threshold, progress=progress)
    corpus = []
    for i, grp in enumerate(groups, 1):
        head = grp[0]                       # 最早的一条 → 归属与日期
        body_src = max(grp, key=lambda r: len(r["_clean"]))   # 最完整的一条 → 正文
        kinds = [g["_kind"] for g in grp]
        corpus.append({
            "id": i,
            "title": pretty_title(head),
            "date": head["page_date"],
            "author": "wxmang",
            "page_kind": "self" if "self" in kinds else kinds[0],
            "category": head["list_cat"] or "未分类",
            "series": head["list_series"] or "",
            "body_chars": len(body_src["_clean"]),
            "body_from": body_src["url"],
            "sources": [{"url": g["url"], "date": g["page_date"],
                         "raw_title": g["page_title"], "batch": g["batch"],
                         "kind": g["_kind"], "part": g.get("_part", 0)} for g in grp],
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
