import os
import re
import json
import openai
import faiss
import numpy as np
from datetime import datetime
from typing import List, Dict, Any, Optional
from Methods import *
openai.api_key = "sk-3fk05T3Cme02GzUGBc56BaBfA7Ff4dCa9d7dE5AeA689913c"

openai.base_url = "https://api.gpt.ge/v1/"
openai.default_headers = {"x-foo": "true"}

# ===== 1. 初始化向量数据库（FAISS） =====
dimension = 1536  # OpenAI text-embedding-3-small 输出向量维度
index = faiss.IndexFlatL2(dimension)  # L2 距离索引

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

        请你根据整段对话的语义，为其中每一轮“实际有内容的对话”打一个“信息量/重要程度”分数 info_score，用来衡量这条发言在整段对话中的重要性。

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

    # 4. 把 score 贴回原 history_chunk，保证每条都有 info_score
    new_history = []
    for m in history:
        mid = m.get("id")
        m2 = dict(m)
        # 如果该 id 没在 LLM 输出里，就给一个默认值 0.5
        m2["info_score"] = float(id2score.get(mid, 0.5))
        new_history.append(m2)

    return new_history

def Topic_Edge_detection(history):
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

    history_text = to_lines(history)

    prompt = f"""你是“对话话题边界检测器”。只输出 JSON 数组，不要解释，不要 Markdown。

    对话片段（每行以 [id][role]: 开头）：
    -role: 表明这句话的发言人是谁
    {history_text}

    任务：把全体消息切分成若干“连续、不重叠、覆盖全部”的话题段。

    要求：
    1) 每段包含连续的 id 范围：start_id <= id <= end_id
    2) 段与段之间必须首尾相接：下一段 start_id = 上一段 end_id + 1
    3) 覆盖全部消息：第一段 start_id=最小id，最后一段 end_id=最大id
    4) slot 用中文名词短语，2~6字，避免口语/虚词，且必须只表达一个核心主题（禁止“X与Y/和/及/多个、”）
    5) is_question：该段是否是提问（true/false）
    6) source：该段来源, 表明这段对话的主要发言人
    6) 段太短(<3条)尽量合并，段太长(>40条)尽量拆分
    7) 输出字段必须包含：start_id, end_id, slot, is_question, confidence(0~1)

    严格输出 JSON，例如：
    [
    {{"start_id":1,"end_id":12,"slot":"婚姻观念","is_question":false,"source":"XXX"}},
    {{"start_id":13,"end_id":27,"slot":"社会压力","is_question":true,"source":"XXX"}}
    ]
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
    arr = parse_json_array_loose(raw)

    # 轻度规整：保证字段存在、类型正确
    out = []
    for it in arr:
        if not isinstance(it, dict):
            continue
        try:
            s = int(it.get("start_id"))
            e = int(it.get("end_id"))
            source = str(it.get("source"))
        except Exception:
            continue
        slot = (it.get("slot") or "").strip()
        if not slot:
            continue
        out.append({
            "start_id": s,
            "end_id": e,
            "slot": slot,
            "is_question": parse_bool(it.get("is_question")),
            "source": source,
        })
    return out

def Topic_merge(topic_description: List[Dict[str, Any]]):
    slot_items = []
    for it in topic_description:
        if not isinstance(it, dict):
            continue
        try:
            start_id = int(it.get("start_id"))
            end_id = int(it.get("end_id"))
            source = str(it.get("source"))
        except Exception:
            continue
        slot_name = (it.get("slot") or it.get("topic_label") or "").strip()
        if not slot_name:
            continue


        slot_items.append({
            "slot": slot_name,
            "id": start_id,
            "source": source,
            "is_question": parse_bool(it.get("is_question")),
            "start_id": start_id,
            "end_id": end_id,
        })

    slot_list_for_prompt = [
        {k: s[k] for k in ("slot","id","source","is_question","start_id","end_id")}
        for s in slot_items
    ]

    prompt = f"""你是“对话话题聚类器”。只输出 JSON 数组，不要解释，不要 Markdown。

    输入：若干 slot（每个 slot 代表一段连续对话），需要把它们聚类成更高层 topic。
    每个 slot 字段：
    - slot, id, source, is_question, start_id, end_id

    聚类要求：
    1) 输出若干 topic，每个 topic 包含若干 slot。
    2) 每个 slot 必须且只能出现一次（不能遗漏、不能重复）。
    3) topic 名称：中文名词短语，2~8字，避免口语/虚词。
    【topic 的约束】
        1. 每一个 "topic" 必须只表达**一个**核心主题，而不是两个或多个并列的主题。
        2. 禁止使用如下并列写法：
           - "XXX与YYY"
           - "XXX和YYY"
           - "XXX及YYY"
           - "XXX / YYY"
        3. 如果你发现某个方向其实包含两个子主题，例如：
           - 原本你想写成 "经济压力与兼职"
           则请改写为两条独立的主题：
           - "经济压力"
           - "兼职工作"
    4) 合并语义接近的 slot（如“播客介绍/播客内容讨论”应归为同一 topic）。
    5) topic 数量一般 2~8 个（slot 很多时可更多）。
    6) 输出结构必须是：
    [
    {{
        "topic": "...",
        "slots": [
        {{"slot":"...","id":1,"source":"...","is_question":false,"start_id":1,"end_id":12}},
        ...
        ]
    }},
    ...
    ]

