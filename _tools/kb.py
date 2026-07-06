#!/usr/bin/env python
"""kb - 个人知识库管理工具

用法:
  kb new "标题" --tags tag1,tag2  创建新笔记
  kb import <文件.docx>            导入 Word 文档
  kb list [--tag 标签]             列出笔记
  kb search "关键词"               全文搜索笔记内容
  kb ask "问题"                     语义搜索 + AI 回答
  kb index                          构建搜索索引
  kb sync                           同步到 GitHub
  kb status                         查看状态
"""

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
from datetime import date

# 知识库根目录（脚本在 _tools/ 下，根目录是上一级）
TOOLS_DIR = Path(__file__).resolve().parent
KB_ROOT = TOOLS_DIR.parent
NOTES_DIR = KB_ROOT / "notes"
ORIGINALS_DIR = KB_ROOT / "_originals"
TEMPLATES_DIR = KB_ROOT / "_templates"
TEMPLATE_FILE = TEMPLATES_DIR / "note-template.md"


def cmd_help():
    """显示帮助"""
    print(__doc__)


# ─── new ───────────────────────────────────────────
def cmd_new(title: str, tags: str = "", category: str = "其他"):
    """创建一篇新笔记"""
    if not TEMPLATE_FILE.exists():
        print(f"[ERROR] 模板文件不存在: {TEMPLATE_FILE}")
        return

    template = TEMPLATE_FILE.read_text(encoding="utf-8")

    # 填充模板
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    content = template.replace("{{date}}", date.today().isoformat())
    content = content.replace("{{title}}", title)
    content = content.replace("tags: []", f"tags: {json.dumps(tag_list, ensure_ascii=False)}")

    # 生成安全文件名
    safe_name = title.replace("/", "-").replace("\\", "-")
    safe_name = "".join(c for c in safe_name if c not in '<>:"|?*')
    file_path = NOTES_DIR / category / f"{safe_name}.md"

    if file_path.exists():
        print(f"[WARN] 笔记已存在: {file_path}")
        return

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    print(f"[OK] 笔记已创建: {file_path}")


# ─── import ────────────────────────────────────────
def cmd_import(docx_path: str, category: str = ""):
    """导入 Word 文档，转为 Markdown，保留原件"""
    docx_path = os.path.abspath(os.path.expanduser(docx_path))

    if not os.path.exists(docx_path):
        print(f"[ERROR] 文件不存在: {docx_path}")
        return

    if not docx_path.lower().endswith(".docx"):
        print(f"[ERROR] 只支持 .docx 文件: {docx_path}")
        return

    # 复制原件到 _originals
    os.makedirs(ORIGINALS_DIR, exist_ok=True)
    dest = ORIGINALS_DIR / os.path.basename(docx_path)
    shutil.copy2(docx_path, dest)
    print(f"[OK] 原件已归档: {dest}")

    # 转换为 Markdown
    try:
        from converter import convert_and_save
        target_dir = str(NOTES_DIR / category) if category else str(NOTES_DIR / "其他")
        os.makedirs(target_dir, exist_ok=True)
        md_path, title = convert_and_save(docx_path, target_dir)
        print(f"[OK] Markdown 已生成: {md_path}")
    except Exception as e:
        print(f"[ERROR] 转换失败: {e}")
        return

    print(f"[DONE] 导入完成！使用 kb list 查看，或 git add + commit 提交。")


# ─── list ──────────────────────────────────────────
def cmd_list(tag: str = ""):
    """列出知识库中的笔记"""
    md_files = sorted(NOTES_DIR.rglob("*.md"))

    if not md_files:
        print("[INFO] 知识库还没有笔记，用 kb new 创建第一篇吧！")
        return

    found = 0
    for f in md_files:
        rel = f.relative_to(NOTES_DIR)
        if tag:
            content = f.read_text(encoding="utf-8")
            if tag not in content:
                continue
        found += 1
        # 尝试读取标题
        try:
            content = f.read_text(encoding="utf-8")
            first_lines = content.split("\n")[:5]
            title_line = [l for l in first_lines if l.startswith("title:")]
            title = title_line[0].split(":", 1)[1].strip().strip('"') if title_line else f.stem
        except Exception:
            title = f.stem
        print(f"  [{rel.parent}] {title}")
        print(f"    {rel}")

    print(f"\n共 {found} 篇笔记" + (f"，标签筛选: {tag}" if tag else ""))


