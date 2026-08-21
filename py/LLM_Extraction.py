import os
import re
import json
import math
import openai
try:
    import faiss
except ImportError:
    faiss = None  # 情绪打分等不依赖向量库的功能可独立运行
import numpy as np
from collections import Counter
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from Methods import *
openai.api_key = os.environ.get("OPENAI_API_KEY", "sk-3fk05T3Cme02GzUGBc56BaBfA7Ff4dCa9d7dE5AeA689913c")
openai.base_url = os.environ.get("OPENAI_BASE_URL", "https://api.gpt.ge/v1/")
openai.default_headers = {"x-foo": "true"}

# ===== 0. 公共辅助函数 =====

# ---- 分块：长对话按窗口切分 ----
def chunk_history(history: List[Dict], window_size: int = 30, overlap: int = 5) -> List[List[Dict]]:
    """将长对话按固定窗口切块，相邻块有 overlap 轮重叠，便于跨块合并。"""
    if len(history) <= window_size:
        return [history]
    chunks = []
    start = 0
    while start < len(history):
        end = min(start + window_size, len(history))
        chunks.append(history[start:end])
        start += window_size - overlap
    return chunks


# ---- Embedding 相似度 ----
_cached_embeddings: Dict[str, np.ndarray] = {}

def _embed_single(text: str, model: str = "text-embedding-3-large") -> np.ndarray:
    """单条文本 embedding，带简单缓存。"""
    key = f"{model}:{text[:100]}:{len(text)}"
    if key in _cached_embeddings:
        return _cached_embeddings[key]
    resp = openai.embeddings.create(model=model, input=text[:2000])
    emb = np.array(resp.data[0].embedding, dtype="float32")
    _cached_embeddings[key] = emb
    return emb


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度。"""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def compute_adjacent_similarities(history: List[Dict]) -> List[float]:
    """计算相邻轮次对话的语义相似度，用于边界检测。"""
    sims = []
    for i in range(len(history) - 1):
        t1 = (history[i].get("content") or history[i].get("text") or "").strip()
        t2 = (history[i+1].get("content") or history[i+1].get("text") or "").strip()
        if not t1 or not t2:
            sims.append(1.0)
            continue
        e1 = _embed_single(t1)
        e2 = _embed_single(t2)
        sims.append(cosine_similarity(e1, e2))
    return sims


def detect_boundary_candidates(sims: List[float], threshold: float = 0.5) -> List[int]:
    """相似度骤降处作为候选边界，返回边界位置（id 索引列表）。"""
    if not sims:
        return []
    mean_sim = np.mean(sims)
    candidates = []
    for i, s in enumerate(sims):
        if s < mean_sim * 0.6 or s < threshold:  # 显著低于均值 或 绝对低
            candidates.append(i + 1)  # 边界在 i 和 i+1 之间
    # 去重相邻边界
    filtered = []
    for c in candidates:
        if not filtered or c - filtered[-1] > 3:
            filtered.append(c)
    return filtered


# ---- 简易 TF-IDF ----
def simple_tfidf(documents: List[str], top_n: int = 30) -> List[List[Tuple[str, float]]]:
    """简易 TF-IDF：纯 Python 实现，不依赖 sklearn。"""
    if not documents:
        return []
    # 分词（按中文单字+常见词组切分）
    def tokenize(text: str) -> List[str]:
        # 简单按 2-4 字滑动窗口切 n-gram
        tokens = []
        # 优先保留完整词语：按标点切分后取 2-4 字片段
        clean = re.sub(r'[^一-鿿\w]', ' ', text)
        for word in clean.split():
            if 2 <= len(word) <= 6:
                tokens.append(word)
            else:
                for i in range(len(word) - 1):
                    for n in [2, 3, 4]:
                        if i + n <= len(word):
                            tokens.append(word[i:i+n])
        return tokens

    N = len(documents)
    tokenized = [tokenize(d) for d in documents]
    # IDF
    doc_freq: Dict[str, int] = {}
    for tokens in tokenized:
        for t in set(tokens):
            doc_freq[t] = doc_freq.get(t, 0) + 1

    results = []
    for tokens in tokenized:
        tf = Counter(tokens)
        scores = {}
        for term, freq in tf.items():
            idf = math.log((N + 1) / (doc_freq.get(term, 1) + 1)) + 1
            scores[term] = freq * idf
        sorted_terms = sorted(scores.items(), key=lambda x: -x[1])[:top_n]
        # 归一化到 0-1
        if sorted_terms:
            max_score = sorted_terms[0][1]
            sorted_terms = [(t, s/max_score) for t, s in sorted_terms]
        results.append(sorted_terms)
    return results


# ---- 层次聚类（用于 Topic_merge 的粗聚类阶段） ----
def hierarchical_cluster_embeddings(
    embs: List[np.ndarray],
    threshold: float = 0.7
) -> List[int]:
    """
    简单层次聚类：合并 cosine similarity > threshold 的相邻簇。
    返回每个 item 的簇标签。
    """
    n = len(embs)
    if n == 0:
        return []
    if n == 1:
        return [0]

    labels = list(range(n))
    # 计算相似度矩阵
    sim_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(i+1, n):
            sim_matrix[i][j] = cosine_similarity(embs[i], embs[j])
            sim_matrix[j][i] = sim_matrix[i][j]

    # 贪心合并：重复合并最相似的两个簇
    active = list(range(n))
    while len(active) > 1:
        best_i, best_j, best_sim = -1, -1, -1
        for i in range(len(active)):
            for j in range(i+1, len(active)):
                ai, aj = active[i], active[j]
                if sim_matrix[ai][aj] > best_sim:
                    best_sim = sim_matrix[ai][aj]
                    best_i, best_j = i, j
        if best_sim < threshold:
            break
        # 合并 j 到 i
        new_label = labels[active[best_i]]
        old_label = labels[active[best_j]]
        for k in range(n):
            if labels[k] == old_label:
                labels[k] = new_label
        active.pop(best_j)

    # 重编号标签为 0..m-1
    label_map = {}
    new_labels = []
    for l in labels:
        if l not in label_map:
            label_map[l] = len(label_map)
        new_labels.append(label_map[l])
    return new_labels


# ===== 1. 初始化向量数据库（FAISS） =====
dimension = 1536  # OpenAI text-embedding-3-small 输出向量维度
index = faiss.IndexFlatL2(dimension) if faiss is not None else None  # L2 距离索引

def embed_texts(
        text_list, 
        model="text-embedding-3-large",
        max_chars_per_item=2000,\
        max_batch_chars=6000,
        max_batch_items=8 ):
    """
    输入: [str, str, ...]
    输出: [np.array(d), ...]
    """
    processed = []
    for text in text_list:
        t = str(text)
        if len(t) > max_chars_per_item:
            t = t[:max_chars_per_item]
        processed.append(t)

    embs = []
    batch = []
    batch_chars = 0

    def _flush_batch(batch_texts):
        if not batch_texts:
            return []
        resp = openai.embeddings.create(
            model=model,
            input=batch_texts,
        )
        return [np.array(d.embedding, dtype="float32") for d in resp.data]

    for t in processed:
        # 如果再加这一条会超出限制，就先把当前 batch 发出去
        if (batch and (batch_chars + len(t) > max_batch_chars
                       or len(batch) >= max_batch_items)):
            embs.extend(_flush_batch(batch))
            batch = []
            batch_chars = 0

        batch.append(t)
        batch_chars += len(t)

    # 别忘了 flush 最后一个 batch
    if batch:
        embs.extend(_flush_batch(batch))

    return embs

# 向量数据库类
class ConvVectorStore:
    def __init__(self, chunks, index, emb_dim):
        self.chunks = chunks          # list[dict], 每个有 start_id/end_id/text
        self.index = index            # faiss index
        self.emb_dim = emb_dim

    @classmethod
    def from_history(cls, history, window_size=20, stride=20):
        """
        从一整轮对话构建向量库：
        - 切 chunk
        - 对每个 text 做 embedding
        - 用 FAISS 建 IndexFlatIP
        """
        chunks = build_conv_chunks(history, window_size=window_size, stride=stride)
        if not chunks:
            # 空 history
            index = None
            return cls([], index, 0)

        texts = [c["text"] for c in chunks]
        embs = embed_texts(texts)  # list[np.array]
        emb_dim = embs[0].shape[0]

        emb_matrix = np.stack(embs, axis=0)  # (N, d)
        index = faiss.IndexFlatIP(emb_dim)   # 内积，相当于余弦相似度（需先归一化的话可以再封装）
        index.add(emb_matrix)

        # 把 embedding 一起存住方便 debug（不一定必须）
        for c, e in zip(chunks, embs):
            c["embedding"] = e

        return cls(chunks, index, emb_dim)

    def search_by_text(self, query_text, top_k=8):
        """
        给一段 query 文本，返回最相关的 top_k 个 chunk（已经按相似度排好）
        """
        if not self.chunks or self.index is None:
            return []

        q_emb = embed_texts([query_text])[0].reshape(1, -1).astype("float32")  # (1, d)
        D, I = self.index.search(q_emb, top_k)  # I: (1, top_k)

        idxs = I[0]
        selected = [self.chunks[i] for i in idxs if 0 <= i < len(self.chunks)]
        # 按时间顺序排一下，方便你后面用
        selected.sort(key=lambda c: c["start_id"])
        return selected

    def build_context(self, query_text, top_k=5):
        """
        把检索到的 top_k chunks 拼成一个上下文文本，用来丢给 LLM 看。
        """
        selected = self.search_by_text(query_text, top_k=top_k)
        if not selected:
            return ""

        ctx = "\n\n".join(
            f"[对话片段 {c['start_id']}~{c['end_id']}]\n{c['text']}"
            for c in selected
        )
        return ctx

def Score_turn_importance(history):
    """
    history: list[dict]，形如：
      [{"id": 1, "role": "user", "content": "..."}, ...]
    返回：同样长度的 list，每个元素多一个 "info_score" 字段（0.2 ~ 1.0）
    """

    if not isinstance(history, list) or not history:
        print("⚠️ Score_turn_importance: history 为空或格式异常，将返回原样。")
        return history

    # 1) 把对话整理成 [id][role]: content 形式，给 LLM 看
    lines = []
    for m in history:
        mid = m.get("id")
        role = m.get("role") or m.get("from") or "user"
        text = (m.get("content") or m.get("text") or "").strip()
        if mid is None or text == "":
            continue
        lines.append(f"[{mid}][{role}]: {text}")

    if not lines:
        return history

    conv_text = "\n".join(lines)

 # 2. 构造 prompt：只让模型输出 id + info_score
    prompt = f"""你是一名严谨的对话分析助手。

        现在给你一段多轮对话，每一行的格式为：
        [id][role]: content

        其中：
        - id 是对话轮次的整数编号；
        - role 是说话人角色；
        - content 是该轮的发言内容。

        请你根据整段对话的语义，为其中每一轮"实际有内容的对话"打一个"信息量/重要程度"分数 info_score，用来衡量这条发言在整段对话中的重要性。

        要求：
        1. 对每一条出现的 id（即每一行发言）都给出一个 info_score；
        2. info_score 为浮点数，范围在 0.2 ~ 1.0 之间：
        - 越接近 1.0，说明这轮发言越关键、信息量越大；
        - 越接近 0.2，说明这轮发言越边缘、重复或闲聊性质；
        3. 不需要输出 role 或 content，只需要输出 id 和 info_score；
        4. 严格输出一个 JSON 数组，禁止任何解释性文字、注释或代码块标记。

        对话内容如下：
        {conv_text}

        请按以下格式输出（示例）：
        [
        {{"id": 1, "info_score": 0.85}},
        {{"id": 2, "info_score": 0.35}}
        ]
        """

    completion = openai.chat.completions.create(
        model="gpt-5.2",
        temperature=0.2,
        messages=[
            {
                "role": "system",
                "content": "你是一名严谨的对话分析助手，只输出严格 JSON。",
            },
            {"role": "user", "content": prompt},
        ],
    )

    raw = completion.choices[0].message.content.strip()

    # 3) 简单鲁棒解析：去掉 ```json 包裹
    clean = raw
    if clean.startswith("```"):
        first_newline = clean.find("\n")
        if first_newline != -1:
            clean = clean[first_newline + 1 :]
        end_fence = clean.rfind("```")
        if end_fence != -1:
            clean = clean[:end_fence]
        clean = clean.strip()

    if "[" in clean and "]" in clean:
        start = clean.find("[")
        end = clean.rfind("]")
        if start != -1 and end != -1 and end > start:
            clean = clean[start : end + 1].strip()

    # 截取第一个 [ 到 最后一个 ] 之间
    if "[" in clean and "]" in clean:
        start = clean.find("[")
        end = clean.rfind("]")
        if start != -1 and end != -1 and end > start:
            clean = clean[start : end + 1].strip()

    id2score: Dict[int, float] = {}

    try:
        arr = json.loads(clean)
        if isinstance(arr, list):
            for item in arr:
                if not isinstance(item, dict):
                    continue
                try:
                    mid = int(item.get("id"))
                except Exception:
                    continue
                score = item.get("info_score")
                try:
                    score = float(score)
                except Exception:
                    score = 0.5
                # 约束到 [0.2, 1.0]
                score = max(0.2, min(1.0, score))
                id2score[mid] = score
    except Exception as e:
        print(f"⚠️ Score_turn_importance: JSON 解析失败，使用默认分数。err={e}, raw={raw}")

    new_history = []
    for m in history:
        mid = m.get("id")
        m2 = dict(m)
        m2["info_score"] = float(id2score.get(mid, 0.5))
        new_history.append(m2)

    return new_history


def extract_sentiment(history):
    """
    history: list[dict]，形如：
      [{"id": 1, "role": "user", "content": "..."}, ...]
    返回：同样长度的 list，每个元素多一个 "sentiment" 字段（-1.0 ~ 1.0）
      -  1.0 明显积极（开心、赞同、感谢、兴奋、幽默）
      -  0.0 中性 / 无明显情绪（客观陈述、过渡话语）
      - -1.0 明显消极（难过、愤怒、焦虑、抱怨、失望）
    """

    if not isinstance(history, list) or not history:
        print("⚠️ extract_sentiment: history 为空或格式异常，将返回原样。")
        return history

    # 1) 把对话整理成 [id][role]: content 形式，给 LLM 看
    lines = []
    for m in history:
        mid = m.get("id")
        role = m.get("role") or m.get("from") or "user"
        text = (m.get("content") or m.get("text") or "").strip()
        if mid is None or text == "":
            continue
        lines.append(f"[{mid}][{role}]: {text}")

    if not lines:
        return history

    conv_text = "\n".join(lines)

    # 2) 构造 prompt：只让模型输出 id + sentiment
    prompt = f"""你是一名严谨的对话分析助手。

        现在给你一段多轮对话，每一行的格式为：
        [id][role]: content

        其中：
        - id 是对话轮次的整数编号；
        - role 是说话人角色；
        - content 是该轮的发言内容。

        请你结合整段对话的上下文，为其中每一轮发言打一个"情绪极性"分数 sentiment，用来衡量说话人在这一轮发言中流露出的情绪倾向。

        要求：
        1. 对每一条出现的 id（即每一行发言）都给出一个 sentiment；
        2. sentiment 为浮点数，范围在 -1.0 ~ 1.0 之间：
        - 越接近 1.0，积极情绪越明显（如开心、赞同、感谢、兴奋、幽默）；
        - 接近 0.0 表示中性或无明显情绪（如客观陈述、事实说明、过渡性话语）；
        - 越接近 -1.0，消极情绪越明显（如难过、愤怒、焦虑、抱怨、失望、自责）；
        3. 判断时请结合上下文与语气（如反讽、语气词、玩笑），不要只看个别词；
        4. 不需要输出 role 或 content，只需要输出 id 和 sentiment；
        5. 严格输出一个 JSON 数组，禁止任何解释性文字、注释或代码块标记。

        对话内容如下：
        {conv_text}

        请按以下格式输出（示例）：
        [
        {{"id": 1, "sentiment": 0.6}},
        {{"id": 2, "sentiment": -0.2}}
        ]
        """

    completion = openai.chat.completions.create(
        model="gpt-5.2",
        temperature=0.2,
        messages=[
            {
                "role": "system",
                "content": "你是一名严谨的对话分析助手，只输出严格 JSON。",
            },
            {"role": "user", "content": prompt},
        ],
    )

    raw = completion.choices[0].message.content.strip()

    # 3) 鲁棒解析：去 ``` 围栏 + 截取第一个 [ 到最后一个 ]
    clean = raw
    if clean.startswith("```"):
        first_newline = clean.find("\n")
        if first_newline != -1:
            clean = clean[first_newline + 1 :]
        end_fence = clean.rfind("```")
        if end_fence != -1:
            clean = clean[:end_fence]
        clean = clean.strip()

    if "[" in clean and "]" in clean:
        start = clean.find("[")
        end = clean.rfind("]")
        if start != -1 and end != -1 and end > start:
            clean = clean[start : end + 1].strip()

    id2senti: Dict[int, float] = {}

    try:
        arr = json.loads(clean)
        if isinstance(arr, list):
            for item in arr:
                if not isinstance(item, dict):
                    continue
                try:
                    mid = int(item.get("id"))
                except Exception:
                    continue
                try:
                    s = float(item.get("sentiment"))
                except Exception:
                    s = 0.0
                # 约束到 [-1.0, 1.0]
                id2senti[mid] = max(-1.0, min(1.0, s))
    except Exception as e:
        print(f"⚠️ extract_sentiment: JSON 解析失败，本批默认 0.0（中性）。err={e}, raw={raw[:200]}")

    new_history = []
    for m in history:
        mid = m.get("id")
        m2 = dict(m)
        m2["sentiment"] = float(id2senti.get(mid, 0.0))
        new_history.append(m2)

    return new_history


# ---- 新增：Embedding 语义熵法（低成本信息量评分）----
def Score_turn_importance_embedding(history,
                                     use_llm_fallback: bool = False):
    """
    基于 Embedding 语义熵的信息量评分（优先使用，成本低速度快）。
    原理：用 text-embedding-3-large 对每轮对话编码，计算与全局平均向量的距离。
    距离越大 → 该轮越独特 → 信息量越高。

    history: [{id, role, content}, ...]
    返回：history 每项增加 info_score 字段（0.2~1.0）。
    """
    if not history:
        return history

    texts = []
    valid_indices = []
    for i, m in enumerate(history):
        text = (m.get("content") or m.get("text") or "").strip()
        if text:
            texts.append(text)
            valid_indices.append(i)

    if not texts:
        for m in history:
            m["info_score"] = 0.5
        return history

    # 批量 embedding
    embs = embed_texts(texts, model="text-embedding-3-large")

    # 全局平均向量（"典型对话"的方向）
    mean_emb = np.mean(np.stack(embs, axis=0), axis=0)

    # 每轮与平均向量的余弦距离 → 独特性 → 映射为 info_score
    scores = []
    for emb in embs:
        sim = cosine_similarity(emb, mean_emb)
        # 相似度越低 → 越独特 → 信息量越高
        # 映射到 [0.2, 1.0]
        score = 1.0 - (sim + 1.0) / 2.0  # cos_sim ∈ [-1,1] → [0,1]
        score = 0.2 + 0.8 * score         # 线性映射到 [0.2, 1.0]
        score = max(0.2, min(1.0, score))
        scores.append(score)

    # 贴回 history
    score_map = {valid_indices[i]: s for i, s in enumerate(scores)}
    for i, m in enumerate(history):
        m2 = dict(m)
        m2["info_score"] = float(score_map.get(i, 0.5))
        history[i] = m2

    # 可选的 LLM 复核（仅对极端高分/低分）
    if use_llm_fallback:
        print("   ℹ️ LLM fallback 已启用，将对极端值复核（会增加 LLM 调用）")

    return history

# ---- 格式化已有主题结构为 LLM 参考文本 ----
def _format_existing_ref(existing_domains: List[Dict]) -> str:
    """将已有抽取结果压缩为一段简洁的参考文本，供 LLM 在 prompt 中使用。"""
    if not existing_domains:
        return ""
    lines = ["【已有主题结构（供参考，新内容应尽量归入已有主题）】"]
    for t in existing_domains:
        if not isinstance(t, dict):
            continue
        topic = t.get("topic", "")
        slots = t.get("slots", [])
        slot_names = [s.get("slot", "") for s in slots if isinstance(s, dict)]
        lines.append(f"  ▪ {topic}: {', '.join(slot_names[:10])}")
    lines.append("")
    return "\n".join(lines)


def Topic_Edge_detection(history, use_embedding_hints: bool = True,
                         existing_domains: List[Dict] = None):
    """优化版: 分块处理 + embedding 辅助边界候选 + 已有主题参考。"""
    CHUNK_SIZE = 30       # 每块 30 轮
    OVERLAP = 5           # 块间重叠 5 轮
    LONG_THRESHOLD = 8000  # 超过 8000 字才分块

    def to_lines(h):
        if isinstance(h, str):
            return h.strip()
        if isinstance(h, dict):
            if isinstance(h.get("messages"), list):
                h = h["messages"]
            elif isinstance(h.get("history"), list):
                h = h["history"]
            else:
                h = [h]
        if isinstance(h, list):
            lines = []
            for m in h:
                if not isinstance(m, dict) or "id" not in m:
                    continue
                try:
                    mid = int(m.get("id"))
                except Exception:
                    continue
                role = (m.get("role") or m.get("from") or m.get("source") or "unknown").strip()
                content = (m.get("content") or m.get("text") or "").replace("\n", " ").strip()
                if content:
                    lines.append(f"[{mid}][{role}]: {content}")
            return "\n".join(lines).strip()
        return str(h).strip()

    # ---- 单次 LLM 调用 ----
    existing_ref = _format_existing_ref(existing_domains)

    def _call_llm(history_text: str, boundary_hints: List[int] = None) -> List[Dict]:
        hint_text = ""
        if boundary_hints:
            hint_text = f"\n💡 辅助信息：以下 turn id 附近可能是话题边界（供参考，非强制）：{boundary_hints}"

        prompt = f"""你是"对话话题边界检测器"。只输出 JSON 数组，不要解释，不要 Markdown。

