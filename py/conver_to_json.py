import ast
import json

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
