import json
import itertools
import matplotlib.pyplot as plt
from LLM_Extraction import llm_extract_information, talk_to_chatbot
from BERT_Extraction import bertopic_extraction_information
# 读取对话文本文件
user_sentences = []
# with open("py/ChatGPT-DST.txt", "r", encoding="utf-8") as f:
#     for line in f:
#         line = line.strip()
#         if line.startswith("## Prompt:"):  # 只保留User开头的行
#            # 统一去掉前缀（可能是 User: 或 User：）
#             line = line.replace("## Prompt:", "").replace("## Prompt：", "").strip()
#             if line:  # 避免空行
#                 user_sentences.append(line)
# 保留下一行
with open("py/ChatGPT-DST.txt", "r", encoding="utf-8") as f:
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
# Step 2: 小模型提取主题
clustered = bertopic_extraction_information(user_sentences)
print("主题聚类结果：")
for cluster in clustered:
    print(cluster)

# Step 3: 逐个主题丢进大模型抽取
results = []
for cluster in clustered:
    content = json.dumps(cluster, ensure_ascii=False, indent=2)
    result = llm_extract_information(content)
    results.append(result)

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


def assign_colors(data):
    """
    给 domain 和 slots 添加颜色
    - domain 用深色
    - slots 用浅色（通过调亮 domain 颜色）
    """
    def lighten_color(color, factor=0.5):
        r, g, b = [int(x*255) for x in color[:3]]
        r = int(r + (255-r) * factor)
        g = int(g + (255-g) * factor)
        b = int(b + (255-b) * factor)
        return f'#{r:02X}{g:02X}{b:02X}'

    color_cycle = itertools.cycle(color_palette)

    def process_item(item):
        """递归处理单个 domain 或 list"""
        if isinstance(item, dict):  
            
            # domain 层
            base_color = next(color_cycle)
            # 大椭圆小椭圆颜色
            domain_color = '#%02X%02X%02X' % tuple(int(x * 255) for x in base_color[:3])
            slot_color = lighten_color(base_color, 0.65)

            item["color"] = domain_color
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

# Step 4: 给抽取结果加颜色
colored_results = assign_colors(results)
print("加颜色的抽取结果：")
print(colored_results)