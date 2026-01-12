import json
import os
import re
from typing import Dict, List, Set, Callable
import jieba
from jieba import analyse
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from Methods import parse_meeting_conversation, parse_conversation

# STEP3_PATH = "py/conversation_example/TF-IDF/step3_topics_with_slots.json"
# STEP4_PATH = "py/conversation_example/TF-IDF/step4_slot_with_wordcloud.json"

STEP3_PATH = "py/conversation_example/TF-IDF/step3_topics_with_slots copy.json"
STEP4_PATH = "py/conversation_example/TF-IDF/step4_slot_with_wordcloud copy.json"

DEFAULT_STOPWORDS = set([
  "我们","你们","他们","然后","就是","其实","可能","大家","这个","那个","一个","一下","以及","因为","所以",
  "的话","感觉","觉得","比较","有点","非常","特别","真的","确实","反正","其实","基本","一直","现在","目前",
  "不是","没有","但是","而且","然后呢","对不对","行","吧","啊","嗯","哦","哈","哈哈","呃","嘛",
  "我要","我怕","我觉得","你觉得","你看","这条","这是","这样","那样","每次","不要","定成","可以"
])

FILLER_SUBSTR = [
  "这条","这是","这样","那样","的话","感觉","觉得","然后","就是",
  "我觉得","你觉得","我怕","我要","每次","不要","定成","对不对"
]

def good_token(w: str) -> bool:
    w = w.strip()
    if not w or w in DEFAULT_STOPWORDS:
        return False
    # 单字通常是虚词/噪声（可视情况放开）
    if len(w) <= 1:
        return False
    # 纯数字/符号
    if re.fullmatch(r"[\d\W_]+", w):
        return False
    # 太口语的高频字头（按需加）
    if w in {"这","那","就","还","又","都","很","挺","啊","嗯","哦","哈","呃"}:
        return False
    return True

