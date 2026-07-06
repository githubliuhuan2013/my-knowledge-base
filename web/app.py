"""
知识库聊天查询 - 网页版
在任何电脑的浏览器打开就能搜索你的知识库。
"""

import streamlit as st
import os
import re
import pickle
import sqlite3
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ─── 页面设置 ───
st.set_page_config(
    page_title="我的知识库",
    page_icon="📚",
    layout="wide",
)

# ─── 路径 ───
KB_ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = KB_ROOT / "notes"
ORIGINALS_DIR = KB_ROOT / "_originals"
INDEX_DIR = KB_ROOT / ".web_index"
INDEX_DIR.mkdir(exist_ok=True)

# ─── CSS 美化 ───
st.markdown("""
<style>
    .main-header {
        font-size: 2em;
        font-weight: bold;
        margin-bottom: 0;
    }
    .result-card {
        background: #1e1e1e;
        border: 1px solid #333;
        border-radius: 10px;
        padding: 15px;
        margin: 10px 0;
    }
    .result-title {
        font-size: 1.2em;
        font-weight: bold;
        color: #4da6ff;
    }
    .result-path {
        font-size: 0.8em;
        color: #888;
    }
    .result-snippet {
        margin-top: 8px;
        line-height: 1.6;
    }
    .result-score {
        font-size: 0.8em;
        color: #666;
    }
    .highlight {
        background-color: #ffd54f;
        color: #000;
        padding: 2px 4px;
        border-radius: 3px;
    }
</style>
""", unsafe_allow_html=True)

# ─── 索引构建 ───
@st.cache_resource
def build_index():
    """构建 TF-IDF 索引（首次加载时运行，之后缓存）"""
    md_files = list(NOTES_DIR.rglob("*.md"))
    if not md_files:
        return None, [], []

    chunks_info = []
    texts = []

    for f in md_files:
        try:
            content = f.read_text(encoding="utf-8")
            # 去掉 frontmatter
            if content.startswith("---"):
                parts = content.split("---", 2)
                body = parts[2] if len(parts) > 2 else content
            else:
                body = content

            rel_path = str(f.relative_to(NOTES_DIR))
            # 按段落切分
            paragraphs = body.split("\n\n")
            for i, para in enumerate(paragraphs):
                para = para.strip()
                if len(para) > 20:
                    chunks_info.append({
                        "note_path": rel_path,
                        "chunk_index": i,
                        "text": para,
                    })
                    texts.append(para)
        except Exception:
            pass

    if not texts:
        return None, [], []

    # 中文友好的分词
    def tokenize(text):
        tokens = re.findall(r'[a-zA-Z]+', text)
        chinese = re.findall(r'[一-鿿]', text)
        for n in [1, 2, 3]:
            for i in range(len(chinese) - n + 1):
                tokens.append(''.join(chinese[i:i+n]))
        return tokens

    vectorizer = TfidfVectorizer(max_features=5000, analyzer=tokenize)
    matrix = vectorizer.fit_transform(texts)

    return vectorizer, matrix, chunks_info


def search(query, vectorizer, matrix, chunks_info, top_k=8):
    """搜索并返回结果"""
    if vectorizer is None:
        return []

    query_vec = vectorizer.transform([query])
    scores = cosine_similarity(query_vec, matrix)[0]
    top_indices = np.argsort(scores)[-top_k:][::-1]

    results = []
    for idx in top_indices:
        score = float(scores[idx])
        if score < 0.01:
            continue
        info = chunks_info[idx].copy()
        info["score"] = round(score, 3)
        results.append(info)
    return results


def search_originals(query):
    """在 _originals 目录中搜索匹配的文件名（支持模糊匹配）"""
    if not ORIGINALS_DIR.exists():
        return []
    results = []
    for f in ORIGINALS_DIR.rglob("*"):
        if f.is_file():
            fname_lower = f.name.lower()
            query_lower = query.lower()
            # 整体匹配 或 拆分词语后任一匹配
            if query_lower in fname_lower or _any_word_match(query_lower, fname_lower):
                results.append({
                    "name": f.name,
                    "path": str(f.relative_to(ORIGINALS_DIR)),
                    "full_path": str(f),
                })
    return results