{existing_ref}
对话片段（每行以 [id][role]: 开头）：
-role: 表明这句话的发言人是谁
{history_text}{hint_text}

任务：把全体消息切分成若干"连续、不重叠、覆盖全部"的话题段。

要求：
1) 每段包含连续的 id 范围：start_id <= id <= end_id
2) 段与段之间必须首尾相接：下一段 start_id = 上一段 end_id + 1
3) 覆盖全部消息：第一段 start_id=最小id，最后一段 end_id=最大id
4) slot 用中文名词短语，2~6字，避免口语/虚词
5) 如果新内容语义上属于已有主题，直接复用已有 slot 名称，保持一致性
6) is_question：该段是否是提问（true/false）
7) source：该段来源，表明这段对话的主要发言人
8) sentence: start_id这个id的句子，用于辅助理解
9) 段太短(<3条)尽量合并，段太长(>40条)尽量拆分

严格输出 JSON，例如：
[{{"start_id":1,"end_id":12,"slot":"婚姻观念","is_question":false,"source":"XXX"}},
 {{"start_id":13,"end_id":27,"slot":"社会压力","is_question":true,"source":"XXX"}}]
"""
        completion = openai.chat.completions.create(
            model="gpt-5.2",
            temperature=0.2,
            messages=[
                {"role": "system", "content": "你只输出 JSON 数组，不要输出解释，不要 Markdown。"},
                {"role": "user", "content": prompt},
            ],
        )
        raw = (completion.choices[0].message.content or "").strip()
        return parse_json_array_loose(raw)

    # ---- 规整单次结果 ----
    def _normalize(arr: List) -> List[Dict]:
        out = []
        for it in arr:
            if not isinstance(it, dict):
                continue
            try:
                s = int(it.get("start_id"))
                e = int(it.get("end_id"))
                source = str(it.get("source"))
                sentence = str(it.get("sentence"))
            except Exception:
                continue
            slot = (it.get("slot") or "").strip()
            if not slot:
                continue
            out.append({
                "start_id": s, "end_id": e, "slot": slot,
                "is_question": parse_bool(it.get("is_question")),
                "source": source, "sentence": sentence,
            })
        return out

    # ---- 跨块合并 ----
    def _merge_chunk_results(all_results: List[List[Dict]], overlap: int) -> List[Dict]:
        """将多个块的边界检测结果拼接，处理重叠区的归属。"""
        if len(all_results) == 1:
            return all_results[0]
        merged = []
        for i, chunk_result in enumerate(all_results):
            if i == 0:
                merged.extend(chunk_result)
                continue
            # 前一块的最后一条 end_id
            prev_end = merged[-1]["end_id"] if merged else 0
            # 裁剪当前块中与上一块重叠的部分（id <= prev_end 的丢弃）
            for seg in chunk_result:
                if seg["start_id"] > prev_end:
                    merged.append(seg)
                elif seg["end_id"] > prev_end:
                    # 部分重叠：截断
                    seg["start_id"] = prev_end + 1
                    merged.append(seg)
        return merged

    # === 主流程 ===
    history_text = to_lines(history)

    # 计算 embedding 边界候选（仅在对话不太短时启用）
    boundary_hints = None
    if use_embedding_hints and isinstance(history, list) and len(history) >= 10:
        try:
            sims = compute_adjacent_similarities(history)
            boundary_hints = detect_boundary_candidates(sims)
        except Exception:
            boundary_hints = None

    # 判断是否需要分块
    if len(history_text) > LONG_THRESHOLD and isinstance(history, list) and len(history) > CHUNK_SIZE:
        chunks = chunk_history(history, window_size=CHUNK_SIZE, overlap=OVERLAP)
        all_results = []
        for chunk in chunks:
            chunk_text = to_lines(chunk)
            if not chunk_text.strip():
                continue
            arr = _call_llm(chunk_text, boundary_hints)
            all_results.append(_normalize(arr))
        out = _merge_chunk_results(all_results, OVERLAP)
    else:
        arr = _call_llm(history_text, boundary_hints)
        out = _normalize(arr)

    return out

def Topic_merge(topic_description: List[Dict[str, Any]],
                use_two_stage: bool = True,
                cluster_threshold: float = 0.7,
                existing_domains: List[Dict] = None):
    """优化版：两阶段聚类 + 已有主题参考。"""
    existing_ref = _format_existing_ref(existing_domains)
    slot_items = []
    for it in topic_description:
        if not isinstance(it, dict):
            continue
        try:
            start_id = int(it.get("start_id"))
            end_id = int(it.get("end_id"))
            source = str(it.get("source"))
            sentence = str(it.get("sentence"))
        except Exception:
            continue
        slot_name = (it.get("slot") or it.get("topic_label") or "").strip()
        if not slot_name:
            continue
        slot_items.append({
            "slot": slot_name, "id": start_id, "source": source,
            "is_question": parse_bool(it.get("is_question")),
            "start_id": start_id, "end_id": end_id, "sentence": sentence,
        })

    if not slot_items:
        return []

    # ---- 阶段 1：Embedding 粗聚类 ----
    if use_two_stage and len(slot_items) >= 3:
        try:
            texts = [f"{s['slot']}: {s['sentence']}" for s in slot_items]
            embs = []
            for t in texts:
                embs.append(_embed_single(t))
            cluster_labels = hierarchical_cluster_embeddings(embs, threshold=cluster_threshold)

            # 按簇分组
            clusters: Dict[int, List[Dict]] = {}
            for i, s in enumerate(slot_items):
                label = cluster_labels[i]
                clusters.setdefault(label, []).append(s)

            # 阶段 2：LLM 只做命名 + 微调（大幅减少 token）
            cluster_summaries = []
            for label, slots in clusters.items():
                slot_names = [s["slot"] for s in slots]
                cluster_summaries.append({
                    "cluster_id": label,
                    "slots": slot_names,
                    "slot_count": len(slots),
                })

            prompt = f"""你是"对话话题命名器"。只输出 JSON 数组。

