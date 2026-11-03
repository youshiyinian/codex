#!/usr/bin/env python3
"""把 i18n/zh-CN/*.json 中的中文翻译应用到 Codex 源码。

用法: python i18n/apply.py <codex 源码根目录> [--strict]

翻译文件格式 (JSON):
{
  "codex-rs/tui/src/slash_command.rs": { "英文原文": "中文译文", ... },
  "*": { ... }   # 对 codex-rs/tui/src 下所有非测试 .rs 文件生效
}

规则:
- 只替换“内容完全等于原文”的普通字符串字面量 "..."，不碰原始字符串 r"..."、字节串 b"..."、注释和字符字面量。
- 原文和译文都按源码里的写法书写（转义保持原样，如 \\n）；译文不要出现英文双引号，用「」代替。
- 原文和译文中的 {占位符} 必须一致，否则报错。
- 官方新版本里找不到的原文只打印警告（说明该句已被官方改写），不会中断构建。
"""
import json, os, re, sys, glob

GLOBAL_ROOTS = ["codex-rs/tui/src"]
PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def is_test_file(path):
    p = path.replace("\\", "/")
    name = os.path.basename(p)
    return ("/tests/" in p or "/snapshots/" in p or name == "tests.rs"
            or name.endswith("_tests.rs") or name.endswith("_test.rs")
            or "test_support" in name)


LOGIC_AFTER = re.compile(r"^\s*(=>|==|!=|\||if\b)")


def in_logic_position(src, start, end):
    """start/end 指向字面量两侧的引号。"""
    before = src[max(0, start - 60):start]
    if start > 0 and src[start - 1] == "b":
        return False
    after = src[end:end + 8]
    if LOGIC_AFTER.match(after):
        return True
    b = before.rstrip()
    if re.search(r"(==|!=)\s*&?$", b):
        return True
    if re.search(r"\b(starts_with|ends_with|strip_prefix|strip_suffix|contains|find|rfind|split|split_once|rsplit_once|"
                 r"eq|eq_ignore_ascii_case|replace|trim_start_matches|trim_end_matches|contains_key|"
                 r"primary_hint|get)\(\s*&?$", b):
        return True
    # match 分支的开头：行首就是字面量并且后面跟 => 或 |（已由 LOGIC_AFTER 覆盖）
    return False


def normalize(raw):
    """Rust 中行尾的反斜杠续行（\\ + 换行 + 缩进）不属于字符串内容，比较前去掉。"""
    return re.sub(r"\\\n[ \t\r\n]*", "", raw) if "\\\n" in raw else raw