# ─── search ────────────────────────────────────────
def cmd_search(keyword: str):
    """基本全文搜索（遍历所有 .md 文件）"""
    md_files = sorted(NOTES_DIR.rglob("*.md"))
    results = []

    for f in md_files:
        try:
            content = f.read_text(encoding="utf-8")
        except Exception:
            continue

        if keyword.lower() in content.lower():
            # 提取匹配行
            lines = content.split("\n")
            match_lines = []
            for i, line in enumerate(lines):
                if keyword.lower() in line.lower():
                    ctx_start = max(0, i - 1)
                    ctx_end = min(len(lines), i + 2)
                    snippet = "\n".join(lines[ctx_start:ctx_end])
                    match_lines.append(f"    行{i+1}: {snippet.strip()[:120]}")
                    if len(match_lines) >= 5:
                        break

            results.append((f, match_lines))

    if not results:
        print(f'[INFO] 未找到包含 "{keyword}" 的内容')
        return

    print(f'搜索 "{keyword}" 找到 {len(results)} 篇相关笔记:\n')
    for f, snippets in results:
        rel = f.relative_to(NOTES_DIR)
        print(f"[{rel}]")
        for s in snippets:
            print(s)
        print()


# ─── ask ───────────────────────────────────────────
def cmd_ask(question: str):
    """语义搜索 + AI 回答"""
    from indexer import search, build_index

    # 确保索引存在
    from indexer import VECTORIZER_PATH
    if not VECTORIZER_PATH.exists():
        print("[..] 首次使用，正在构建搜索索引...")
        result = build_index()
        if result["status"] == "empty":
            print("[INFO] 知识库还没有笔记，先创建或导入一些笔记吧！")
            return
        print(f"[OK] 索引已构建：{result['notes']} 篇笔记，{result['chunks']} 个段落")

    # 语义搜索
    results = search(question, top_k=5)

    if not results:
        print(f'[INFO] 未找到关于 "{question}" 的相关内容')
        print(f'[INFO] 试试用 kb search "{question}" 进行全文搜索')
        return

    print(f'\n搜索 "{question}" 找到 {len(results)} 条相关内容:\n')
    for i, r in enumerate(results, 1):
        print(f"[{i}] {r['note_path']} (相关度: {r['score']})")
        print(f"    {r['text'][:200]}")
        print()

    # 构建 RAG 提示词
    context_parts = []
    for r in results:
        context_parts.append(f"### [{r['note_path']}]\n{r['text']}")
    context = "\n\n---\n\n".join(context_parts)

    prompt = f"""你是个人知识库的智能搜索助手。请基于以下笔记内容回答用户的问题。
如果笔记中没有足够的信息，请如实说明。
回答时请引用具体的笔记来源。

## 知识库相关内容:
{context}

## 用户问题:
{question}

## 回答（请用中文）:"""

    print("[..] 正在调用 Claude 合成回答...\n")
    print("=" * 50)

    import subprocess
    result = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "text", "--permission-mode", "auto"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode == 0 and result.stdout.strip():
        print(result.stdout.strip())
    else:
        print("[INFO] Claude 调用失败，以上是搜索到的原始内容。")
        if result.stderr:
            print(f"错误: {result.stderr[-200]}")

    print("=" * 50)


# ─── index ──────────────────────────────────────────
def cmd_index():
    """构建/重建搜索索引"""
    from indexer import build_index
    print("[..] 正在构建索引...")
    result = build_index()
    if result["status"] == "empty":
        print("[INFO] 知识库还没有笔记，无法构建索引")
    else:
        print(f"[OK] 索引构建完成：{result['notes']} 篇笔记，{result['chunks']} 个段落")


