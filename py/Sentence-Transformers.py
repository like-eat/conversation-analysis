import re
import json
import math
from typing import List, Dict, Any, Tuple

import numpy as np
from sklearn.preprocessing import MinMaxScaler
from sklearn.feature_extraction.text import TfidfVectorizer
from sentence_transformers import SentenceTransformer


# -------------------------
# Utils
# -------------------------
def _clean_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s

def _is_question(s: str) -> float:
    return 1.0 if ("?" in s or "？" in s) else 0.0

def _has_numbers(s: str) -> float:
    # 包括：数字、百分号、小数、金额符号
    return 1.0 if re.search(r"(\d+(\.\d+)?%?)|([￥$]\s*\d+)", s) else 0.0

def _length_score(s: str) -> float:
    # 过短一般信息少；过长也不一定更重要，这里用平滑上升到上限
    # 你可以改成 log 或者分段
    n = len(s)
    return float(min(1.0, n / 80.0))  # 80字左右基本到1

def contrast_pow(scores, out_min=0.2, out_max=1.0, gamma=1.8):
    # 先归一化到 0~1
    x = (scores - out_min) / (out_max - out_min + 1e-12)
    x = np.clip(x, 0.0, 1.0)
    # 幂变换
    x = x ** gamma
    # 映射回 out_min~out_max
    return out_min + x * (out_max - out_min)

def parse_conversation(file_path):
    """读取对话文本，生成消息列表"""
    messages = []
    id_counter = 1
    role = None
    content = ""

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if line.startswith("## Prompt:") or line.startswith("## Prompt："):
            if content and role:
                messages.append({"id": id_counter, "role": role, "content": content.strip()})
                id_counter += 1
                content = ""
            role = "user"
            continue

        elif line.startswith("## Response:") or line.startswith("## Response："):
            if content and role:
                messages.append({"id": id_counter, "role": role, "content": content.strip()})
                id_counter += 1
                content = ""
            role = "bot"
            continue

        if role:
            content += line + "\n"

    if content and role:
        messages.append({"id": id_counter, "role": role, "content": content.strip()})
    return messages

