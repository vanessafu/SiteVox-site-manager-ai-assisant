# SiteVox – AI Site Manager Assistant（AN 侧 Bauleiter）

把工地口述、照片、邮件、会议纪要变成 **带证据的** Bautagebuch、Soll-Ist 分析和 VOB/B 文书草稿。
UI 为德语，立场始终是承包商（Auftragnehmer）写给业主（Auftraggeber）。

> „Entwurf – keine Rechtsberatung, Prüfung durch Bauleitung/Unternehmen erforderlich.“

## 三条设计原则 → 代码位置

| 原则 | 实现 |
| --- | --- |
| LLM 只负责理解和写作 | 抽取 `sitevox/understand/extract.py`（Qwen3-4B），起草 `sitevox/drafting/composer.py`（Qwen3-8B，只写 Sachverhalt/Auswirkungen）。偏差、关键路径、期限、置信度全在 `sitevox/engine/` 和 `sitevox/confidence.py`，纯 Python，可复现 |
| 每条事实都有证据 | 每句带 `[E-xx]`；`sitevox/verify.py` 核对每个数字、日期、时间、公司/人名是否出现在证据中，找不到标红，**未确认前无法放行和导出** |
| AI 不发送任何文件 | 没有任何发送接口。放行只生成 DOCX/PDF 和 `.eml`（`X-Unsent: 1`，Outlook 打开即草稿）；Graph 只申请 `Mail.ReadWrite`，不申请 `Mail.Send`（`sitevox/export/outlook.py`）。"Versendet" 只能由 Bauleiter 手动标记 |

## 目录

```text
config/models.toml      模型配置（Whisper / Qwen3-4B / Qwen3-8B / Qwen3-VL / BGE-M3 / Docling）
config/rules.toml       确定性规则：告警阈值、子弹图颜色、天气阈值、置信度权重
config/baseline.yaml    项目主数据（AG、授权代表、合同号、班组/设备）
sitevox/                AI 核心包
  understand/           asr.py · vision.py · documents.py · email_ingest.py · extract.py
  engine/               schedule.py(CPM) · deviation.py(Soll-Ist/告警/影响链) · sphere.py(Risikosphäre)
                        deadlines.py · weather.py(Bright Sky/DWD) · timeline.py(Tagesverlauf)
  drafting/             composer.py + templates/*.j2（Betreff/Bezug/Vorbehalt 固定，法条只来自模板）
  confidence.py verify.py rag.py pipeline.py store.py(SQLite) llm.py(结构化输出+重试+Replay)
  export/               docx_export.py · pdf.py(LibreOffice) · outlook.py · privacy.py(人脸打码)
scripts/                make_demo_data.py · seed_demo.py · run_pipeline.py · build_index.py
                        serve_models.py · data/audio/sythesize_noise_data.py
backend/                FastAPI（main.py 路由，views.py 视图模型）
frontend/               Next.js 15 + Tailwind PWA：/p/[pid] 办公室视图，/m/[pid] 工地手机采集
data/knowledge/         VOB/B（现行版）与 BGB 摘录（RAG 法律库）
data/demo/BV-RIEM/      演示项目文档、输入（音频/照片/邮件）、模型 Replay-Fixtures
tests/                  pytest：CPM、风险归属矩阵、置信度、事实核对、HITL 放行流程
```

## 快速开始（Demo 模式，无需 GPU）

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/make_demo_data.py          # 加 --tts 用 macOS say 生成真实语音
.venv/bin/python scripts/seed_demo.py               # 把 20.11.2026 的 9 条采集逐条跑过流水线
.venv/bin/uvicorn backend.main:app --port 8000

cd frontend && npm install && npm run build && npm start    # http://localhost:3000
```

- 办公室视图：`http://localhost:3000/p/BV-RIEM`
- **手机（需要 HTTPS 才能录音/拍照）**：
  ```bash
  bash scripts/make_cert.sh                     # 生成含本机局域网 IP 的证书（有 mkcert 则为受信任证书）
  cd frontend && npm run build && HTTP_REDIRECT_PORT=3000 npm run start:https
  # 手机打开 https://<电脑IP>:3443/m/BV-RIEM，首次确认一次证书警告
  ```
  开发时可用 `npm run dev:https`。手机和电脑需在同一网络；eduroam 等网络常屏蔽设备互访，此时用手机热点。
