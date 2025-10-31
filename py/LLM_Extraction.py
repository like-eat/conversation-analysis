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

def llm_extract_information_incremental(new_sentence, existing_topics=None): 
    
    """
    对新句子进行主题抽取，并与已有抽取结果合并
    """
    existing_topics = existing_topics or []

    # 👉 支持 dict 或 str
    if isinstance(new_sentence, dict):
        sentence_text = new_sentence.get("content", "")
    else:
        sentence_text = str(new_sentence)

    prompt = f"""请完成以下任务：

        任务：首先你需要将新的一句对话中无关紧要的信息进行过滤，然后对这句对话进行主题抽取。
        句子: {sentence_text}
        已有主题: {json.dumps(existing_topics, ensure_ascii=False)}
        请只输出新句子的主题 JSON，不修改已有主题。

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
        3. 不允许每个子句都单独成为一个 slot。
        4. slot **禁止**空泛/笼统/抽象指代，例如只写“研究”“问题”“应用”“方法论”“影响”“发展”“现状”“讨论”等泛词。
        5. topic只表示核心领域，slots 负责细分问题。
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
