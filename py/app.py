from flask import Flask, request, jsonify
from flask_cors import CORS
from copy import deepcopy
import json
import re
import itertools
import colorsys
import uuid
import matplotlib.pyplot as plt

from LLM_Extraction import llm_extract_information_incremental, talk_to_chatbot
from BERT_Extraction import bertopic_extraction_information
from Methods import assign_colors, merge_domains_timeline

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "http://localhost:5173"}})

# 全局已抽取主题
merged_results_global = []
user_id = "default_user"
# 第一个路由 调用LLM返回询问结果
@app.route('/back_message', methods=['POST'])
def back_message():
    try:
        data = request.get_json(force=True)
        if not data or 'message' not in data:
            return jsonify({"error": "请求体为空或缺少 message 字段"}), 400

        # 接收完整 userMsg
        user_msg = data['message']
        user_query = user_msg.get('text', '')
        user_from = user_msg.get('from')
    
        # 接收完整历史
        history_msgs = data.get('history', [])
        # # -------------------------
        # # 获取用户 ID
        # # 优先使用前端传来的 user_id
        # user_id = data.get('user_id')
        # if not user_id:
        #     # 如果前端没有传，生成新的 UUID，返回给前端保存
        #     user_id = str(uuid.uuid4())
        # # -------------------------
        print("history_msgs:", history_msgs)
        result = talk_to_chatbot(user_id, user_query, user_from, history_msgs)

        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": "后端异常", "details": str(e)}), 500

# 第二个路由 产生带颜色的抽取结果
@app.route('/extract', methods=['POST'])
def extract():
   try:
        global merged_results_global

        # 读取对话文本文件
        data = request.get_json(force=True)
        if not data or 'content' not in data:
            return jsonify({'error': '缺少 content 字段'}), 400
        
        content = data['content']
        reset_flag = data['reset']

        if reset_flag:
            merged_results_global = []  # 清空全局结果
        
        # ✅ 兼容两种格式
        if isinstance(content, list):
            # [{role: 'user'/'bot', content: '...'}]
            if all(isinstance(msg, dict) and 'content' in msg for msg in content):
                messages = content  # 新格式：完整消息列表
            else:
                # 旧格式：纯字符串列表
                messages = [{'role': 'user', 'content': str(msg)} for msg in content]
        else:
            # 单个字符串的情况
            split_docs = [s.strip() for s in re.split(r'[。！？\n]', str(content)) if s.strip()]
            messages = [{'role': 'user', 'content': s} for s in split_docs]

        new_results = []
        # 小数据：直接 LLM 处理
        if len(messages) < 100:
            # 只处理最新一轮对话
            latest_msgs = messages[-2:]  # 最后两条：user + bot
            for msg in latest_msgs:
                id = msg.get("id", "")
                role = msg.get("role", "user")
                text = msg.get("content", "").strip()
                if not text:
                    continue

                # 小数据直接 LLM，大数据可扩展为批处理
                result = llm_extract_information_incremental(text, existing_domains=merged_results_global)

                # 给每个 slot 添加来源标识
                for domain in result:
                    for slot in domain.get("slots", []):
                        slot["source"] = role  # user 或 bot

                # 给每个 slot 添加id
                for domain in result:
                    for slot in domain.get("slots", []):
                        slot["id"] = id  # 给每个 slot 赋予唯一 id

                new_results.append(result)
        else:
            # 大数据：先 BERTopic，再 LLM
            clustered = bertopic_extraction_information(docs=messages, keep_noise=True)
            print("主题聚类结果：", clustered)

            for cluster in clustered:
                content = json.dumps(cluster, ensure_ascii=False, indent=2)
                result = llm_extract_information_incremental(content, existing_domains=merged_results_global)
                # 给结果的每个 slot 添加来源标识
                for domain in result:
                    for slot in domain.get("slots", []):
                        slot["source"] = role  # user 或 bot
                new_results.append(result)

        # 先扁平化 results
        flat_new_results = []
        for r in new_results:
            if isinstance(r, list):
                flat_new_results.extend(r)
            else:
                flat_new_results.append(r)

        # 把新结果合并到全局
        all_results = merged_results_global + flat_new_results
        # print("扁平化结果：", flat_new_results)
        merged_results_global = merge_domains_timeline(all_results)
        print("合并结果:", merged_results_global)
        colored_results = assign_colors(merged_results_global)
        # print("带颜色的抽取结果：", colored_results)
    
        # Step 5: 返回 JSON 给前端
        return jsonify(colored_results), 200
   except Exception as e:
        return jsonify({'error': '抽取失败，添加颜色失败', 'details': str(e)}), 500
   
# 测试路由
@app.route('/test_extract', methods=['GET'])
def test_extract():
   try:
        user_sentences = []

        with open("py/conversation_example/ChatGPT-DST.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()

            for i, line in enumerate(lines):
                line = line.strip()
                if line.startswith("## Prompt:") or line.startswith("## Prompt："):
                    # 取下一行，确保索引不越界
                    if i + 1 < len(lines):
                        next_line = lines[i+1].strip()
                        if next_line:  # 避免空行
                            user_sentences.append(next_line)
        print("User Sentences:")
        print(user_sentences)
        
        docs = user_sentences

        new_results = []
        latest_msgs = messages[-2:]  # 最后两条：user + bot
        for msg in latest_msgs:
            id = msg.get("id", "")
            role = msg.get("role", "user")
            text = msg.get("content", "").strip()
            if not text:
                continue

            # 小数据直接 LLM，大数据可扩展为批处理
            result = llm_extract_information_incremental(text, existing_domains=merged_results_global)

            # 给每个 slot 添加来源标识
            for domain in result:
                for slot in domain.get("slots", []):
                    slot["source"] = role  # user 或 bot

            # 给每个 slot 添加id
            for domain in result:
                for slot in domain.get("slots", []):
                    slot["id"] = id  # 给每个 slot 赋予唯一 id

            new_results.append(result)

        # 先扁平化 results
        flat_new_results = []
        for r in new_results:
            if isinstance(r, list):
                flat_new_results.extend(r)
            else:
                flat_new_results.append(r)

        # 把新结果合并到全局
        all_results = merged_results_global + flat_new_results
        # print("扁平化结果：", flat_new_results)
        merged_results_global = merge_domains_timeline(all_results)
        print("合并结果:", merged_results_global)
        colored_results = assign_colors(merged_results_global)
        # print("带颜色的抽取结果：", colored_results)
    
        # Step 5: 返回 JSON 给前端
        return jsonify(colored_results), 200
   except Exception as e:
        return jsonify({'error': '抽取失败，添加颜色失败', 'details': str(e)}), 500
        

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)