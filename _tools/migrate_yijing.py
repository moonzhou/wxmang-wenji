# -*- coding: utf-8 -*-
"""《读易经》系列整理：把散落各处的旧文件清掉，只保留 fetch_articles 新生成的
   正文页 + 迁移过来的问答页。幂等：先校验、后操作。

旧位置（待清理的**正文页**）：
  - 03-传统文化/读《易经》心得/001-044-*.md   （旧系列页，编号已作废）
  - 03-传统文化/099,100,102,112,...131-*.md   （20 篇散在根目录）
  - 01-管理学/128-临卦*.md
  - 09-其他/142-引子*.md, 143-入门介绍*.md
  - 01-管理学/101-用《易经》算卦*.md
  - 03-传统文化/372-读《易经》总结*.md

问答页（-qa.md）要**跟着正文一起迁移**，不能丢。
"""
import io, json, os, re, shutil, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERIES_DIR = os.path.join(REPO, "03-传统文化", "读《易经》心得")
SERIES_SLUG = "i-ching"
SERIES = "读《易经》心得"

sys.path.insert(0, os.path.join(REPO, "_tools"))
import taxonomy as tx  # noqa


def load_corpus():
    return json.load(io.open(os.path.join(REPO, "_meta", "corpus.json"),
                             encoding="utf-8"))


def target_names():
    """新编号 → 标题（来自 corpus + 顺序表），用于定位新旧文件对应关系。"""
    corpus = load_corpus()
    for c in corpus:
        c["series"] = tx.series_of(c["title"], c.get("series"))
    arr = [c for c in corpus if c["series"] == SERIES]
    arr.sort(key=lambda x: tx.series_sort_key(SERIES, x))
    out = []
    for i, c in enumerate(arr, 1):
        out.append((i, c["title"], c["id"]))
    return out


def safe_name(s, limit=50):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "", s)
    s = re.sub(r"\s+", " ", s).strip().rstrip(".")
    return s[:limit].strip() or "untitled"


def main():
    dry = "--apply" not in sys.argv
    names = target_names()
    print(f"目标篇数: {len(names)}  ({'预演' if dry else '执行'})")

    # ---- 1) 新正文页清单（fetch_articles 已生成；recovered 篇目为 X-*.md） ----
    new_bodies = {}
    ready = 0
    for i, title, _id in names:
        fn = f"{i:03d}-{safe_name(title)}.md"
        p = os.path.join(SERIES_DIR, fn)
        new_bodies[title] = fn
        if os.path.exists(p):
            ready += 1
        elif os.path.exists(os.path.join(SERIES_DIR, f"X-{safe_name(title)}.md")):
            print(f"  >> 待重命名: X-{safe_name(title)}.md -> {fn}")
        else:
            print(f"  !! 缺新正文页: {fn}")
    print(f"新正文页就位: {ready}/{len(names)}（其余为待重命名的 recovered 篇目）")

    # ---- 2) 扫描系列目录里的**旧**文件（不在新清单里的非 _index 文件） ----
    keep = set(new_bodies.values())
    recovered_pending = {f"X-{safe_name(t)}.md" for i, t, _ in names}   # 待改名，不算 stale
    stale = []
    for fn in os.listdir(SERIES_DIR):
        if fn == "_index.md":
            continue
        if fn in keep or fn in recovered_pending:
            continue
        # 新正文页的配套问答页形如 `NNN-title-qa.md`
        base = re.sub(r"-qa\.md$", ".md", fn)
        if fn.endswith("-qa.md") and base in keep:
            continue
        stale.append(fn)
    print(f"\n系列目录内待清理旧文件: {len(stale)}")
    for fn in sorted(stale):
        print("   -", fn)

    # ---- 3) 扫描外部旧文件（根目录 / 其它大类） ----
    ext = []
    patterns = [
        ("03-传统文化", r"^(099|100|102|112|113|115|116|117|118|119|120|121|122|124|125|126|127|130|131|372)-"),
        ("01-管理学", r"^(101|128)-"),
        ("09-其他", r"^(142|143)-"),
    ]
    for d, pat in patterns:
        dd = os.path.join(REPO, d)
        for fn in sorted(os.listdir(dd)):
            if re.match(pat, fn) and fn.endswith(".md"):
                ext.append(os.path.join(dd, fn))
    print(f"\n外部待清理旧文件: {len(ext)}")
    for p in ext:
        print("   -", os.path.relpath(p, REPO).replace("\\", "/"))

    if dry:
        print("\n[预演] 加 --apply 执行")
        return

    # ---- 4) 迁移问答页（旧 qa → 新编号 qa），并同步正文页里的链接与 url ----
    # 4a) 先把 recovered 篇目（X-*.md）改名为新编号
    for i, title, _id in names:
        old = os.path.join(SERIES_DIR, f"X-{safe_name(title)}.md")
        if os.path.exists(old):
            new = os.path.join(SERIES_DIR, f"{i:03d}-{safe_name(title)}.md")
            shutil.move(old, new)
            print(f"   重命名: X-{safe_name(title)}.md -> {i:03d}-{safe_name(title)}.md")
    # 用「旧正文页文件名 → 标题」映射来找到旧 qa
    # 旧 qa 命名 = 旧编号-旧标题-qa.md
    moved_qa = 0
    old_body_map = {}   # 旧文件名 -> 标题
    for p in ext + [os.path.join(SERIES_DIR, s) for s in stale]:
        fn = os.path.basename(p)
        if fn.startswith("_") or fn.endswith("-qa.md"):
            continue
        txt = io.open(p, encoding="utf-8").read()
        m = re.search(r'^title:\s*"?(.+?)"?\s*$', txt, re.M)
        if m:
            old_body_map[fn] = m.group(1).strip()

    print("\n--- 迁移问答页 ---")
    for old_p in list(ext) + [os.path.join(SERIES_DIR, s) for s in stale]:
        d = os.path.dirname(old_p)
        fn = os.path.basename(old_p)
        if fn.endswith("-qa.md"):
            continue
        qa_old = os.path.join(d, fn[:-3] + "-qa.md")
        if not os.path.exists(qa_old):
            continue
        title = old_body_map.get(fn)
        if not title or title not in new_bodies:
            print("   ! 无法对应:", fn, "->", title)
            continue
        qa_new = os.path.join(SERIES_DIR, new_bodies[title][:-3] + "-qa.md")
        if os.path.exists(qa_new):
            print("   = 已存在，跳过:", os.path.basename(qa_new))
            continue
        shutil.move(qa_old, qa_new)
        moved_qa += 1
        # 问答页内的 url 与指向正文的链接要跟着改
        t = io.open(qa_new, encoding="utf-8").read()
        t = t.replace("/wxmang/classics/", f"/wxmang/classics/{SERIES_SLUG}/")
        io.open(qa_new, "w", encoding="utf-8", newline="\n").write(t)
        print("   ->", os.path.basename(qa_new))
    print(f"迁移问答页: {moved_qa}")

    # ---- 5) 删除旧文件 ----
    removed = 0
    for p in ext + [os.path.join(SERIES_DIR, s) for s in stale]:
        if os.path.exists(p):
            os.remove(p)
            removed += 1
    print(f"\n删除旧文件: {removed}")
    print("剩余系列目录文件数:", len(os.listdir(SERIES_DIR)))


if __name__ == "__main__":
    main()