def find_literals(src):
    """返回 [(内容起始, 内容结束)]，仅普通字符串字面量。"""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and src.startswith("/*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if src.startswith("/*", i):
                    depth += 1; i += 2
                elif src.startswith("*/", i):
                    depth -= 1; i += 2
                else:
                    i += 1
            continue
        # 原始字符串 r"..." r#"..."# br"..."
        m = re.match(r'(b|c)?r(#*)"', src[i:i + 40]) if c in "rbc" else None
        if m and (i == 0 or not (src[i - 1].isalnum() or src[i - 1] == "_")):
            hashes = m.group(2)
            end = src.find('"' + hashes, i + m.end())
            i = n if end < 0 else end + 1 + len(hashes)
            continue
        if c == "'":
            # 字符字面量 vs 生命周期
            m2 = re.match(r"'(\\(x[0-9a-fA-F]{2}|u\{[0-9a-fA-F]+\}|.)|[^\\'\n])'", src[i:i + 16])
            if m2:
                i += m2.end(); continue
            i += 1; continue
        if c == '"':
            prefix_b = i > 0 and src[i - 1] in "bc" and (i < 2 or not (src[i - 2].isalnum() or src[i - 2] == "_"))
            j = i + 1
            while j < n and src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            if not prefix_b:
                out.append((i + 1, j))
            i = j + 1
            continue
        if c.isalnum() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            if j < n and src[j] == '"' and src[i:j] in ("b", "c"):
                i = j  # 交给下一轮作为 b"..." 处理
                continue
            i = j
            continue
        i += 1
    return out


def main():
    # Windows 控制台默认编码不是 UTF-8，打印中文会报错
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    root = sys.argv[1]
    strict = "--strict" in sys.argv
    here = os.path.dirname(os.path.abspath(__file__))
    table = {}
    errors = []
    for jf in sorted(glob.glob(os.path.join(here, "zh-CN", "*.json"))):
        data = json.load(open(jf, encoding="utf-8"))
        for scope, entries in data.items():
            if scope.startswith("_"):
                continue
            dst = table.setdefault(scope, {})
            for en, zh in entries.items():
                if sorted(PLACEHOLDER.findall(en)) != sorted(PLACEHOLDER.findall(zh)):
                    errors.append(f"{os.path.basename(jf)}: 占位符不一致: {en!r} -> {zh!r}")
                if (en.count("(") != en.count(")")) and ("（" in zh or "）" in zh):
                    errors.append(f"{os.path.basename(jf)}: 原文括号不成对，译文请用半角括号: {en!r} -> {zh!r}")
                if re.search(r'(?<!\\)"', zh):
                    errors.append(f"{os.path.basename(jf)}: 译文含未转义的英文双引号: {zh!r}")
                dst[en] = zh
    if errors:
        print("\n".join(errors)); sys.exit(1)

    global_tbl = table.pop("*", {})
    # “文件路径!force” 段中的译文即使出现在比较/匹配位置也强制替换（用于确认安全的情况）
    forced = {}
    for scope in [k for k in table if k.endswith("!force")]:
        forced[scope[:-len("!force")]] = table.pop(scope)
    for f, entries in forced.items():
        table.setdefault(f, {}).update(entries)
    files = set(table)
    for gr in GLOBAL_ROOTS:
        for dp, _, fns in os.walk(os.path.join(root, gr)):
            for fn in fns:
                if fn.endswith(".rs"):
                    files.add(os.path.relpath(os.path.join(dp, fn), root).replace("\\", "/"))

    used = {k: set() for k in table}
    used_global = set()
    skipped = set()
    total = 0
    for rel in sorted(files):
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            print(f"警告: 文件不存在（官方可能已移动）: {rel}")
            continue
        if is_test_file(rel) and rel not in table:
            continue
        local = table.get(rel, {})
        src = open(path, encoding="utf-8").read()
        lits = [(s_, e_, normalize(src[s_:e_])) for s_, e_ in find_literals(src)]
        # 同一文件中，只要某条原文有一处出现在比较/匹配位置（== != => starts_with 等），
        # 就整体跳过该原文，避免改坏程序逻辑。
        m_test = re.search(r"#\[cfg\(test\)\]\s*\n\s*(pub(\(crate\))?\s+)?mod \w+\s*\{", src)
        test_cut = m_test.start() if m_test else len(src)
        unsafe = {raw for s_, e_, raw in lits
                  if s_ < test_cut and in_logic_position(src, s_ - 1, e_ + 1)}
        pieces, last, count = [], 0, 0
        for s, e, raw in lits:
            if raw in local:
                zh = local[raw]
            elif raw in global_tbl:
                zh = global_tbl[raw]
            else:
                continue
            if raw in unsafe and raw not in forced.get(rel, {}):
                skipped.add((rel, raw))
                (used[rel] if raw in local else used_global).add(raw)
                continue
            (used[rel] if raw in local else used_global).add(raw)
            pieces.append(src[last:s]); pieces.append(zh)
            last = e; count += 1
        if count:
            pieces.append(src[last:])
            open(path, "w", encoding="utf-8", newline="").write("".join(pieces))
            total += count
    stale = [(f, k) for f, ks in table.items() for k in ks if k not in used[f]]
    stale += [("*", k) for k in global_tbl if k not in used_global]
    for f, k in stale:
        print(f"警告: 未找到原文（可能已被官方修改）: [{f}] {k!r}")
    for f, k in sorted(skipped):
        print(f"提示: 原文在比较/匹配中使用，已跳过以保证逻辑正确: [{f}] {k!r}")
    print(f"完成: 共替换 {total} 处字符串, {len(stale)} 条翻译未匹配")
    if strict and stale:
        sys.exit(1)


if __name__ == "__main__":
    main()
