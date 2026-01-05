import itertools
import colorsys
import re
import ast
import json
from copy import deepcopy
# 自定义颜色调色板，深色系，每个元素是 (r,g,b)，范围 0~1
color_palette = [
    (0.12, 0.47, 0.91),  # 深蓝
    (1.00, 0.40, 0.05),  # 橙
    (0.17, 0.73, 0.17),  # 绿
    (0.94, 0.15, 0.16),  # 红
    (0.58, 0.40, 0.84),  # 紫
    (0.55, 0.34, 0.29),  # 褐
    (0.89, 0.47, 0.76),  # 粉
    (0.49, 0.49, 0.49),  # 灰
    (0.74, 0.74, 0.13),  # 黄绿
    (0.09, 0.75, 0.81),  # 青
    (0.36, 0.20, 0.70),  # 靛蓝
    (0.95, 0.77, 0.06),  # 金黄
    (0.10, 0.60, 0.50),  # 蓝绿
    (0.80, 0.25, 0.50),  # 洋红
    (0.70, 0.70, 0.70),  # 浅灰
    (0.30, 0.30, 0.30),  # 深灰
    (0.20, 0.50, 0.90),  # 浅蓝
    (0.90, 0.55, 0.10),  # 琥珀
    (0.40, 0.75, 0.25),  # 草绿
    (0.80, 0.10, 0.30),  # 酒红
]
# 生成颜色
def assign_colors(data):
    """
    给 topic 和 slots 添加颜色
    - topic 用深色
    - slots 用浅色（通过调亮 topic 颜色）
    """
    def lighten_color(color, factor=0.5):
        r, g, b = [int(x*255) for x in color[:3]]
        r = int(r + (255-r) * factor)
        g = int(g + (255-g) * factor)
        b = int(b + (255-b) * factor)
        return f'#{r:02X}{g:02X}{b:02X}'

    color_cycle = itertools.cycle(color_palette)
    topic_color_map = {}  # 新增：记录 topic -> 颜色的映射

    def process_item(item):
        """递归处理单个 topic 或 list"""
        if isinstance(item, dict):  
            topic_name = item.get("topic")

            if topic_name:
                # 如果 topic 已有颜色，直接取
                if topic_name in topic_color_map:
                    base_color = topic_color_map[topic_name]
                else:
                    # 否则分配新颜色，并存下来
                    base_color = next(color_cycle)
                    topic_color_map[topic_name] = base_color

                topic_color = '#%02X%02X%02X' % tuple(int(x * 255) for x in base_color[:3])
                slot_color = lighten_color(base_color, 0.65)

                item["color"] = topic_color
                if "slots" in item and isinstance(item["slots"], list):
                    for slot in item["slots"]:
                        if isinstance(slot, dict):
                            slot["color"] = slot_color
            return item

        elif isinstance(item, list):  
            # 如果是 list，就递归处理里面的元素
            return [process_item(sub) for sub in item]

        return item  # 其他类型，直接返回

    return process_item(data)

# 合并增量主题
def merge_topics_timeline(new_results):
    if not new_results:
        return []
    merged = []
    for item in new_results:
        if not merged:
            merged.append(item)
        else:
            last = merged[-1]
            if last["topic"] == item["topic"]:
                # 相邻且 topic 相同，合并 slots
                existing = {(s["slot"]) for s in last["slots"]}
                for slot in item.get("slots", []):
                    # 只有当slot和sentence都重复时才会跳过
                    key = (slot.get("slot", ""))
                    if key not in existing:
                        last["slots"].append(slot)
                        existing.add(key)
            else:
                # 不相邻，开新块
                merged.append(item)

    return merged

# 提取内容
def extract_json_content(text):
    """
    从文本中提取被 ```json 包裹的内容，如果没有就返回原文本。
    """
    pattern = r"```json(.*?)```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        # 提取中间内容并去掉首尾空白
        return match.group(1).strip()
    else:
        return text

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

def parse_meeting_conversation(file_path):
    """读取会议对话文本，生成消息列表"""
    messages = []
    current_id = None
    current_role = None
    content_lines = []

    with open(file_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.strip()

            # 空行直接跳过（但不立刻 flush，id/内容逻辑还是看下面）
            if not stripped:
                continue

            # 如果这一行是纯数字 -> 说明是一个新的 id
            if stripped.isdigit():
                # 先把上一个说话人收尾
                if current_id is not None and current_role and content_lines:
                    messages.append({
                        "id": current_id,
                        "role": current_role,
                        "content": "\n".join(content_lines).strip(),
                    })
                # 开启下一条
                current_id = int(stripped)
                current_role = None
                content_lines = []
                continue

            # 尝试匹配 [说话人]内容
            m = re.match(r'^\[(.+?)\](.*)$', stripped)
            if m:
                # 开启这个 id 对应的第一句
                current_role = m.group(1).strip() or "Unknown"
                first_text = m.group(2).lstrip()
                if first_text:
                  content_lines.append(first_text)
            else:
                # 没有中括号，则视为当前说话人的后续内容
                if current_id is not None:
                    content_lines.append(stripped)
                # 否则（连 id 都没有），直接忽略

    # 文件结束，把最后一条补上
    if current_id is not None and current_role and content_lines:
        messages.append({
            "id": current_id,
            "role": current_role,
            "content": "\n".join(content_lines).strip(),
        })

    return messages

def split_history_by_turns(history, max_turns=80):
    """
    history: [{id, role, content}, ...]
    按条数把对话切成多个小段，每段最多 max_turns 条。
    不改动原来的 id。
    """
    chunks = []
    cur = []
    for m in history:
        cur.append(m)
        if len(cur) >= max_turns:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks

def conver_to_json(data):
   
    # 1. 读入原始文本（Python 风格的 list/dict 字面量）
    with open("py/conversation_example/slots_raw.txt", "r", encoding="utf-8") as f:
        raw = f.read()

    # 2. 先当成 Python 表达式安全解析
    data = ast.literal_eval(raw)   # 得到 Python 对象（list / dict）

    # 3. 再导出为标准 JSON 字符串
    json_str = json.dumps(data, ensure_ascii=False, indent=2)

    # 4. 写入文件
    with open("py/conversation_example/slots.json", "w", encoding="utf-8") as f:
        f.write(json_str)
    print("转换完成，已写入 slots.json")
