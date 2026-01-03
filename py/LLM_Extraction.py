import os
import re
import json
import openai
import faiss
import numpy as np
from datetime import datetime
from typing import List, Dict, Any
from Methods import *
openai.api_key = "sk-3fk05T3Cme02GzUGBc56BaBfA7Ff4dCa9d7dE5AeA689913c"

openai.base_url = "https://api.gpt.ge/v1/"
openai.default_headers = {"x-foo": "true"}

# ===== 1. 初始化向量数据库（FAISS） =====
dimension = 1536  # OpenAI text-embedding-3-small 输出向量维度
index = faiss.IndexFlatL2(dimension)  # L2 距离索引

# ====== 工具：把对话切成窗口 ======
def build_conv_chunks(history, window_size=20, stride=20):
    """
    把整轮对话按 id 排序后，切成一段段 chunk，
    每段包含 window_size 条对话（可重叠，步长 stride）。
    每个 chunk 结构：{start_id, end_id, text}
    """
    # 先按 id 排序
    history_sorted = sorted(
        [m for m in history if isinstance(m, dict) and m.get("content")],
        key=lambda x: x.get("id", 0)
    )

    chunks = []
    n = len(history_sorted)
    if n == 0:
        return chunks

    idx = 0
    while idx < n:
        sub = history_sorted[idx: idx + window_size]
        if not sub:
            break
        text = "\n".join(
            f"[{m['id']}][{m['role']}]: {m['content'].strip()}"
            for m in sub if m.get("content")
        )
        chunks.append({
            "start_id": sub[0]["id"],
            "end_id": sub[-1]["id"],
            "text": text,
        })
        if idx + window_size >= n:
            break
        idx += stride

    return chunks

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
        model="gpt-4o",
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


def Semantic_pre_scanning(history):
    if isinstance(history, dict):
        history = history.get("content", "")
    else:
        history = str(history)

    prompt = f"""请完成以下任务：
        任务：请你基于以下的语义摘要，根据这段摘要生成可能存在的一级对话主题。
        语义摘要：{history}

        【重要约束（请严格遵守）】：
        1. 每一个 "topic" 必须只表达**一个**核心主题，而不是两个或多个并列的主题。
        2. 禁止使用如下并列写法：
           - "XXX与YYY"
           - "XXX和YYY"
           - "XXX及YYY"
           - "XXX / YYY"
           - 包含多个“、”把好几个词串在一起（如 "学习、工作、感情问题"）。
        3. 如果你发现某个方向其实包含两个子主题，例如：
           - 原本你想写成 "经济压力与兼职"
           则请改写为两条独立的主题：
           - "经济压力"
           - "兼职工作"
        4. topic 应该是**名词或名词短语**，尽量简短清晰，并有一定普遍性，方便下面再扩展出多个子主题；
           - ✅ 推荐示例： "经济压力"、"睡眠问题"、"身体形象焦虑"
           - ❌ 不要： "关于我最近经济压力很大的问题"（太长、像一句话）
        5. 同一类语义非常相近的主题，请使用一个更通用、概括性的名字：
           - 例如 "身体形象与健康"、"减肥与身体健康"、"身材焦虑"
           最终可以统一为一个更概括的主题： "身体形象与健康状况" 或 "身体形象焦虑"
           （注意仍然不要用 "X与Y" 时，优先写成 "身体形象与健康状况" 这种整体概念，
            或者直接写 "身体形象与健康状况问题"——**不要明显看成两个并列对象**）

        【输出要求】：
        1. 严格输出为标准 JSON 数组，禁止代码块标记和多余文字。
        2. 每个主题包含字段：
           - "topic": 主题名称（符合以上约束）
           - "support_count": 从摘要中可佐证该主题的要点数量（粗略估计，整数）
           - "support_examples": 1~3 条摘自摘要的短证据片段（必须是原文子串）
        3. 主题应互相区分、涵盖主要语义方向；如无足够证据，不要臆造。

        【正确输出示例（示意）】：
        [
          {{
            "topic": "经济压力",
            "support_count": 3,
            "support_examples": ["…原文片段A…", "…原文片段B…"]
          }},
          {{
            "topic": "兼职工作",
            "support_count": 2,
            "support_examples": ["…原文片段C…"]
          }},
          {{
            "topic": "身体形象焦虑",
            "support_count": 2,
            "support_examples": ["…原文片段D…"]
          }}
        ]
    """
    completion = openai.chat.completions.create(
        model="gpt-4o",
        temperature=0.2,
        messages=[
            {"role": "system", "content": "你是一名文本聚类分析师，擅长从对话中提取出对话主题。"},
            {"role": "user", "content": prompt }
            ],)
    try:
        result = json.loads(completion.choices[0].message.content)
    except json.JSONDecodeError:
        result = []

    return result

