import os
import re
import json
import openai
import faiss
import numpy as np
from datetime import datetime
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


def Semantic_pre_scanning(history):
    if isinstance(history, dict):
        history = history.get("content", "")
    else:
        history = str(history)

    prompt = f"""请完成以下任务：
        任务：请你基于以下的语义摘要，根据这段摘要生成可能存在的一级对话主题。
        语义摘要：{history}

        输出要求：
        1. 严格输出为标准 JSON 数组，禁止代码块标记和多余文字。
        2. 每个主题包含字段：
        - "topic": 主题名称（名词或名词短语，主题必须具有普遍性，并且不易过于具体，方便扩充出更多的子主题）
        - "support_count": 从摘要中可佐证该主题的要点数量（粗略估计，整数）
        - "support_examples": 1~3 条摘自摘要的短证据片段（必须是原文子串）
        3. 主题应互相区分、涵盖主要语义方向；如无足够证据，不要臆造。
        正确输出示例（示意）：
        [
            {{
            "topic": "人工智能",
            "support_count": 3,
            "support_examples": ["…原文片段A…", "…原文片段B…"]
            }},
            {{
            "topic": "城市排水仿真",
            "support_count": 2,
            "support_examples": ["…原文片段C…"]
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

def Topic_cleaning(history,topic_description,min_support=2):

    # 1) 构建向量库（history 应该是 list[dict] 的对话历史）
    if isinstance(history, list) and history:
        store = ConvVectorStore.from_history(history, window_size=40, stride=40)

        # 2) 把 topic_description 作为 query，检索相关片段
        if isinstance(topic_description, (list, tuple)):
            topic_json_str = json.dumps(topic_description, ensure_ascii=False)
        else:
            topic_json_str = str(topic_description)

        # 从向量库里取 top_k 个片段，拼成上下文
        history_context = store.build_context(topic_json_str)

    else:
        # 如果 history 不是标准 list[dict]（例如已经是字符串），
        # 就直接当成上下文使用（退化成非 RAG，保证兼容）
        if isinstance(topic_description, (list, tuple)):
            topic_json_str = json.dumps(topic_description, ensure_ascii=False)
        else:
            topic_json_str = str(topic_description)

        history_context = str(history)

    prompt = f"""请完成以下任务：
        任务：对下面的“主题列表”进行清洗与合并。
        语义摘要（供相关性参考）：
        {history_context}
        主题列表（JSON数组，元素可能包含 support_count/support_examples，也可能不包含）：{topic_json_str}

        清洗规则：
        1. 相关性与证据：
        - 如存在 "support_count"，要求 support_count ≥ {min_support}；
        - 如不存在 "support_count"，请基于语义与摘要是否匹配来判定是否保留（保守策略，宁缺毋滥）。
        2. 去重合并：
        - 合并语义重复或高度相似的主题，合并后名称更清晰、描述更具体；
        - 如存在多个 support_count，请累加或取最大值；
        - "support_examples" 合并后保留 1~3 条代表性原文子串。
        3. 空泛主题剔除：如仅出现“研究/问题/现状/发展/讨论”等。
        4. 字段结构：
        - 若输入元素含有 "support_count"/"support_examples"，请保留；
        - 若输入元素没有这些字段，不要新增（保持与原结构一致）。
        输出要求：
        - 严格输出标准 JSON 数组，不得出现代码块标记或多余文字。
    """
    completion = openai.chat.completions.create(
        model="gpt-4o",
        temperature=0.2,
        messages=[
            {"role": "system", "content": "你是一名文本分析师，擅长主题去重、相关性判定和证据检查。"},
            {"role": "user", "content": prompt }
            ])
    
    raw = completion.choices[0].message.content.strip()

    # 3. 去掉可能的 ```json 包裹等噪声
    clean = raw
    if clean.startswith("```"):
        first_newline = clean.find("\n")
        if first_newline != -1:
            clean = clean[first_newline+1:]
        end_fence = clean.rfind("```")
        if end_fence != -1:
            clean = clean[:end_fence]
        clean = clean.strip()

    # 4. 如果前后还有解释文字，只取第一个 '[' 到最后一个 ']' 之间
    if "[" in clean and "]" in clean:
        start = clean.find("[")
        end = clean.rfind("]")
        if start != -1 and end != -1 and end > start:
            clean = clean[start:end+1].strip()

    try:
        result = json.loads(clean)
    except json.JSONDecodeError as e:
        print("⚠️ [Topic_cleaning] JSON 解析失败，将直接返回原始 topic_description。错误：", e)
        print("⚠️ 原始内容片段：", clean[:500])
        # 解析失败时，宁可原样返回，不要清空
        if isinstance(topic_description, list):
            result = topic_description
        else:
            result = []

    return result

def Topic_Allocation(history, cleaned_topics, top_k_chunks=6):

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

            请你在上述对话中，抽取若干与该主题密切相关的“二级子主题”(slot)。
            输出为 JSON 数组，每个元素为一个对象，包含字段：
            - "sentence": 对话中的原文句子（必须与上面某一行的 content 完全一致，可以包含前后少量标点，但不要自行改写）
            - "slot": 该句子对应的二级子主题名称（简短、具体的名词短语或动宾短语）
            - "id": 该句子对应行前面的 id（整数）
            - "sentiment": 该句子的情绪分数，范围 -1 (最负面，如沮丧、批评) 到 1 (最正面，如赞美、乐观)，0 表示中性。
            - "source": 说话人角色，只能是 "user" 或 "bot"：
                * 如果该行的 [role] 表示来访者 / 用户（例如包含 "user"、"User"、"用户" 等），请填 "user"；
                * 如果该行的 [role] 表示助理 / AI（例如包含 "assistant"、"Assistant"、"bot"、"助手" 等），请填 "bot"。

            具体要求：
            1. 只考虑与一级主题 "{topic_name}" 明确相关的句子；
            2. 对于同一个 id，只能在输出数组中出现一次：
               - 如果你认为同一个 id 的句子涉及多个子主题，请只选择你认为“最核心”的一个作为 slot；
               - 严禁为同一个 id 输出多条记录。
            3. 每条 sentence 最多对应一个 slot
            4. 如果多句表达完全相同的二级子主题，可只保留信息更完整的句子；
            5. 严格输出 JSON 数组，不要包含任何解释性文字，也不要使用代码块标记。
            示例输出（示意）：
            [
              {{"sentence": "我们需要改进 SWMM 模型的参数校准过程。", "slot": "SWMM 参数校准", "id": 45, "sentiment": 0.2, "source": "user"}},
              {{"sentence": "本次主要讨论 DrainScope 中的排水风险指标可视分析。", "slot": "排水风险指标可视分析", "id": 52, "sentiment": -0.1, "source": "bot"}}
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

            raw_source = (s.get("source") or "").strip().lower()
            if raw_source in ["user", "u", "client", "来访者", "用户"]:
                source = "user"
            elif raw_source in ["bot", "assistant", "ai", "助手", "系统"]:
                source = "bot"
            else:
                source = "user"  # 实在不确定就默认 user，或者你可以改成 None

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
                "source": source
            })

        norm_slots.sort(key=lambda x: x["id"])

        # 6) 严格按你要求的格式写入结果
        results.append({
            "topic": topic_name,
            "slots": norm_slots
        })

    return results


# def llm_extract_information_incremental(history_sentences,new_sentence, existing_topics=None): 
    
#     """
#     对新句子进行主题抽取，并与已有抽取结果合并
#     """
#     existing_topics = existing_topics or []

