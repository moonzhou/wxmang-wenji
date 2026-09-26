#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_bad_urls.py —— 把正文里“含非法百分号转义”的裸 URL 用反引号包住。

背景
----
站上原帖里存在**被截断的 URL**，例如：
    http://hi.baidu.com/%B4%F3%B1%F0%C9%BD%B...64edd.html
    http://www.hudong.com/wiki/%E8%9
它们在原文里就无法访问（作者当时粘贴时截断了），却残留非法的百分号转义。
Hugo 的 render-link 钩子会对链接目标调用 urls.Parse，遇到非法转义直接**构建失败**
（v0.166 起为硬错误，非警告）：
    error calling Parse: invalid URL escape "%B."

处置
----
这类 URL 在原文中本就不指向任何有效页面，改为**行内代码**（反引号）呈现：
既完整保留原文，又不再被 Markdown/Hugo 解析为链接。文档更诚实，构建也不再炸。

用法
----
    python _tools/fix_bad_urls.py            # 只报告，不改动
    python _tools/fix_bad_urls.py --write    # 实际写入

幂等：已被反引号包住的 URL 不会重复处理。
"""

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# URL 的合法终止符：空白、全角空格、中英文括号、尖括号、引号、中文标点、竖线、反引号
# ⚠️ 反引号必须计入：否则已被 ` 包住的 URL 会把收尾反引号一并吞进匹配，
#    导致 m.end() 落到行尾、幂等判断失效（本脚本初版即踩此坑）。
_ENDS = ''.join([
    r'\s', r'\u3000', '（）()', '<>', '"\'',
    '\u201c\u201d\u2018\u2019', '，。；：、！？…', '|', '`',
])
RE_BARE = re.compile(r'https?://[^' + _ENDS + r']*')
# % 后面不是两位十六进制 → 非法转义
RE_BAD_ESC = re.compile(r'%(?![0-9A-Fa-f]{2})')

SKIP_DIRS = {'.git', '_meta', '_tools'}


def is_bad_url(u):
    return bool(RE_BAD_ESC.search(u))


def fix_line(line):
    """把一行里所有非法裸 URL 包成反引号，返回 (新行, 修复数)。"""
    out = []
    pos = 0
    n = 0
    for m in RE_BARE.finditer(line):
        u = m.group(0)
        if not is_bad_url(u):
            continue
        # 幂等：若已被反引号包住则跳过
        if m.start() > 0 and line[m.start() - 1] == '`' and \
           m.end() < len(line) and line[m.end()] == '`':
            continue
        out.append(line[pos:m.start()])
        out.append('`' + u + '`')
        pos = m.end()
        n += 1
    if not out:
        return line, 0
    out.append(line[pos:])
    return ''.join(out), n


def main():
    write = '--write' in sys.argv
    total_files = 0
    total_fixes = 0

    for dp, dn, fn in os.walk(REPO):
        parts = dp.replace('\\', '/').split('/')
        if SKIP_DIRS & set(parts):
            continue
        for f in sorted(fn):
            if not f.endswith('.md'):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, REPO).replace('\\', '/')
            try:
                text = open(p, encoding='utf-8').read()
            except Exception as e:
                print(f'  [跳过] {rel}: {e}')
                continue
            lines = text.split('\n')
            changed = 0
            for i, ln in enumerate(lines):
                new, n = fix_line(ln)
                if n:
                    lines[i] = new
                    changed += n
            if changed:
                total_files += 1
                total_fixes += changed
                print(f'  {rel}  →  {changed} 处')
                if write:
                    # 只替换行内子串，不动换行符 → 行尾风格原样保留
                    open(p, 'w', encoding='utf-8', newline='').write('\n'.join(lines))

    mode = '已写入' if write else '仅报告（加 --write 才写入）'
    print(f'\n[{mode}] 命中文件 {total_files} 个 / 非法 URL {total_fixes} 处')
    if not write and total_fixes:
        print('确认无误后执行：python _tools/fix_bad_urls.py --write')
    return 0


if __name__ == '__main__':
    sys.exit(main())