def Topic_cleaning(history, topic_description, min_support=2):
    """
    版本说明：
    - 步骤1：按 topic 字符串聚合（完全相同的主题名合并，support_count 累加）
    - 步骤2：按 support_count 过滤掉出现次数太少的主题
    - 步骤3：调用 LLM 做“语义去重”，但只能在原始 topic 名里选子集
             （禁止改名、禁止生成新主题）
    - 输出：最终保留的主题对象列表，每个元素一定来自原始输入
    """
    # -------- 0. 输入兜底 --------
    if not isinstance(topic_description, list):
        return []

    # -------- 1. 先做本地聚合：同名 topic 合并 --------
    # key: topic 名字（去掉首尾空格）
    agg = {}  # topic_name -> merged_obj

    for item in topic_description:
        if not isinstance(item, dict):
            continue
        raw_name = (item.get("topic") or "").strip()
        if not raw_name:
            continue

        # 初始化
        if raw_name not in agg:
            new_item = dict(item)
            # 保证有 support_count 字段
            sc = new_item.get("support_count")
            if isinstance(sc, int):
                pass
            else:
                # 没给就当作 1 次
                new_item["support_count"] = 1
            # 确保 support_examples 为 list
            se = new_item.get("support_examples")
            if se is None:
                new_item["support_examples"] = []
            elif isinstance(se, list):
                new_item["support_examples"] = se
            else:
                new_item["support_examples"] = [str(se)]
            agg[raw_name] = new_item
        else:
            # 已经有一个代表，做累加
            exist = agg[raw_name]
            # support_count 累加
            sc_old = exist.get("support_count", 0)
            sc_new = item.get("support_count", 0)
            try:
                sc_old = int(sc_old)
            except Exception:
                sc_old = 0
            try:
                sc_new = int(sc_new)
            except Exception:
                sc_new = 0
            exist["support_count"] = sc_old + sc_new

            # 合并 support_examples
            se_old = exist.get("support_examples") or []
            if not isinstance(se_old, list):
                se_old = [str(se_old)]
            se_new = item.get("support_examples") or []
            if not isinstance(se_new, list):
                se_new = [str(se_new)]
            merged_examples = se_old + se_new
            # 去重 + 截断到最多 3 条
            dedup_examples = []
            for ex in merged_examples:
                ex = str(ex)
                if ex not in dedup_examples:
                    dedup_examples.append(ex)
                if len(dedup_examples) >= 3:
                    break
            exist["support_examples"] = dedup_examples

    # -------- 2. support_count 过滤：出现次数太少的剔除 --------
    filtered = []
    for name, obj in agg.items():
        sc = obj.get("support_count", 0)
        try:
            sc = int(sc)
        except Exception:
            sc = 0
        if sc < min_support:
            # 丢掉低频主题
            continue
        filtered.append(obj)

    # 如果过滤完之后空了，直接返回聚合结果（最多只做过本地过滤）
    if not filtered:
        return list(agg.values())

    # -------- 3. 调用 LLM 做语义去重（但禁止新主题/改名） --------
    # 准备给 LLM 的简化结构，只传 topic 名 + support_count
    candidates = [
        {
            "topic": (t.get("topic") or "").strip(),
            "support_count": int(t.get("support_count", 0)),
        }
        for t in filtered
        if (t.get("topic") or "").strip()
    ]

    topics_for_llm = json.dumps(candidates, ensure_ascii=False)

    dedup_prompt = f"""你将看到一组候选的一级主题，它们有可能语义上有重复或非常相近。

        候选主题列表（JSON 数组，每个元素包含 topic 和 support_count）：
        {topics_for_llm}

        你的任务：
        1. 识别其中语义高度重复、仅表述略有不同的主题；
        2. 在这些重复主题中，选择一个作为“代表主题”保留，其余视为被合并，不再单独保留；
        3. 你只能在【原始 topic 字符串】中选择保留对象：
        - 不允许对 topic 文本进行任何改写；
        - 不允许生成新的主题名称；
        - 输出中的每一个字符串必须严格等于输入里某个对象的 topic 字段。

        选择策略建议（不是硬性要求）：
        - 可以优先保留 support_count 较大的那个；
        - 如果 support_count 接近，可以保留语义更清晰、信息量更大的那个；
        - 如果两个主题语义差异较大（例如“就业压力”和“职业发展规划”），请不要合并。

        输出要求：
        - 严格输出一个 JSON 数组；
        - 数组中的每个元素是一个字符串，对应需要保留的 topic 名称；
        - 这些字符串必须全部来自输入的 topic 字段，不允许新增、不允许改写；
        - 不要输出任何解释性文字、注释或代码块标记（例如 ```json）。
        示例（仅示意格式）：
        ["自我价值怀疑", "心理健康问题", "就业压力", "职业发展规划"]
        """

    try:
        completion = openai.chat.completions.create(
            model="gpt-4o",
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": "你是一名严格的主题去重助手，只在给定的 topic 名称中选择子集，不会改写或生成新主题。",
                },
                {"role": "user", "content": dedup_prompt},
            ],
        )
        raw = completion.choices[0].message.content.strip()

        # 去掉可能的 ```json ...
        clean = raw
        if clean.startswith("```"):
            first_newline = clean.find("\n")
            if first_newline != -1:
                clean = clean[first_newline + 1 :]
            end_fence = clean.rfind("```")
            if end_fence != -1:
                clean = clean[:end_fence]
            clean = clean.strip()

        # 截取第一个 [ ... ] 区间
        if "[" in clean and "]" in clean:
            start = clean.find("[")
            end = clean.rfind("]")
            if start != -1 and end != -1 and end > start:
                clean = clean[start : end + 1].strip()

        kept_names = json.loads(clean)
        if not isinstance(kept_names, list):
            raise ValueError("LLM 输出不是数组")

        # -------- 4. 严格兜底：只保留“原始 topic 名集合”中的字符串 --------
        original_names = { (t.get("topic") or "").strip() for t in filtered }
        final_names = []
        for name in kept_names:
            if not isinstance(name, str):
                continue
            name = name.strip()
            if name in original_names and name not in final_names:
                final_names.append(name)

        # 万一 LLM 全删了，就退回到 filtered 全部保留
        if not final_names:
            return filtered

        # 根据最终保留的名字，从 filtered 中取出对应对象
        name_to_obj = { (t.get("topic") or "").strip(): t for t in filtered }
        result = [name_to_obj[n] for n in final_names if n in name_to_obj]
        return result

    except Exception as e:
        print("⚠️ [Topic_cleaning] LLM 去重阶段失败，将返回本地过滤结果。错误：", e)
        return filtered


