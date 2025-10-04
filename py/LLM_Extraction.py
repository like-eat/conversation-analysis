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


with open('py/conversation_example/ChatGPT.txt', 'r', encoding='utf-8') as file:
    content = file.read()
    # print(content)

# ===== 1. 初始化向量数据库（FAISS） =====
dimension = 1536  # OpenAI text-embedding-3-small 输出向量维度
index = faiss.IndexFlatL2(dimension)  # L2 距离索引
# 定义全局消息列表（保存上下文）
history = []

def llm_extract_information_incremental(new_sentence, existing_domains=None): 
    
    """
    对新句子进行主题抽取，并与已有抽取结果合并
    """
    existing_domains = existing_domains or []

    prompt = f"""请完成以下任务：

        任务：对一句新的对话进行主题抽取，只处理这句话，不重新抽取已有主题。
        新句子: {new_sentence}
        已有主题: {json.dumps(existing_domains, ensure_ascii=False)}
        请只输出新句子的主题 JSON，不修改已有主题。

        输出要求：
        1. 输出必须是标准 JSON 对象，严禁包含代码块标记（如```json）或多余文字；
        2. 每个主题包含字段：
        - "domain": 主题名称
        - "slots": 一个数组，每个元素包含 {{"sentence": 原始句子, "slot": 对应的子主题}}
        3. 保持主题与子主题表述简洁，不超过 8 个字。
        4. 输出的标准 JSON 格式：
        [
            {{
                "domain": "主题名称",
                "slots": [
                    {{"sentence": "原始句子", "slot": "子主题"}}
                ]
            }}
        ]

        规则补充：
        1. 所有问题首先要识别最高层的大主题（如“可视化”），作为唯一的 domain。
        2. 与该主题相关的不同角度（如课程、技术、定义等），必须放在 slots 中，不允许拆分为多个 domain。
        3. domain 只表示核心领域，不超过 6 个字；slots 负责细分问题。
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
def talk_to_chatbot(user_id, content, top_k=3):
    global history, index

    # 1. 先检索Memory
    memory_context = get_user_memory(user_id)

    # 2. 为用户输入生成 embedding
    query_emb = get_embedding(content).reshape(1, -1)

    # 检索相似历史related_context
    if len(history) > 0:
        D, I = index.search(query_emb, top_k)
        related_context = "\n".join([history[i] for i in I[0] if i < len(history)])
    else:
        related_context = ""

    # 3. 组织 prompt，把 Memory 和 RAG 检索内容都拼进去
    messages = [
        {"role": "system", "content": "你是一名对话分析助手，擅长与用户进行沟通, 请根据用户的输入，合理回答，并保持沟通连贯。"},
        {"role": "user", "content": f"""
        下面是与本问题相关的历史对话：{related_context}
        用户信息：
        {memory_context}
        现在用户的问题是：
        {content}"""}
        ]
    # 4. 调用大模型生成回复 

    completion = openai.chat.completions.create(
        model="gpt-4o",
        temperature=0.5,
        messages=messages,
        )
    result = (completion.choices[0].message.content)

    # 5. 更新 FAISS 向量数据库（存用户问题即可，也可存模型回答）
    for text in [content, result]:  # 你要是只想存用户问题，可以去掉 result
        emb = get_embedding(text).reshape(1, -1)
        index.add(emb)
        history.append(text)

    # 6. 自动从用户输入和模型回答抽取 Memory 信息
    extract_memory_from_text(user_id, content)  # 从用户输入中提取

    return result

def create_theme_variables(result_dict):
    for theme, questions in result_dict.items():
        # 创建合法变量名（移除非法字符）
        var_name = theme.replace(" ", "_").replace("：", "").replace("-", "_")
        globals()[var_name] = questions
    
    print(f"{var_name} = {questions}")  # 可选：打印出来