- 测试：`.venv/bin/python -m pytest -q tests`

Demo 模式下 Whisper/Qwen 的输出来自 `data/demo/BV-RIEM/fixtures/`（Replay）；新的手机文字/语音走关键词启发式，或使用浏览器转写作为 hint。

## GPU 模式

```bash
pip install -r requirements-gpu.txt
python scripts/serve_models.py --run          # vLLM：Qwen3-4B-Instruct-2507 :8001，Qwen3-8B-AWQ :8002
SITEVOX_MODE=gpu python scripts/seed_demo.py  # 同样的输入，真实模型
SITEVOX_MODE=gpu uvicorn backend.main:app --port 8000
```

`config/models.toml` 里可切换 `engine = "llama_cpp"`（GGUF Q4）。注意：Qwen3-8B 是 dense 模型；想用 MoE 改成 `Qwen/Qwen3-30B-A3B-Instruct-2507`。

## Demo 剧本：„Ein Tag im Leben eines Bauleiters“（Fr 20.11.2026, BV Riem）

| 时间 | 采集 | 系统结果 |
| --- | --- | --- |
| 07:00 | 语音：14/16 人，Kolonne Müller 2 人病假 | Personalmangel → **AN**，只做内部预警，不发函 |
| 07:30 | 语音 + 照片：Achse C 配筋图（Index b）未到 | Planlieferverzug → **AG** → Behinderungsanzeige § 6 Abs. 1，计时开始 |
| 10:02 | 语音：挖掘机液压管爆裂 | Geräteausfall → **AN** → 只记 Bautagebuch（不会误起草 Behinderungsanzeige） |
| 11:02 | 邮件（建筑师）：追加 4 个 Kernbohrung DN150 | LV 中无此项 → Mehrkostenankündigung § 2 Abs. 6，**须执行前**；提示建筑师无授权 |
| 12:15 | 邮件（结构工程师）：图纸"voraussichtlich Montag" | 合并到 Planlieferverzug；引擎推算 Bewehrung +2 AT → Betonage → Wände EG 18.12. 代替 16.12.，**超出合同工期 2 AT**；影响天数置信度仅 0.59（"voraussichtlich"） |
| 13:00 | 语音：混凝土泵取消 | 时间轴上 Betonpumpe "geplant, nicht begonnen" |
| 16:30 | 语音：当日产量 | 子弹图：Aushub 59 %（红）、Bewehrung 81 %（黄）、Schalung 105 %（绿） |

审核编辑器中，起草的 Behinderungsanzeige 有一句"已于 16.11.2026 电话催告"——证据里找不到这个日期，被标红并阻止放行，直到 Bauleiter 填写依据并确认（写入 Audit-Log）。

## 编辑与删除

- 所有输入都可在界面中修改：项目主数据（点击仪表盘标题）、Bauzeitenplan 工序（新增/修改/删除、前置关系带环检测）、每日 Ist 产量、人员、事件（类型/原因/时间/受影响工序/阻塞至/设备时间轴）、采集（标题/摘要/转写文本，可选"重新分析"）。
- KPI、甘特、子弹图、预测、置信度不直接编辑，而是由修改后的输入重新计算。
- 用户上传的采集（语音、照片、笔记、邮件、文档）可删除：文件和由其派生的证据、产量、人员记录、事件一并清除；草稿信件重新核对。已放行/已发送信件中使用的证据禁止删除（举证）。所有修改和删除写入 Audit-Log。

## 合规要点

- **DSGVO**：Whisper/Qwen 本地运行；导出前自动人脸打码（OpenCV），照片附 Anlage 时带时间戳与 GPS。
- **免责声明**：界面页脚与导出文件页脚。
- **置信度**不使用 LLM 自报：证据数量 + WhisperX 词分 + 多次采样一致性 + 检索相关度 + 规则校验，阈值 0.8 / 0.5。
- VOB/B 文本为现行版（2016）摘录，生产使用前请对照官方文本。