def Topic_Allocation(history, cleaned_topics, top_k_chunks=12):

    # 0. 构建对话向量库
    if not (isinstance(history, list) and history):
        print("⚠️ Topic_Allocation_v2: history 为空或格式异常，将返回空结果。")
        return []

    store = ConvVectorStore.from_history(history, window_size=40, stride=40)

    results = []

    for topic_obj in cleaned_topics:
        topic_name = topic_obj.get("topic", "").strip()
        if not topic_name:
            continue

        support_examples = topic_obj.get("support_examples", []) or []
        if not isinstance(support_examples, list):
            support_examples = [str(support_examples)]

        # 1) 构造 query：topic 名 + 支撑例子
        query_text = topic_name + "\n" + "\n".join(support_examples)

        # 2) 检索与该 topic 相关的对话片段
        context = store.build_context(query_text, top_k=top_k_chunks)
        if not context.strip():
            # 没检索到就跳过或给空 slots
            results.append({"topic": topic_name, "slots": []})
            continue

        # 3) 让 LLM 在这个上下文中抽取二级子主题（slots）
        #    注意：上下文中每行都是 "[id][role]: content"，让模型复制 id 即可
        prompt = f"""请完成以下任务：
            任务：你将看到一段与某个一级主题高度相关的对话原文片段。
            一级主题为："{topic_name}"

            对话片段（每行以 [id][role]: 开头）：
            {context}

            对话片段中，每一行的格式类似：
            [id][role]: content

            其中：
            - id：一个整数，是该行对话的唯一编号；
            - role：说话人角色标记；
            - content：这一行对话的具体文本。

            请你在上述对话中，抽取若干与该主题密切相关的“二级子主题”(slot)。

            输出为 JSON 数组，每个元素为一个对象，包含字段：
            - "sentence":  
                - 取自对话片段中某一行的 content 原文；
                - 必须与原文完全一致（允许只加减极少量前后标点），不要改写、总结或翻译；
                - 不要把多行合并成一句。
            - "slot": 
                - 对该 sentence 的一个“二级子主题”名称；
                - 必须**非常简洁**，严格控制在**不超过 6 个汉字**（不计空格和标点）；
                - 使用简短、具体的名词短语或动宾短语，例如“参数校准”“指标分析”“风险评估”，不要写成完整句子；
                - **禁止重复一级主题 "{topic_name}"**，不能出现“{topic_name}的XXX”“关于{topic_name}XXX”等形式，也不要把 topic 名直接写进 slot；
                - **禁止并列结构**，例如：
                    - “XXX与XXX”“XXX和XXX”“XXX及XXX”“XXX、XXX”等形式都不允许；
                    - 如果原句中包含多个要点，只选择你认为最核心的一个要点，用单一概念表达；
                - 若提炼出的短语超过 6 个汉字，请进一步压缩，宁可省略修饰词，也不要超过长度限制。
            - "id": 
                - 该 sentence 所在行前面的 id（一个整数）；
                - 必须直接来自对话片段中对应行的 [id]，禁止自己编造新的 id。
            - "sentiment": 
                - 该句子的情绪分数，范围为 -1 到 1：
                    - 接近 1：明显积极、赞美、乐观、表达感谢/满意；
                    - 接近 -1：明显消极、抱怨、沮丧、焦虑、批评；
                    - 接近 0：客观陈述、技术性描述、普通疑问等中性语气；
                - 如果你不确定，可以使用 0 或接近 0 的值。
            - "source":  
                - 说话人角色标签，一个字符串；
                - 必须直接来自该行对话中方括号里的 [role]，去掉方括号后原样填写；
                    - 例如原行是 `[12][user]: ...`，则 source 填 `"user"`；
                    - 原行是 `[35][Speaker_A]: ...`，则 source 填 `"Speaker_A"`；
                    - 原行是 `[7][主持人]: ...`，则 source 填 `"主持人"`；
                - 不要自行创造新的角色名称，也不要翻译或改写。
            - "is_question":  
                - 布尔值 true/false；
                - 当该 sentence 是说话人提出的一个**明确的问题、请求帮助或解决需求**时，请填 true（无论 source 是谁）；
                    - 例如包含明显的疑问、征求意见、请求操作等；
                - 其他所有情况（普通陈述、情绪表达、总结、回应等）一律填 false。

            【抽取规则与约束】
            1. 只考虑与一级主题 "{topic_name}" 明确相关的句子；
            2. 对于同一个 id，在结果 JSON 中**最多出现一次**：
                - 即使你觉得这句涉及多个子主题，也只选择你认为“最核心”的一个 slot；
                - 严禁为同一个 id 输出多条记录。
            3. 每条 "sentence" 只能对应一个 "slot"，不要把同一 sentence 拆成多个对象。
            4. 如果多句表达的是几乎完全相同的子主题，你可以只保留信息更完整、语义更清楚的一句。
            5. 严格输出 JSON 数组，不要包含任何解释性文字，也不要使用代码块标记。

            示例输出（仅示意，注意实际内容应来自当前对话片段）：
            [
              {{"sentence": "我应该怎么改进 SWMM 模型的参数校准？", "slot": "SWMM 参数校准方法", "id": 45, "sentiment": 0.2, "source": "user", "is_question": true}},
              {{"sentence": "本次主要讨论 DrainScope 中的排水风险指标可视分析。", "slot": "指标可视分析", "id": 52, "sentiment": -0.1, "source": "bot", "is_question": false}}
            ]
        """

        completion = openai.chat.completions.create(
            model="gpt-4o",
            temperature=0.2,
            messages=[
                {"role": "system", "content": "你是一名对话分析助手，擅长从对话中抽取结构化主题信息。"},
                {"role": "user", "content": prompt}
            ]
        )

        raw = completion.choices[0].message.content.strip()

        # 4) 解析 JSON（和你清洗那边一样的鲁棒套路）
        clean = raw
        if clean.startswith("```"):
            first_newline = clean.find("\n")
            if first_newline != -1:
                clean = clean[first_newline + 1:]
            end_fence = clean.rfind("```")
            if end_fence != -1:
                clean = clean[:end_fence]
            clean = clean.strip()

        if "[" in clean and "]" in clean:
            start = clean.find("[")
            end = clean.rfind("]")
            if start != -1 and end != -1 and end > start:
                clean = clean[start:end + 1].strip()

        try:
            slots = json.loads(clean)
        except json.JSONDecodeError as e:
            print(f"⚠️ [Topic_Allocation_v2] 解析 slots JSON 失败，topic={topic_name}, 错误: {e}")
            slots = []

        # 5) 规范化 & 排序（按 id 时间顺序）
        norm_slots = []
        seen_ids = set()

        for s in slots:
            if not isinstance(s, dict):
                continue
            sent = s.get("sentence", "").strip()
            slot_name = s.get("slot", "").strip()
            try:
                sid = int(s.get("id"))
            except Exception:
                continue
            sentiment = s.get("sentiment", 0.0)  # 默认 0，如果缺失

            # 解析 source：直接保留模型给出的角色标签
            raw_source = s.get("source")
            if raw_source is None:
                source = ""
            else:
                source = str(raw_source).strip()

            # 解析 is_question：相信模型的布尔值，不再强制依赖 source
            raw_iq = s.get("is_question")
            if isinstance(raw_iq, bool):
                is_question = raw_iq
            elif isinstance(raw_iq, str):
                is_question = raw_iq.strip().lower() == "true"
            else:
                is_question = False

            if not sent or not slot_name:
                continue

            # ✅ 去重：同一个 topic 里，一个 id 只保留一次
            if sid in seen_ids:
                # 如果你以后想换策略（比如选情绪更强的那条），可以在这里改逻辑
                continue
            seen_ids.add(sid)

            norm_slots.append({
                "sentence": sent,
                "slot": slot_name,
                "id": sid,
                "sentiment": sentiment,  # 新增字段
                "source": source,
                "is_question": is_question
            })

        norm_slots.sort(key=lambda x: x["id"])

        # 6) 严格按你要求的格式写入结果
        results.append({
            "topic": topic_name,
            "slots": norm_slots
        })

    return results

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


