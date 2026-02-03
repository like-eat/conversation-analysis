from collections import Counter
import itertools
import colorsys
import re
import ast
import json
from copy import deepcopy
from typing import Any, Dict, List
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

# ====== 工具：把对话切成窗口 ======
def build_conv_chunks(history, window_size=30, stride=30):
    """
    把整轮对话按 id 排序后，切成一段段 chunk，
    每段包含 window_size 条对话（可重叠，步长 stride）。
    每个 chunk 结构：{start_id, end_id, text}
    """
    # 先按 id 排序
    history_sorted = sorted(
        [m for m in history if isinstance(m, dict) and m.get("content")],
        key=lambda x: x.get("id", 0)
    )

    chunks = []
    n = len(history_sorted)
    if n == 0:
        return chunks

    idx = 0
    while idx < n:
        sub = history_sorted[idx: idx + window_size]
        if not sub:
            break
        text = "\n".join(
            f"[{m['id']}][{m['role']}]: {m['content'].strip()}"
            for m in sub if m.get("content")
        )
        chunks.append({
            "start_id": sub[0]["id"],
            "end_id": sub[-1]["id"],
            "text": text,
        })
        if idx + window_size >= n:
            break
        idx += stride

    return chunks

def dedup_slots_keep_first(segments: List[Dict[str, Any]], label_key: str = "slot") -> List[Dict[str, Any]]:
    """
    segments: [{"start_id":..,"end_id":..,"slot"/"topic_label":..,"confidence":..}, ...]
    label_key: 你的字段名，可能是 "slot" 或 "topic_label"

    规则：
    - 同名 label 只保留最先出现的那段
    - 后面重复段删除，但其 id 范围会合并到“前一个保留段”的 end_id 上，保证覆盖连续
    """
    if not segments:
        return []

    # 先按 start_id 排序，防止乱序
    segs = sorted(segments, key=lambda x: int(x.get("start_id", 0)))

    seen = set()
    kept: List[Dict[str, Any]] = []

    for seg in segs:
        label = (seg.get(label_key) or "").strip()
        if not label:
            # 没 label 的段：直接保留（或你也可以选择跳过）
            kept.append(seg)
            continue

        if label in seen:
            # 重复：删除，但把它的范围并到上一个 kept 段里（保证无空洞）
            if kept:
                kept[-1]["end_id"] = max(int(kept[-1]["end_id"]), int(seg["end_id"]))
            continue

        seen.add(label)
        kept.append(seg)

    # 可选：再强制修一下首尾相接（把间隙吃掉）
    for i in range(1, len(kept)):
        prev = kept[i - 1]
        cur = kept[i]
        prev_end = int(prev["end_id"])
        cur_start = int(cur["start_id"])
        if cur_start > prev_end + 1:
            # 中间有空洞：让 prev 覆盖到 cur_start-1
            prev["end_id"] = cur_start - 1
        elif cur_start <= prev_end:
            # 重叠：把 cur_start 推到 prev_end+1
            cur["start_id"] = prev_end + 1

    # 再做一次：去掉 start>end 的坏段（极少见，保险）
    kept = [s for s in kept if int(s["start_id"]) <= int(s["end_id"])]

    return kept

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

# ---------- 工具：从 history 里取某个 id 区间的文本 ----------
def slice_history(history: List[Dict[str, Any]], start_id: int, end_id: int) -> List[Dict[str, Any]]:
    out = []
    for m in history:
        if "id" not in m:
            continue
        try:
            mid = int(m["id"])
        except Exception:
            continue
        if start_id <= mid <= end_id:
            txt = (m.get("content") or "").strip()
            if txt:
                out.append({"id": mid, "role": (m.get("role") or "").strip(), "content": txt})
    out.sort(key=lambda x: x["id"])
    return out

def infer_source(messages_in_range: List[Dict[str, Any]]) -> str:
    # 优先：出现最多的 role
    roles = [m.get("role","").strip() for m in messages_in_range if (m.get("role") or "").strip()]
    if roles:
        return Counter(roles).most_common(1)[0][0]
    # 否则空
    return ""

def pack_context(messages_in_range: List[Dict[str, Any]], max_chars: int = 500) -> str:
    # 拼成短上下文，避免 prompt 太长
    lines = []
    for m in messages_in_range:
        rid = m["id"]
        role = m.get("role","")
        content = (m.get("content") or "").replace("\n", " ").strip()
        if role:
            lines.append(f"[{rid}][{role}]: {content}")
        else:
            lines.append(f"[{rid}]: {content}")
    s = "\n".join(lines)
    if len(s) > max_chars:
        s = s[:max_chars] + "…"
    return s

def parse_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y", "是", "对"):
        return True
    if s in ("false", "0", "no", "n", "否", "不", "不是"):
        return False
    return False

