import json
import os
from LLM_Extraction import llm_extract_information_incremental
from Methods import assign_colors, merge_topics_timeline

CHECKPOINT_PATH = "py/conversation_example/ChatGPT-DST-checkpoint.json"
FINAL_PATH = "py/conversation_example/ChatGPT-DST-processed.json"


def safe_process_llm_result(result, role, id_counter):
    """确保 LLM 返回结果是列表字典，并给每个 slot 添加 source 和 id"""
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            print("⚠️ 警告：LLM 返回的字符串无法解析为 JSON，将作为单条文本处理")
            result = [{"topic": "unknown", "slots": [{"slot": result, "source": role, "id": id_counter}]}]

    if isinstance(result, dict):
        result = [result]

    for topic in result:
        slots = topic.get("slots", [])
        if not isinstance(slots, list):
            slots = []
            topic["slots"] = slots
        for slot in slots:
            slot["source"] = role
            slot["id"] = id_counter

    return result


def load_checkpoint():
    """加载中断点文件"""
    if os.path.exists(CHECKPOINT_PATH):
        try:
            with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
                checkpoint = json.load(f)
            print(f"✅ 已加载中断点，恢复到第 {checkpoint.get('last_id', 0)} 条记录。")
            return checkpoint
        except Exception as e:
            print("⚠️ 加载中断点失败，重新开始:", e)
    return {"merged_results_global": [], "last_id": 0}


def save_checkpoint(merged_results_global, last_id):
    """保存中断点（包含已合并并分配颜色的完整结果）"""
    checkpoint_data = {
        "merged_results_global": merged_results_global,
        "last_id": last_id
    }
    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump(checkpoint_data, f, ensure_ascii=False, indent=2)
    print(f"💾 已保存中断点（含颜色）：处理到第 {last_id} 条消息。")


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


def process_conversation(file_path):
    """主处理逻辑：带中断恢复"""
    checkpoint = load_checkpoint()
    merged_results_global = checkpoint["merged_results_global"]
    last_id = checkpoint["last_id"]

     # ✅ 关键：先初始化，确保后面一定有值
    colored_results = assign_colors(merged_results_global)

    messages = parse_conversation(file_path)
    total = len(messages)

    print(f"🧩 共 {total} 条消息，准备从第 {last_id + 1} 条继续。")

    for msg in messages:
        id_counter = msg.get("id", 1)
        role = msg.get("role", "user")
        text = msg.get("content", "").strip()
        if id_counter <= last_id:
            continue  # 跳过已处理
        if not text:
            continue

        try:
            print(f"🧠 正在处理第 {id_counter}/{total} 条消息（{role}）...")
            result = llm_extract_information_incremental(text, existing_topics=merged_results_global)
            safe_result = safe_process_llm_result(result, role, id_counter)

            # 合并结果
            merged_results_global = merge_topics_timeline(merged_results_global + safe_result)

            # 分配颜色
            colored_results = assign_colors(merged_results_global)

            # 每处理一条自动保存
            save_checkpoint(merged_results_global, id_counter)

        except Exception as e:
            print(f"❌ 第 {id_counter} 条处理失败：{e}")
            save_checkpoint(merged_results_global, id_counter)
            continue  # 保持健壮性



    # 保存最终文件
    with open(FINAL_PATH, "w", encoding="utf-8") as f:
        json.dump(colored_results, f, ensure_ascii=False, indent=2)
    print(f"✅ 处理完成，结果已保存：{FINAL_PATH}")

    # 删除中断点（可选）
    # os.remove(CHECKPOINT_PATH)

    return colored_results


if __name__ == "__main__":
    file_path = "py/conversation_example/ChatGPT-DST.txt"
    final_data = process_conversation(file_path)
    # 生成之后的数据要转移到public目录下
    # 删掉最外层字典