下面是 slot 列表（必须覆盖且只覆盖这些 slot）：
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

    # ✅ 后处理校验：确保每个 slot 只出现一次（不信 LLM，自己兜底）
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

    # 把遗漏的 slot 兜底塞到 “其他”
    missing = [s for s in slot_items if (s["slot"], s["id"]) not in seen]
    if missing:
        fixed.append({
            "topic": "其他",
            "slots": [
                {k: m[k] for k in ("slot","id","source","is_question","start_id","end_id")}
                for m in missing
            ]
        })

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

        现在给你一段“问题/需求 slot”对应的对话段（start_id~end_id），以及其后的后续对话。
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
        - resolved=true：后续出现明确、具体、与该 slot 高度对应的回答/解释/可执行方案/结论，或明确达成共识（如“明白了/那就这样/OK”）。
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
                           max_slots=50):
    """
    history: [{id, role, content}, ...]
    topics_with_slots: Topic_Allocation 的输出：
      [
        {"topic": "...", "slots": [ {...}, {...} ]},
        ...
      ]

    返回：结构相同，但每个 slot 的 resolved 字段经过二阶段 LLM 复核。
    max_slots: 最多复核多少个 slot，防止爆调用。
    新逻辑：不区分 source，只要 is_question == True 的 slot 都会尝试判断是否已解决。
    """
    refined = []
    # 统计一下已经复核了多少个，避免对话特别长时太贵
    checked = 0

    for topic_obj in topics_with_slots:
        topic_name = topic_obj.get("topic")
        slots = topic_obj.get("slots", []) or []
        new_slots = []

        for s in slots:
            s2 = dict(s)

            # 1) 不是问句（is_question != True），不需要判断解决与否
            if not s2.get("is_question", False):
                # 明确标记：不是问题，自然不存在“已解决”
                s2["resolved"] = False
                new_slots.append(s2)
                continue

            # 2) 是问句，但已经超过调用上限，避免花太多 token
            if checked >= max_slots:
                # 超上限，不再调用 LLM，保留 is_question=True 但 resolved 默认 False
                s2["resolved"] = False
                new_slots.append(s2)
                continue

            final_resolved = ask_if_resolved(history, s2)
            s2["resolved"] = bool(final_resolved.get("resolved", False))
            checked += 1

            new_slots.append(s2)


        refined.append({
            "topic": topic_name,
            "slots": new_slots,
        })

    return refined

