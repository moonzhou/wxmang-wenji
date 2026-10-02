#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取 wxmang.site 全量页面的**真实元数据**，建立权威底册。

为什么需要这一步：
    梳理报告里的「作者归属」是按标题关键词猜的（排除求助/请教/代发/回复类标题），
    抽样核验后发现与页面真实署名严重不符（120 篇随机样本中真实署名 wxmang 的仅 52.5%，
    而报告口径为 89.5%）。本脚本改用页面自带的 <p class="author"> 字段作为唯一依据。

页面结构（已在多篇上核验）：
    <body><div class="BODY">
      <div class="BACK">…</div>
      <h1>标题</h1>
      <p class="author">真实署名</p>
      <p class="DATE">2005-08-03 10:04:57</p>
      <br><br>
      <div class="POST">  ← 正文；留言区从第一个 <div class="LI"> 开始
        <p>…</p> …
        <div class="LI">  ← 楼层：USER / SAY / REPLY（wxmang 的回复在 REPLY 里）
      </div>
      <div class="BACK">…</div>
    </div></body>

输出：
    原始 HTML 缓存 → wxmang-梳理/raw/<batch>_<id>.html
    权威元数据     → wxmang-梳理/wxmang-权威元数据.csv / .json
"""

import csv
import hashlib
import html as htmllib
import io
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import wxlib  # noqa: E402  同目录公共库；工作区根解析统一放在它里面

ROOT = wxlib.ROOT
WORK = os.path.join(ROOT, "wxmang-梳理")
RAW = os.path.join(WORK, "raw")
SRC_CSV = os.path.join(WORK, "wxmang-文章总清单.csv")
OUT_CSV = os.path.join(WORK, "wxmang-权威元数据.csv")
OUT_JSON = os.path.join(WORK, "wxmang-权威元数据.json")

UA = "Mozilla/5.0 (compatible; wxmang-archive-indexer/1.0)"
WORKERS = 12
RETRY = 3

RE_H1 = re.compile(r"<h1>(.*?)</h1>", re.S)
RE_AUTHOR = re.compile(r'<p class="author">(.*?)</p>', re.S)
RE_DATE = re.compile(r'<p class="DATE">(.*?)</p>', re.S)
RE_POST = re.compile(r'<div class="POST">', re.I)
RE_LI = re.compile(r'<div class="LI"', re.I)
RE_BACK = re.compile(r'<div class="BACK"', re.I)
RE_TAG = re.compile(r"<[^>]+>")
RE_WS = re.compile(r"[ \t\u3000]+")


def fetch(url, dest):
    """抓取一页；命中本地缓存则直接读盘，避免重复下载。"""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        with io.open(dest, encoding="utf-8", errors="ignore") as f:
            return f.read(), True
    last = None
    for i in range(RETRY):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                data = r.read().decode("utf-8", "ignore")
            with io.open(dest, "w", encoding="utf-8", newline="\n") as f:
                f.write(data)
            return data, False
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"fetch failed: {url} :: {last}")


def to_text(fragment):
    """HTML 片段 → 纯文本（用于去重哈希与摘要）。"""
    s = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    s = re.sub(r"</p>", "\n", s, flags=re.I)
    s = RE_TAG.sub("", s)
    s = htmllib.unescape(s)
    s = RE_WS.sub(" ", s)
    s = "\n".join(ln.strip() for ln in s.splitlines())
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def split_body(html_text):
    """切出正文区（剔除留言楼层）。"""
    m = RE_POST.search(html_text)
    if not m:
        return None
    start = m.end()
    li = RE_LI.search(html_text, start)
    back = RE_BACK.search(html_text, start)
    ends = [x.start() for x in (li, back) if x]
    end = min(ends) if ends else len(html_text)
    return html_text[start:end]


def norm_key(text):
    """去重键：去掉全部空白与标点差异后的正文指纹。"""
    s = re.sub(r"\s+", "", text)
    s = re.sub(r"[，。、；：！？…—－\-·“”‘’（）《》〈〉\[\]【】,.!?;:]", "", s)
    return s


def parse(row, idx):
    url = row["原文链接"]
    m = re.search(r"/(\d+)_(\d+)\.html", url)
    batch, pid = (m.group(1), m.group(2)) if m else ("x", str(idx))
    dest = os.path.join(RAW, f"{batch}_{pid}.html")

    html_text, cached = fetch(url, dest)

    h1 = RE_H1.search(html_text)
    au = RE_AUTHOR.search(html_text)
    dt = RE_DATE.search(html_text)
    body = split_body(html_text)
    text = to_text(body) if body else ""

    n_li = len(RE_LI.findall(html_text))
    n_reply = len(re.findall(r'<div class="REPLY"', html_text, re.I))

    return {
        "序号": row["序号"],
        "url": url,
        "batch": batch,
        "page_title": to_text(h1.group(1)) if h1 else "",
        "page_author": to_text(au.group(1)) if au else "",
        "page_datetime": to_text(dt.group(1)) if dt else "",
        "page_date": (to_text(dt.group(1))[:10] if dt else ""),
        "list_title": row["标题"],
        "list_date": row["日期"],
        "list_author_guess": row["作者归属"],
        "list_cat": row["主题分类"],
        "list_series": row["系列"],
        "body_chars": len(text),
        "body_sha1": hashlib.sha1(norm_key(text).encode("utf-8")).hexdigest() if text else "",
        "body_key_len": len(norm_key(text)),
        "n_comment_blocks": n_li,
        "n_reply_blocks": n_reply,
        "has_body": bool(body),
        "cached": cached,
    }


def main():
    os.makedirs(RAW, exist_ok=True)
    rows = list(csv.DictReader(io.open(SRC_CSV, encoding="utf-8-sig")))
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if limit:
        rows = rows[:limit]
    print(f"[fetch_meta] 待抓取 {len(rows)} 页（缓存命中将跳过下载）", flush=True)

    out, errs = [], []
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(parse, r, i): r for i, r in enumerate(rows)}
        for fut in futs:
            r = futs[fut]
            try:
                out.append(fut.result())
            except Exception as e:  # noqa: BLE001
                errs.append({"url": r["原文链接"], "error": str(e)[:200]})
            done += 1
            if done % 100 == 0:
                print(f"  … {done}/{len(rows)}", flush=True)

    out.sort(key=lambda x: (x["list_date"], x["序号"]))
    fields = list(out[0].keys())
    with io.open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out)
    with io.open(OUT_JSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"[fetch_meta] 完成：{len(out)} 条 → {OUT_CSV}")
    if errs:
        print(f"[fetch_meta] 失败 {len(errs)} 条：")
        for e in errs[:20]:
            print("   ", e["url"], e["error"])
        with io.open(os.path.join(WORK, "fetch_errors.json"), "w",
                     encoding="utf-8", newline="\n") as f:
            json.dump(errs, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
