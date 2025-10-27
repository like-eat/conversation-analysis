import itertools
import colorsys
import re
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

# 合并主题
# def merge_topics(results):
#     merged = {}
#     for item in results:
#         topic = item["topic"]
#         if topic not in merged:
#             merged[topic] = {
#                 "topic": topic,
#                 "slots": [],
#             }
#         merged[topic]["slots"].extend(item.get("slots", []))
#     return list(merged.values())

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
