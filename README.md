# SiteVox – AI Site Manager Assistant（AN 侧 Bauleiter）

把工地口述、照片、邮件、会议纪要变成 **带证据的** Bautagebuch、Soll-Ist 分析和 VOB/B 文书草稿。
UI 为德语，立场始终是承包商（Auftragnehmer）写给业主（Auftraggeber）。

> „Entwurf – keine Rechtsberatung, Prüfung durch Bauleitung/Unternehmen erforderlich.“

## 三条设计原则 → 代码位置

| 原则 | 实现 |
| --- | --- |
| LLM 只负责理解和写作 | 抽取 `sitevox/understand/extract.py`（Qwen3-4B），起草 `sitevox/drafting/composer.py`（Qwen3-8B，只写 Sachverhalt/Auswirkungen）。偏差、关键路径、期限、置信度全在 `sitevox/engine/` 和 `sitevox/confidence.py`，纯 Python，可复现 |
| 每条事实都有证据 | 每句带 `[E-xx]`；`sitevox/verify.py` 核对每个数字、日期、时间、公司/人名是否出现在证据中，找不到标红，**未确认前无法放行和导出** |
| AI 不自行发送 | 放行（Freigeben）本身**从不发送**，只生成 DOCX/PDF 和 `.eml` 草稿（`X-Unsent: 1`）。只有 Bauleiter 在发送对话框中核对收件人并点“Jetzt senden”后，才会通过绑定的邮箱以 SMTP 发出（`POST /api/letters/<lid>/send-email` 必须带 `confirm: true`，`sitevox/export/smtp_send.py`）。挂号原件提醒保留，直到手动标记 |

## 目录

