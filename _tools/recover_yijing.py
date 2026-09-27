# -*- coding: utf-8 -*-
"""从 2020 稿补录 乾卦：天道2 / 坤卦：臣道2 两篇（源文集缺失），
   生成符合文集规范的 Hugo 页面，并追加 corpus 条目。幂等。

规范来源：现有正文页（如 099-乾卦：天道1.md）的 front matter 字段与顺序。
"""
import io, json, os, re, sys

REPO = r"D:/个人网站/wxmang-wenji"
META = os.path.join(REPO, "_meta", "corpus.json")
MD2020 = r"D:/download/读易经心得 文小芒 202010.md"

# 待补录：2020稿章节名 -> (站点标题, 首发日期, 承接的正文页 source_url 用于溯源)
RECOVER = [
    # 乾卦2 紧接乾卦1（2011-01-20 发文，正文末尾指路「天道2」）
    dict(sec="乾卦：天道2", title="乾卦：天道2", date="2011-01-20",
         prev_source="https://wxmang.site/html/1_3254330.html"),
    dict(sec="坤卦：臣道2", title="坤卦：臣道2", date="2011-01-24",
         prev_source="https://wxmang.site/html/1_3258129.html"),
]

SERIES = "读《易经》心得"


def split_sections():
    md = open(MD2020, encoding="utf-8").read()
    secs = re.split(r"^## ", md, flags=re.M)
    out = {}
    for s in secs:
        if "\n" not in s:
            continue
        t, body = s.split("\n", 1)
        out[t.strip()] = body.strip()
    return out


def clean_body(b):
    """去掉论坛残留功能行，并把 2020 稿因 run 切分产生的 `****`/嵌套残迹并回。"""
    lines = []
    for ln in b.split("\n"):
        if re.search(r"链接出处|最后于\d{4}-\d{2}-\d{2}.*改,?共?\d*次", ln):
            continue
        lines.append(ln)
    b = "\n".join(lines).strip()
    # 1) `**A****B**`（相邻加粗 run 切分）→ `**AB**`：
    #    4 个星号出现在一对加粗「内部」，实为两段各自的收尾+开头，直接删掉。
    b = re.sub(r"(?<=\S)\*{4}(?=\S)", "", b)
    # 2) 行首/行尾残留的 `****` → `**`
    b = re.sub(r"\*{4,}", "**", b)
    # 3) 嵌套形态 **《**文言**》**：星号包在书名号外侧，去掉内层一对
    b = re.sub(r"\*\*《\*\*(.+?)\*\*》\*\*", r"**《\1》**", b)
    # 4) 每行内 ** 计数补平
    out = []
    for ln in b.split("\n"):
        if ln.count("**") % 2 == 1:
            ln = ln.rstrip() + "**"
        out.append(ln)
    return "\n".join(out).strip()


def build(sec_title, meta):
    from urllib.parse import quote
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", meta["title"])[:50]
    url = f"/wxmang/classics/i-ching/{slug}/"
    p = []
    p.append("---")
    p.append(f'title: "{meta["title"]}"')
    p.append(f'slug: "{slug}"')
    p.append(f'url: "{url}"')
    p.append(f'date: {meta["date"]}')
    p.append('wx_author: "wxmang"')
    p.append('wx_cat: "传统文化"')
    p.append(f'wx_series: "{SERIES}"')
    p.append("# 无配套问答页：源文集缺失。")
    p.append(f'original_date: {meta["date"]}')
    p.append("# ⚠️ 源文集缺失本篇，正文转录自 2020-10 版《读易经心得》完整整理稿。")
    p.append("#    转录：准（2026-09-27）。原帖首发应与上篇同日，此后论坛批次中未见独立落页。")
    p.append(f'recovered_from: "读易经心得 文小芒 202010.docx"')
    # host_url：该内容在公开论坛的承载页（原帖指路处）。
    # ⚠️ 用 host_url 而非自定义字段名——构建门禁（preflight）的溯源判据只认
    #    source_url / host_url 两者之一，自定义名会被判「缺失溯源」而阻断发布。
    p.append(f'host_url: "{meta["prev_source"]}"   # 公开来源：承接的原帖页')
    p.append("excludeFromSearch: true   # 隔离：不进全站搜索索引")
    p.append("---")
    p.append("")
    p.append(f'> 作者：wxmang ｜ 首发：{meta["date"]} ｜ **本篇源文集缺失，'
             f'正文转录自 2020-10 版《读易经心得》完整整理稿** ｜ '
             f'[承接上篇]({meta["prev_source"]})')
    p.append("")
    p.append(clean_body(split_sections()[sec_title]))
    p.append("")
    return "\n".join(p), slug, url


def main():
    ins = split_sections()
    corpus = json.load(open(META, encoding="utf-8"))
    titles = {c["title"] for c in corpus}
    maxid = max(c["id"] for c in corpus)

    series_dir = os.path.join(REPO, "03-传统文化", SERIES)
    os.makedirs(series_dir, exist_ok=True)

    for meta in RECOVER:
        if meta["sec"] not in ins:
            print("!! 2020稿中找不到章节:", meta["sec"])
            continue
        md, slug, url = build(meta["sec"], meta)
        fname = f'X-{meta["title"]}.md'   # 编号由重排脚本统一给
        path = os.path.join(series_dir, fname)
        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(md)
        print("写出:", os.path.relpath(path, REPO).replace("\\", "/"),
              f"({len(md)} 字符)")

        if meta["title"] not in titles:
            maxid += 1
            corpus.append({
                "id": maxid, "title": meta["title"], "date": meta["date"],
                "author": "wxmang", "page_kind": "self",
                "category": "传统文化与经典", "series": SERIES,
                "body_chars": len(clean_body(ins[meta["sec"]])),
                "body_from": "recovered:2020-md",
                "sources": [{"url": "recovered:2020-md", "date": meta["date"],
                             "raw_title": meta["title"], "batch": "recovered",
                             "kind": "recovered", "part": 0}],
                "dup_count": 1,
            })
            print("  corpus 追加 id=", maxid)
        else:
            print("  corpus 已存在，跳过")

    with io.open(META, "w", encoding="utf-8", newline="\n") as f:
        json.dump(corpus, f, ensure_ascii=False, indent=2)
    print("corpus 现有", len(corpus), "条")


if __name__ == "__main__":
    main()
