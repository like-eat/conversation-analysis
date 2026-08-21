# 情绪可视化功能 · 实现计划

> 状态：数据脚本已就绪，待 LLM 额度恢复后执行。
> 本文档供下次会话直接按阶段实施，每阶段可独立验收。

## 0. 前置：生成情绪数据（用户执行，代码已完成）

```powershell
# 项目根目录，用 py（Python 3.12，已装 openai/numpy），不要用 PATH 上的 python
py py/Sentiment_Generation.py --dataset xinli     # 先跑小的（108 条 / 4 批），抽查质量
py py/Sentiment_Generation.py --dataset meeting   # 再跑大的（422 条 / 15 批）
```

产出：
- `public/xinli_sentiment.json`、`public/meeting_sentiment.json`
- 格式：`[{"id": 1, "sentiment": 0.6}, ...]`（与 `*_info_with_scores.json` 同构）
- 分数约定：**-1.0（消极）~ +1.0（积极）**，阈值 `>0.15 积极 / ±0.15 内中性 / <-0.15 消极`

已完成的代码（本次会话已写入并验证过 API 链路）：
- `py/LLM_Extraction.py` → 新增 `extract_sentiment(history)`（gpt-5.2，同 `Score_turn_importance` 模式）；`import faiss` 改为可选
- `py/Sentiment_Generation.py` → 打分脚本（`--dataset/--window/--dry-run`）

验收：抽查 json 中 10 条，分数与语境是否吻合；脚本打印的分布统计合理（不应全部 0.0，否则说明某批解析失败需重跑）。

---

## 1. 前端数据接入（改动最小，先行）

| 文件 | 改动 |
|---|---|
| `src/types/index.ts` | `Slot` 和 `Point` 增加 `sentiment?: number` |
| `src/utils/Methods.ts` `extractPointsAndTopics`（L485） | 增加第 4 个可选参数 `sentiMap?: Map<number, number>`；参照 L511 `info_score` 的合并方式，写入 `sentiment: sentiMap?.get(s.id) ?? 0` |
| `src/components/CapsuleUI.vue` `DATASETS`（L146） | 每个数据集增加 `sentiUrl: '/meeting_sentiment.json'` / `'/xinli_sentiment.json'` |
| `CapsuleUI.vue` `loadAndDraw`（L228） | 仿照 scoreUrl 的 fetch，建 `turnSentimentMap` 并传入 `extractPointsAndTopics`；文件不存在时 catch 降级（sentiment 全 0），保证没跑数据也能正常显示 |
| 实时数据 watch（L1419） | 暂不接入情绪，传空 map 即可 |

验收：`npm run dev` 后，在 SpeakerDashboard 里 `console.log` 抽查 point.sentiment 有值；切换数据集无报错。

---

## 2. SpeakerDashboard：情绪分布条形图 + 环图增强

文件：`src/components/SpeakerDashboard.vue`

**2a. 右侧"待开发"占位 → 情绪分布发散条形图**
- 数据：按发言人聚合当前 `activeTopics` 范围内的 points（未选主题时 = 全场）
- 每人一条：左红（neg%）｜中灰（neu%）｜右绿（pos%），阈值 ±0.15
- 颜色：`#e57373 / #c7c7c7 / #4caf50`（情绪专属发散色，不与主题/发言人分类色冲突）
- 参考设计稿 `design-mockup.html` 右下角

**2b. 占比环图两个增强**
- 未选中主题时默认显示**全场**发言占比（现在只显示"点击上方主题查看发言占比"占位）
- 点击环图扇区 → emit 给 CapsuleUI 设置 `activeSpeakerKey`（复用现有发言人过滤链路）

验收：不点主题时右侧也有内容；选中"婚姻与家庭生育"后两个图联动更新；点扇区后河流只剩该发言人线。

---

## 3. 情绪窄带组件（核心新增）

新建 `src/components/SentimentLane.vue`，插入 `CapsuleUI.vue` 模板中河流与 `<SpeakerDashboard>` 之间（右侧布局：河流 → 窄带 → 仪表盘）。

- Props：`allPoints`（含 sentiment）、`speakers`、`speakerColorMap`、`xDomain`（globalMinTurn/globalMaxTurn，从 CapsuleUI 传入，与河流 x 轴对齐）
- 渲染（D3）：每位发言人一条 lane
  - 点 = 单条消息原始 sentiment；线 = 滑动平均（窗口 ~5 轮）平滑趋势
  - 发散渐变填充（上绿下红，中线虚线 y=0）
- **可折叠，默认收起**为 24px 标题栏（"情绪趋势（按发言人）"），点击展开
- 交互：hover 显示轮次+分数 tooltip；点击某点 → `FileStore.selectedSlotId = id`（复用现有通道，左侧原文滚动定位）
- 设计稿参照 `design-mockup.html` 第③层

验收：展开后三条 lane 与河流时间轴对齐；点情绪点左侧原文滚动；折叠后仪表盘自动补上空间。

---

## 4. DialogBox：聊天气泡情绪色条

文件：`src/components/DialogBox.vue`（该组件已有 `datasetKey` prop，自行解析 `/meeting_talk.txt`、`/xinli_talk.md`）

- 按 datasetKey 额外 fetch 对应 `*_sentiment.json`，建 `id → sentiment` map
- 气泡左侧（自己的消息右侧）渲染 4px 圆角色条：绿/灰/红
- 弱编码，不抢戏；fetch 失败时不渲染色条（静默降级）
- 聊天气泡头部或图例处加一行小字说明"色条=情绪"

验收：切换数据集后色条随之切换；无 sentiment 文件时界面与现状一致。

---

## 5. 验收总清单

- [ ] `py py/Sentiment_Generation.py` 两个数据集跑完，json 抽查合理
- [ ] 前端 `npm run dev` 无控制台报错
- [ ] 环图默认全场占比；选中主题后环图+条形图联动
- [ ] 情绪窄带可折叠、与河流时间轴对齐、点击定位原文
- [ ] 气泡色条随数据集切换正确渲染
- [ ] 删掉/无 sentiment json 时全系统静默降级不崩

## 6. 后续更大改动（视图重构，已单列计划）

河流 LOD 标签分级（段级水平标签替代逐点斜排标签）、主题片段细节带（focus+context）、brush 导航条、双向联动游标、词云气泡搬家、工具栏修复——见 **`VIEW_PLAN.md`**（阶段 0–6）与 `design-mockup.html` 设计稿。

整合点：视图重构的阶段 6（布局整合）实施时，把本计划阶段 3 的情绪窄带插入"细节带"与"统计面板"之间。