```text
config/models.toml      模型配置（Whisper / Qwen3-4B / Qwen3-8B / Qwen3-VL / BGE-M3 / Docling）
config/rules.toml       确定性规则：告警阈值、子弹图颜色、天气阈值、置信度权重
config/baseline.yaml    项目主数据（AG、授权代表、合同号、班组/设备）
sitevox/                AI 核心包
  understand/           asr.py · vision.py · documents.py · email_ingest.py · extract.py
                        gaeb_io.py(GAEB 导入/导出) · ocr.py(CPU OCR) · imap_mail.py(IMAP 邮箱)
                        contract_info.py(合同关键信息) · contacts.py(联系人 / 业主收件邮箱)
  mail_accounts.py      项目绑定的邮箱账号：添加/测试/同步/解绑，每 5 分钟自动拉取
  engine/               schedule.py(CPM) · deviation.py(Soll-Ist/告警/影响链) · sphere.py(Risikosphäre)
                        deadlines.py · weather.py(Bright Sky/DWD) · timeline.py(Tagesverlauf)
  drafting/             composer.py + templates/*.j2（Betreff/Bezug/Vorbehalt 固定，法条只来自模板）
  confidence.py verify.py rag.py pipeline.py store.py(SQLite) llm.py(结构化输出+重试+Replay)
  export/               docx_export.py · pdf.py(LibreOffice) · outlook.py · privacy.py(人脸打码)
                        daily_report.py · report_pdf.py · report_docx.py(Bautagesbericht) · smtp_send.py(发送)
scripts/                make_demo_data.py · seed_demo.py · run_pipeline.py · build_index.py
                        serve_models.py · make_cert.sh / make_cert.py(HTTPS 证书) · data/audio/*
backend/                FastAPI（main.py 路由，views.py 视图模型）
frontend/               Next.js 15 + Tailwind PWA：/p/[pid] 办公室视图，/m/[pid] 工地手机采集
data/knowledge/         VOB/B（现行版）与 BGB 摘录（RAG 法律库，初始内容；界面上传的新版本存 data/_legal/）
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

- 所有输入都可在界面中修改：项目主数据（**Projekt bearbeiten** 页面 `/p/<pid>/projekt`：点 dashboard 上的项目名，或左侧项目名旁的 ✎）、日报中的人员和设备行（直接在 dashboard 表格中修改，PDF 同步生效）、Bauzeitenplan 工序（独立页面已移除，目前通过 Excel 导入或 `/api/projects/<pid>/activities` 修改）、每日 Ist 产量、人员、事件（类型/原因/时间/受影响工序/阻塞至/设备时间轴）、采集（标题/摘要/转写文本，可选"重新分析"）。
- KPI、甘特、子弹图、预测、置信度不直接编辑，而是由修改后的输入重新计算。
- 用户上传的采集（语音、照片、笔记、邮件、文档）可删除：文件和由其派生的证据、产量、人员记录、事件一并清除；草稿信件重新核对。已放行/已发送信件中使用的证据禁止删除（举证）。所有修改和删除写入 Audit-Log。

## 项目、Dashboard 与 History

**项目增删改**
- **新建**：左侧 PROJECTS 旁边的 **+**，可以填写：
  - 简称（必填）
  - 工程名称、工地地址、**坐标**（用于自动天气）
  - 合同号、合同日期
  - 业主、授权代表、**业主邮箱**、业主地址

  同时可以**拖入资料**：合同、LV（含 GAEB）、Bauzeitenplan（Excel）、Planlieferliste、Protokoll。系统按文件名猜测类型，可以手动修改。Bauzeitenplan 直接导入为工序（`POST /api/projects/<pid>/schedule-import`），其他文档进入 Wissensbasis；合同里的关键信息会自动填入空字段（见下文）。
- **修改**：`/p/<pid>/projekt`，顶部显示“Aus dem Vertrag erkannt”的建议，下方是完整的主数据表单。
- **删除**：鼠标移到左侧项目名上，点垃圾桶图标并确认。删除数据库中该项目的全部数据（采集、事件、文书、邮箱绑定等），不可撤销；`data/<项目>/` 下的原始文件保留，Audit-Log 保留。
- 接口：
  - 新建：`POST /api/projects`
  - 删除：`DELETE /api/projects/<pid>`
  - 主数据：`GET|PUT /api/projects/<pid>/master`（`coords: "48.13, 11.69"`、`client.email`、`client.phone`）

**Dashboard = 当天的 Bautagesbericht**
- 内容和 PDF/DOCX 一致，都来自 `daily_report.build`（`GET /api/projects/<pid>/report`）。右上角用大字显示日期（星期、日、月、年）和日报编号。
- 人员、设备的行可以直接修改，修改结果存在 `report_rows` 表，同时作用于 PDF。
- 独立的 Bauzeitenplan / Schedule 页面已经删除。工序数据仍用于项目概览和预测，通过新建项目时导入 Excel 或接口维护。

**History（左侧栏最下方）**
- `/p/<pid>/verlauf` 按日期列出所有有内容的日报，最新在上：
  - 每天显示记录数、照片数、事件数、未处理文书、天气
  - 每天可以单独下载 PDF（`GET /api/projects/<pid>/days`）
- 点某一天打开**当天完整的 dashboard**（`/p/<pid>/verlauf/<日期>`），不只是 PDF。可以切换前一天、后一天，或回到今天。历史日期的人员和设备行也可以修改。

## 知识库、GAEB、邮箱、证据视图

**Wissensbasis（`/p/<pid>/vertrag`，原 "Vertrag / LV"）**
- 法律依据 + 项目文档（合同、LV、Planlieferliste、Protokoll…），全文检索（BM25；GPU 模式加 BGE-M3 + Rerank）。
- 上传 PDF / DOCX / 图片 / GAEB。没有 Docling（Demo 模式）时走轻量解析 `documents._light`：PDF 文字层用 `pypdf`，Word 用 `python-docx`，图片和扫描页用 RapidOCR（CPU，PP-OCRv5 latin，支持德语变音；首次运行从 modelscope.cn 下载约 15 MB 模型；`SITEVOX_OCR=0` 可关闭）。

**合同关键信息提取（`sitevox/understand/contract_info.py`，规则提取，不需要 GPU）**
- 上传类型为“Vertrag”的文档后，自动识别以下信息，每一项都记录出处（原句和页码）：
  - 合同号、合同日期
  - 工程名称和工地地址
  - 业主（AG）公司名称和地址
  - **业主授权代表**（姓名、职务、邮箱、电话）
  - 合同依据（VOB/B）
  - 合同工期节点
  - 明确“nicht bevollmächtigt”（无授权）的参与方
- **只填空字段**：项目主数据里为空或“N. N.”的字段会自动填入。施工经理已经填写的内容不会被覆盖。
- 与现有数据不一致的值，在 dashboard → 点项目名 → “Aus dem Vertrag erkannt” 里列为建议，可以逐项或全部“Übernehmen”。
- 接口：`GET /api/projects/<pid>/contract-info`，`POST …/contract-info/apply {keys}`

**联系人（`/p/<pid>/kontakte`，`contacts.all_contacts`）**
- 从项目主数据、合同、全部文档和邮件（发件人、收件人、抄送、正文）中提取人员和公司：姓名、公司、职务、邮箱、电话、地址、**授权状态**（bevollmächtigt / nicht bevollmächtigt），每条都附出处。
- 不包含自己公司的联系人。同一个人的多条记录会合并，例如合同里的 Wagner 和邮件里的 t.wagner@… 合并为一个联系人。
- 联系人可以手动新增、修改、删除。修改优先于自动识别；删除自动识别的联系人只会将其隐藏。
- **发送对话框**：“An”下方列出所有带邮箱的联系人，点一下填入收件人，点“Cc”加入抄送。如果选中的是合同中注明无授权的参与方，会显示红色警告。
- 新建项目时可以填写 **E-Mail AG**。这个地址算作施工经理手动填写的数据：资料中找不到业主邮箱时，Schreiben 会把它作为收件人建议，标黄提示核对；资料中能找到时，以资料为准。

**法律条文可更新（Wissensbasis → Rechtsgrundlagen）**
- **+ Hinzufügen**：新增一部法律文本（PDF 需带文字层、DOCX、TXT、MD），填标题和“Fassung / Stand”，对所有项目生效。
- 条目上的 **📄+（Neue Fassung hochladen）**：上传新版本。旧版本**不会删除**，而是归档：已经发出的 Schreiben 仍然可以引用旧版本，新的 Schreiben 和检索只用新版本。
- **归档 / 恢复**：归档后的条目不再参与检索，列在“Frühere / archivierte Fassungen”下，可以恢复。法律条文不能硬删除。
- 没有 Markdown 标题的上传文本，会在每个“§ n”前自动切段，检索可以精确到条。文件存放在 `data/_legal/`。所有操作写入 Audit-Log。
- 接口：
  - 新增或上传新版本：`POST /api/legal`（multipart：`file`、`title`、`version`、`replaces`）
  - 归档 / 恢复：`POST /api/legal/<doc_id>/archive`
- VOB/B 是收费标准（DIN 1961），无法自动下载，需要手动上传购买的版本。BGB 可以从 gesetze-im-internet.de 获取。

**天气（`sitevox/engine/weather.py`，自动获取，无需手工录入）**
- 数据来自 **Bright Sky**（`https://api.brightsky.dev/weather`）。这是免费、无需 API Key 的开放接口，数据来自**德国气象局 DWD**的公开数据。
- 按项目坐标取当天 07–17 点的逐小时数据，汇总成最低/最高温度、降水、阵风和天气状况，写进日报 § 1。再按 `config/rules.toml` 的 `[weather]` 阈值判断是否属于“超出预期的天气”（§ 6 Abs. 2 Nr. 2 VOB/B）。
- **自动获取**（`pipeline.ensure_weather`）：
  - 打开某天的 dashboard、History 或导出日报时自动拉取。
  - 当天的数据最多每 60 分钟更新一次。后端另有后台线程，每小时为所有有坐标的项目更新当天天气，并重新评估当天的事件。
  - 过去的日期在当天结束后拉一次，之后固定不变。未来的日期不拉取。
  - 拉取失败（离线等）时 10 分钟后自动重试，日报照常生成。
