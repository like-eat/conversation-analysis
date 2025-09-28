import os
import re
import json
import openai
import faiss
import numpy as np
from Methods import *
openai.api_key = "sk-3fk05T3Cme02GzUGBc56BaBfA7Ff4dCa9d7dE5AeA689913c"

openai.base_url = "https://api.gpt.ge/v1/"
openai.default_headers = {"x-foo": "true"}


with open('py/conversation_example/ChatGPT.txt', 'r', encoding='utf-8') as file:
    content = file.read()
    # print(content)

# system_prompt = {
#     "role": "system",
#     "content": """你是一名对话分析助手。 
# 请根据用户的输入，合理回答，并保持沟通连贯。"""
# }

# ===== 1. 初始化向量数据库（FAISS） =====
dimension = 1536  # OpenAI text-embedding-3-small 输出向量维度
index = faiss.IndexFlatL2(dimension)  # L2 距离索引
# 定义全局消息列表（保存上下文）
history = []

# def llm_extract_information(content): 
    
#     # 插入进系统 prompt
#     prompt = f"""请完成以下任务：

#         任务：
#         1. 从对话中提取用户(## Prompt)提出的主要主题，对话句子存储在"sentences"中；
#         2. 为每个主要主题提取若干子主题，子主题必须严格来自对话内容，不能编造或推测；
#         3. 子主题应是该主题下更具体的讨论点或内容。

#         输出要求：
#         1. 输出必须是标准 JSON 对象，严禁包含代码块标记（如```json）或多余文字；
#         2. 每个主题包含字段：
#         - "domain": 主题名称
#         - "slots": 一个数组，每个元素包含 {{"sentence": 原始句子, "slot": 对应的子主题}}
#         3. 保持主题与子主题表述简洁，不超过 8 个字。

#         规则补充：
#         1. 所有问题首先要识别最高层的大主题（如“可视化”），作为唯一的 domain。
#         2. 与该主题相关的不同角度（如课程、技术、定义等），必须放在 slots 中，不允许拆分为多个 domain。
#         3. domain 只表示核心领域，不超过 6 个字；slots 负责细分问题。

#         DST 输出示例：
#         [
#             {{
#                 "domain": "AI发展",
#                 "slots": [
#                     {{ "sentence": "多模态模型未来有什么应用？", "slot": "多模态应用"}},
#                     {{ "sentence": "未来十年AI发展趋势？", "slot": "发展趋势"}}
#                 ]
#             }},
#             {{
#                 "domain": "量子计算",
#                 "slots": [
#                     {{ "sentence": "我还想学量子计算。",  "slot": "学习计划" }},
#                     {{ "sentence": "量子计算和AI结合会怎样？", "slot": "结合应用" }}
#                 ]
#             }}
#         ] 

#         下面是多轮对话内容，对话内容存储在sentences当中：
#         {content}
#         """
    
#     # 短期记忆存储历史对话
#     # completion = openai.chat.completions.create(
#     # model="gpt-4o",
#     # temperature=1.0,
#     # messages=[
#     #     {"role": "system", "content": "你是一名对话分析助手，擅长从对话中提取出用户的对话主题。"},
#     #     {"role": "user", "content": prompt }
#     #     ],)
#     completion = openai.chat.completions.create(
#         model="gpt-4o",
#         temperature=0.5,
#         messages=[
#             {"role": "system", "content": "你是一名对话分析助手，擅长从对话中提取出用户的对话主题。"},
#             {"role": "user", "content": prompt }
#             ],)
#     print("抽取结果：")
#     print(completion.choices[0].message.content)
    
#     # 模型返回空或者非json文本报错
#     try:
#         result = json.loads(completion.choices[0].message.content)
#     except json.JSONDecodeError:
#         result = []
#     return result

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
    
    # 短期记忆存储历史对话
    # completion = openai.chat.completions.create(
    # model="gpt-4o",
    # temperature=1.0,
    # messages=[
    #     {"role": "system", "content": "你是一名对话分析助手，擅长从对话中提取出用户的对话主题。"},
    #     {"role": "user", "content": prompt }
    #     ],)
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

# 短期记忆函数
# def talk_to_chatbot(content):
#     global history

#      # 添加用户输入
#     history.append({"role": "user", "content": content})

#     completion = openai.chat.completions.create(
#         model="gpt-4o",
#         temperature=1.0,
#         messages=history,
#         )
#     result = (completion.choices[0].message.content)

#     # 把模型的回复也存进去，形成对话历史
#     history.append({"role": "assistant", "content": result})

#     return result

# 生成 embedding
def get_embedding(text):
    emb = openai.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return np.array(emb.data[0].embedding, dtype="float32")

# 和 GPT 对话 + 使用 FAISS
def talk_to_chatbot(content, top_k=3):
    global history, index

    # 1. 为用户输入生成 embedding
    query_emb = get_embedding(content).reshape(1, -1)
    # 检索相似历史
    if len(history) > 0:
        D, I = index.search(query_emb, top_k)
        related_context = "\n".join([history[i] for i in I[0] if i < len(history)])
    else:
        related_context = ""

    # 2. 组织 prompt，把相关历史拼进去
    messages = [
        {"role": "system", "content": "你是一名对话分析助手，擅长与用户进行沟通, 请根据用户的输入，合理回答，并保持沟通连贯。"},
        {"role": "user", "content": f"""下面是与本问题相关的历史对话：{related_context}

        现在用户的问题是：
        {content}"""}
        ]
    
    # 3. 调用大模型生成回复
    completion = openai.chat.completions.create(
        model="gpt-4o",
        temperature=0.5,
        messages=messages,
        )
    result = (completion.choices[0].message.content)

    # 4. 把用户输入和模型回答都放入向量数据库
    for text in [content, result]:  # 你要是只想存用户问题，可以去掉 result
        emb = get_embedding(text).reshape(1, -1)
        index.add(emb)
        history.append(text)

    return result

def create_theme_variables(result_dict):
    for theme, questions in result_dict.items():
        # 创建合法变量名（移除非法字符）
        var_name = theme.replace(" ", "_").replace("：", "").replace("-", "_")
        globals()[var_name] = questions
    
    print(f"{var_name} = {questions}")  # 可选：打印出来