{existing_ref}
下面是把一段对话的 slot 按语义相似度自动分好的 {len(clusters)} 个组，你的任务是：
1) 为每个组起一个合适的中文 topic 名称（2~8字）
2) 优先复用已有主题名称（语义相同时），避免创建重复 topic
3) 必要时可以把组内的 slot 拆分到更合适的 topic（微调）

自动分组结果：
{json.dumps(cluster_summaries, ensure_ascii=False)}

输出格式：
[
  {{"topic": "...", "cluster_ids": [0, ...]}},
  ...
]
"""
            completion = openai.chat.completions.create(
                model="gpt-5.2",
                temperature=0.2,
                messages=[
                    {"role": "system", "content": "你只输出JSON数组，不要解释，不要Markdown。"},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = (completion.choices[0].message.content or "").strip()
            topic_map = parse_json_array_loose(raw)

            # 用 LLM 命名结果构建最终输出
            fixed = []
            seen = set()
            for tm in topic_map if isinstance(topic_map, list) else []:
                topic_name = (tm.get("topic") or "").strip()
                if not topic_name:
                    continue
                cids = tm.get("cluster_ids", [])
                new_slots = []
                for cid in cids:
                    for s in clusters.get(cid, []):
                        key = (s["slot"], s["id"])
                        if key not in seen:
                            seen.add(key)
                            new_slots.append({k: s[k] for k in ("slot","id","source","is_question","start_id","end_id","sentence")})
                if new_slots:
                    fixed.append({"topic": topic_name, "slots": new_slots})

            # 兜底未覆盖的 slot
            missing = [s for s in slot_items if (s["slot"], s["id"]) not in seen]
            if missing:
                fixed.append({
                    "topic": "其他",
                    "slots": [{k: m[k] for k in ("slot","id","source","is_question","start_id","end_id","sentence")} for m in missing]
                })
            return fixed

        except Exception as e:
            print(f"⚠️ 两阶段聚类失败，回退到纯 LLM 聚类: {e}")

    # ---- 回退：纯 LLM 聚类（slot 较少或 embedding 失败时） ----
    slot_list_for_prompt = [
        {k: s[k] for k in ("slot","id","source","is_question","start_id","end_id")}
        for s in slot_items
    ]
    prompt = f"""你是"对话话题聚类器"。只输出 JSON 数组，不要解释，不要 Markdown。

