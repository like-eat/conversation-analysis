"""
实时对话抽取 API
- 接收前端发来的新对话消息
- 用滑动窗口（最近 N 句）做增量抽取
- 与已有结果合并后返回完整数据，前端直接更新可视化

用法: python realtime_api.py
端口: 5001（独立于 chat 服务的 5000）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, request, jsonify
from flask_cors import CORS
from LLM_Extraction import pipeline_on_messages, Score_turn_importance_embedding
from Methods import merge_topics_timeline, assign_colors, segment_by_timeline

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# 全局状态：每个会话的 { results, last_extracted_idx }
session_state: dict = {}

CONTEXT_SIZE = 8     # 新消息前的上下文轮数（帮助 LLM 理解衔接）
MIN_FIRST_WINDOW = 6  # 首次抽取最少需要多少条消息

@app.route('/extract_realtime', methods=['POST'])
def extract_realtime():
    """
    智能增量抽取：只对新增消息做抽取，拼接少量上文做上下文。

    策略：
    - 首次：取最近 25 句全量抽取
    - 后续：只抽取「上次抽取后新增」的消息 + 前 8 句上下文
    - 新结果与已有结果合并，避免重复抽取

    输入 JSON:
    {
        "session_id": "xxx",
        "history": [{"id":1, "role":"user", "content":"..."}, ...],
        "reset": false
    }
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "请求体为空"}), 400

        session_id = data.get("session_id", "default")
        history = data.get("history", [])
        reset = data.get("reset", False)

        if not history:
            return jsonify({"topics": [], "info_scores": []})

        if reset:
            session_state.pop(session_id, None)

        state = session_state.get(session_id, {"results": [], "last_idx": 0})
        existing = state["results"]
        last_idx = state["last_idx"]

        total_msgs = len(history)
        new_count = total_msgs - last_idx

        print(f"[realtime] session={session_id}, total={total_msgs}条, "
              f"new={new_count}条, existing={len(existing)} topics")

        # ---- 首次抽取：消息太少就跳过 ----
        if not existing and total_msgs < MIN_FIRST_WINDOW:
            print(f"  ⏳ 消息不足 {MIN_FIRST_WINDOW} 条，暂不抽取")
            return jsonify({"topics": [], "info_scores": [], "waiting": True}), 200

        # ---- 首次抽取：全量处理最近 25 句 ----
        if not existing:
            window = history[-25:]  # 首次：最近 25 句
            new_result = pipeline_on_messages(
                window,
                existing_domains=None,
                max_resolution_slots=20,
                max_wordcloud_words=15,
            )
            session_state[session_id] = {"results": new_result, "last_idx": total_msgs}

        # ---- 无新消息：跳过 ----
        elif new_count <= 0:
            return jsonify({
                "topics": existing,
                "info_scores": [],
                "unchanged": True,
            }), 200

        # ---- 增量抽取：只抽新增消息 + 上文上下文 ----
        else:
            # 取「上次结束位置 - 上下文」到末尾
            ctx_start = max(0, last_idx - CONTEXT_SIZE)
            window = history[ctx_start:]  # 上文 8 句 + 所有新消息

            print(f"  📝 增量窗口: [{ctx_start}..{total_msgs-1}] ({len(window)} 句)")

            new_result = pipeline_on_messages(
                window,
                existing_domains=existing,
                max_resolution_slots=10,
                max_wordcloud_words=15,
            )
            session_state[session_id] = {"results": new_result, "last_idx": total_msgs}

        # === 信息量评分：用 embedding 法（低成本） ===
        info_scores = []
        try:
            scored = Score_turn_importance_embedding(history)
            info_scores = [{"id": m["id"], "info_score": m.get("info_score", 0.5)}
                          for m in scored]
        except Exception as e:
            print(f"  ⚠️ 信息量评分失败: {e}")

        return jsonify({
            "topics": new_result,
            "info_scores": info_scores,
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": "抽取失败", "details": str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "sessions": len(session_state)})

if __name__ == '__main__':
    print("=" * 50)
    print("🚀 实时对话抽取服务启动")
    print("   端口: 5001")
    print("   上下文: {} 句 | 首次窗口: 25 句 | 最少消息: {} 句".format(CONTEXT_SIZE, MIN_FIRST_WINDOW))
    print("=" * 50)
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)
