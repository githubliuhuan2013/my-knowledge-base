"""知识库索引器 - 基于 TF-IDF 的语义搜索

使用 scikit-learn 的 TfidfVectorizer 构建全文索引，
支持中文分词（基于字符级 n-gram），无需额外依赖。
"""

import os
import pickle
import sqlite3
import re
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

KB_ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = KB_ROOT / "_index"
DB_PATH = INDEX_DIR / "chunks.db"
VECTORIZER_PATH = INDEX_DIR / "vectorizer.pkl"
MATRIX_PATH = INDEX_DIR / "tfidf_matrix.npy"


def _chunk_text(text: str, size: int = 500, overlap: int = 50) -> list[str]:
    """将文本按段落边界切分为重叠的块"""
    paragraphs = text.split("\n\n")
    chunks = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) < size:
            current += para + "\n\n"
        else:
            if current.strip():
                chunks.append(current.strip())
            current = para[-overlap:] + "\n\n" + para + "\n\n" if overlap else para + "\n\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks if chunks else [text]


def _tokenize_chinese(text: str) -> list[str]:
    """中文字符级 n-gram 分词 (1-3 gram)，兼容英文单词"""
    # 提取中文和英文
    tokens = []
    # 英文单词
    eng_words = re.findall(r'[a-zA-Z]+', text)
    tokens.extend(eng_words)
    # 中文 n-gram
    chinese = re.findall(r'[一-鿿]', text)
    for n in [1, 2, 3]:
        for i in range(len(chinese) - n + 1):
            tokens.append(''.join(chinese[i:i+n]))
    return tokens


def build_index(notes_dir: str = None) -> dict:
    """构建/重建索引。返回统计信息。"""
    if notes_dir is None:
        notes_dir = KB_ROOT / "notes"
    else:
        notes_dir = Path(notes_dir)

    os.makedirs(INDEX_DIR, exist_ok=True)

    md_files = list(Path(notes_dir).rglob("*.md"))
    if not md_files:
        return {"status": "empty", "notes": 0, "chunks": 0}

    chunks = []
    for f in md_files:
        try:
            content = f.read_text(encoding="utf-8")
            # 跳过 frontmatter
            if content.startswith("---"):
                parts = content.split("---", 2)
                body = parts[2] if len(parts) > 2 else content
            else:
                body = content

            rel_path = str(f.relative_to(notes_dir))
            for i, chunk in enumerate(_chunk_text(body)):
                chunks.append({
                    "note_path": rel_path,
                    "chunk_index": i,
                    "text": chunk,
                })
        except Exception as e:
            print(f"[WARN] 跳过 {f}: {e}")

    if not chunks:
        return {"status": "empty", "notes": len(md_files), "chunks": 0}

    texts = [c["text"] for c in chunks]

    # 构建 TF-IDF
    vectorizer = TfidfVectorizer(
        max_features=10000,
        analyzer=_tokenize_chinese,
        ngram_range=(1, 1),  # 我们自己做了 n-gram
    )
    matrix = vectorizer.fit_transform(texts)

    # 保存
    with open(VECTORIZER_PATH, "wb") as f:
        pickle.dump(vectorizer, f)
    np.save(MATRIX_PATH, matrix.toarray())

    # SQLite 存储 chunk 元数据
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DROP TABLE IF EXISTS chunks")
    conn.execute("""CREATE TABLE chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        note_path TEXT,
        chunk_index INTEGER,
        text TEXT
    )""")
    conn.executemany(
        "INSERT INTO chunks (note_path, chunk_index, text) VALUES (?, ?, ?)",
        [(c["note_path"], c["chunk_index"], c["text"]) for c in chunks]
    )
    conn.commit()
    conn.close()

    return {"status": "ok", "notes": len(md_files), "chunks": len(chunks)}


def search(query: str, top_k: int = 5) -> list[dict]:
    """语义搜索，返回 top_k 相关结果"""
    if not VECTORIZER_PATH.exists() or not MATRIX_PATH.exists():
        return []

    with open(VECTORIZER_PATH, "rb") as f:
        vectorizer = pickle.load(f)
    matrix = np.load(MATRIX_PATH)

    query_vec = vectorizer.transform([query])
    scores = cosine_similarity(query_vec, matrix)[0]

    top_indices = np.argsort(scores)[-top_k:][::-1]

    results = []
    conn = sqlite3.connect(str(DB_PATH))
    for idx in top_indices:
        score = float(scores[idx])
        if score < 0.01:
            continue
        row = conn.execute(
            "SELECT note_path, chunk_index, text FROM chunks WHERE id=?",
            (int(idx) + 1,)
        ).fetchone()
        if row:
            results.append({
                "note_path": row[0],
                "chunk_index": row[1],
                "text": row[2][:300],
                "score": round(score, 3),
            })
    conn.close()
    return results


def search_and_format(query: str, top_k: int = 5) -> str:
    """搜索并格式化输出"""
    results = search(query, top_k)
    if not results:
        return f'[INFO] 未找到与 "{query}" 相关的内容\n[INFO] 试试用 kb search "关键词" 进行全文搜索'

    lines = [f'搜索 "{query}" 找到 {len(results)} 条相关内容:\n']
    for r in results:
        lines.append(f"[{r['note_path']}] (相关度: {r['score']})")
        lines.append(f"  {r['text'][:200]}...")
        lines.append("")
    return "\n".join(lines)


def get_stats() -> dict:
    """获取索引统计"""
    if not DB_PATH.exists():
        return {"indexed": False, "chunks": 0, "notes": 0}
    conn = sqlite3.connect(str(DB_PATH))
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    notes = conn.execute("SELECT COUNT(DISTINCT note_path) FROM chunks").fetchone()[0]
    conn.close()
    return {"indexed": True, "chunks": chunks, "notes": notes}
