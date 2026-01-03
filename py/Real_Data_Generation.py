import os

import json
from typing import Any, Dict, List
from LLM_Extraction import Score_turn_importance ,Semantic_pre_scanning, Topic_cleaning, Topic_Allocation,refine_slot_resolution
from Methods import assign_colors, parse_conversation, parse_meeting_conversation, split_history_by_turns

CHECKPOINT_PATH = "py/conversation_example/ChatGPT-xinli_result.json"
FINAL_PATH = "py/conversation_example/ChatGPT-xinli_processed.json"
FINAL_PATH_SCORE = "py/conversation_example/meeting_score.json"


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
                "sentiment": s.get("sentiment"),
                "source": s.get("source"),
                "is_question": s.get("is_question", False),
                "resolved": s.get("resolved", False),
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
            "sentiment": item["sentiment"],
            "source": item["source"],
            "is_question": item.get("is_question", False),
            "resolved": item.get("resolved", False),
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

def process_score(file_path):
    # 1) 解析原始对话：[{id, role, content}, ...]
    messages = parse_meeting_conversation(file_path)

    # 2) 按条数切成多个 chunk，例如每段 80 轮
    history_chunks = split_history_by_turns(messages, max_turns=80)

    scored_all = []
    for i, chunk in enumerate(history_chunks, 1):
        print(f"🧠 第 {i}/{len(history_chunks)} 段打分中，包含 {len(chunk)} 条对话...")

        # 3) 对每个 chunk 独立打分
        scored_chunk = Score_turn_importance(chunk)

        # 4) 拼回大列表（注意：chunk 里的 id 是原始 id，没有被改动）
        scored_all.extend(scored_chunk)

    # 5) 写入文件（scored_all 长度应该 == messages 长度）
    with open(FINAL_PATH_SCORE, "w", encoding="utf-8") as f:
        json.dump(scored_all, f, ensure_ascii=False, indent=2)

    print(f"✅ 处理完成，结果已保存：{FINAL_PATH_SCORE}")
    return scored_all



def process_conversation(file_path):
    # user和llm的对话模式
    messages = parse_conversation(file_path)       # list[dict]: {id, role, content}
    lines = []
    for m in messages:
        content = (m.get("content") or "").replace("\n", " ").strip()
        if not content:
            continue
        lines.append(f"[{m['id']}] ({m['role']}) {content}")

    full_text = "\n".join(lines)
    chunks = chunk_text(full_text, max_chars=40000)   # 每段约 1/3 模型上限
    all_results = []
    
    for i, chunk in enumerate(chunks, 1):
        print(f"🧠 第 {i}/{len(chunks)} 段抽取中...")
        # 生成 chunk 格式保持结构的对话列表
        chunk_messages = []
        for line in chunk:  # chunk 是一堆 "[id] (role) content" 的行
            try:
                # "[12] (user) hello world"
                id_part, rest = line.split("] (", 1)   # id_part = "[12"
                mid = int(id_part[1:])                 # 去掉左中括号，转为 int
                role, text = rest.split(") ", 1)       # role = "user", text = "hello world"
            except ValueError:
                # 行格式不对就跳过，避免炸
                continue
            chunk_messages.append({
                "id": mid,
                "role": role,
                "content": text.strip()
            })
        # print("chunk_messages:", chunk_messages)
        if not chunk_messages:
            print(f"⚠️ 第 {i} 段没有解析出有效对话，跳过 Semantic_pre_scanning")
            continue

        result = Semantic_pre_scanning(chunk_messages)  
        print("result:", result)        
        all_results.extend(result)

    clear_results = Topic_cleaning(messages, all_results)
    print("clear_results:", clear_results)
    last_result = Topic_Allocation(messages, clear_results)
    print("last_result:", last_result)
    refined_result = refine_slot_resolution(messages, last_result,max_slots=80)
    print("refined_result:", refined_result)
    colored_results = assign_colors(refined_result)   
    print("colored_results:", colored_results)
    segmented_results = segment_by_timeline(colored_results)

    with open(FINAL_PATH, "w", encoding="utf-8") as f:
        json.dump(segmented_results, f, ensure_ascii=False, indent=2)
    print(f"✅ 处理完成，结果已保存：{FINAL_PATH}")
    
    return segmented_results

STEP1_PATH = "py/conversation_example/test/step1_topics_raw.json"
STEP2_PATH = "py/conversation_example/test/step2_topics_clean.json"
STEP3_PATH = "py/conversation_example/test/step3_topics_with_slots.json"
FINAL_PATH = "py/conversation_example/test/final_result.json"

