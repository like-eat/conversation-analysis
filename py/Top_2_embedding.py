import json
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple, Optional

import numpy as np
from sentence_transformers import SentenceTransformer


"""
每句文本 → embedding 向量（N×D）

每个主题 slot → 向量（K×D）（默认用该 slot 段内句向量的平均 centroid）

计算余弦相似度矩阵 sim = sent_embs @ slot_vecs.T（N×K）

对每句取 sim 的 top2 平均 → raw 分数（N）

raw 分数做 min-max → [0.2,1]（N）

输出 JSON / NPZ
"""

# -----------------------------
# Utils
# -----------------------------
# 把 JSON 文件读成 Python 对象
def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
    
# 最基本的文本清洗
def clean_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s

# 在一次矩阵乘法中算完 “每句 vs 每主题” 的相似度
def cosine_matrix(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """
    A: (N, D) normalized
    B: (K, D) normalized
    Return: (N, K) cosine similarities
    """
    return A @ B.T

# 把一句话变成“带上下文”的文本
def build_context_text_by_index(texts: List[str], idx: int, ctx: int) -> str:
    """按顺序取上下文（更稳健，不依赖 id 连续）"""
    if ctx <= 0:
        return texts[idx]
    parts = []
    lo = max(0, idx - ctx)
    hi = min(len(texts), idx + ctx + 1)
    for j in range(lo, hi):
        t = clean_text(texts[j])
        if t:
            parts.append(t)
    return " ".join(parts)


def softmax_probs(sim_row: np.ndarray, beta: float = 12.0) -> np.ndarray:
    z = beta * sim_row
    z = z - np.max(z)  # stability
    ez = np.exp(z)
    return ez / (np.sum(ez) + 1e-12)

def confidence_entropy(sim_row: np.ndarray, beta: float = 12.0) -> float:
    K = sim_row.size
    if K <= 1:
        return 1.0
    p = softmax_probs(sim_row, beta=beta)
    H = -float(np.sum(p * np.log(p + 1e-12)))
    H_norm = H / float(np.log(K))
    return float(1.0 - np.clip(H_norm, 0.0, 1.0))

def cosine_to_01(x: float) -> float:
    return float(np.clip((x + 1.0) * 0.5, 0.0, 1.0))

def score_strength_confidence(sim_row: np.ndarray, topic_idx: Optional[int], beta: float = 12.0) -> Tuple[int, float, float, float]:
    """
    Return: (best_idx, strength_cos, confidence, info_score)
    """
    if sim_row.size == 0 or topic_idx is None or topic_idx < 0 or topic_idx >= sim_row.size:
        return -1, 0.0, 0.0, 0.0

    strength = float(sim_row[topic_idx])             # <-- 关键：不再 argmax
    conf = confidence_entropy(sim_row, beta=beta)    # [0,1] 仍用整行
    strength01 = cosine_to_01(strength)              # [0,1]
    info_score = strength01 * conf                   # [0,1]
    return int(topic_idx), strength, conf, float(info_score)

@dataclass
class SlotSeg:
    start_id: int
    end_id: int
    slot: str

# 得到SlotSeg 列表
def parse_slots(slot_items: List[Dict[str, Any]]) -> List[SlotSeg]:
    segs = []
    for it in slot_items:
        segs.append(SlotSeg(
            start_id=int(it["start_id"]),
            end_id=int(it["end_id"]),
            slot=str(it["slot"]).strip(),
        ))
    segs.sort(key=lambda x: (x.start_id, x.end_id))
    return segs

# 根据id找到属于哪个slot
def slot_index_for_id(segs: List[SlotSeg], msg_id: int) -> Optional[int]:
    for k, seg in enumerate(segs):
        if seg.start_id <= msg_id <= seg.end_id:
            return k
    return None

# 
def build_slot_centroids(
    sentence_embs: Dict[int, np.ndarray],
    segs: List[SlotSeg],
    dim: int,
) -> np.ndarray:
    """
    Slot vector = mean embedding of sentences within the slot.
    Return (K, D) normalized (already normalized if sentence embeddings are normalized).
    """
    K = len(segs)
    C = np.zeros((K, dim), dtype=np.float32)
    for k, seg in enumerate(segs):
        vecs = []
        for msg_id in range(seg.start_id, seg.end_id + 1):
            if msg_id in sentence_embs:
                vecs.append(sentence_embs[msg_id])
        if vecs:
            C[k] = np.mean(np.stack(vecs, axis=0), axis=0)
        else:
            C[k] = np.zeros((dim,), dtype=np.float32)

    # L2 normalize
    norms = np.linalg.norm(C, axis=1, keepdims=True) + 1e-12
    return (C / norms).astype(np.float32)


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
# -----------------------------
# Main
# -----------------------------
def main(
    conversation_path: str,
    topic_names: List[str],
    segs: List[SlotSeg],
    out_path: str,                 
    model_name: str = "BAAI/bge-small-zh-v1.5",
    context_window: int = 1,
):
    USE_NORM = True   # True 输出归一化到 [0.2,1]；False 输出 raw top2 mean

    conv = parse_meeting_conversation(conversation_path)
    conv = sorted(conv, key=lambda x: int(x["id"]))

    ids = [int(m["id"]) for m in conv]
    texts = [clean_text(m.get("content", "")) for m in conv]

    # 1) 构造输入文本（带上下文）
    sentence_texts = [build_context_text_by_index(texts, i, context_window) for i in range(len(texts))]

    # 2) embedding
    model = SentenceTransformer(model_name)
    sent_embs = model.encode(sentence_texts, batch_size=64, show_progress_bar=True, normalize_embeddings=True).astype(np.float32)

    topic_vecs = model.encode(topic_names, batch_size=64, show_progress_bar=False, normalize_embeddings=True).astype(np.float32)

    # 3) 相似度矩阵（不落盘 npz）
    sim = sent_embs @ topic_vecs.T  # (N,K)

    beta = 15.0  # 可调：8~20 常用，越大越偏向 top1

    out = []
    for i in range(sim.shape[0]):
        msg_id = ids[i]
        topic_idx = slot_index_for_id(segs, msg_id)  # <-- 这句所属主题段索引

        assigned_idx, strength, conf, score = score_strength_confidence(
            sim[i], topic_idx, beta=beta
        )

        out.append({
            "id": msg_id,
            "topic_id": assigned_idx,
            "topic_name": topic_names[assigned_idx] if 0 <= assigned_idx < len(topic_names) else "",
            "strength": strength,
            "confidence": conf,
            "info_score": score,
        })



    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[OK] Wrote: {out_path}  (info_score = strength01 * confidence)")



if __name__ == "__main__":
    conversation_path = "py/conversation_example/meeting_talk.txt"
    slots_path = "py/conversation_example/meeting_content/slots.json"
    out_path = "py/conversation_example/meeting_content/info_with_scores.json"

    # 从 slots.json 中提取 topic_names（去重并保持出现顺序）
    slot_items = load_json(slots_path)
    segs = parse_slots(slot_items)
    topic_names = [seg.slot for seg in segs]   # 不去重

    main(conversation_path=conversation_path, topic_names=topic_names, segs=segs, out_path=out_path)