#     # 👉 支持 dict 或 str
#     if isinstance(new_sentence, dict):
#         sentence_text = new_sentence.get("content", "")
#     else:
#         sentence_text = str(new_sentence)
#         history_sentences = str(history_sentences)

#     prompt = f"""请完成以下任务：

#         任务：首先你需要将新的一句对话中无关紧要的信息进行过滤，然后对这句对话进行主题抽取。
#         历史对话:{history_sentences}

#         新的对话：{new_sentence}

#         新的句子: {sentence_text}

#         已有主题: {json.dumps(existing_topics, ensure_ascii=False)}

#         抽取主题过程要按照下面三步来进行：
#         Step 1：理解整轮语义背景
#         请先阅读历史对话内容，理解整轮对话的主要语义焦点或讨论方向。

#         Step 2：聚焦当前轮的前10句
#         从当前对话中选取**新的句子: {sentence_text}的前10句**（若不足10句则全部使用），
#         和它们的主题。

#         Step 3：主题抽取与输出
#         结合 Step 1 的全局语义理解与 Step 2 的局部焦点，抽取出本轮对话的主题，请只输出新句子的主题 JSON，不修改已有主题。

#         输出要求：
#         1. 输出必须是标准 JSON 对象，严禁包含代码块标记（如```json）或多余文字。
#         2. 每个主题包含字段：
#         - "topic": 主题名称（最高层领域名，如“人工智能”“可视化”“智慧城市”），为名词短语。
#         - "slots": 一个数组，每个元素包含 {{ "sentence": 原始句子, "slot": 对应的子主题}}
#         3. slot必须是**简洁、具体、可落地的名词短语或动宾短语**，能指向一个清晰的关注点。
#         4. 保持主题与子主题表述简洁。
#         5. 输出的标准 JSON 格式：
#         [
#             {{
#                 "topic": "主题名称",
#                 "slots": [
#                     {{"sentence": "原始句子", "slot": "子主题"}}
#                 ]
#             }}
#         ]
#         例子：
#         [
#             {{
#                 "topic": "人工智能",
#                 "slots": [
#                     {{"sentence": "人工智能伦理关注的不仅是算法的公平性与隐私保护，还包括数据使用的透明度、模型决策的可解释性。", "slot": "人工智能伦理"}}
#                 ]
#             }}
#         ]


#         规则补充：
#         1. 所有问题首先要识别最高层的大主题，作为唯一的topic。
#         2. 若句子涉及多个内容，请提炼出最核心的主题。
#         3. slot **禁止**空泛/笼统/抽象指代，例如只写“研究”“问题”“应用”“方法论”“影响”“发展”“现状”“讨论”等泛词。
#         4. topic只表示核心领域，slots 负责细分问题。
#         5. 大部分时间bot的回复是根据user的问题来的，所以大部分时间bot回复的主题和user的问题的主题是一致的。
#         """
    
#     completion = openai.chat.completions.create(
#         model="gpt-4o",
#         temperature=0.5,
#         messages=[
#             {"role": "system", "content": "你是一名对话分析助手，擅长从对话中提取出用户的对话主题并合并到已有主题。"},
#             {"role": "user", "content": prompt }
#             ],)
    
#     try:
#         result = json.loads(completion.choices[0].message.content)
#     except json.JSONDecodeError:
#         result = []

#     print("抽取结果：")
#     print(result)

#     return result

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