def run_step1_semantic_scan(file_path: str, out_path: str = STEP1_PATH):
    messages = parse_conversation(file_path)   # [{id, role, content}]
    lines = []
    for m in messages:
        content = (m.get("content") or "").replace("\n", " ").strip()
        if not content:
            continue
        lines.append(f"[{m['id']}] ({m['role']}) {content}")

    full_text = "\n".join(lines)
    chunks = chunk_text(full_text, max_chars=40000)

    all_results = []
    for i, chunk in enumerate(chunks, 1):
        print(f"🧠 [Step1] 第 {i}/{len(chunks)} 段抽取中...")
        chunk_messages = []
        for line in chunk:
            try:
                id_part, rest = line.split("] (", 1)
                mid = int(id_part[1:])
                role, text = rest.split(") ", 1)
            except ValueError:
                continue
            chunk_messages.append({
                "id": mid,
                "role": role,
                "content": text.strip()
            })

        if not chunk_messages:
            print(f"⚠️ [Step1] 第 {i} 段没有解析出有效对话，跳过 Semantic_pre_scanning")
            continue

        result = Semantic_pre_scanning(chunk_messages)
        print("  partial result:", result)
        all_results.extend(result)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"✅ [Step1] 语义预扫描完成，结果已保存：{out_path}")

def run_step2_topic_clean(file_path: str,
                          step1_path: str = STEP1_PATH,
                          out_path: str = STEP2_PATH):
    messages = parse_conversation(file_path)   # history: [{id, role, content}]

    with open(step1_path, "r", encoding="utf-8") as f:
        raw_topics = json.load(f)

    print(f"🧠 [Step2] Topic_cleaning 中，原始主题数：{len(raw_topics)}")

    clear_results = Topic_cleaning(messages, raw_topics)
    print(f"🧠 [Step2] 清洗后主题数：{len(clear_results)}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(clear_results, f, ensure_ascii=False, indent=2)
    print(f"✅ [Step2] 主题清洗完成，结果已保存：{out_path}")

def postprocess_topics_unique_and_prune(topics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    对 Topic_Allocation + refine_slot_resolution 的结果做两件事：
      1）全局去重：同一个 id 只保留在第一个出现的 topic 中；
      2）自动丢掉 slots 为空的 topic。

    输入结构示例：
    [
      {"topic": "...", "slots": [ {...}, {...} ]},
      {"topic": "...", "slots": [ {...} ]},
      ...
    ]
    """
    used_ids = set()
    new_topics: List[Dict[str, Any]] = []

    for t in topics:
        slots = t.get("slots") or []
        if not isinstance(slots, list):
            slots = []

        uniq_slots = []
        for s in slots:
            if not isinstance(s, dict):
                continue
            sid = s.get("id")
            if not isinstance(sid, int):
                # id 异常的直接丢掉
                continue
            if sid in used_ids:
                # 这个 id 已经被前面的 topic 占了，跳过
                continue
            used_ids.add(sid)
            uniq_slots.append(s)

        # 如果这个 topic 经过去重后还有 slot，就保留；否则丢掉
        if uniq_slots:
            t_new = dict(t)      # 拷一份，避免原地修改
            # 按 id 排个序，时间顺序更稳定
            t_new["slots"] = sorted(uniq_slots, key=lambda x: x["id"])
            new_topics.append(t_new)

    return new_topics


def run_step3_slots_and_resolution(file_path: str,
                                   step2_path: str = STEP2_PATH,
                                   out_path: str = STEP3_PATH):
    messages = parse_conversation(file_path)

    with open(step2_path, "r", encoding="utf-8") as f:
        cleaned_topics = json.load(f)

    print(f"🧠 [Step3] Topic_Allocation 中，topic 数：{len(cleaned_topics)}")
    topic_with_slots = Topic_Allocation(messages, cleaned_topics)
    print("🧠 [Step3] Topic_Allocation 完成")

    # 二阶段判断是否解决
    refined = refine_slot_resolution(messages, topic_with_slots, 
                                     max_slots=80)
    print("🧠 [Step3] refine_slot_resolution 完成")

    result = postprocess_topics_unique_and_prune(refined)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"✅ [Step3] slot + resolved 结果已保存：{out_path}")

def run_step4_segment_and_color(step3_path: str = STEP3_PATH,
                                out_path: str = FINAL_PATH):
    with open(step3_path, "r", encoding="utf-8") as f:
        topics_with_slots = json.load(f)

    print(f"🧠 [Step4] assign_colors 中...")
    colored_results = assign_colors(topics_with_slots)

    print(f"🧠 [Step4] segment_by_timeline 中...")
    segmented_results = segment_by_timeline(colored_results)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(segmented_results, f, ensure_ascii=False, indent=2)
    print(f"✅ [Step4] 最终结果已保存：{out_path}")

if __name__ == "__main__":
    print("🤖 启动对话处理程序...")
    file_path = "py/conversation_example/xinli-test.txt"
    # run_step1_semantic_scan(file_path)
    # run_step2_topic_clean(file_path=file_path, step1_path=STEP1_PATH,out_path=STEP2_PATH)
    # run_step3_slots_and_resolution(file_path=file_path,step2_path=STEP2_PATH,out_path=STEP3_PATH)
    # run_step4_segment_and_color(step3_path=STEP3_PATH, out_path=FINAL_PATH)
    
    # final_data = process_conversation(file_path)
    # final_data = process_score(file_path)