{existing_ref}
输入若干 slot，把它们聚类成更高层 topic，优先复用已有主题（语义相同时使用已有 topic 名称）。
topic 名称 2~8 字中文短语，禁止并列写法。
输出结构：[{{"topic": "...", "slots": [{{"slot":"...","id":1,...}}]}}, ...]

slot 列表（必须覆盖全部）：
{json.dumps(slot_list_for_prompt, ensure_ascii=False, indent=2)}
"""
    completion = openai.chat.completions.create(
        model="gpt-5.2",
        temperature=0.2,
        messages=[
            {"role": "system", "content": "你只输出JSON数组，不要解释，不要Markdown。"},
            {"role": "user", "content": prompt},
        ],
    )
    raw = (completion.choices[0].message.content or "").strip()
    result = parse_json_array_loose(raw)

    expected = {(s["slot"], s["id"]) for s in slot_items}
    seen = set()
    fixed = []
    for t in result if isinstance(result, list) else []:
        if not isinstance(t, dict) or "slots" not in t:
            continue
        topic = (t.get("topic") or "").strip()
        if not topic:
            continue
        new_slots = []
        for s in (t.get("slots") or []):
            if not isinstance(s, dict):
                continue
            key = (str(s.get("slot","")).strip(), int(s.get("id", -1)))
            if key in expected and key not in seen:
                seen.add(key)
                new_slots.append(s)
        if new_slots:
            fixed.append({"topic": topic, "slots": new_slots})

    missing = [s for s in slot_items if (s["slot"], s["id"]) not in seen]
    if missing:
        fixed.append({"topic": "其他", "slots": [
            {k: m[k] for k in ("slot","id","source","is_question","start_id","end_id")}
            for m in missing
        ]})
    return fixed

def build_local_window(history, center_id, window_size=8):
    """
    按 id 在 history 里截一段窗口：
    [center_id - window_size, center_id + window_size]
    返回一个字符串，按对话顺序拼好，供 LLM 判断。
    """
    # 1. 先按 id 排个序，确保顺序一致
    sorted_msgs = sorted(history, key=lambda m: m.get("id", 0))

    # 2. 找到 center_id 对应位置
    center_idx = None
    for i, m in enumerate(sorted_msgs):
        if m.get("id") == center_id:
            center_idx = i
            break
    if center_idx is None:
        return ""

    start = max(0, center_idx - window_size)
    end = min(len(sorted_msgs), center_idx + window_size + 1)
    window_msgs = sorted_msgs[start:end]

    # 3. 格式化成类似：
    # [12][user]: xxx
    # [13][bot]: yyy
    lines = []
    for m in window_msgs:
        mid = m.get("id")
        role = m.get("role") or m.get("from") or "user"
        text = (m.get("content") or m.get("text") or "").strip()
        lines.append(f"[{mid}][{role}]: {text}")
    return "\n".join(lines)

def ask_if_resolved(history: List[Dict[str, Any]], slot_obj: Dict[str, Any],
                       followup_horizon: int = 40,
                       max_chars: int = 3000) -> Dict[str, Any]:
    """
    history: 原始对话 [{id, role, content}, ...]
    slot_obj: {"slot","id","source","is_question","start_id","end_id", ...}
    返回: {"resolved": bool, "confidence": float}
    """
    # 非问题 slot：你可以直接标 False 或者跳过不判
    if not slot_obj.get("is_question", False):
        return {"resolved": False, "confidence": 0.0}

    hist = sort_history(history)

    try:
        start_id = int(slot_obj.get("start_id", slot_obj.get("id")))
        end_id = int(slot_obj.get("end_id", slot_obj.get("id")))
    except:
        return {"resolved": False, "confidence": 0.0}

    slot_name = (slot_obj.get("slot") or "").strip()
    source = (slot_obj.get("source") or "").strip()

    # 1) 问题段（slot 段本身）
    seg_msgs = slice_by_id(hist, start_id, end_id)
    seg_text = pack_msgs(seg_msgs, max_chars=max_chars)

    # 2) 后续段（看有没有回应/解决）
    follow_msgs = followup_after_id(hist, end_id, horizon=followup_horizon)
    follow_text = pack_msgs(follow_msgs, max_chars=max_chars)

    if not seg_text.strip():
        return {"resolved": False, "confidence": 0.0}

    prompt = f"""你是一名严谨的对话分析助手。只输出 JSON，不要解释，不要 Markdown。

        现在给你一段"问题/需求 slot"对应的对话段（start_id~end_id），以及其后的后续对话。
        请判断该 slot 的问题/需求是否在后续对话中已被基本回应或解决。

        slot 信息：
        - slot: {slot_name}
        - source: {source}
        - start_id: {start_id}
        - end_id: {end_id}

        【slot 段内容】（这段里提出了问题/需求）：
        {seg_text}

        【后续对话】（用于判断是否解决）：
        {follow_text}

        判定标准：
        - resolved=true：后续出现明确、具体、与该 slot 高度对应的回答/解释/可执行方案/结论，或明确达成共识（如"明白了/那就这样/OK"）。
        - resolved=false：后续没有针对性回答；只有安慰、模糊回应、跑题、重复提问、或信息不足导致未形成解决。

        严格输出 JSON：
        {{"resolved": true/false, "confidence": 0.0~1.0}}
        """

    completion = openai.chat.completions.create(
        model="gpt-5.2",
        temperature=0.2,
        messages=[
            {"role": "system", "content": "只输出JSON，不要解释，不要Markdown。"},
            {"role": "user", "content": prompt},
        ],
    )

    raw = (completion.choices[0].message.content or "").strip()

    # 鲁棒截取 { ... }
    l, r = raw.find("{"), raw.rfind("}")
    if l != -1 and r != -1 and r > l:
        raw = raw[l:r+1]

    try:
        obj = json.loads(raw)
        resolved = obj.get("resolved", False)
        conf = obj.get("confidence", 0.0)
        if isinstance(resolved, str):
            resolved = resolved.strip().lower() == "true"
        try:
            conf = float(conf)
        except:
            conf = 0.0
        return {"resolved": bool(resolved), "confidence": conf}
    except Exception:
        return {"resolved": False, "confidence": 0.0}

def refine_slot_resolution(history, topics_with_slots,
                           max_slots=50,
                           batch_size: int = 10,
                           prefilter_threshold: float = 0.3):
    """优化版：批量判定 + embedding 预过滤。"""
    hist = sort_history(history)
    refined = []

    # 1) 收集所有 question slots
    all_question_slots: List[Tuple[int, int, Dict]] = []  # (topic_idx, slot_idx, slot)
    for ti, topic_obj in enumerate(topics_with_slots):
        for si, s in enumerate(topic_obj.get("slots", []) or []):
            if s.get("is_question", False):
                all_question_slots.append((ti, si, dict(s)))

    if not all_question_slots:
        return topics_with_slots

    # 2) 预过滤：embedding 比较 question 段与后续段语义相关性
    need_llm: List[Tuple[int, int, Dict]] = []
    skipped_count = 0
    for ti, si, s in all_question_slots[:max_slots]:
        try:
            start_id = int(s.get("start_id", s.get("id")))
            end_id = int(s.get("end_id", s.get("id")))
        except Exception:
            s["resolved"] = False
            continue

        seg_msgs = slice_by_id(hist, start_id, end_id)
        seg_text = pack_msgs(seg_msgs, max_chars=2000)
        follow_msgs = followup_after_id(hist, end_id, horizon=40)
        follow_text = pack_msgs(follow_msgs, max_chars=2000)

        if not follow_text.strip():
            s["resolved"] = False
            skipped_count += 1
            continue

        # Embedding 预过滤
        try:
            q_emb = _embed_single(seg_text)
            f_emb = _embed_single(follow_text)
            sim = cosine_similarity(q_emb, f_emb)
            if sim < prefilter_threshold:
                s["resolved"] = False
                skipped_count += 1
                continue
        except Exception:
            pass  # embedding 失败就交给 LLM 判断

        need_llm.append((ti, si, s))

    if skipped_count:
        print(f"   🔍 预过滤跳过 {skipped_count} 个低相关 slot（相似度 < {prefilter_threshold}）")

    # 3) 批量判定：每 batch_size 个 slot 打包一次 LLM 调用
    checked = 0
    for batch_start in range(0, len(need_llm), batch_size):
        batch = need_llm[batch_start:batch_start + batch_size]
        if not batch:
            break

        # 构建批量 prompt
        slot_descriptions = []
        for _, _, s in batch:
            slot_name = s.get("slot", "")
            source = s.get("source", "")
            start_id = int(s.get("start_id", s.get("id")))
            end_id = int(s.get("end_id", s.get("id")))
            seg = slice_by_id(hist, start_id, end_id)
            seg_t = pack_msgs(seg, max_chars=800)
            follow = followup_after_id(hist, end_id, horizon=40)
            follow_t = pack_msgs(follow, max_chars=800)
            slot_descriptions.append({
                "idx": len(slot_descriptions),
                "slot": slot_name, "source": source,
                "start_id": start_id, "end_id": end_id,
                "question_segment": seg_t,
                "followup": follow_t,
            })

        prompt = f"""你是一名严谨的对话分析助手。判断以下 {len(slot_descriptions)} 个问题是否在后续对话中已被解决。