def _any_word_match(query: str, target: str) -> bool:
    """把查询拆成词，只要目标包含任一词就匹配"""
    # 拆分中文：单字+词组
    words = []
    # 英文词
    words.extend(re.findall(r'[a-zA-Z]+', query))
    # 中文2字词组
    chinese = re.findall(r'[一-鿿]', query)
    for i in range(len(chinese) - 1):
        words.append(''.join(chinese[i:i+2]))
    for i in range(len(chinese) - 2):
        words.append(''.join(chinese[i:i+3]))
    # 只要目标包含任一词组就匹配
    match_count = sum(1 for w in words if w.lower() in target)
    return match_count >= 2  # 至少匹配2个词才算


# ─── 初始化 ───
vectorizer, matrix, chunks_info = build_index()
note_count = len(set(c["note_path"] for c in chunks_info)) if chunks_info else 0

# ─── 页面头部 ───
st.markdown('<div class="main-header">📚 我的知识库</div>', unsafe_allow_html=True)
st.caption(f"已索引 {note_count} 篇笔记 · 数据来源：GitHub 私有仓库")

# ─── 聊天区域 ───
# 初始化聊天记录
if "messages" not in st.session_state:
    st.session_state.messages = []

# 显示历史消息
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            st.markdown(msg["content"], unsafe_allow_html=True)
        else:
            st.markdown(msg["content"])

# 输入框
if prompt := st.chat_input("输入你的问题，比如：Claude Code 怎么安装？"):
    # 用户消息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 搜索
    with st.chat_message("assistant"):
        with st.spinner("正在搜索知识库..."):
            results = search(prompt, vectorizer, matrix, chunks_info)
            doc_results = search_originals(prompt)

            if not results and not doc_results:
                response = f"""😕 没有找到关于「**{prompt}**」的相关内容。

💡 **建议：**
- 换个关键词试试
- 检查知识库是否已添加相关笔记
- 用 `kb import` 导入相关文档"""
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})

            else:
                response_parts = []

                if results:
                    response_parts.append(f"### 🔍 找到 {len(results)} 条相关内容：\n")
                    for i, r in enumerate(results, 1):
                        # 高亮关键词
                        text = r["text"]
                        for kw in prompt.split():
                            if kw in text:
                                text = text.replace(kw, f'<span class="highlight">{kw}</span>')

                        card = f"""<div class="result-card">
<div class="result-title">📄 {r['note_path'].split('/')[-1].replace('.md', '')}</div>
<div class="result-path">{r['note_path']} · 相关度 {r['score']}</div>
<div class="result-snippet">{text[:500]}</div>
</div>"""
                        response_parts.append(card)

                if doc_results:
                    response_parts.append(f"\n### 📎 匹配的原始文档：\n")
                    for d in doc_results:
                        response_parts.append(f"- 📁 `{d['path']}`")

                # 底部的搜索建议
                response_parts.append(f"""
---
💬 *搜索结果基于语义匹配。如果不够精确，试试换个角度提问。*
""")

                response = "\n".join(response_parts)
                st.markdown(response, unsafe_allow_html=True)
                st.session_state.messages.append({"role": "assistant", "content": response})

# ─── 侧边栏 ───
with st.sidebar:
    st.markdown("### 📊 知识库统计")
    if note_count > 0:
        st.metric("已索引笔记", f"{note_count} 篇")
    else:
        st.warning("还没有笔记，用 kb new 创建第一篇吧！")

    st.markdown("### 📁 原始文档")
    if ORIGINALS_DIR.exists():
        all_files = list(ORIGINALS_DIR.rglob("*"))
        all_files = [f for f in all_files if f.is_file()]
        st.metric("文档数量", f"{len(all_files)} 个")
    else:
        st.caption("暂无文档")

    st.markdown("### 🔗 链接")
    st.markdown("[GitHub 仓库](https://github.com/githubliuhuan2013/my-knowledge-base)")

    st.markdown("---")
    st.caption("知识库网页版 v1.0")