def ask_if_resolved(history, slot_obj):
    """
    history: 原始对话 [{id, role, content}, ...]
    slot_obj: {"sentence", "slot", "id", "source", ...}
    返回 True/False
    """
    sid = slot_obj["id"]
    sentence = slot_obj["sentence"]
    slot_name = slot_obj["slot"]

    local_ctx = build_local_window(history, sid, window_size=8)
    if not local_ctx.strip():
        return False

    prompt = f"""你是一名对话分析助手。
        现在给你一段对话片段，以及其中一条“某位说话人提出的问题/需求”所在的句子。

        对话片段如下（按时间顺序）：
        {local_ctx}

        其中，在 id = {sid} 的这一句中，该说话人提出了一个子主题/问题：
        "{sentence}"
        子主题名称为："{slot_name}"

        请你只根据上面的对话片段，判断这个问题/需求在后续对话中是否已经在对话中被基本回应或解决。
        这里的“解决”指：
        - 有发言给出了明确、具体、与该问题高度对应的回答、解释或可执行方案；
        - 不要求提问者显式说“谢谢，解决了”，但解决者的回应应该覆盖了核心疑问。

        如果解决者只是简单安慰、模糊回应、部分答复，或者没有明显针对该问题的回答，都视为“未解决”。

        请严格输出一个 JSON 对象，不要包含多余文字，不要使用代码块：
        例如：
        {{"resolved": true}}
        或
        {{"resolved": false}}
        """

    completion = openai.chat.completions.create(
        model="gpt-4o",
        temperature=0.2,
        messages=[
            {"role": "system", "content": "你是一名严谨的对话分析助手，只输出结构化 JSON。"},
            {"role": "user", "content": prompt}
        ],
    )

    raw = completion.choices[0].message.content.strip()

    # 简单鲁棒解析
    try:
        # 有些模型会输出前后空行或其它东西，就粗略截一下 {...} 部分
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start:end+1]
        data = json.loads(raw)
        val = data.get("resolved")
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() == "true"
    except Exception as e:
        print(f"⚠️ ask_if_resolved 解析失败，默认 False: {e}, raw={raw}")
    return False

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
            s2["resolved"] = final_resolved
            checked += 1

            new_slots.append(s2)


        refined.append({
            "topic": topic_name,
            "slots": new_slots,
        })

    return refined

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
                                        max_slots=80,   # 按你能接受的调用量调
                                        only_user=True)

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
        model="gpt-4o",
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
        model="gpt-4o",
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