def extract_wordcloud(
    history: List[Dict[str, Any]],
    topics_with_slots: List[Dict[str, Any]],
    max_words: int = 30,
    limit_slots: Optional[int] = None,
    max_chars: int = 2000,
):

    # 1) history 排序 + id -> index
    hist = sorted(history, key=lambda m: int(m.get("id", 0)))

    # 2) 主循环：slot -> 调用 LLM 抽词云
    done = 0
    for topic_obj in topics_with_slots:
        topic_name = (topic_obj.get("topic") or "").strip()
        slots = topic_obj.get("slots") or []
        if not isinstance(slots, list):
            continue

        for s in slots:
            if not isinstance(s, dict):
                continue

            # 测试限额
            if limit_slots is not None and done >= limit_slots:
                return topics_with_slots

            # 跳过已存在
            if isinstance(s.get("wordcloud"), list) and len(s["wordcloud"]) > 0:
                continue

            slot_name = (s.get("slot") or "").strip()

            try:
                start_id = int(s.get("start_id", s.get("id")))
                end_id = int(s.get("end_id", s.get("id")))
            except Exception:
                continue

            seg_msgs = slice_by_id(hist, start_id, end_id)
            local_ctx = pack_msgs(seg_msgs, max_chars=max_chars)

            # 兜底：如果这个段没内容，就别抽了（或退回 sentence）
            if not local_ctx.strip():
                s["wordcloud"] = []
                continue

            k = max(10, min(int(max_words), 50))

            prompt = f"""你是一名严格的关键词抽取助手，只输出 JSON 数组。
            为下面的局部对话片段生成词云关键词。

            【一级主题】{topic_name}
            【当前slot】{slot_name}
            【slot范围】start_id={start_id}, end_id={end_id}

            【slot段对话】
            {local_ctx}

            要求：
            - 抽取不超过 {k} 个关键词/短语（中文为主，2~6 个字为主，别整句）
            - 过滤虚词（如 我们/你们/然后/就是/其实/可能/大家 等）
            - 每个词给权重 weight（0~1），，越重要越大

            严格输出 JSON 数组，例如：
            [{{"word":"婚姻观念","weight":0.92}},{{"word":"离婚成本","weight":0.76}}]
            """

            # --- 调 OpenAI ---
            completion = openai.chat.completions.create(
                model="gpt-5.2",
                temperature=0.2,
                messages=[
                    {"role": "system", "content": "你是一名严格的关键词抽取助手，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
            )

            raw = (completion.choices[0].message.content or "").strip()
            arr = parse_json_array_loose(raw)

            # 3) 轻度校验 + 去重 + 截断
            out = []
            seen = set()
            for it in arr:
                if not isinstance(it, dict):
                    continue
                w = str(it.get("word", "")).strip()
                if not w or w in seen:
                    continue
                try:
                    weight = float(it.get("weight", 0.0))
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

def pipeline_on_messages(messages):

    # 1. 如果没有 id，就顺手补一遍递增 id，保证后面能用 id 做时间轴
    normalized_messages = []
    for idx, m in enumerate(messages, start=1):
        normalized_messages.append({
            "id": m.get("id", idx),
            "role": m.get("role") or m.get("from") or "user",
            "content": (m.get("content") or m.get("text") or "").strip()
        })

    # 🧠 第一步：语义预扫描（粗抽）
    pre_scan_result = Semantic_pre_scanning(normalized_messages)
    # pre_scan_result 结构应该就是你之前 all_results 的那一类 topic/slots 列表

    # 🧹 第二步：主题清洗 / 去噪 / 合并
    cleaned_topics = Topic_cleaning(normalized_messages, pre_scan_result)

    # 🎯 第三步：把 slot 重新对齐到具体的消息 / turn 上
    allocated_topics = Topic_Allocation(normalized_messages, cleaned_topics)


    # 🌈 第四步：是否解决问题
    refined_result = refine_slot_resolution(messages, allocated_topics,
                                        max_slots=50)

    # 🎨 第五步：给每个 topic 分配颜色
    colored_results = assign_colors(refined_result)

    # ⛰️ 第六步：按时间轴切段，给前端画带状图
    segmented_results = segment_by_timeline(colored_results)

    return segmented_results

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
    
    # 如果 key 已存在，做“追加”而不是覆盖
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

def create_theme_variables(result_dict):
    for theme, questions in result_dict.items():
        # 创建合法变量名（移除非法字符）
        var_name = theme.replace(" ", "_").replace("：", "").replace("-", "_")
        globals()[var_name] = questions
    
    print(f"{var_name} = {questions}")  # 可选：打印出来