对每个问题输出：{{"idx": 编号, "resolved": true/false, "confidence": 0.0~1.0}}

问题列表：
{json.dumps(slot_descriptions, ensure_ascii=False, indent=2)}

严格输出 JSON 数组：[{{"idx":0,"resolved":true,"confidence":0.9}}, ...]
"""
        completion = openai.chat.completions.create(
            model="gpt-5.2",
            temperature=0.2,
            messages=[
                {"role": "system", "content": "只输出JSON数组。"},
                {"role": "user", "content": prompt},
            ],
        )
        raw = (completion.choices[0].message.content or "").strip()
        results = parse_json_array_loose(raw)

        # 映射回 slot
        result_map: Dict[int, Dict] = {}
        for r in results if isinstance(results, list) else []:
            if isinstance(r, dict):
                result_map[r.get("idx", -1)] = r

        for i, (_, _, s) in enumerate(batch):
            r = result_map.get(i, {})
            s["resolved"] = bool(r.get("resolved", False))
            checked += 1

    # 4) 重建数据结构
    for ti, topic_obj in enumerate(topics_with_slots):
        new_slots = []
        for si, s in enumerate(topic_obj.get("slots", []) or []):
            s2 = dict(s)
            if not s2.get("is_question", False):
                s2["resolved"] = False
            elif "resolved" not in s2:
                s2["resolved"] = False
            new_slots.append(s2)
        refined.append({"topic": topic_obj.get("topic"), "slots": new_slots})

    print(f"   ✅ refine_slot_resolution: {checked} 个批量判定（{len(all_question_slots)} 个问题 slot）")
    return refined

def extract_wordcloud(
    history: List[Dict[str, Any]],
    topics_with_slots: List[Dict[str, Any]],
    max_words: int = 30,
    limit_slots: Optional[int] = None,
    max_chars: int = 2000,
    use_tfidf_prescreen: bool = True,
    batch_size: int = 5,
):
    """优化版：批量抽取（同一 Topic 下多 Slot 打包）+ TF-IDF 预筛候选词。"""
    hist = sorted(history, key=lambda m: int(m.get("id", 0)))

    done = 0
    for topic_obj in topics_with_slots:
        topic_name = (topic_obj.get("topic") or "").strip()
        slots = topic_obj.get("slots") or []
        if not isinstance(slots, list):
            continue

        # 收集本 Topic 下待处理的 slot
        pending: List[Tuple[int, Dict]] = []  # (slot_index, slot_dict)
        for si, s in enumerate(slots):
            if not isinstance(s, dict):
                continue
            if limit_slots is not None and done >= limit_slots:
                break
            if isinstance(s.get("wordcloud"), list) and len(s["wordcloud"]) > 0:
                continue
            pending.append((si, s))

        if not pending:
            continue

        # TF-IDF 预筛：提取候选词供 LLM 筛选
        tfidf_candidates: Dict[int, List[Tuple[str, float]]] = {}
        if use_tfidf_prescreen and len(pending) >= 2:
            documents = []
            for _, s in pending:
                start_id = int(s.get("start_id", s.get("id")))
                end_id = int(s.get("end_id", s.get("id")))
                seg = slice_by_id(hist, start_id, end_id)
                documents.append(pack_msgs(seg, max_chars=max_chars))
            try:
                all_tfidf = simple_tfidf(documents, top_n=max_words * 2)  # 多给一些候选
                for (_, s), candidates in zip(pending, all_tfidf):
                    tfidf_candidates[id(s)] = candidates
            except Exception:
                pass

        # 批量抽取：每 batch_size 个 slot 打包一次 LLM 调用
        for batch_start in range(0, len(pending), batch_size):
            batch = pending[batch_start:batch_start + batch_size]
            slot_descriptions = []
            for idx, (_, s) in enumerate(batch):
                slot_name = (s.get("slot") or "").strip()
                start_id = int(s.get("start_id", s.get("id")))
                end_id = int(s.get("end_id", s.get("id")))
                seg = slice_by_id(hist, start_id, end_id)
                local_ctx = pack_msgs(seg, max_chars=max_chars)
                # TF-IDF 候选词提示
                candidates = tfidf_candidates.get(id(s), [])
                cand_hint = ""
                if candidates:
                    top_terms = [w for w, _ in candidates[:15]]
                    cand_hint = f"\n💡 TF-IDF 预选词（供参考，可选用、替换或忽略）：{top_terms}"

                slot_descriptions.append({
                    "idx": idx,
                    "slot": slot_name,
                    "start_id": start_id, "end_id": end_id,
                    "content": local_ctx[:max_chars],
                    "candidates": cand_hint,
                })

            k = max(8, min(int(max_words), 40))

            prompt = f"""你是关键词抽取助手。为以下 {len(slot_descriptions)} 个对话片段各抽取不超过 {k} 个关键词。

