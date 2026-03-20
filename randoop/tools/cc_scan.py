# -*- coding: utf-8 -*-
"""
统计 Java 方法的近似圈复杂度（Cyclomatic Complexity, CC）
CC = 1 + count(if, for, while, do, case, catch, ?, &&, ||)
输出 CC > threshold 的方法列表到 CSV

修复点：
1) 不再用复杂正则匹配方法声明，改为线性扫描，避免卡死
2) 对扫描到的 Java 文件做 realpath 去重，避免 src 与 src/java 重复统计

兼容 Python 3.5（不使用 f-string）
"""

from __future__ import print_function
import os
import re
import csv
import argparse

# ----------------------------
# Java 文本预处理：去注释/字符串
# ----------------------------

def _strip_comments_and_strings(code):
    """
    去掉：
    - // 行注释
    - /* */ 块注释
    - "..." 字符串字面量
    - 'a' / '\n' 字符字面量
    用空格填充，尽量保持行号不变（对定位友好）
    """
    out = []
    i = 0
    n = len(code)

    IN_LINE = 1
    IN_BLOCK = 2
    IN_STR = 3
    IN_CHAR = 4
    state = 0

    while i < n:
        ch = code[i]
        nxt = code[i + 1] if i + 1 < n else ''

        if state == 0:
            # line comment
            if ch == '/' and nxt == '/':
                state = IN_LINE
                out.append(' ')
                out.append(' ')
                i += 2
                continue
            # block comment
            if ch == '/' and nxt == '*':
                state = IN_BLOCK
                out.append(' ')
                out.append(' ')
                i += 2
                continue
            # string
            if ch == '"':
                state = IN_STR
                out.append(' ')
                i += 1
                continue
            # char
            if ch == "'":
                state = IN_CHAR
                out.append(' ')
                i += 1
                continue

            out.append(ch)
            i += 1
            continue

        if state == IN_LINE:
            if ch == '\n':
                state = 0
                out.append('\n')
            else:
                out.append(' ')
            i += 1
            continue

        if state == IN_BLOCK:
            if ch == '*' and nxt == '/':
                out.append(' ')
                out.append(' ')
                i += 2
                state = 0
            else:
                out.append('\n' if ch == '\n' else ' ')
                i += 1
            continue

        if state == IN_STR:
            if ch == '\\' and i + 1 < n:
                out.append(' ')
                out.append(' ')
                i += 2
                continue
            if ch == '"':
                out.append(' ')
                i += 1
                state = 0
            else:
                out.append('\n' if ch == '\n' else ' ')
                i += 1
            continue

        if state == IN_CHAR:
            if ch == '\\' and i + 1 < n:
                out.append(' ')
                out.append(' ')
                i += 2
                continue
            if ch == "'":
                out.append(' ')
                i += 1
                state = 0
            else:
                out.append('\n' if ch == '\n' else ' ')
                i += 1
            continue

    return ''.join(out)

# ----------------------------
# 近似 CC 计算
# ----------------------------

_CC_PATTERNS = [
    (re.compile(r'\bif\b'), 1),
    (re.compile(r'\bfor\b'), 1),
    (re.compile(r'\bwhile\b'), 1),
    (re.compile(r'\bdo\b'), 1),
    (re.compile(r'\bcase\b'), 1),
    (re.compile(r'\bcatch\b'), 1),
    (re.compile(r'\?'), 1),
    (re.compile(r'&&'), 1),
    (re.compile(r'\|\|'), 1),
]

def compute_cc(method_body):
    cc = 1
    for (pat, w) in _CC_PATTERNS:
        m = pat.findall(method_body)
        if m:
            cc += w * len(m)
    return cc

# ----------------------------
# 基础信息提取
# ----------------------------

def read_package(code):
    m = re.search(r'^\s*package\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;', code, re.M)
    return m.group(1) if m else ''

def guess_source_roots(root):
    """
    常见 Java 源码目录自动猜测（可能同时存在多个）
    注意：即使返回多个，也会在主循环里对文件 realpath 去重，避免重复统计
    """
    candidates = [
        os.path.join(root, 'src', 'main', 'java'),
        os.path.join(root, 'src', 'java'),
        os.path.join(root, 'source'),
        os.path.join(root, 'src'),
    ]
    exists = []
    for p in candidates:
        if os.path.isdir(p):
            exists.append(p)
    if exists:
        return exists
    return [root]

def iter_java_files(src_root):
    """
    遍历 .java 文件
    """
    skip = set(['target', 'build', '.git', '.idea', '.svn', 'out'])
    for base, dirs, files in os.walk(src_root):
        # 过滤无关目录（不会影响 HITS 的“方法级 CC”定义，只是提速/减少噪音）
        dirs[:] = [d for d in dirs if d not in skip]
        for fn in files:
            if fn.endswith('.java'):
                yield os.path.join(base, fn)

# ----------------------------
# 方法提取：线性扫描（避免正则灾难回溯）
# ----------------------------

