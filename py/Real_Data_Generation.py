import json
import os
from LLM_Extraction import llm_extract_information_incremental, Semantic_pre_scanning, Topic_cleaning, Topic_Allocation
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

def chunk_text(text, max_chars=40000):
    """把长文本切成安全的多段"""
    chunks = []
    current_chunk = []
    current_length = 0

    for line in text.split("\n"):
        line_length = len(line)
        if current_length + line_length > max_chars:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = [line]
            current_length = line_length
        else:
            current_chunk.append(line)
            current_length += line_length

    if current_chunk:
        chunks.append(current_chunk)

    return chunks

def segment_by_timeline(topics):

    # 1. 先把所有 slot 打平，变成一个按句子粒度的列表
    flat_items = []
    for t in topics:
        topic_name = t.get("topic")
        topic_color = t.get("color")
        for s in t.get("slots", []):
            flat_items.append({
                "topic": topic_name,
                "topic_color": topic_color,
                "id": int(s["id"]),
                "sentence": s.get("sentence"),
                "slot": s.get("slot"),
                "color": s.get("color"),
            })

    # 2. 按 id 从小到大排序 —— 严格时间顺序
    flat_items.sort(key=lambda x: x["id"])

    segments = []
    current_topic = None
    current_topic_color = None
    current_slots = []

    def flush_segment():
        nonlocal current_topic, current_topic_color, current_slots
        if not current_topic or not current_slots:
            return
        
        # 段内按 id 再保险排一下，并可选做去重（按 sentence）
        best_by_slot = {}
        for s in current_slots:
            slot_name = s.get("slot")
            if not slot_name:
                continue
            if slot_name not in best_by_slot:
                best_by_slot[slot_name] = s
            else:
                # 如果当前这条的 id 更小，就替换
                if s["id"] < best_by_slot[slot_name]["id"]:
                    best_by_slot[slot_name] = s
                    
         # 段内按 id 再排一次
        uniq_slots = sorted(best_by_slot.values(), key=lambda x: x["id"])

        if uniq_slots:
            segments.append({
                "topic": current_topic,
                "slots": uniq_slots,
                "color": current_topic_color,
            })
        current_topic = None
        current_topic_color = None
        current_slots = []

    # 3. 沿时间轴扫描，topic 一变就切一段
    for item in flat_items:
        t = item["topic"]
        tc = item["topic_color"]
        slot = {
            "sentence": item["sentence"],
            "slot": item["slot"],
            "id": item["id"],
            "color": item["color"],
        }

        if current_topic is None:
            # 第一条
            current_topic = t
            current_topic_color = tc
            current_slots = [slot]
        else:
            if t == current_topic:
                # 同一个 topic，归到当前段
                current_slots.append(slot)
            else:
                # topic 发生切换，先收尾前一段，再开新段
                flush_segment()
                current_topic = t
                current_topic_color = tc
                current_slots = [slot]

    # 收最后一段
    flush_segment()
    return segments


def process_conversation(file_path):

    messages = parse_conversation(file_path)       # list[dict]: {id, role, content}
    lines = [f"[{m['id']}] ({m['role']}) {m['content'].strip()}" for m in messages if m.get('content')]
    full_text = "\n".join(lines)
    chunks = chunk_text(full_text, max_chars=40000)   # 每段约 1/3 模型上限
    all_results = []
    
    for i, chunk in enumerate(chunks, 1):
        print(f"🧠 第 {i}/{len(chunks)} 段抽取中...")
        # 生成 chunk 格式保持结构的对话列表
        chunk_messages = []
        id_counter = 1
        for line in chunk:
            parts = line.split('] (')
            if len(parts) == 2:
                id_part, content = parts
                role = content.split(") ")[0]
                text = content.split(") ")[1] if len(content.split(") ")) > 1 else ""
                chunk_messages.append({"id": id_counter, "role": role, "content": text.strip()})
                id_counter += 1
        # print("chunk_messages:", chunk_messages)
        result = Semantic_pre_scanning(chunk_messages)  
        print("result:", result)        
        all_results.extend(result)
    clear_results = Topic_cleaning(messages, all_results)
    print("clear_results:", clear_results)
    last_result = Topic_Allocation(messages, clear_results)
    print("last_result:", last_result)
    colored_results = assign_colors(last_result)   
    print("colored_results:", colored_results)
    segmented_results = segment_by_timeline(colored_results)
    with open(FINAL_PATH, "w", encoding="utf-8") as f:
        json.dump(segmented_results, f, ensure_ascii=False, indent=2)
    print(f"✅ 处理完成，结果已保存：{FINAL_PATH}")
    return segmented_results


    # print(f"🧩 共 {total} 条消息，准备从第 {last_id + 1} 条继续。")

    # # --- 初始化历史记录 ---
    # history_so_far = []

    # for msg in messages:
    #     id_counter = msg.get("id", 1)
    #     role = msg.get("role", "user")
    #     text = msg.get("content", "").strip()

    #     if id_counter <= last_id or not text:
    #                 history_so_far.append(msg)
    #                 continue

    #     try:
    #         print(f"🧠 正在处理第 {id_counter}/{total} 条消息（{role}）...")
    #         result = llm_extract_information_incremental(history_so_far,msg, existing_topics=merged_results_global)
    #         safe_result = safe_process_llm_result(result, role, id_counter)

    #         # 合并结果
    #         merged_results_global = merge_topics_timeline(merged_results_global + safe_result)

    #         # 分配颜色
    #         colored_results = assign_colors(merged_results_global)

    #         # 每处理一条自动保存
    #         save_checkpoint(merged_results_global, id_counter)

    #     except Exception as e:
    #         print(f"❌ 第 {id_counter} 条处理失败：{e}")
    #         save_checkpoint(merged_results_global, id_counter)
    #         continue  # 保持健壮性



    # # 保存最终文件
    # with open(FINAL_PATH, "w", encoding="utf-8") as f:
    #     json.dump(colored_results, f, ensure_ascii=False, indent=2)
    # print(f"✅ 处理完成，结果已保存：{FINAL_PATH}")

    # 删除中断点（可选）
    # os.remove(CHECKPOINT_PATH)

    


if __name__ == "__main__":
    file_path = "py/conversation_example/ChatGPT-DST copy.txt"
    final_data = process_conversation(file_path)
    # 生成之后的数据要转移到public目录下
    # 删掉最外层字典