一级主题：{topic_name}

对每个片段输出：{{"idx": 编号, "words": [{{"word":"...", "weight":0.X}}]}}
要求：2~6字中文为主，过滤虚词，weight 0~1。

片段列表：
{json.dumps(slot_descriptions, ensure_ascii=False, indent=2)}

输出 JSON 数组：[{{"idx":0,"words":[...]}}, ...]
"""
            completion = openai.chat.completions.create(
                model="gpt-5.2",
                temperature=0.2,
                messages=[
                    {"role": "system", "content": "你只输出JSON数组。"},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = (completion.choices[0].message.content or "").strip()
            arr = parse_json_array_loose(raw)

            # 映射回 slot
            result_map: Dict[int, List[Dict]] = {}
            for r in arr if isinstance(arr, list) else []:
                if isinstance(r, dict):
                    result_map[r.get("idx", -1)] = r.get("words", [])

            for idx, (_, s) in enumerate(batch):
                words = result_map.get(idx, [])
                out = []
                seen = set()
                for w_obj in words if isinstance(words, list) else []:
                    if not isinstance(w_obj, dict):
                        continue
                    w = str(w_obj.get("word", "")).strip()
                    if not w or w in seen:
                        continue
                    try:
                        weight = float(w_obj.get("weight", 0.0))
                    except Exception:
                        weight = 0.0
                    weight = max(0.0, min(1.0, weight))
                    out.append({"word": w, "weight": weight})
                    seen.add(w)
                    if len(out) >= k:
                        break
                s["wordcloud"] = out
                done += 1

    return topics_with_slots

def pipeline_on_messages(history,
                         new_message: str = "",
                         existing_domains: List[Dict[str, Any]] = None,
                         max_resolution_slots: int = 50,
                         max_wordcloud_words: int = 20):
    """
    完整的对话主题抽取 Pipeline。

    参数：
    - history: 历史对话 [{id, role, content}, ...]
    - new_message: 新增消息文本（增量模式时使用，留空则全量处理）
    - existing_domains: 已有的抽取结果（增量合并用）
    - max_resolution_slots: 最多判定多少个问题的解决状态
    - max_wordcloud_words: 每个 slot 的词云关键词数量

    返回：segment_by_timeline 格式的最终结果
    """

    # 1. 标准化消息格式
    normalized = []
    for idx, m in enumerate(history, start=1):
        normalized.append({
            "id": m.get("id", idx),
            "role": m.get("role") or m.get("from") or "user",
            "content": (m.get("content") or m.get("text") or "").strip()
        })

    if not normalized:
        return existing_domains or []

    # 2. Step 0: 边界检测 → 切分成连续 Slot
    raw_segments = Topic_Edge_detection(normalized,
                                          existing_domains=existing_domains)
    if not raw_segments:
        return existing_domains or []

    # 3. Step 1: 主题合并 → 将 Slot 聚类为高层 Topic
    merged_topics = Topic_merge(raw_segments,
                                existing_domains=existing_domains)
    if not merged_topics:
        return existing_domains or []

    # 4. Step 2: 问题解决判定（仅对 is_question=True 的 Slot）
    resolved_topics = refine_slot_resolution(
        normalized, merged_topics, max_slots=max_resolution_slots
    )

    # 5. Step 3: 词云抽取
    topics_with_wc = extract_wordcloud(
        normalized, resolved_topics, max_words=max_wordcloud_words
    )

    # 6. 增量合并：如果有已有结果，合并时间线
    if existing_domains:
        all_topics = existing_domains + topics_with_wc
        topics_with_wc = merge_topics_timeline(all_topics)

    # 7. Step 4: 着色 + 按时间轴分段
    colored = assign_colors(topics_with_wc)
    segmented = segment_by_timeline(colored)

    return segmented

# 生成 embedding
def get_embedding(text):
    emb = openai.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return np.array(emb.data[0].embedding, dtype="float32")

# ===== 初始化 Memory（可以换成数据库） =====
user_memory_db = {}  # 示例: {user_id: {key: value}}

# ===== Memory操作函数 =====
# 得到用户Memory
def get_user_memory(user_id):
    """
    返回整理好的文本，用于拼接到prompt
    """
    if user_id not in user_memory_db:
        return ""
    memory = user_memory_db[user_id]
    return "\n".join([f"{k}: {v}" for k, v in memory.items()])

# 更新用户Memory
def update_user_memory(user_id, key, value):
    global user_memory_db
    if user_id not in user_memory_db:
        user_memory_db[user_id] = {}
    
    # 如果 key 已存在，做"追加"而不是覆盖
    if key in user_memory_db[user_id]:
        old_value = user_memory_db[user_id][key]
        if value not in old_value:
            user_memory_db[user_id][key] = f"{old_value}; {value}"
    else:
        user_memory_db[user_id][key] = value
    
    user_memory_db[user_id]['last_updated'] = str(datetime.now())

    print(f"Memory更新：{user_id} - {key} - {value}")
    print("Memory库:" ,user_memory_db)

def extract_memory_from_text(user_id, new_sentence):
    """
    调用 GPT 自动从文本中抽取关键信息（如名字、兴趣、偏好等）
    并更新 Memory
    """
    prompt = f"""
    请从下面的文本中提取用户可能想记住的关键信息，包括姓名、兴趣、爱好、学习目标等。
    输出必须是标准 JSON 对象，严禁包含代码块标记（如```json）或多余文字，键名随意但要能描述信息，如：
    {{
        "name": "Alice",
        "favorite_language": "Python"
    }}

    文本内容：
    {new_sentence}
    """

    completion = openai.chat.completions.create(
        model="gpt-5.2",
        temperature=0,
        messages=[
            {"role": "system", "content": "你是一名信息抽取助手。"},
            {"role": "user", "content": prompt}
        ]
    )
    result = (completion.choices[0].message.content)
    # 更新解析结果到Memory
    try:
        memory_data = json.loads(result)
        for key, value in memory_data.items():
            update_user_memory(user_id, key, value)
    except json.JSONDecodeError:
        # 出现解析错误时可以忽略或记录日志
        print("Memory JSON解析失败:", result)

# ===== GPT + Memory + RAG函数 =====
def talk_to_chatbot(user_id, content, source, history_msgs, top_k=3):
    global index

    # 1. 先检索Memory
    memory_context = get_user_memory(user_id)

    # 2. 为用户输入生成 embedding
    query_emb = get_embedding(content).reshape(1, -1)

    # 3. 检索相关 Memory
    related_context = ""
    if index is not None and memory_context:
        D, I = index.search(query_emb, top_k)
        # 简单示例：用索引对应的 Memory 行（假设 memory_text 分行存储）
        memory_lines = memory_context.split("\n")
        related_context = "\n".join([memory_lines[i] for i in I[0] if i < len(memory_lines)])

    # 4.先把历史对话整理成文本
    history_text = "\n".join(
    [f"{msg.get('from', 'user').capitalize()}: {msg.get('text', '')}" for msg in history_msgs])

    # 5. 组织 prompt，把 Memory 和 RAG 检索内容都拼进去
    messages = [
        {"role": "system", "content": "你是一名对话分析助手，擅长与用户进行沟通, 请根据用户的输入，合理回答，并保持沟通连贯。"},
        {"role": "user", "content": f"""
        下面是与本问题相关的历史对话：{history_text}
        用户信息：
        {memory_context}
        相关 Memory 检索内容：
        {related_context}
        现在用户的问题是：
        {content}"""}
        ]
    
    # 6. 调用大模型生成回复 
    completion = openai.chat.completions.create(
        model="gpt-5.2",
        temperature=0.5,
        messages=messages,
        )
    result = (completion.choices[0].message.content)

    # 7. 更新 Memory（长期记忆）到 FAISS
    if index is not None and memory_context:
        memory_text = "\n".join([f"{k}: {v}" for k, v in user_memory_db[user_id].items()])
        emb = get_embedding(memory_text).reshape(1, -1)
        index.add(emb)

    # 8. 自动抽取最新 Memory 信息
    extract_memory_from_text(user_id, content)

    return result