def extract_methods(clean_code):
    """
    线性扫描提取方法（避免正则灾难性回溯）
    逻辑：
    - 找到 '('，向左找方法名
    - 匹配对应 ')'
    - 跳过空白与可选的 throws 子句
    - 紧跟 '{' 认为是方法体，做大括号配对抽取 body
    注意：会跳过接口/抽象方法（以 ; 结尾的）
    """
    methods = []
    n = len(clean_code)

    control_keywords = set(['if', 'for', 'while', 'switch', 'catch', 'do', 'try', 'synchronized', 'new'])

    i = 0
    while i < n:
        if clean_code[i] != '(':
            i += 1
            continue

        # 1) 向左找方法名（identifier）
        j = i - 1
        while j >= 0 and clean_code[j].isspace():
            j -= 1

        name_end = j
        while j >= 0 and (clean_code[j].isalnum() or clean_code[j] == '_' or clean_code[j] == '$'):
            j -= 1
        name_start = j + 1

        if name_start > name_end:
            i += 1
            continue

        name = clean_code[name_start:name_end + 1]

        # 排除控制结构 / super/this 调用
        if name in control_keywords or name in ('super', 'this'):
            i += 1
            continue

        # 2) 匹配对应的 ')'
        depth = 1
        k = i + 1
        while k < n and depth > 0:
            if clean_code[k] == '(':
                depth += 1
            elif clean_code[k] == ')':
                depth -= 1
            k += 1
        if depth != 0:
            i += 1
            continue

        params_end = k - 1  # index of ')'

        # 3) 右侧跳过空白
        t = k
        while t < n and clean_code[t].isspace():
            t += 1

        # 4) 可选 throws 子句
        if clean_code.startswith('throws', t):
            t += len('throws')
            while t < n and clean_code[t] not in '{;':
                t += 1
            while t < n and clean_code[t].isspace():
                t += 1

        if t >= n:
            i += 1
            continue

        if clean_code[t] == ';':
            # 抽象/接口方法
            i += 1
            continue

        if clean_code[t] != '{':
            # 不是方法体（可能是 lambda/cast/其它结构）
            i += 1
            continue

        brace_pos = t

        # 5) 大括号配对提取方法体
        bd = 0
        p = brace_pos
        while p < n:
            if clean_code[p] == '{':
                bd += 1
            elif clean_code[p] == '}':
                bd -= 1
                if bd == 0:
                    body = clean_code[brace_pos:p + 1]
                    start_line = clean_code.count('\n', 0, brace_pos) + 1
                    params = clean_code[i + 1:params_end].strip()
                    methods.append({
                        'name': name,
                        'params': params,
                        'start_line': start_line,
                        'body': body
                    })
                    break
            p += 1

        i = brace_pos + 1

    return methods

# ----------------------------
# 主流程
# ----------------------------

def main():
    parser = argparse.ArgumentParser(description='Scan Java methods CC > threshold')
    parser.add_argument('--root', required=True, help='project root path')
    parser.add_argument('--out', default='cc_results.csv', help='output csv')
    parser.add_argument('--threshold', type=int, default=10, help='CC threshold, default 10')
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    threshold = args.threshold

    src_roots = guess_source_roots(root)

    results = []
    total_methods = 0
    total_files_seen = 0

    # 文件去重：避免 src 与 src/java 重复扫描
    seen_files = set()

    for sr in src_roots:
        for fp in iter_java_files(sr):
            real_fp = os.path.realpath(fp)
            if real_fp in seen_files:
                continue
            seen_files.add(real_fp)
            total_files_seen += 1

            try:
                with open(fp, 'r') as f:
                    code = f.read()
            except Exception:
                try:
                    with open(fp, 'r') as f:
                        code = f.read().decode('utf-8', 'ignore')
                except Exception:
                    continue

            pkg = read_package(code)
            clean = _strip_comments_and_strings(code)
            methods = extract_methods(clean)

            total_methods += len(methods)

            rel = os.path.relpath(fp, root).replace('\\', '/')
            cls_guess = os.path.splitext(os.path.basename(fp))[0]
            fqn_class = (pkg + '.' + cls_guess) if pkg else cls_guess

            for md in methods:
                cc = compute_cc(md['body'])
                if cc > threshold:
                    results.append({
                        'file': rel,
                        'class_guess': fqn_class,
                        'method': md['name'],
                        'params': md['params'],
                        'start_line': md['start_line'],
                        'cc': cc
                    })

    results.sort(key=lambda x: (-x['cc'], x['file'], x['start_line']))

    with open(args.out, 'w') as f:
        w = csv.writer(f)
        w.writerow(['file', 'class_guess', 'method', 'params', 'start_line', 'cc'])
        for r in results:
            w.writerow([r['file'], r['class_guess'], r['method'], r['params'], r['start_line'], r['cc']])

    print('=== 圈复杂度统计完成 ===')
    print('项目路径: ' + root)
    print('扫描源码根目录: ' + ', '.join(src_roots))
    print('扫描 Java 文件数(去重后): ' + str(total_files_seen))
    print('识别到的方法数(含非复杂): ' + str(total_methods))
    print('CC > ' + str(threshold) + ' 的方法数: ' + str(len(results)))

    if results:
        print('\nTop 20 (按 CC 降序):')
        top = results[:20]
        for i, r in enumerate(top):
            line = '#%d CC=%d %s::%s(%s) @%s:%d' % (
                i + 1, r['cc'], r['class_guess'], r['method'], r['params'], r['file'], r['start_line']
            )
            print(line)

    print('\n已导出 CSV: ' + os.path.abspath(args.out))

if __name__ == '__main__':
    main()