- **坐标**：新建项目对话框和项目主数据里填“Koordinaten Baustelle”，例如 `48.1305, 11.6955`（Google Maps 里右键点工地，第一行坐标点一下即可复制）。修改坐标后会清空旧天气并重新拉取。没有坐标时，dashboard 会提示补填。
- dashboard 的天气栏不再显示“Belege”按钮。数据仍然作为 DWD 证据挂在“天气导致的停工”事件上，Behinderungsanzeige 可以引用。
- Demo 模式下，`data/demo/<项目>/fixtures/weather/<日期>.json` 存在时优先读取本地文件。测试设置了 `SITEVOX_WEATHER_ONLINE=0`，不会访问网络。

**GAEB（`sitevox/understand/gaeb_io.py`，库 [`gaeb`](https://pypi.org/project/gaeb/)，MIT）**
- 导入：GAEB DA XML 2.x–3.3（`.x81`–`.x89`）、GAEB 2000（`.p8x`）、GAEB 90（`.d8x`）→ LV 文档（每个标题一页、`Pos. | Kurztext | Menge | Einheit | EP` 表格、结构化 `lv_items`），自动 `kind = "lv"`，因此 "LV 中无此项" 的检查（`rag.lv_contains`）也能用于文件名不含 "LV" 的 GAEB 文件。
- 导出：任何含 LV 表格（Pos./Kurztext/Menge/Einheit）的项目文档 → GAEB DA XML 3.3，阶段 X81/X83/X84/X86：`GET /api/documents/<doc_id>/gaeb?phase=83`；界面在文档视图右上角。
- 注意：`gaeb` 写出时标题 RNoPart 固定 2 位、位置 4 位，所以 OZ 被规范成 2(+2 每层)+4，例如 `03.010` → `03.0010`。库未附带官方 XSD，导出文件尚未做 schema 校验，也还没在 AVA 软件里实测。

**邮箱绑定**：步骤见下方 [邮箱绑定与发送](#邮箱绑定与发送临时说明)。

**证据按来源显示（`GET /api/evidence-sources?ids=…`，`backend/views.py: source_key / evidence_sources`）**
- 一条语音、一张照片、一封邮件、一份文档只出现一次，其中所有被引用的位置一起高亮：语音 = 转写中的时间段（点击从该处播放），照片 = 原图上的 bbox（AI 观察与裁剪图归到原图），文本 = 引用句子。
- 选中某个 `[E-xx]` 时该处深色高亮并滚动到位。`[E-xx]` 编号本身不变（LLM 起草与 `verify.py` 仍按单条证据工作），分组只发生在显示层。
- 前端组件：`EvidenceSources` / `SourceCard`（`frontend/components/EvidenceViewer.tsx`），用于函件页、事件页、侧边抽屉、Erfassungen。旧的 `EvidenceCard` 已移除。

## 邮箱绑定与发送（临时说明）

> 这是当前实现的操作说明，邮箱接入还在完善中，后续（尤其是 Outlook / OAuth）会改。

SiteVox 用**同一个绑定的邮箱**做两件事：
- **收**（IMAP，只读）：把与项目相关的邮件拉进来，走正常的 E-Mail-Erfassung。
- **发**（SMTP）：Schreiben 放行（Freigeben）后，经用户在发送对话框里确认，把 PDF/DOCX 作为附件发给 AG。

### 1. 先在邮箱服务商那边准备

| 服务商 | 要做的事 | 密码填什么 | IMAP / SMTP（自动带出） |
|---|---|---|---|
| **Gmail** | Google 账号开启两步验证 → [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) 生成应用专用密码 | 16 位应用专用密码（空格可以照抄，系统会自动去掉） | `imap.gmail.com:993` / `smtp.gmail.com:465` |
| **GMX** | 网页版 → E-Mail → Einstellungen → POP3 & IMAP → 勾选 „POP3 und IMAP Zugriff erlauben“ | 登录密码；开了两步验证则用应用专用密码 | `imap.gmx.net:993` / `mail.gmx.net:465` |
| **WEB.DE** | Einstellungen → POP3/IMAP Abruf → 允许 IMAP | 同 GMX | `imap.web.de:993` / `smtp.web.de:587`（STARTTLS） |
| **T-Online** | 在 Kundencenter / E-Mail-Center 设置单独的 **E-Mail-Passwort**（不是 Telekom 登录密码） | E-Mail-Passwort | `secureimap.t-online.de:993` / `securesmtp.t-online.de:465` |
| **IONOS** | 无需额外设置 | 邮箱密码 | `imap.ionos.de:993` / `smtp.ionos.de:465` |
| **公司自建服务器** | 向 IT 要 IMAP / SMTP 地址、端口、加密方式 | 按 IT 提供 | 在“Erweiterte Einstellungen”里手填 |
| **Outlook / Microsoft 365** | 目前不能直接绑定，见下方 [Outlook](#outlook--microsoft-365) | — | — |

> 常见报错：*Anmeldung abgelehnt*（登录被拒）基本都是用了普通登录密码而不是应用专用密码，或者服务商那边还没开 IMAP。Google Workspace（公司 Gmail）的管理员可能禁用了应用专用密码，需要找管理员。

### 2. 在 SiteVox 里绑定

1. 打开项目 → 左侧 **Postfach** → **Postfach verbinden**。
2. 选 **Anbieter**（服务商），填 **E-Mail-Adresse** 和 **App-Passwort**。
3. 勾选“只导入属于本项目的邮件”时，系统按合同号、项目名和已知发件人判断邮件属于哪个项目。建议保持勾选。
4. 需要时展开 **Erweiterte Einstellungen**：
   - IMAP 服务器、端口、加密方式。
   - 用户名（和邮箱地址不同时才填）。
   - 文件夹（默认 `INBOX`）。
   - 拉取多少天内的邮件（默认 14 天）。
   - **SMTP-Server / SMTP-Port**：留空时，已知服务商自动带出；其他情况按 `imap.xxx` 推成 `smtp.xxx:465`。
5. 点 **Verbinden & testen**。系统先测试 IMAP 登录，成功后才保存账号。
6. **自动拉取**：绑定成功或解锁后立即拉一次，之后后台每 **5 分钟**自动拉取所有已解锁的邮箱。
   - Postfach 页面显示“Automatischer Abruf alle 5 Min. · nächster HH:MM”。
   - 某个邮箱拉取失败时，错误显示在该邮箱下面，不影响其他邮箱。
   - 想立刻拉取可以点 **Abrufen**。
   - 间隔可用环境变量 `SITEVOX_MAIL_SYNC_MIN` 调整；设为 `0` 时完全关闭自动拉取，只能手动拉取。
   - 拉取是只读的：不标已读，不删除，同一封邮件按 Message-ID 去重。

**密码不落盘**：密码只在后端进程内存里，账号配置（不含密码）存在项目文档的 `mail_accounts` 中。后端重启后邮箱显示为“gesperrt”，**锁定期间不会自动拉取**，需要在 Postfach 页面（**Passwort** 按钮）或发送对话框里重新输入密码解锁。

### 3. 发送 Schreiben

1. 打开要发的 Schreiben，逐项确认后点 **Freigeben**（放行）。**放行本身从不发邮件**，只是打开发送对话框。
2. 在发送对话框里核对：
   - **Von**：用哪个已绑定的邮箱发。锁着的话，当场输入密码 → **Entsperren**。
   - **An**：AG 的邮箱，只从上传资料（合同、邮件等）里自动识别。没识别出来就是空的，需要施工经理自己查好填上。改过的收件人会写入 Audit-Log。
   - **Cc**：可选，多个地址用逗号分隔。
   - **Betreff**、正文、**Anhang**（PDF，没有 PDF 时用 DOCX）。
3. 点 **Jetzt senden**。可以点 **Später**，之后在 Schreiben 页面再发。
4. 发送成功后：
   - 状态变为 **Versendet**。
   - 发出的邮件另存一份 `…_gesendet.eml`。
   - 邮件请求了阅读回执。
5. **原件提醒**：单靠 E-Mail 可能不满足书面形式要求（Schriftform）。页面会一直提示寄 **Einschreiben mit Rückschein**（挂号回执）。实际寄出后，选择寄送方式，点 **Original versendet**。

另一条路：Schreiben 页面的 **Outlook-Entwurf (.eml)** 会下载一封带附件的未发送草稿，用 Outlook 打开后自己点发送。这条路不需要绑定邮箱，Outlook 用户目前用这个。

### Outlook / Microsoft 365

**现状**：Microsoft 已经不允许第三方程序用“邮箱 + 密码 / 应用专用密码”登录 IMAP，个人版 Outlook.com 连 SMTP 也要求 OAuth2（Modern Auth）。所以 SiteVox 里 “Microsoft 365 / Outlook” 这个选项目前是灰的（*folgt (OAuth)*）。
- Outlook.com / Hotmail / Live（个人账号）：IMAP 和 SMTP 都必须走 OAuth2，应用专用密码基本不再可用。
- Microsoft 365（公司账号，Exchange Online）：
  - IMAP 的基本认证早已关闭。
  - SMTP AUTH 的基本认证按 Microsoft 2026 年 1 月的时间表，**从 2026 年 12 月起默认关闭**，管理员暂时还能手动重新打开，最终移除时间会在 2027 年下半年公布。不建议再依赖它。

**现在能用的办法：**
1. **发**：用 **Outlook-Entwurf (.eml)**。下载后双击，用 Outlook 打开，检查后发送。发完在 SiteVox 里选寄送方式，点 **Habe ich versendet**。
2. **收**：在 Outlook 里建一条规则，把项目相关邮件（比如主题或正文含合同号的）**转发**到一个已绑定的 Gmail/GMX 邮箱，由 SiteVox 从那里拉取。
   - Outlook 网页版：设置 → 邮件 → 规则 → 添加新规则 → “转发到”。
   - 公司 M365 的出站反垃圾策略可能禁止自动转发到外部地址，需要 IT 放行。

**之后接 Microsoft Graph（OAuth）需要提前准备的东西。代码还没实现，这些是预计需要的配置：**

1. 用公司 IT 或个人 Microsoft 账号登录 [Microsoft Entra admin center](https://entra.microsoft.com) → **Identity → Applications → App registrations → New registration**。
   - **Name**：`SiteVox`
   - **Supported account types**：
     - 同时支持公司账号和 Outlook.com：选 *Accounts in any organizational directory and personal Microsoft accounts*。
     - 只用本公司账号：选 *Single tenant*。
   - **Redirect URI**：平台选 *Public client/native (mobile & desktop)*，填 `http://localhost`。
2. 创建后进入 **Authentication**，把 *Allow public client flows* 设为 **Yes**。SiteVox 计划用 Device-Code 流程：界面显示一个代码，用户在浏览器打开 microsoft.com/devicelogin 输入代码并登录，不需要 Client Secret。
3. **API permissions → Add a permission → Microsoft Graph → Delegated permissions**，添加：
   - `Mail.Read`（收）
   - `Mail.Send`（发）
   - `offline_access`（刷新令牌，不用每次重新登录）
   - `User.Read`
4. 公司租户：请 IT 管理员点 **Grant admin consent for <公司>**。很多公司禁止用户自行同意第三方应用，不点这个就会卡在登录页。
5. 记下 **Overview** 页的：
   - **Application (client) ID**
   - **Directory (tenant) ID**（个人账号或多租户用 `common`）

   将来填到 SiteVox 的配置里。

参考：
- [Outlook.com POP/IMAP/SMTP 设置](https://support.microsoft.com/en-us/office/d088b986-291d-42b8-9564-9c414e2aa040)
- [Outlook.com 不再支持 Basic Auth](https://support.microsoft.com/office/outlook-and-other-apps-are-unable-to-connect-to-outlook-com-f4202ebf-89c6-4a8a-bec3-3d60cf7deaef)
- [Exchange Online SMTP AUTH 时间表（2026-01 更新）](https://techcommunity.microsoft.com/blog/exchange/updated-exchange-online-smtp-auth-basic-authentication-deprecation-timeline/4489835)

### 接口

- 服务商列表：`GET /api/mail-providers`
- 账号：`GET|POST /api/projects/<pid>/mail-accounts`
  - 解锁：`POST …/<aid>/unlock`
  - 手动拉取：`POST …/<aid>/sync`（自动拉取在后端启动时开启，见 `mail_accounts.start_auto_sync`）
  - 解绑：`DELETE …/<aid>`
- 发送：
  - 发送对话框内容：`GET /api/letters/<lid>/send-preview`
  - 发送：`POST /api/letters/<lid>/send-email`，必须带 `confirm: true`
  - 修改收件人：`PUT /api/letters/<lid>/recipient-email`
  - 标记原件已寄出：`POST /api/letters/<lid>/original-sent`

## 合并说明（frontend_develop → main）

- **本分支新增的数据结构**：
  - SQLite 表 `report_rows`（日报行修改），后端启动时自动创建。
  - 项目文档新增字段：
    - `contacts`、`contacts_hidden`（联系人的修改和隐藏）
    - `client.email_source`、`client.phone`
    - `lat` / `lon`
    - `mail_accounts[].smtp_*`
  - 文档新增字段：`version`、`superseded_by`；`collection = "legal_archive"` 表示已归档的法律条文。
- **新的环境变量**：
  - `SITEVOX_MAIL_SYNC_MIN`：邮件自动拉取间隔，默认 5 分钟，设为 0 关闭。
  - `SITEVOX_WEATHER_ONLINE=0`：不访问天气接口，测试时使用。
- **后台线程**：后端启动时开启（`@app.on_event("startup")`）：
  - 邮件自动拉取
  - 每小时更新当天天气

  `TestClient` 不以 context manager 方式使用时不会触发这些线程。

- **依赖**：`pip install -r requirements.txt`（新增 `pypdf`、`rapidocr`、`onnxruntime`、`gaeb`，在 "Dateiverarbeitung" 一组）。合并后前端请删除 `frontend/.next` 再 `npm run build`。
- **ASR**：试验过的"项目词表喂给 Whisper"已整体移除（识别本身还不准，从识别结果里加关键词没有意义）。`asr.py` 回到按语言的固定 `initial_prompt` + 配置里的 `hotwords`。同时修复了 main 合并（`41fa4c8`）遗留的两个崩溃：faster-whisper 路径的 `NameError: vocab`、mlx 路径参数个数不对（有回归测试）。`asr_server.py` 接口与 main 相同。
- **Next.js 15.5 的一个 bug**：客户端页面模块若被分到确定性模块 ID `0`，会从 React Client Manifest 中漏掉（`flight-manifest-plugin` 里 `if (concatenatedModId)`），页面 500：*Could not find the module … in the React Client Manifest*。`frontend/next.config.mjs` 里对浏览器构建改用 `moduleIds = "named"`，升级 Next 修复后可去掉。
- **容易冲突的文件**：`sitevox/understand/asr.py`、`sitevox/pipeline.py`、`backend/main.py`、`backend/views.py`、`frontend/lib/i18n.tsx`、`frontend/components/EvidenceViewer.tsx`、`tests/test_core.py`。i18n 冲突一般只是两边都加了词条，保留双方即可（注意不能有重复键，`npx tsc --noEmit` 会报）。
- `data/demo/` 下的 `.eml` 和 `Bauzeitenplan.xlsx` 每次跑测试都会被 `make_demo_data.py` 重写，无实际变化，不要提交。
- 测试：54 个，全部通过（`pytest tests --basetemp=.pytest_tmp -p no:cacheprovider`）。

## 合规要点

- **DSGVO**：Whisper/Qwen 本地运行；导出前自动人脸打码（OpenCV），照片附 Anlage 时带时间戳与 GPS。
- **免责声明**：界面页脚与导出文件页脚。
- **置信度**不使用 LLM 自报：证据数量 + WhisperX 词分 + 多次采样一致性 + 检索相关度 + 规则校验，阈值 0.8 / 0.5。
- VOB/B 文本为现行版（2016）摘录，生产使用前请对照官方文本。
