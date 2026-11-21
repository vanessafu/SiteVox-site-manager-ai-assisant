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
                        gaeb_io.py(GAEB 导入/导出) · ocr.py(CPU OCR) · imap_mail.py(IMAP 邮箱)
  mail_accounts.py      项目绑定的邮箱账号：添加/测试/同步/解绑
  engine/               schedule.py(CPM) · deviation.py(Soll-Ist/告警/影响链) · sphere.py(Risikosphäre)
                        deadlines.py · weather.py(Bright Sky/DWD) · timeline.py(Tagesverlauf)
  drafting/             composer.py + templates/*.j2（Betreff/Bezug/Vorbehalt 固定，法条只来自模板）
  confidence.py verify.py rag.py pipeline.py store.py(SQLite) llm.py(结构化输出+重试+Replay)
  export/               docx_export.py · pdf.py(LibreOffice) · outlook.py · privacy.py(人脸打码)
scripts/                make_demo_data.py · seed_demo.py · run_pipeline.py · build_index.py
                        serve_models.py · make_cert.sh / make_cert.py(HTTPS 证书) · data/audio/*
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
  开发时可用 `npm run dev:https`。手机和电脑需在同一网络；eduroam 等网络常屏蔽设备互访，此时用手机热点（IP 变了要重新生成证书）。
  **Windows**（没有 bash/openssl/mkcert）：
  ```powershell
  .venv\Scripts\pip install cryptography
  .venv\Scripts\python scripts\make_cert.py      # 同样写到 frontend\certs\，可追加额外 IP/主机名作为参数
  cd frontend; npm run build; $env:HTTP_REDIRECT_PORT="3000"; npm run start:https
  ```
- 测试：`.venv/bin/python -m pytest -q tests`（Windows：设置 `PYTHONUTF8=1`；用户目录含中文时加 `--basetemp=<ASCII 路径>`，否则 OpenCV 读不了临时文件）

- 日报导出：`/api/projects/<pid>/daily-report?fmt=pdf|docx|json`（PDF 由 reportlab 生成，无需 LibreOffice）

### ASR 测试数据（语音 + 工地噪声）

```bash
python scripts/data/audio/download_data.py          # Windows 可双击 scripts\data\audio\download_data.bat
# → data/raw/speech/<语言>/  data/raw/noise/<来源>/  data/raw/speech_noisy/  transcripts.csv  README_SOURCES.md
python scripts/data/audio/sythesize_noise_data.py --speech data/raw/speech/pl --noise data/raw/noise --out data/asr_eval/noisy_pl
```

`data/raw/` 不入库（部分数据为 CC BY-NC / 非商用许可）。

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

## 知识库、GAEB、邮箱、证据视图

**Wissensbasis（`/p/<pid>/vertrag`，原 "Vertrag / LV"）**
- 法律依据 + 项目文档（合同、LV、Planlieferliste、Protokoll…），全文检索（BM25；GPU 模式加 BGE-M3 + Rerank）。
- 上传 PDF / DOCX / 图片 / GAEB。没有 Docling（Demo 模式）时走轻量解析 `documents._light`：PDF 文字层用 `pypdf`，Word 用 `python-docx`，图片和扫描页用 RapidOCR（CPU，PP-OCRv5 latin，支持德语变音；首次运行从 modelscope.cn 下载约 15 MB 模型；`SITEVOX_OCR=0` 可关闭）。

**GAEB（`sitevox/understand/gaeb_io.py`，库 [`gaeb`](https://pypi.org/project/gaeb/)，MIT）**
- 导入：GAEB DA XML 2.x–3.3（`.x81`–`.x89`）、GAEB 2000（`.p8x`）、GAEB 90（`.d8x`）→ LV 文档（每个标题一页、`Pos. | Kurztext | Menge | Einheit | EP` 表格、结构化 `lv_items`），自动 `kind = "lv"`，因此 "LV 中无此项" 的检查（`rag.lv_contains`）也能用于文件名不含 "LV" 的 GAEB 文件。
- 导出：任何含 LV 表格（Pos./Kurztext/Menge/Einheit）的项目文档 → GAEB DA XML 3.3，阶段 X81/X83/X84/X86：`GET /api/documents/<doc_id>/gaeb?phase=83`；界面在文档视图右上角。
- 注意：`gaeb` 写出时标题 RNoPart 固定 2 位、位置 4 位，所以 OZ 被规范成 2(+2 每层)+4，例如 `03.010` → `03.0010`。库未附带官方 XSD，导出文件尚未做 schema 校验，也还没在 AVA 软件里实测。

**邮箱绑定（`/p/<pid>/postfach` → "Postfach verbinden"）**
- IMAP：Gmail、GMX、WEB.DE、T-Online、IONOS、自定义服务器；Microsoft 365/Outlook 只允许 OAuth，暂不可选（计划走 Graph）。
- 添加时先测试登录；同步只读（`BODY.PEEK[]`，不标已读、不删除），按 Message-ID 去重，默认只导入能归到本项目的邮件（合同号、项目名、已知发件人），然后走正常的 E-Mail-Erfassung。
- **密码不落盘**，只在后端进程内存里；后端重启后需重新输入（界面会提示）。账号配置（无密码）存在项目文档 `mail_accounts`。
- 接口：`GET /api/mail-providers`，`GET|POST /api/projects/<pid>/mail-accounts`，`POST …/<aid>/unlock`，`POST …/<aid>/sync`，`DELETE …/<aid>`。

**证据按来源显示（`GET /api/evidence-sources?ids=…`，`backend/views.py: source_key / evidence_sources`）**
- 一条语音、一张照片、一封邮件、一份文档只出现一次，其中所有被引用的位置一起高亮：语音 = 转写中的时间段（点击从该处播放），照片 = 原图上的 bbox（AI 观察与裁剪图归到原图），文本 = 引用句子。
- 选中某个 `[E-xx]` 时该处深色高亮并滚动到位。`[E-xx]` 编号本身不变（LLM 起草与 `verify.py` 仍按单条证据工作），分组只发生在显示层。
- 前端组件：`EvidenceSources` / `SourceCard`（`frontend/components/EvidenceViewer.tsx`），用于函件页、事件页、侧边抽屉、Erfassungen。旧的 `EvidenceCard` 已移除。

## 合并说明（frontend_develop → main）

- **依赖**：`pip install -r requirements.txt`（新增 `pypdf`、`rapidocr`、`onnxruntime`、`gaeb`，在 "Dateiverarbeitung" 一组）。合并后前端请删除 `frontend/.next` 再 `npm run build`。
- **ASR**：试验过的"项目词表喂给 Whisper"已整体移除（识别本身还不准，从识别结果里加关键词没有意义）。`asr.py` 回到按语言的固定 `initial_prompt` + 配置里的 `hotwords`。同时修复了 main 合并（`41fa4c8`）遗留的两个崩溃：faster-whisper 路径的 `NameError: vocab`、mlx 路径参数个数不对（有回归测试）。`asr_server.py` 接口与 main 相同。
- **Next.js 15.5 的一个 bug**：客户端页面模块若被分到确定性模块 ID `0`，会从 React Client Manifest 中漏掉（`flight-manifest-plugin` 里 `if (concatenatedModId)`），页面 500：*Could not find the module … in the React Client Manifest*。`frontend/next.config.mjs` 里对浏览器构建改用 `moduleIds = "named"`，升级 Next 修复后可去掉。
- **容易冲突的文件**：`sitevox/understand/asr.py`、`sitevox/pipeline.py`、`backend/main.py`、`backend/views.py`、`frontend/lib/i18n.tsx`、`frontend/components/EvidenceViewer.tsx`、`tests/test_core.py`。i18n 冲突一般只是两边都加了词条，保留双方即可（注意不能有重复键，`npx tsc --noEmit` 会报）。
- `data/demo/` 下的 `.eml` 和 `Bauzeitenplan.xlsx` 每次跑测试都会被 `make_demo_data.py` 重写，无实际变化，不要提交。
- 测试：44 个，全部通过。

## 合规要点

- **DSGVO**：Whisper/Qwen 本地运行；导出前自动人脸打码（OpenCV），照片附 Anlage 时带时间戳与 GPS。
- **免责声明**：界面页脚与导出文件页脚。
- **置信度**不使用 LLM 自报：证据数量 + WhisperX 词分 + 多次采样一致性 + 检索相关度 + 规则校验，阈值 0.8 / 0.5。
- VOB/B 文本为现行版（2016）摘录，生产使用前请对照官方文本。
