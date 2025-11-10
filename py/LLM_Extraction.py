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

def chunk_text(text, max_chars=40000):
    """把长文本切成安全的多段"""
    chunks = []
    while len(text) > max_chars:
        # 尽量在句号后切
        split_idx = text.rfind("。", 0, max_chars)
        if split_idx == -1:
            split_idx = max_chars
        chunks.append(text[:split_idx+1])
        text = text[split_idx+1:]
    if text.strip():
        chunks.append(text)
    return chunks

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
    # 统一转 str
    if isinstance(history, dict):
        history = history.get("content", "")
    else:
        history = str(history)

    # 入参既可能是 str(JSON)，也可能是 Python list
    if isinstance(topic_description, (list, tuple)):
        topic_json_str = json.dumps(topic_description, ensure_ascii=False)
    else:
        topic_json_str = str(topic_description)

    prompt = f"""请完成以下任务：
        任务：对下面的“主题列表”进行清洗与合并，仅保留与“语义摘要”高度相关、且不空泛的主题。
        语义摘要：{history}
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
    try:
        result = json.loads(completion.choices[0].message.content)
    except json.JSONDecodeError:
        result = []

    return result

def Topic_Allocation(history,topic_description):
    # 统一转 str
    if isinstance(history, dict):
        history = history.get("content", "")
    else:
        history = str(history)

    # 入参既可能是 str(JSON)，也可能是 Python list
    if isinstance(topic_description, (list, tuple)):
        topic_json_str = json.dumps(topic_description, ensure_ascii=False)
    else:
        topic_json_str = str(topic_description)

    prompt = f"""请完成以下任务：
        任务：你的任务是识别可以概括的二级子主题，这些子主题可以作为所提供的一级主题的子主题。
        对话历史：{history}
        一级主题清单：{topic_json_str}

        实例：
        [
            {{
                "topic": "人工智能",
                "slots": [
                    {{"sentence": "人工智能伦理关注的不仅是算法的公平性与隐私保护，还包括数据使用的透明度、模型决策的可解释性。", "slot": "人工智能伦理"}},
                    {{"sentence": "人工智能在医疗领域的应用正在迅速扩展，从辅助诊断到个性化治疗方案。", "slot": "医疗领域应用"}}
                ]
            }},
            {{
                "topic": "可视化",
                "slots": [
                    {{"sentence": "可视化技术的发展使得数据更加丰富、复杂，同时也带来了新的可视化方式。", "slot": "可视化技术的发展"}}
                ]
            }}
        ]


        规则：
        1. "topic" 必须是上面清单中的某一个，禁止创造新主题名，主题必须具有普遍性，并且不易过于具体，方便扩充出更多的子主题。
        2. "slots[*].sentence" 必须是上面对话历史中的原文子串；请优先直接拷贝对应行的子串。
        3. "slots[*].slot" 必须是二级子主题，必须是**简洁、具体、可落地的名词短语或动宾短语**，能指向一个清晰的关注点。
        4. 每条对话/句子最多分配 1 个主题；若均不匹配，跳过该条。

        输出要求：
        1. 输出必须是标准 JSON 数组，严禁包含代码块标记（如```json）或多余文字。
        2. 每个主题包含字段：
        - "topic": 主题名称（最高层领域名，如“人工智能”“可视化”“智慧城市”），为名词短语。
        - "slots": 一个数组，每个元素包含 {{ "sentence": 原始句子}}，{{ "slot": 二级子主题}}
        3. 输出的标准 JSON 格式：
        [
            {{
                "topic": "一级主题名称",
                "slots": [
                    {{"sentence": "原始句子", "slot": "二级子主题"}}
                ]
            }}
        ]
        

    """

    completion = openai.chat.completions.create(
        model="gpt-4o",
        temperature=0.2,
        messages=[
            {"role": "system", "content": "你是一名对话分析助手，擅长从对话中提取出对话主题。"},
            {"role": "user", "content": prompt }
            ],)
    
    try:
        result = json.loads(completion.choices[0].message.content)
    except json.JSONDecodeError:
        result = []

    return result

def topic_extraction(history):
     # --- 统一 history 视图 ---
    if isinstance(history, list):
        # 将 parse_conversation 的输出条目化，方便 LLM 逐条引用原文子串
        lines = []
        for m in history:
            if not m.get("content"): 
                continue
            lines.append(f"[{m.get('id')}] ({m.get('role')}) {m['content'].strip()}")
        history_view = "\n".join(lines)
    elif isinstance(history, dict):
        history_view = history.get("content", "")
    else:
        history_view = str(history)

    topic_description = Semantic_pre_scanning(history=history_view)
    topic_description = Topic_cleaning(history=history_view,topic_description=topic_description)

    result = Topic_Allocation(history=history_view,topic_description=topic_description)

    return result 


def llm_extract_information_incremental(history_sentences,new_sentence, existing_topics=None): 
    
    """
    对新句子进行主题抽取，并与已有抽取结果合并
    """
    existing_topics = existing_topics or []

    # 👉 支持 dict 或 str
    if isinstance(new_sentence, dict):
        sentence_text = new_sentence.get("content", "")
    else:
        sentence_text = str(new_sentence)
        history_sentences = str(history_sentences)

    prompt = f"""请完成以下任务：

        任务：首先你需要将新的一句对话中无关紧要的信息进行过滤，然后对这句对话进行主题抽取。
        历史对话:{history_sentences}

        新的对话：{new_sentence}

        新的句子: {sentence_text}

        已有主题: {json.dumps(existing_topics, ensure_ascii=False)}

        抽取主题过程要按照下面三步来进行：
        Step 1：理解整轮语义背景
        请先阅读历史对话内容，理解整轮对话的主要语义焦点或讨论方向。

        Step 2：聚焦当前轮的前10句
        从当前对话中选取**新的句子: {sentence_text}的前10句**（若不足10句则全部使用），
        和它们的主题。

        Step 3：主题抽取与输出
        结合 Step 1 的全局语义理解与 Step 2 的局部焦点，抽取出本轮对话的主题，请只输出新句子的主题 JSON，不修改已有主题。

        输出要求：
        1. 输出必须是标准 JSON 对象，严禁包含代码块标记（如```json）或多余文字。
        2. 每个主题包含字段：
        - "topic": 主题名称（最高层领域名，如“人工智能”“可视化”“智慧城市”），为名词短语。
        - "slots": 一个数组，每个元素包含 {{ "sentence": 原始句子, "slot": 对应的子主题}}
        3. slot必须是**简洁、具体、可落地的名词短语或动宾短语**，能指向一个清晰的关注点。
        4. 保持主题与子主题表述简洁。
        5. 输出的标准 JSON 格式：
        [
            {{
                "topic": "主题名称",
                "slots": [
                    {{"sentence": "原始句子", "slot": "子主题"}}
                ]
            }}
        ]
        例子：
        [
            {{
                "topic": "人工智能",
                "slots": [
                    {{"sentence": "人工智能伦理关注的不仅是算法的公平性与隐私保护，还包括数据使用的透明度、模型决策的可解释性。", "slot": "人工智能伦理"}}
                ]
            }}
        ]


        规则补充：
        1. 所有问题首先要识别最高层的大主题，作为唯一的topic。
        2. 若句子涉及多个内容，请提炼出最核心的主题。
        3. slot **禁止**空泛/笼统/抽象指代，例如只写“研究”“问题”“应用”“方法论”“影响”“发展”“现状”“讨论”等泛词。
        4. topic只表示核心领域，slots 负责细分问题。
        5. 大部分时间bot的回复是根据user的问题来的，所以大部分时间bot回复的主题和user的问题的主题是一致的。
        """
    
    completion = openai.chat.completions.create(
        model="gpt-4o",
        temperature=0.5,
        messages=[
            {"role": "system", "content": "你是一名对话分析助手，擅长从对话中提取出用户的对话主题并合并到已有主题。"},
            {"role": "user", "content": prompt }
            ],)
    
    try:
        result = json.loads(completion.choices[0].message.content)
    except json.JSONDecodeError:
        result = []

    print("抽取结果：")
    print(result)

    return result

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
    """
    content: 本轮用户问题
    source: 消息来源，可传入
    history_msgs: 短期对话列表 [{"role": "user"/"assistant", "content": "..."}]
    index: FAISS 索引对象，用于存储长期记忆
    top_k: RAG 检索数量
    """
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