def parse_json_array_loose(raw: str):
    """更鲁棒：截取最外层 [] 再 json.loads"""
    if not raw:
        return []
    raw = raw.strip()
    l = raw.find("[")
    r = raw.rfind("]")
    if l != -1 and r != -1 and r > l:
        raw = raw[l:r+1]
    try:
        arr = json.loads(raw)
        return arr if isinstance(arr, list) else []
    except Exception:
        return []
    
def sort_history(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _id(m):
        try:
            return int(m.get("id", 0))
        except:
            return 0
    return sorted([m for m in history if isinstance(m, dict)], key=_id)

def pack_msgs(msgs: List[Dict[str, Any]], max_chars: int = 3000) -> str:
    lines = []
    total = 0
    for m in msgs:
        try:
            mid = int(m.get("id", 0))
        except:
            continue
        role = (m.get("role") or m.get("from") or m.get("source") or "unknown").strip()
        text = (m.get("content") or m.get("text") or "").replace("\n", " ").strip()
        if not text:
            continue
        line = f"[{mid}][{role}]: {text}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)

def slice_by_id(hist: List[Dict[str, Any]], start_id: int, end_id: int) -> List[Dict[str, Any]]:
    out = []
    for m in hist:
        try:
            mid = int(m.get("id", -1))
        except:
            continue
        if start_id <= mid <= end_id:
            if (m.get("content") or m.get("text") or "").strip():
                out.append(m)
    return out

def followup_after_id(hist: List[Dict[str, Any]], end_id: int, horizon: int = 40) -> List[Dict[str, Any]]:
    # 取 end_id 之后的 horizon 条“有内容”的消息
    out = []
    started = False
    for m in hist:
        try:
            mid = int(m.get("id", -1))
        except:
            continue
        if mid <= end_id:
            continue
        started = True
        if started:
            txt = (m.get("content") or m.get("text") or "").strip()
            if txt:
                out.append(m)
            if len(out) >= horizon:
                break
    return out

def median(nums: List[int]) -> float:
    if not nums:
        return 0.0
    nums = sorted(nums)
    n = len(nums)
    mid = n // 2
    if n % 2 == 1:
        return float(nums[mid])
    return 0.5 * (nums[mid - 1] + nums[mid])

def cluster_by_gap(xs: List[int], gap: float) -> List[List[int]]:
    # xs 已排序
    if not xs:
        return []
    segs = [[xs[0]]]
    for i in range(1, len(xs)):
        if xs[i] - xs[i - 1] > gap:
            segs.append([xs[i]])
        else:
            segs[-1].append(xs[i])
    return segs

def prune_isolated_slots_keep_multi_clusters(
    slots: List[Dict[str, Any]],
    min_pts: int = 2,          # 2: 删单点段；3: 删 1-2 点碎段
    min_gap_floor: int = 15,   # GAP 下限
    gap_multiplier: float = 2.0,
    use_start_id: bool = True,
    mark_only: bool = False,   # True: 不删，只标记 is_outlier
) -> List[Dict[str, Any]]:
    if not isinstance(slots, list) or not slots:
        return []

    # 取坐标（start_id 更合理）
    def get_x(s):
        if use_start_id and isinstance(s.get("start_id"), int):
            return s["start_id"]
        if isinstance(s.get("id"), int):
            return s["id"]
        return None

    items = [(get_x(s), s) for s in slots]
    items = [(x, s) for x, s in items if isinstance(x, int)]
    if not items:
        return [] if not mark_only else slots

    items.sort(key=lambda t: t[0])
    xs = [x for x, _ in items]

    gaps = [xs[i+1] - xs[i] for i in range(len(xs) - 1)]
    med = median(gaps)
    GAP = max(min_gap_floor, gap_multiplier * med)

    # 切段（用 x 序列）
    seg_xs = cluster_by_gap(xs, GAP)

    # 每段 x -> keep?
    keep_x = set()
    for seg in seg_xs:
        if len(seg) >= min_pts:
            keep_x.update(seg)

    if mark_only:
        # 标记 outlier
        out = []
        for s in slots:
            x = get_x(s)
            s2 = dict(s)
            s2["is_outlier"] = (x not in keep_x)
            out.append(s2)
        return out

    # 直接过滤
    out = []
    for s in slots:
        x = get_x(s)
        if x in keep_x:
            out.append(s)
    return out

def save_messages_as_txt(messages, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(f"{msg['id']}\n")
            f.write(f"[{msg['role']}]\n")
            f.write((msg.get("content") or "").rstrip() + "\n\n")  # 空一行分隔


if __name__ == "__main__":
    print("🤖 启动对话处理程序...")
    file_path = "py/conversation_example/meeting_talk.txt"
    out_path = "py/conversation_example/meeting_talk-clear.txt"

    messages = parse_meeting_conversation(file_path)  # 或 parse_meeting_conversation
    save_messages_as_txt(messages, out_path)