# ─── sync ──────────────────────────────────────────
def cmd_sync(message: str = ""):
    """Git 同步：add + commit + pull + push"""
    os.chdir(KB_ROOT)

    # 检查是否为 git 仓库
    if not (KB_ROOT / ".git").exists():
        print("[ERROR] 尚未初始化 Git 仓库，请先运行:")
        print("  cd knowledge-base")
        print("  git init")
        print("  git remote add origin <你的GitHub仓库地址>")
        return

    cmds = [
        ("git add -A", "添加文件"),
        (f'git commit -m "sync: {message or date.today().isoformat()}"', "提交更改"),
        ("git pull --rebase origin main 2>/dev/null || git pull --rebase origin master 2>/dev/null || echo 'skip pull'", "拉取远程更新"),
        ("git push origin main 2>/dev/null || git push origin master 2>/dev/null || echo 'push failed'", "推送到远程"),
    ]

    for cmd, desc in cmds:
        print(f"[..] {desc}...")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0 and "skip" not in cmd:
            stderr = result.stderr.strip()
            if stderr and "nothing to commit" not in stderr and "Everything up-to-date" not in stderr:
                print(f"     {stderr}")

    print("[DONE] 同步完成！")


# ─── status ────────────────────────────────────────
def cmd_status():
    """查看知识库状态"""
    md_files = list(NOTES_DIR.rglob("*.md"))
    docx_files = list(ORIGINALS_DIR.rglob("*.docx"))

    print(f"知识库根目录: {KB_ROOT}")
    print(f"笔记总数: {len(md_files)} 篇")
    print(f"原始文档: {len(docx_files)} 份")

    # 索引统计
    try:
        from indexer import get_stats
        stats = get_stats()
        if stats["indexed"]:
            print(f"搜索索引: {stats['notes']} 篇已索引，{stats['chunks']} 个段落")
        else:
            print("搜索索引: 未构建（运行 kb index 构建）")
    except Exception:
        pass
    print()

    # Git 状态
    if (KB_ROOT / ".git").exists():
        os.chdir(KB_ROOT)
        result = subprocess.run("git status --short", shell=True, capture_output=True, text=True)
        if result.stdout.strip():
            print("未提交的更改:")
            print(result.stdout)
        else:
            print("Git: 工作区干净")

        result = subprocess.run("git log --oneline -3", shell=True, capture_output=True, text=True)
        if result.stdout.strip():
            print("最近提交:")
            print(result.stdout)
    else:
        print("Git: 尚未初始化")


# ─── main ──────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        cmd_help()
        return

    cmd = sys.argv[1].lower()
    args = sys.argv[2:]

    if cmd == "new" and args:
        # kb new "title" --tags x,y --category 技术
        title = args[0]
        tags = _parse_arg(args, "--tags", "")
        category = _parse_arg(args, "--category", "其他")
        cmd_new(title, tags, category)

    elif cmd == "import" and args:
        docx_path = args[0]
        category = _parse_arg(args, "--category", "")
        cmd_import(docx_path, category)

    elif cmd == "list":
        tag = _parse_arg(args, "--tag", "")
        cmd_list(tag)

    elif cmd == "search" and args:
        cmd_search(args[0])

    elif cmd == "ask" and args:
        cmd_ask(args[0])

    elif cmd == "index":
        cmd_index()

    elif cmd == "sync":
        msg = args[0] if args else ""
        cmd_sync(msg)

    elif cmd == "status":
        cmd_status()

    elif cmd in ("help", "-h", "--help"):
        cmd_help()

    else:
        print(f"[ERROR] 未知命令: {cmd}")
        cmd_help()


def _parse_arg(args: list, flag: str, default: str) -> str:
    """从命令行参数中解析 --flag value"""
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
    return default


if __name__ == "__main__":
    main()