# ----------------------------
# 基础清洗
# ----------------------------
def clean_text(s: str) -> str:
    s = (s or "").replace("\n", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s

# ----------------------------
# 1) 自动构建“人名/昵称”黑名单
# ----------------------------
def build_name_banlist(messages: List[dict], topics_with_slots: List[dict]) -> Set[str]:
    names = set()

    # history 里可能是 role / from / source
    for m in messages:
        for k in ("role", "from", "source"):
            v = (m.get(k) or "").strip()
            if v:
                names.add(v)

    # slots 里也有 source
    for t in topics_with_slots:
        for s in (t.get("slots") or []):
            v = (s.get("source") or "").strip()
            if v:
                names.add(v)

    # 扩展：把名字分词后也加入（避免 “浅井佑右” -> “浅井/佑右”漏掉）
    ban = set()
    for nm in names:
        ban.add(nm)
        for tok in jieba.lcut(nm):
            tok = tok.strip()
            if tok:
                ban.add(tok)

    # 额外：常见口头禅/称呼（可按你数据再加）
    ban.update({"老师", "同学", "主持人"})
    return ban

def make_is_good_phrase(stopwords: Set[str], name_ban: Set[str]) -> Callable[[str], bool]:
    def is_banned_phrase(p: str) -> bool:
        p = p.strip()
        if not p:
            return True
        if p in name_ban:
            return True
        # 严格一点：包含任何名字片段也禁（会更干净，但可能误杀）
        for nm in name_ban:
            if nm and len(nm) >= 2 and nm in p:
                return True
        return False

    def is_good_phrase(p: str) -> bool:
        def has_filler(p: str) -> bool:
            for t in FILLER_SUBSTR:
                if t in p:
                    return True
            return False

        p = p.strip()
        if len(p) < 2 or len(p) > 12:
            return False
        if p in stopwords:
            return False
        if re.fullmatch(r"[\d\W_]+", p):
            return False
        if re.search(r"[A-Za-z0-9_]", p):  # 过滤 yoyo / yo 之类
            return False
        if is_banned_phrase(p):
            return False
        if has_filler(p):
            return False
        return True

    return is_good_phrase

# ----------------------------
# 2) TF-IDF 全局模型
# ----------------------------
def fit_global_tfidf(corpus: List[str], stopwords: Set[str]) -> TfidfVectorizer:
    def jieba_tokenize(x: str):
        x = clean_text(x)
        return [w.strip() for w in jieba.lcut(x) if w.strip() and w not in stopwords]

    vec = TfidfVectorizer(tokenizer=jieba_tokenize, lowercase=False, min_df=1, max_df=0.98)
    vec.fit(corpus if corpus else [""])
    return vec

# ----------------------------
# 3) 候选：分词 + ngram
# ----------------------------
def extract_candidates_token_ngrams(text: str, is_good_phrase: Callable[[str], bool], stopwords: Set[str], max_ngram: int = 2) -> List[str]:
    text = clean_text(text)
    text = re.sub(r"[A-Za-z0-9_]+", " ", text)  # 去英文数字噪声

    toks = [w for w in jieba.lcut(text) if good_token(w)]

    # token 也要过滤人名/太短/符号
    toks = [w for w in toks if is_good_phrase(w)]

    cands = []
    L = len(toks)
    for n in range(1, max_ngram + 1):
        for i in range(0, L - n + 1):
            p = "".join(toks[i:i+n])
            if is_good_phrase(p):
                cands.append(p)

    # 去重保序
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out

# ----------------------------
# 4) TF-IDF / TextRank 打分 + 融合
# ----------------------------
def score_tfidf_candidates(vec: TfidfVectorizer, local_text: str, candidates: List[str], stopwords: Set[str]) -> Dict[str, float]:
    local_text = clean_text(local_text)
    X = vec.transform([local_text])
    vocab = vec.vocabulary_
    row = X.toarray()[0]

    def token_score(tok: str) -> float:
        idx = vocab.get(tok)
        return float(row[idx]) if idx is not None else 0.0

    scores = {}
    for c in candidates:
        toks = [t for t in jieba.lcut(c) if t.strip() and t not in stopwords]
        if not toks:
            continue
        s = sum(token_score(t) for t in toks)  # 或 np.mean(...)
        if s > 0:
            scores[c] = s
    return scores

def score_textrank(local_text: str, is_good_phrase: Callable[[str], bool], topk: int = 80) -> Dict[str, float]:
    local_text = clean_text(local_text)
    pairs = analyse.textrank(local_text, topK=topk, withWeight=True, allowPOS=("n","vn","v","ns","nt","nz"))
    scores = {}
    for w, s in pairs:
        w = (w or "").strip()
        if is_good_phrase(w):
            scores[w] = float(s)
    return scores

def norm(d: Dict[str, float]) -> Dict[str, float]:
    if not d:
        return {}
    vals = list(d.values())
    vmin, vmax = min(vals), max(vals)
    if abs(vmax - vmin) < 1e-12:
        return {k: 1.0 for k in d}
    return {k: (v - vmin) / (vmax - vmin) for k, v in d.items()}

def fuse_scores(a: Dict[str, float], b: Dict[str, float], alpha: float = 0.65) -> Dict[str, float]:
    keys = set(a) | set(b)
    if not keys:
        return {}
    A = norm(a)
    B = norm(b)
    return {k: alpha * A.get(k, 0.0) + (1 - alpha) * B.get(k, 0.0) for k in keys}

def extract_keywords_for_slot_stats(
    local_ctx: str,
    vec: TfidfVectorizer,
    is_good_phrase: Callable[[str], bool],
    stopwords: Set[str],
    k: int = 20,
    min_weight: float = 0.05,     # ✅ 过滤太低的
) -> List[Dict[str, float]]:
    cand_phrases = extract_candidates_token_ngrams(local_ctx, is_good_phrase, stopwords, max_ngram=2)
    tr = score_textrank(local_ctx, is_good_phrase, topk=120)

    candidates = cand_phrases + list(tr.keys())
    tfidf = score_tfidf_candidates(vec, local_ctx, candidates, stopwords)
    fused = fuse_scores(tfidf, tr, alpha=0.65)

    items = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    if not items:
        return []

    # 输出前先把分数压到 0~1（仅用于可视化）
    vmax = items[0][1]
    vmin = items[-1][1]
    denom = (vmax - vmin) if (vmax - vmin) > 1e-12 else 1.0

    out = []
    for w, s in items:
        ww = float((s - vmin) / denom)
        if ww < min_weight:
            continue
        out.append({"word": w, "weight": ww})
        if len(out) >= k:
            break
    return out

# ----------------------------
# 5) Step4 主流程（带 window_size 上下文）
# ----------------------------
def run_step4_slot_with_wordcloud(
    file_path: str,
    step3_path: str = STEP3_PATH,
    out_path: str = STEP4_PATH,
    window_size: int = 20,   # 前后各 window_size 句
    k_words: int = 20,       # 每个 slot 输出词数
):
    # messages = parse_meeting_conversation(file_path)
    messages = parse_conversation(file_path)

    with open(step3_path, "r", encoding="utf-8") as f:
        topics_with_slots = json.load(f)

    print("🧠 [Step4] extract_wordcloud(stats) 中...")

    # ✅ 先构建 NAME_BAN（必须在读完数据之后）
    name_ban = build_name_banlist(messages, topics_with_slots)
    is_good_phrase = make_is_good_phrase(DEFAULT_STOPWORDS, name_ban)

    # 全局语料建 TF-IDF
    corpus = [clean_text(m.get("content") or m.get("text") or "") for m in messages]
    corpus = [c for c in corpus if c]
    vec = fit_global_tfidf(corpus, DEFAULT_STOPWORDS)

    # id2idx，用于上下文窗口
    hist = sorted(messages, key=lambda m: int(m.get("id", 0)))
    id2idx = {int(m["id"]): i for i, m in enumerate(hist) if "id" in m}

    def build_local_ctx(center_id: int) -> str:
        if center_id not in id2idx:
            return ""
        c = id2idx[center_id]
        s = max(0, c - window_size)
        e = min(len(hist), c + window_size + 1)

        # ✅ 只拼接正文，别加 [id][role] 这种噪声
        lines = []
        for m in hist[s:e]:
            text = clean_text(m.get("content") or m.get("text") or "")
            if text:
                lines.append(text)
        return "\n".join(lines)

    miss_cnt = 0

    for topic_obj in topics_with_slots:
        slots = topic_obj.get("slots", [])
        if not isinstance(slots, list):
            continue

        for s in slots:
            if isinstance(s.get("wordcloud"), list) and len(s["wordcloud"]) > 0:
                continue

            try:
                sid = int(s.get("id"))
            except Exception:
                sid = None

            sentence = clean_text(s.get("sentence", ""))

            local_ctx = build_local_ctx(sid) if sid is not None else ""
            if not local_ctx:
                miss_cnt += 1
                local_ctx = sentence

            out = extract_keywords_for_slot_stats(
                local_ctx=local_ctx,
                vec=vec,
                is_good_phrase=is_good_phrase,
                stopwords=DEFAULT_STOPWORDS,
                k=k_words,
                min_weight=0.05,
            )
            s["wordcloud"] = out

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(topics_with_slots, f, ensure_ascii=False, indent=2)

    print(f"✅ [Step4] 完成，结果已保存：{out_path}")
    if miss_cnt > 0:
        print(f"⚠️ 有 {miss_cnt} 个 slot 的 id 没命中 history，已退回只用 sentence 抽词。")

if __name__ == "__main__":
    file_path = "py/conversation_example/ChatGPT-xinli.txt"
    run_step4_slot_with_wordcloud(
        file_path=file_path,
        step3_path=STEP3_PATH,
        out_path=STEP4_PATH,
        window_size=15,
        k_words=30,
    )
