import itertools
import colorsys
import re
import json
from copy import deepcopy
from LLM_Extraction import Semantic_pre_scanning, Topic_cleaning, Topic_Allocation
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

def pipeline_on_messages(messages):

    # 1. 如果没有 id，就顺手补一遍递增 id，保证后面能用 id 做时间轴
    normalized_messages = []
    for idx, m in enumerate(messages, start=1):
        normalized_messages.append({
            "id": m.get("id", idx),
            "role": m.get("role") or m.get("from") or "user",
            "content": (m.get("content") or m.get("text") or "").strip()
        })

    # 2. 这里你有两种选择：
    #    A) 和 process_conversation 一样，先拼成大文本 + chunk_text 再丢给 Semantic_pre_scanning
    #    B) 直接把 normalized_messages 丢给 Semantic_pre_scanning（对话不是特别长时更简单）
    #
    # 先给你一个简单版：直接对整段对话做 Semantic_pre_scanning
    # 如果你确实需要像 process_conversation 那样分 chunk，再照你上面的 chunk_text 那套改就行。

    # 🧠 第一步：语义预扫描（粗抽）
    pre_scan_result = Semantic_pre_scanning(normalized_messages)
    # pre_scan_result 结构应该就是你之前 all_results 的那一类 topic/slots 列表

    # 🧹 第二步：主题清洗 / 去噪 / 合并
    cleaned_topics = Topic_cleaning(normalized_messages, pre_scan_result)

    # 🎯 第三步：把 slot 重新对齐到具体的消息 / turn 上
    allocated_topics = Topic_Allocation(normalized_messages, cleaned_topics)

    # 🎨 第四步：给每个 topic 分配颜色
    colored_results = assign_colors(allocated_topics)

    # ⛰️ 第五步：按时间轴切段，给前端画带状图
    segmented_results = segment_by_timeline(colored_results)

    return segmented_results