def parse_meeting_conversation(file_path):
    """读取会议对话文本，生成消息列表"""
    messages = []
    current_id = None
    current_role = None
    content_lines = []

    with open(file_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.strip()

            # 空行直接跳过（但不立刻 flush，id/内容逻辑还是看下面）
            if not stripped:
                continue

            # 如果这一行是纯数字 -> 说明是一个新的 id
            if stripped.isdigit():
                # 先把上一个说话人收尾
                if current_id is not None and current_role and content_lines:
                    messages.append({
                        "id": current_id,
                        "role": current_role,
                        "content": "\n".join(content_lines).strip(),
                    })
                # 开启下一条
                current_id = int(stripped)
                current_role = None
                content_lines = []
                continue

            # 尝试匹配 [说话人]内容
            m = re.match(r'^\[(.+?)\](.*)$', stripped)
            if m:
                # 开启这个 id 对应的第一句
                current_role = m.group(1).strip() or "Unknown"
                first_text = m.group(2).lstrip()
                if first_text:
                  content_lines.append(first_text)
            else:
                # 没有中括号，则视为当前说话人的后续内容
                if current_id is not None:
                    content_lines.append(stripped)
                # 否则（连 id 都没有），直接忽略

    # 文件结束，把最后一条补上
    if current_id is not None and current_role and content_lines:
        messages.append({
            "id": current_id,
            "role": current_role,
            "content": "\n".join(content_lines).strip(),
        })

    return messages
# -------------------------
# Main scorer (No training)
# -------------------------
def score_turn_importance_explainable(
    history: List[Dict[str, Any]],
    model_name: str = "BAAI/bge-small-zh-v1.5",
    window_prev: int = 20,
    window_future: int = 30,
    sim_ref: float = 0.55,
    weights: Tuple[float, float, float, float, float] = (0.35, 0.25, 0.25, 0.10, 0.05),
    #                novelty central future  question numbers length
    out_min: float = 0.2,
    out_max: float = 1.0,
    batch_size: int = 64,
    use_tfidf_fallback: bool = False,
) -> List[Dict[str, Any]]:
    """
    输入: history = [{"id":..., "role":..., "content":...}, ...]
    输出: [{"id":..., "info_score":...}, ...]  (只对有内容的句子打分)
    """

    # 1) 过滤出有效文本
    items = []
    for m in history:
        mid = m.get("id")
        text = _clean_text(m.get("content") or m.get("text") or "")
        if mid is None or text == "":
            continue
        items.append({"id": int(mid), "text": text})

    if not items:
        return []

    texts = [it["text"] for it in items]
    n = len(texts)

    # 2) 得到每句话的语义向量 E 使用SentenceTransformer
    if not use_tfidf_fallback:

        emb_model = SentenceTransformer(model_name)
        # normalize_embeddings=True 会直接输出单位向量，cosine更稳定
        embs = emb_model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        E = np.asarray(embs, dtype=np.float32)  # (n,d)
    # 如果SentenceTransformer下载不成功使用TF-IDF
    else:
        # 中文可以用 char ngram，简单有效
        vec = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=1)
        X = vec.fit_transform(texts).astype(np.float32)
        # 转成 dense（n较大时你也可以只做稀疏相似度，但实现会长一点）
        E = X.toarray()
        # 归一化
        E = E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-12)

    # 3) 计算中心性，对话是否在核心内容E中
    centroid = E.mean(axis=0, keepdims=True)
    centroid = centroid / (np.linalg.norm(centroid, axis=1, keepdims=True) + 1e-12)
    centrality = (E @ centroid.T).reshape(-1)
    centrality = np.clip(centrality, 0.0, 1.0)

    # 4) 计算新颖性 如果差异大则新颖 1是前面没说过 0是完全一样
    novelty = np.zeros(n, dtype=np.float32)
    for i in range(n):
        j0 = max(0, i - window_prev)
        if i == j0:
            novelty[i] = 0.5  # 第一条/窗口为空，认为新颖
            continue
        sims = (E[i:i+1] @ E[j0:i].T).reshape(-1)
        max_sim = float(np.max(sims)) if sims.size else 0.0
        novelty[i] = float(np.clip(1.0 - max_sim, 0.0, 1.0))

    # 5) future_ref: 被后面“承接/引用”的比例
    future_ref = np.zeros(n, dtype=np.float32)
    for i in range(n):
        k1 = min(n, i + 1 + window_future)
        if i + 1 >= k1:
            future_ref[i] = 0.0
            continue
        sims = (E[i:i+1] @ E[i+1:k1].T).reshape(-1)
        future_ref[i] = float(np.mean(sims >= sim_ref)) if sims.size else 0.0

    # 6) structural cues
    # 是否是疑问句
    qfeat = np.array([_is_question(t) for t in texts], dtype=np.float32)
    # 是否含数字
    nfeat = np.array([_has_numbers(t) for t in texts], dtype=np.float32)
    # 长度得分，太短通常信息少
    lfeat = np.array([_length_score(t) for t in texts], dtype=np.float32)

    # 7) 加权向量 
    w_nov, w_cen, w_fut, w_q, w_num = weights[0], weights[1], weights[2], weights[3], weights[4]
    # length 作为一个很弱的额外项（可选）
    # 你也可以把 length 并入 weights，或关掉
    raw = (
        w_nov * novelty +
        w_cen * centrality +
        w_fut * future_ref +
        w_q   * qfeat +
        w_num * nfeat +
        0.03  * lfeat
    )

    # 8) 把raw归一化
    scaler = MinMaxScaler(feature_range=(out_min, out_max))
    scores = scaler.fit_transform(raw.reshape(-1, 1)).reshape(-1)
    scores = contrast_pow(scores, out_min, out_max, gamma=2.5)

    # 9) 输出
    out = []
    for it, sc in zip(items, scores):
        out.append({"id": it["id"], "info_score": float(round(float(sc), 4))})
    return out


# -------------------------
# Example usage
# -------------------------
if __name__ == "__main__":
    file_path_meeting = "py/conversation_example/meeting_talk.txt" 
    # file_path_xinli = "py/conversation_example/ChatGPT-xinli.txt"
    text = parse_meeting_conversation(file_path_meeting)

    scores = score_turn_importance_explainable(
        text,
        model_name="BAAI/bge-small-zh-v1.5",
        window_prev=20,
        window_future=30,
        sim_ref=0.55,
        use_tfidf_fallback=False,  # True 就完全不下模型
    )

    with open("py/conversation_example/meeting_talk_scores.json", "w", encoding="utf-8") as f:
        json.dump(scores, f, ensure_ascii=False, indent=2)

    print("Saved to meeting_talk_scores.json, n=", len(scores))
