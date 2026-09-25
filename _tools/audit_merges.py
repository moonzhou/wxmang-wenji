#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_merges.py —— 合并质量审计。

对每个由去重产生的"合并组"，计算组内两两的覆盖率（较短一篇有多大比例被较长一篇覆盖）。
覆盖率过低的组说明可能把不相干的文章并到了一起，需要人工看。

用法：python _tools/audit_merges.py [阈值，默认 0.80]
"""

import difflib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wxlib  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def body_of(entry, url):
    src = next((s for s in entry["sources"] if s["url"] == url), entry["sources"][0])
    return wxlib.norm(wxlib.clean_body(
        {"url": src["url"], "batch": src["batch"], "page_date": src["date"]}))


def main():
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 0.80
    corpus = json.load(io.open(os.path.join(REPO, "_meta", "corpus.json"),
                              encoding="utf-8"))
    groups = [c for c in corpus if c["dup_count"] >= 2]
    print(f"[audit_merges] 检查 {len(groups)} 个合并组（阈值 {limit}）")

    worst_all, suspects = 1.0, []
    for g in groups:
        bs = [body_of(g, s["url"]) for s in g["sources"]]
        worst = 1.0
        for i in range(len(bs)):
            for j in range(i + 1, len(bs)):
                sm = difflib.SequenceMatcher(None, bs[i], bs[j])
                short = max(min(len(bs[i]), len(bs[j])), 1)
                cov = sum(b.size for b in sm.get_matching_blocks()) / short
                worst = min(worst, cov)
        worst_all = min(worst_all, worst)
        if worst < limit:
            suspects.append((worst, g["title"], g["dup_count"]))

    print(f"  全库最低覆盖率：{worst_all:.4f}")
    if suspects:
        print(f"  ⚠️ 低于阈值的可疑组 {len(suspects)} 个：")
        for w, t, n in sorted(suspects):
            print(f"     cov={w:.3f}  ×{n}  {t}")
    else:
        print(f"  ✅ 没有低于阈值的组，未发现明显误并")
    return 1 if suspects else 0


if __name__ == "__main__":
    sys.exit(main())
