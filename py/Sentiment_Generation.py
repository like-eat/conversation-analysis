# -*- coding: utf-8 -*-
"""
情绪打分脚本：为每个数据集的每轮对话抽取情绪极性分数 sentiment（-1.0 ~ 1.0）

输出：public/<dataset>_sentiment.json，格式 [{"id": 1, "sentiment": 0.6}, ...]
（与 *_info_with_scores.json 同构，前端按 id 合并即可）

用法（在项目根目录执行）：
    python py/Sentiment_Generation.py                  # 跑全部数据集
    python py/Sentiment_Generation.py --dataset meeting
    python py/Sentiment_Generation.py --dataset xinli
    python py/Sentiment_Generation.py --dry-run        # 只解析源文件、打印分批，不调用 API
"""
import os
import sys
import json
import argparse
from typing import Dict, List

# Windows GBK 控制台兼容：避免 emoji/中文打印报错
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from LLM_Extraction import extract_sentiment
from Methods import parse_meeting_conversation, parse_conversation, build_conv_chunks

DATASETS = {
    "meeting": {
        # 会议/综艺转写格式：纯数字 id 行 + [说话人]内容
        "src": "py/conversation_example/meeting_talk.txt",
        "parser": "meeting",
        "out": "public/meeting_sentiment.json",
    },
    "xinli": {
        # ChatGPT 导出格式：## Prompt: / ## Response:
        "src": "py/conversation_example/ChatGPT-xinli.txt",
        "parser": "chatgpt",
        "out": "public/xinli_sentiment.json",
    },
}

PARSERS = {
    "meeting": parse_meeting_conversation,
    "chatgpt": parse_conversation,
}


def run_dataset(key: str, cfg: Dict, window: int = 30, dry_run: bool = False) -> List[Dict]:
    parser = PARSERS[cfg["parser"]]
    messages = parser(cfg["src"])
    messages = [m for m in messages if (m.get("content") or "").strip()]
    if not messages:
        print(f"⚠️ [{key}] 源文件未解析出消息：{cfg['src']}")
        return []

    chunks = build_conv_chunks(messages, window_size=window, stride=window)
    print(f"📦 [{key}] 共 {len(messages)} 条消息，按每批 {window} 条分为 {len(chunks)} 批")

    if dry_run:
        for i, ch in enumerate(chunks, 1):
            print(f"   批 {i}: id {ch['start_id']} ~ {ch['end_id']}")
        print(f"🔎 [{key}] dry-run 结束，未调用 API")
        return []

    scored: List[Dict] = []
    for i, ch in enumerate(chunks, 1):
        # 按 chunk 的 id 范围取回原始消息（与 run_step0 同一模式）
        chunk_msgs = [
            {"id": int(m["id"]), "role": m.get("role", ""), "content": (m.get("content") or "").strip()}
            for m in messages
            if ch["start_id"] <= int(m["id"]) <= ch["end_id"]
        ]
        if not chunk_msgs:
            continue
        print(f"🧠 [{key}] 第 {i}/{len(chunks)} 批打分中（id {ch['start_id']}~{ch['end_id']}，{len(chunk_msgs)} 条）...")
        scored.extend(extract_sentiment(chunk_msgs))

    # 按 id 去重 + 压缩为 [{id, sentiment}]
    best: Dict[int, float] = {}
    for m in scored:
        best[int(m["id"])] = float(m.get("sentiment", 0.0))
    result = [{"id": mid, "sentiment": best[mid]} for mid in sorted(best)]

    # 质检：分布统计（与可视化阈值一致：±0.15 为中性带）
    pos = sum(1 for r in result if r["sentiment"] > 0.15)
    neg = sum(1 for r in result if r["sentiment"] < -0.15)
    neu = len(result) - pos - neg
    mean_s = sum(r["sentiment"] for r in result) / max(1, len(result))
    print(f"📊 [{key}] 分布：积极 {pos} / 中性 {neu} / 消极 {neg}，均值 {mean_s:+.3f}")

    os.makedirs(os.path.dirname(cfg["out"]), exist_ok=True)
    with open(cfg["out"], "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"✅ [{key}] 已保存：{cfg['out']}（{len(result)} 条）")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="对话情绪极性打分")
    ap.add_argument("--dataset", choices=["meeting", "xinli", "all"], default="all")
    ap.add_argument("--window", type=int, default=30, help="每批发给 LLM 的消息条数")
    ap.add_argument("--dry-run", action="store_true", help="只解析源文件并打印分批，不调用 API")
    args = ap.parse_args()

    keys = list(DATASETS) if args.dataset == "all" else [args.dataset]
    for k in keys:
        run_dataset(k, DATASETS[k], window=args.window, dry_run=args.dry_run)
