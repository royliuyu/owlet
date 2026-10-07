# owlet — 实现方案

> **owlet** · 本地优先的个人第二大脑：文件 + 笔记 + 邮件 + 日历 + 云盘，统一检索、带引用回答、可执行动作。
>
> 全新仓库，不继承 `Knowledge-Base-Intelligent-Paper-Retrieval` 的目录与历史。
> 原项目的论文 RAG 在此降级为**一个 connector**，仅移植三处代码（见 §10）。
>
> 状态：阶段 0 与 0.5 完成 —— 结构化切块、混合检索、带引用回答、PDF 原文高亮已端到端跑通 · 最后更新 2026-10-04

---

## 1. 目标与范围

### 1.1 最终形态

```
              ┌── PDF / Word
              ├── Notion / Obsidian
你的数据 ──────┼── Gmail
              ├── Calendar
              └── Google Drive
                    ↓  数据解析 / Chunk
                    ↓  Embedding
                    ↓  Vector DB / 混合搜索
用户问题 → Query → 检索相关资料
                    ↓  LLM
              回答 + 引用资料来源
                    ↓  Tools / Actions
         发邮件 / 建日程 / 创建任务
```

### 1.2 关键约束

| 约束 | 决策 |
|---|---|
| 隐私 | 本地优先，LLM 与 Embedding 默认走本地 Ollama |
| 用户规模 | 单用户（保留 `user_id` 抽象，但不做鉴权系统） |
| 远程访问 | Tailscale / 内网穿透，手机访问家中电脑，**不直接暴露公网** |
| 客户端 | 一套响应式 Web 应用（PWA），同时适配宽屏与手机窄屏，不做原生 App |
| 可扩展性 | 新增数据源 / 新增动作只加文件，不改主流程 |
| 数据与代码 | 严格分离，`data/` 整个不入库，位置可配置 |

### 1.3 不在本期范围

- 多用户与权限隔离
- 原生 iOS / Android App（PWA 已足够；Tauri / Capacitor 留作后续选项）
- 手机端操控其他 App（iOS 沙盒限制，仅能通过快捷指令间接调用 HTTP API）
- Postgres / pgvector（见 §11）

---

## 2. 总体架构

```
        ┌─────────── 中枢（家中电脑 / NAS）────────────┐
        │  FastAPI + 索引 + Ollama + MCP Server         │
        │  + 定时同步任务 + SQLite(FTS5 + sqlite-vec)   │
        └──────────────┬────────────────────────────────┘
                       │ Tailscale（加密，不开放公网端口）
     ┌─────────────────┼──────────────────┬─────────────────┐
  手机 PWA        电脑浏览器         Claude / Cursor    桌面伴侣
                                      （MCP 客户端）    （本地 MCP，可选）
```

单一 origin 同时提供 API 与静态资源 → 无跨域问题，Tailscale 下配置最简。

---

## 3. 技术栈决策

### 3.1 后端

| 项目 | 选型 | 理由 |
|---|---|---|
| Python | ≥ 3.10 | 迁就现有 `ai-nvr` 环境（3.10.16）。**代价**：3.10 已于 2026-10 到达 EOL，不再有安全更新；且不可使用 `datetime.UTC`、`StrEnum`、`TaskGroup` 等 3.11+ 特性。后续若 LangGraph / Chroma 要求更高版本，需改用独立环境 |
| Web 框架 | FastAPI | SSE 支持好，Pydantic 原生集成 |
| 元数据库 | SQLite + FTS5（WAL） | 单用户足够；FTS5 提供 BM25。**不预留 Postgres 迁移设计** |
| 向量库 | **sqlite-vec**（`vec0` 虚拟表） | 与元数据同库同事务，无需再跑一个服务。十万 chunk 以内够用；藏在 `VectorStore` 后，换 Chroma / Qdrant / pgvector 只换一个文件 |
| PDF 解析 | **PyMuPDF** | 引用要高亮到页面上的矩形，必须拿到每行的 bbox 与字号；pypdf 只给扁平字符串。Docling 结构更好但带 torch 量级依赖、CPU 上每页数秒，整库一次性索引吃不消 |
| 编排 | LangGraph ≥ 1.2（**阶段 3 才引入**） | checkpoint + interrupt 同时对齐 A2A 与 MCP 任务模型 |
| LangChain | 仅 `langchain-text-splitters` | chain / memory / vectorstore 包装均已废弃，不采用 |
| 配置 | pydantic-settings | YAML + env 分层覆盖，路径从 `__file__` 解析 |
| LLM / Embedding | Ollama 原生 API（httpx） | `/api/chat` 与 `/api/embed`。**不传 `think` 参数**：推理模型被要求不思考时照样思考，只是把思考文字塞进 `content`；放任不管它会分到 `thinking`，`content` 就干净了 |
| 分层约束 | import-linter | 在 CI 里机器强制，防止 `domain/` 被框架污染 |

### 3.2 前端

**React + Vite + TypeScript + Tailwind + shadcn/ui**，构建产物落 `web/dist/`，由 FastAPI 挂载。

理由：流式输出、引用面板、可拖拽分栏、动作确认卡片、索引进度等富交互，模板 + 原生 JS 难以为继。shadcn/ui 组件以源码形式进仓库，可自由改，且自带 Sheet / Drawer / Dialog 等移动端必需组件。

前端是独立工程（独立 `package.json` 与工具链），与 `src/core/` **平级**，不嵌入后端包。

### 3.3 已核实的外部协议版本（2026-10）

| 协议 | 版本 | 关键事实 |
|---|---|---|
| MCP | 规范 `2026-07-28`，Python SDK `mcp` 2.x | **无状态**：无 initialize 握手、无 `Mcp-Session-Id`；单 POST 端点 `/mcp`；`MCP-Protocol-Version` 头必填；新增 Tasks 扩展 |
| A2A | v1.0（Linux Foundation） | Agent Card 位于 `/.well-known/agent-card.json`；`url` / `preferredTransport` 已合并进 `supportedInterfaces[]`；绑定支持 JSON-RPC / gRPC / REST |
| LangGraph | 1.2（2026-05） | 节点级 `timeout` / `error_handler`；优雅停机 `request_drain()`；streaming v3；durability 模式 `exit` / `async` / `sync` |

---

## 4. 仓库布局

```
owlet/
├── pyproject.toml              依赖 · ruff · pytest · import-linter 分层规则
├── README.md
├── .gitignore
├── .env.example
├── config/
│   ├── default.yaml            提交
│   └── local.yaml              gitignore，覆盖默认值
├── docs/
│   ├── IMPLEMENTATION_PLAN.md  本文档
│   └── adr/                    架构决策记录
├── src/core/
│   ├── config.py               pydantic-settings
│   ├── domain/                 ← 零框架依赖
│   │   ├── models.py           Document · Chunk · Citation · StructuredQuery
│   │   ├── chat.py             Block · SSE 事件 · PendingAction
│   │   └── errors.py
│   ├── store/
│   │   ├── db.py               连接与建表，WAL，每连接加载 sqlite-vec
│   │   ├── sources.py          读哪些文件夹（用户数据，UI 增删）
│   │   ├── documents.py        documents / chunks / FTS5，藏在 DocumentStore 后
│   │   ├── vectors.py          VectorStore Protocol + sqlite-vec 实现
│   │   └── checkpoint.py       LangGraph checkpointer（阶段 3）
│   ├── connectors/
│   │   ├── base.py             Connector Protocol
│   │   └── local_files · obsidian · notion · gmail · gcal · gdrive
│   ├── ingestion/
│   │   ├── parse/              pdf（PyMuPDF，带 bbox）· docx · markdown · email
│   │   ├── chunk/              structure.py 按章节切块 · tokens.py 估算
│   │   ├── pipeline.py         增量同步（content_hash + layout_version）
│   │   └── scheduler.py        APScheduler
│   ├── retrieval/
│   │   ├── understand.py       问题 → StructuredQuery（阶段 3）
│   │   ├── hybrid.py           BM25 + 向量 + RRF
│   │   ├── rerank.py           （阶段 1）
│   │   └── answer.py           提示词组装 + 编号引用 + 流式回答
│   ├── llm/
│   │   └── ollama.py           EmbeddingClient Protocol + OllamaClient
│   ├── tools/
│   │   ├── registry.py         ★ 枢纽
│   │   └── search · calendar · email · tasks
│   ├── agent/                  阶段 3
│   │   ├── graph.py  state.py  nodes/
│   └── interfaces/             只调用 core.tools，不含业务逻辑
│       ├── http/   app.py · engine.py · routes/{chat,collections,documents,index,actions}.py
│       ├── mcp/    server.py           registry → MCP tools
│       ├── a2a/    server.py           Agent Card + task 生命周期（阶段 6）
│       └── cli/
├── web/                        前端 Vite 工程
│   ├── package.json
│   ├── src/lib/types.ts        与 domain 镜像的契约
│   └── dist/                   gitignore，由 FastAPI 挂载
├── tests/
└── data/                       ← gitignore，位置可配置
    └── metadata.db             元数据 + 全文索引 + 向量，一个文件
```

**三条布局原则**

1. **代码 / 数据 / 配置严格分离。** 所有可变数据收在 `data/` 一处，整个 gitignore，位置由 `OWLET_DATA_DIR` 可配置（可指向其他盘或 `~/.owlet`）。
2. **用 `src/` 布局。** 避免从 cwd 误导入，配合 `pip install -e .` 后 `import core` 行为稳定。
3. **`interfaces/` 作为包内子包**，而非顶层目录 —— 只产出一个可安装包；分层由依赖方向保证，不靠目录层级。

`src/core/sources/` 这类"论文专属"目录不存在：**本地 PDF 只是 `connectors/local_files.py` 一项**，与 Gmail、Calendar 完全平权。

---

## 5. 分层与依赖约束

**唯一硬性规则：依赖只能向下，`domain/` 不 import 任何框架。**

```
┌──────────────────────────────────────────────────────────┐
│ interfaces   HTTP(SSE) │ MCP Server │ A2A Server │ CLI   │
├──────────────────────────────────────────────────────────┤
│ agent        LangGraph（state + checkpoint + interrupt）  │
├──────────────────────────────────────────────────────────┤
│ tools        Tool Registry  ← 枢纽，单一事实来源           │
├──────────────────────────────────────────────────────────┤
│ retrieval │ ingestion │ actions                          │
├──────────────────────────────────────────────────────────┤
│ store │ connectors │ llm                                 │
├──────────────────────────────────────────────────────────┤
│ domain       纯 Pydantic，零框架依赖                       │
└──────────────────────────────────────────────────────────┘
```

由 `pyproject.toml` 里的 import-linter 契约机器强制：

```toml
[[tool.importlinter.contracts]]
name = "分层：依赖只能向下"
type = "layers"
layers = [
  "core.interfaces",
  "core.retrieval",
  "core.ingestion",
  "core.connectors",
  "core.store",
  "core.llm",
  "core.domain",
]

[[tool.importlinter.contracts]]
name = "domain 不依赖任何框架"
type = "forbidden"
source_modules = ["core.domain"]
forbidden_modules = ["fastapi", "langchain", "langgraph", "httpx", "sqlite3"]
```

`core.agent` 与 `core.tools` 层在阶段 3 / 4 引入时再插回 `core.interfaces` 之下。

---

## 6. 核心契约

### 6.1 领域模型

```python
# src/core/domain/models.py
SourceKind = Literal["paper", "note", "email", "event", "file", "task"]

class Document(BaseModel):
    id: str                       # f"{source}:{source_id}"
    source: SourceKind
    source_id: str                # 原系统 ID（messageId / eventId / fileId）
    title: str
    uri: str                      # 可点击跳回原文
    author: str | None = None
    participants: list[str] = []  # 邮件收发件人、会议参与者
    collection: str | None = None
    created_at: datetime
    updated_at: datetime
    content_hash: str             # 增量索引依据
    extra: dict = {}              # 线程 ID、标签、地点等源特有字段

class BBox(BaseModel):
    page: int
    x0: float; y0: float; x1: float; y1: float   # 页面比例，左上原点，与缩放无关

class Chunk(BaseModel):
    id: str                       # 内容寻址，见下
    doc_id: str
    ord: int
    text: str                     # 原文，embedding 不能替代它
    token_count: int = 0
    page_start: int = 1
    page_end: int = 1
    section_path: str | None = None   # "2 Related Work > 2.1 Solo Inference"
    section_kind: str | None = None   # abstract / methods / results / ...
    bboxes: list[BBox] = []           # 点引用 → PDF 高亮
    char_start: int = 0
    char_end: int = 0

    @property
    def locator(self) -> dict: ...    # 给前端的 {"page", "section", "bboxes"}

class Citation(BaseModel):
    n: int
    kind: SourceKind
    doc_id: str
    title: str
    uri: str
    locator: dict = {}
    snippet: str

class StructuredQuery(BaseModel):
    text: str
    sources: list[SourceKind] | None = None
    time_range: tuple[datetime, datetime] | None = None
    people: list[str] = []
    collection: str | None = None
```

`web/src/lib/types.ts` 是本文件的 TypeScript 镜像，两者必须同步修改。

### 6.2 工具注册表（枢纽）

**整个方案的核心：工具只定义一次，由适配器分发到四个出口。** 这样 LangChain / LangGraph / MCP / A2A 中任一框架过时或被替换，都不触及核心代码。

```python
# src/core/tools/registry.py
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[BaseModel], Awaitable[BaseModel]]
    effect: Literal["read", "write"] = "read"
    requires_confirmation: bool = False
    expose: frozenset[str] = frozenset({"agent", "http"})   # agent/http/mcp/a2a
    scopes: tuple[str, ...] = ()

REGISTRY: dict[str, ToolSpec] = {}

def tool(**kw):
    def deco(fn):
        REGISTRY[kw["name"]] = ToolSpec(handler=fn, **kw)
        return fn
    return deco
```

```python
# src/core/tools/search.py
@tool(
    name="search_knowledge",
    description="在个人知识库中检索论文、笔记、邮件、日程，返回带引用的片段",
    input_model=SearchInput, output_model=SearchOutput,
    effect="read",
    expose=frozenset({"agent", "http", "mcp", "a2a"}),
)
async def search_knowledge(inp: SearchInput) -> SearchOutput: ...
```

四个适配器都很薄（Pydantic 可直接导出 JSON Schema）：

| 出口 | 适配方式 |
|---|---|
| LangGraph | `bind_tools` / `StructuredTool.from_function` |
| MCP Server | `mcp.add_tool()`，schema 自 `input_model` 生成 |
| REST | FastAPI 路由直接以 `input_model` 为请求体 |
| A2A | 映射为 Agent Card 的 `skills[]` |

`effect` 与 `requires_confirmation` 使权限策略集中在一处，杜绝「REST 有确认、MCP 却能直接发邮件」这类漏洞。

### 6.3 数据库 Schema

```sql
sources(id PK, kind, path, collection, enabled, created_at)  -- 在 Settings 页增删
documents(id PK, source, source_id, title, uri, author, collection,
          created_at, updated_at, content_hash, extra_json,
          indexed_at, deleted_at)
chunks(id PK, doc_id FK, ord, text, token_count,
       char_start, char_end, page_start, page_end,
       section_path, section_kind, bboxes_json,
       chunking_version, created_at,
       UNIQUE(doc_id, chunking_version, ord))
chunks_fts                     -- FTS5 虚拟表，external content = chunks
embeddings(chunk_id PK, model, dim, created_at)   -- 用哪个模型算的
vec_chunks                     -- sqlite-vec vec0 虚拟表，KNN
index_runs(id PK, started_at, finished_at, status, detail_json)
sync_state(source, account, cursor, last_sync_at, status)  -- historyId / syncToken
conversations(id PK, title, created_at, updated_at)
messages(id PK, conversation_id FK, role, blocks_json, created_at)
actions(id PK, conversation_id FK, kind, params_json, status,
        confirmed_at, result_json, created_at)
audit_log(id PK, actor, tool, params_json, result, created_at)
```

要点：
- `content_hash` 实现增量索引；`sync_state` 保存各源游标。
- 开启 WAL 模式；事务保持短小（后台同步与聊天并发写）。
- **FTS5 是 SQLite 独有**，全文检索必须藏在 `DocumentStore.search_fulltext()` 接口后。
- **chunk_id 内容寻址**：`sha256(doc_id ‖ chunking_version ‖ ord ‖ text)[:32]`。同样的输入必得同样的 id，所以重复索引是幂等的；改了切块参数就换了 version，于是每个 id 都变，重建因此是可见的而非悄悄半截。
- **什么时候该重建**：`layout_version = PARSER_VERSION | chunking.version`。解析行为变了却没 bump `PARSER_VERSION`，增量索引会把旧 chunk 当成最新的跳过。
- `embeddings` 记下模型与维度：换 embedding 模型是一次重建，不是一次静默的改动。维度对不上时客户端直接报错。

#### 与 Vector DB 解耦

```python
class VectorStore(Protocol):
    model: str
    dim: int
    def upsert(self, chunk_ids: Sequence[str], vectors: Sequence[list[float]]) -> None: ...
    def search(self, vector: Sequence[float], *, limit: int) -> list[VectorHit]: ...
    def delete(self, chunk_ids: Sequence[str]) -> None: ...
    def missing(self, chunk_ids: Sequence[str]) -> list[str]: ...
```

**跨过这个边界的只有 chunk id**，没有文本、没有元数据。检索到向量后一律回 `chunks` 表取原文。
`sqlite-vec` 这个名字只出现在 `store/db.py` 与 `store/vectors.py` 两处，换库即换这两处。

### 6.4 Connector 协议

```python
class Connector(Protocol):
    source: SourceKind
    async def list_changes(self, cursor: str | None) -> AsyncIterator[ChangeSet]: ...
    async def fetch(self, source_id: str) -> RawDocument: ...
    def resolve_uri(self, doc: Document) -> str: ...
```

| 源 | 增量机制 | 注意事项 |
|---|---|---|
| 本地文件（含论文） | mtime + content_hash | 多个源根存在 `sources` 表，UI 增删，无需重启 |
| Obsidian | 文件监听 | 按标题层级切块；frontmatter / tag / `[[双链]]` 入元数据 |
| Gmail | `history.list`（historyId） | 剥离引用回复与签名；**按线程聚合后切块**；跳过推广与通知类 |
| Calendar | `syncToken` | 结构化数据，除向量外**另存 SQL 表**供精确查询 |
| Drive | `changes.list`（pageToken） | Google Docs 需导出为文本 |
| Notion | `last_edited_time` 轮询 | block 树需递归展开 |

### 6.5 API 契约

```
POST /api/v1/chat          SSE 流
     { conversation_id, question, sources: ["paper"], filters: {...} }

event: start     {"message_id": "..."}
event: tool      {"tool": "search_knowledge", "status": "running"}
event: tool      {"tool": "search_knowledge", "status": "done", "hits": 6}
event: delta     {"text": "这篇论文提出"}
event: citation  {"n": 1, "kind": "paper", "title": "...", "locator": {"page": 7}}
event: action    {"action_id": "a1", "kind": "create_event", "params": {...}}
event: done      {"latency_ms": 3200}
event: error     {"message": "..."}
```

```
GET    /api/v1/collections            列出源根
POST   /api/v1/collections            新增源根 { path, label? }
PATCH  /api/v1/collections/{id}       改名 / 启停 { label?, enabled? }
DELETE /api/v1/collections/{id}
GET  /api/v1/collections/{id}/files
GET  /api/v1/documents/{id}           ?view=meta 分页文本 / ?view=file 原始 PDF
POST /api/v1/index                    { force } 建索引，增量或重建
GET  /api/v1/index/status             进度与计数
POST /api/v1/search                   不经 LLM 的检索，便于调参
POST /api/v1/actions/{id}/confirm     确认动作 → Command(resume=...)
GET  /api/v1/conversations
```

反代下需设 `X-Accel-Buffering: no`，否则 SSE 可能被缓冲。

---

## 7. 切块与检索

### 7.1 切块：按论文结构，不按字符数

硬切 N 个字符会把一个实验结论从中间劈开，检索到半句话无法回答问题。所以：

- **章节边界优先。** 遇到标题一定收口，Methods 不会渗进 Results。
- **标题栈构成 `section_path`**（`2 Related Work > 2.1 Solo Inference`），随 chunk 一起存，并前置到 chunk 文本里 —— 检索到的片段自己说得清出自论文哪一部分。
- **大小是区间不是规矩。** 块累积到 `target_tokens`（默认 500）才收口；只有单块超过 `max_tokens`（800）才切，且切在句子边界并带 `overlap_tokens`（80）重叠。四个数字都在 `config` 里，不写死。
- **保留原文。** embedding 只是索引，检索回来一律用 `chunks.text`。

**标题怎么认出来**（`parse/pdf.py`）。字号单独一项不够用：论文把图注、公式、参考文献条目都排得比正文大，却常把章节标题排得和正文一样大甚至小 0.1pt。所以一行还必须读起来像标题：

| 规则 | 挡掉的东西 |
|---|---|
| 正文字号取**按字符数加权的众数**，而非行中位数 | 中位数被又多又短的参考文献压到 9.0，于是 10.1 的正文行全被当成标题 |
| 实词**首字母大写比例 ≥ 0.65**（停用词不计，`mAP` 这类含大写的算数） | `However, the normalized average latency...`、`Training job`、`Optical flow analysis` |
| 带章节号的（`4.2. ...`）直接认，长也无妨 | 保住 `5. CNN Models, Transformer Models, Datasets, ...` |
| 具名章节（Abstract / References / ...）须 ≤ 5 词且不小于正文字号 | `Acknowledgments: We appreciate anonymous reviwers...`、表头里的 `Results` |
| 含 `;` `=` `//` 的一律不是 | 伪代码、公式、参考文献条目 |
| 至少有一个 ≥3 字母的词 | 页眉页脚 `14 of 19` |

在 5 篇真实论文上：真标题一个不漏，误报从约 40 条降到 7 条，且全部落在插图内部的大字标签（`YOL`、`GPU`）—— 这类要再往下压就得做图区检测了。规则由 `tests/ingestion/test_headings.py` 按真实行逐条钉住。

### 7.2 溯源

每个 chunk 带着它在页面上的矩形（每页合并成一个框，不是上百个）。坐标是**页面比例、左上原点**，所以与缩放、DPI、设备无关 —— 前端按百分比定位即可。点击引用 → 跳到页 → 画框。

抽样核对：把存下的框映射回 PDF 坐标、取框内文字，与 chunk 原文比对，词召回 98–100%。

### 7.3 检索

```
问题 ─┬→ BM25 (FTS5)  top50 ─┐
      └→ 向量 (sqlite-vec) top50 ─┴→ RRF 融合 → top 8 → 组装上下文（编号引用）
```

- BM25 对人名、项目代号、邮件主题等精确词显著优于纯向量。
- RRF 只看名次不看分数，所以不必校准两条路的分值量纲。
- **一个 embedding 都还没算时跳过向量这一路**，关键词结果照常返回；模型服务挂了也一样降级，不整体失败。
- 引用由检索结果生成，**不从模型输出里正则抠**。模型编造的编号不会变成引用。
- Reranker（`bge-reranker-v2-m3` / Qwen3-Reranker）留到阶段 1，要有评测集才谈得上调。
- `k` 取 8（旧项目的 `k=2` 对跨源问答明显不足）。

---

## 8. 编排层（阶段 3 引入）

选择 LangGraph 的真正理由：**其状态机同时对齐 A2A 与 MCP 的任务模型**。

| 概念 | LangGraph 1.2 | A2A v1.0 | MCP Tasks 扩展 |
|---|---|---|---|
| 任务标识 | `thread_id` | task UUID | task handle |
| 暂停等人工输入 | `interrupt()` | `input-required` | mid-flight input |
| 恢复 | `Command(resume=...)` | 续发 message | 轮询后恢复 |
| 增量输出 | streaming v3 | SSE | SSE |
| 产物 | state 中的 citations | Artifact | tool result |

即：用 checkpointer + `interrupt()` 实现「动作确认」后，A2A / MCP 的长任务支持几乎白送。单用户用 `langgraph-checkpoint-sqlite` 即可。

```
START → understand ─┬─→ (闲聊/无需检索) ─────────→ generate → END
                    ├─→ retrieve → rerank ───────→ generate → END
                    └─→ act → interrupt(确认) → execute → generate → END
```

```python
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    query: StructuredQuery | None
    citations: list[Citation]
    pending_action: PendingAction | None
```

LangGraph 流 → SSE 事件映射：

| LangGraph | SSE |
|---|---|
| `stream_mode="updates"` | `tool` |
| `stream_mode="messages"` | `delta` |
| `get_stream_writer()` 自定义 | `citation` |
| `__interrupt__` | `action` |

注意：`interrupt()` 之前的副作用必须幂等（节点会从头重放）。

---

## 9. 前端设计

### 9.1 响应式布局

```
桌面 ≥1280px                          手机 <640px
┌────┬──────────┬─────────────────┐   ┌─────────────────┐
│ 图 │ 资料源   │ 对话区          │   │  ☰  对话标题  ⋮ │
│ 标 │ 对话列表 │                 │   ├─────────────────┤
│ 栏 │          │  消息流         │   │                 │
│    │ □ 论文   │  ├ 文本         │   │   消息流        │
│ 💬 │ □ 笔记   │  ├ 引用[1][2]   │   │   引用[1] 可点  │
│ 📅 │ □ 邮件   │  └ 动作确认卡   │   │                 │
│ 📚 │ □ 日历   │                 │   ├─────────────────┤
│ ✅ │          │ ┌─────────────┐ │   │ 输入框      发送│
│ ⚙  │          │ │ 输入框  发送│ │   ├─────────────────┤
│    │          │ └─────────────┘ │   │ 💬  📅  📚  ✅  │
└────┴──────────┴─────────────────┘   └─────────────────┘
          ↕ 可拖拽              ↑
  右侧引用面板（≥1440 常驻）    点引用 → 底部弹出原文
```

| 断点 | 侧边栏 | 引用面板 |
|---|---|---|
| `<640px` 手机 | 抽屉 | 底部 Sheet |
| `640–1280px` 平板 | 可折叠 | 右侧覆盖层 |
| `≥1280px` 桌面 | 常驻 | 可切换 |
| `≥1440px` 宽屏 | 常驻 | 常驻三栏 |

路由：`/chat/:id` · `/today` · `/library` · `/actions` · `/settings`

### 9.2 前端目录

```
web/src/
  app/         AppShell.tsx（三种布局）· routes.tsx
  components/
    layout/    NavRail · MobileTabs · SideDrawer · ContextPanel · ResizeHandle
    chat/      ChatView · MessageList · Composer · SourceFilterChips
    blocks/    BlockRenderer   ← 扩展点 1
    cards/     registry.ts     ← 扩展点 2
    viewers/   PdfViewer（Original / Text 切换）
               PdfDocument · PdfPage   ← pdf.js 连续画布 + 高亮层
               MarkdownViewer · EmailViewer
    library/   AddFolderForm · FolderList · IndexPanel
  lib/         api.ts · useChatStream.ts · types.ts · pdf.ts（worker 配置）
```

PDF 不能用 `<iframe>`：浏览器内置阅读器不给你地方画高亮框。所以自己用 pdf.js 渲染 —— 逐页 canvas、`IntersectionObserver` 懒渲染、按比例叠高亮层。pdf.js 体积和整个 app 相当，且多数会话不开论文，故用 `lazy()` 随第一篇论文一起到。

### 9.3 两个扩展点

**扩展点 1 — 块渲染器。** 后端返回结构化块而非整段 Markdown：

```ts
export type Block =
  | { type: 'text';      content: string }
  | { type: 'tool';      tool: string; status: 'running' | 'done'; summary: string }
  | { type: 'citations'; items: Citation[] }
  | { type: 'action';    action_id: string; kind: ActionKind; params: object }
  | { type: 'error';     message: string };
```

**扩展点 2 — 卡片注册表。** 新增数据源只需加卡片与查看器，再注册一行：

```ts
export const sourceRegistry: Record<SourceKind, SourceRenderer> = {
  paper: { icon: FileText,    Card: PaperCard, Viewer: PdfViewer,      label: '论文' },
  note:  { icon: NotebookPen, Card: NoteCard,  Viewer: MarkdownViewer, label: '笔记' },
  // email: { icon: Mail,     Card: EmailCard, Viewer: EmailViewer,    label: '邮件' },
};
```

聊天主流程、引用面板、筛选器自动支持新来源 —— 这是「可扩展」的具体含义。

### 9.4 移动端注意事项

- 用 `100dvh` 而非 `100vh`，否则键盘弹出时输入框被顶出屏幕。
- 输入框字号 ≥16px，否则 iOS Safari 自动放大页面。
- `viewport-fit=cover` + `env(safe-area-inset-bottom)`，避开 iPhone 手势条。
- 拖拽分栏用 Pointer Events（鼠标事件在触屏无效）。
- Markdown 渲染经 DOMPurify 清洗 —— 接入邮件后这是 XSS 的主要入口。
- Service Worker 的 `navigateFallback` 必须配 `navigateFallbackDenylist: [/^\/api\//]`。**iframe 加载也算一次 navigation**，否则 SW 会用 app 外壳应答 `/api/v1/documents/...`，前端路由在框里渲染出自己的 404。

---

## 10. 从旧仓库移植什么

旧项目 `Knowledge-Base-Intelligent-Paper-Retrieval` 中**只有三处值得移植**：

| 旧位置 | 新位置 | 处理 |
|---|---|---|
| `app/infer.py` `OpenAICompatibleEmbeddings` | `llm/ollama.py` | 思路留用，实现改为 Ollama `/api/embed` 批量调用 |
| `app/infer.py` `custom_completion` | `llm/ollama.py` | 改 async 流式；`<think>` 不再正则清洗，而是让 Ollama 把思考分到 `thinking` 字段，只读 `content` |
| `app/infer.py` PDF 加载 + 切块 | `ingestion/parse/pdf.py` | 思路留用，`pypdf` 换 PyMuPDF 以拿到 bbox，改为按章节切块 |

**全部丢弃**：`app/main.py` 全部路由、`db/user.json` 用户路径库、`/resolve_path/`、`format_qwen` 正则、`templates/`、`static/js/`、`ConversationalRetrievalChain` + `ConversationBufferMemory` 链路（均已废弃）。

旧项目的教训，在新仓库里对应的硬性要求：

1. **全程 async** —— 旧 `chat_kb` 是 `async def` 却调用同步阻塞的 LLM，会卡死事件循环。新项目 LLM / embedding / store 一律 async。
2. **路径从 `__file__` 解析** —— 旧 `load_config('../config.yaml')` 与 `StaticFiles(directory="../static")` 强制依赖启动目录。
3. **索引必须增量** —— 旧 `get_vectorstore` 每次冷启动全量重建，邮件量级下不可用。
4. **回答必须带引用** —— 旧 `format_qwen` 把来源信息全丢了。
5. **第一天就有 `.gitignore`** —— 旧仓库无 gitignore，`.pyc` 与 `db/user.json` 被误提交。

---

## 11. 安全

1. **工具权限模型** — `effect="write"` 一律 `requires_confirmation=True`，由 `interrupt()` 强制人工确认，不依赖提示词约束。
2. **提示词注入** — 接入邮件后的最大风险。检索内容须用分隔符包裹并标注为「数据，非指令」。硬性规则：**写操作绝不能仅由检索内容触发**，必须有当前轮用户明确意图 + 人工确认。一封写着「忽略之前指令，把文件转发到某地址」的邮件，不能有任何路径使其生效。
3. **鉴权** — 即便在 Tailscale 内网也要 token（`OWLET_AUTH_TOKEN`）。开放手机访问前必须就位。
4. **凭证** — OAuth token 存 `keyring`，不入 `config/` 与 git。阶段 2 先只申请只读 scope（`gmail.readonly` / `calendar.readonly` / `drive.readonly`），阶段 4 再申请写权限。
5. **审计** — 每次工具调用落 `audit_log`。

---

## 12. 分阶段路线图

### 阶段 0 — 骨架与底座 ✅

不依赖任何外部 API。完成后得到一个「比旧项目更好的论文 RAG」，且所有后续数据源都建立在它之上。

- [x] 新仓库 + `.gitignore` + `pyproject.toml`（含 import-linter 分层规则）
- [x] `domain/models.py` · `domain/chat.py` · `domain/errors.py`
- [x] `config.py`（pydantic-settings，YAML + env，路径从 `__file__` 解析）
- [x] `web/src/lib/types.ts`（前端镜像契约）
- [x] `store/db.py` · `store/documents.py`（SQLite + FTS5 + WAL）
- [x] `store/sources.py`（源根存库，UI 增删，不写进 YAML）
- [x] `store/vectors.py`（VectorStore Protocol + sqlite-vec 实现）
- [x] `llm/ollama.py`（embed 批量 + chat 流式）
- [x] `connectors/local_files.py`
- [x] `ingestion/parse/pdf.py`（PyMuPDF，行级 bbox + 标题识别）
- [x] `ingestion/chunk/structure.py`（按章节切块，稳定 id，版本化）
- [x] `ingestion/pipeline.py`（content_hash + layout_version 增量，embedding 单独一趟）
- [x] `retrieval/hybrid.py` + `retrieval/answer.py`（BM25 + 向量 + RRF，带引用）
- [x] `interfaces/http/`：集合、原文预览、`/api/v1/chat` SSE、鉴权 token
- [x] `/api/v1/index` + `/api/v1/index/status`

**验收**（已达成）：5 篇论文 → 135 chunk → 全部 embedded；提问 8 条命中且关键词与向量双路都有；回答逐字输出并附带页码与高亮框；重启不重建；`lint-imports` 与 64 项测试通过。

遗留：索引目前由用户在 Settings 点按钮触发，尚无 APScheduler 定时任务。

### 阶段 0.5 — 新 UI ✅

- [x] Vite 工程 + AppShell 三种布局 + 路由（/chat、/today、/library、/actions、/settings）
- [x] `useChatStream` 对接 SSE，渲染 text / tool / citations / action / error 块
- [x] 引用：PaperCard + PdfViewer，桌面右栏 / 手机底部 Sheet
- [x] `/library` 列出集合；源根在 UI 增删（无 `webkitdirectory`）
- [x] Settings 的 IndexPanel：建索引 / 重建，进度轮询
- [x] **点引用 → 跳页 → PDF 原文高亮**（pdf.js 画布 + 比例高亮层 + 缩放）
- [x] PWA：manifest / 图标 / Service Worker

**验收**：手机经 Tailscale 打开可正常问答、查看引用原文、添加到主屏幕。

### 阶段 1 — 本地知识增强（1–2 周）★ 当前

- [ ] `tools/registry.py` 建立；`search_knowledge` 为首个工具
- [x] 混合检索：FTS5 BM25 + 向量 + RRF；`k` 提至 8
- [ ] rerank（须先有评测集）
- [ ] Word（python-docx / unstructured）、Markdown / Obsidian 解析
- [x] 按结构切块（标题层级 / 段落）
- [ ] **建立评测集**：30–50 组「问题 → 应命中文档」，后续每次调参回归
- [ ] APScheduler 定时增量索引

**验收**：评测集命中率基线确立；精确词（人名 / 项目代号）检索明显改善。

### 阶段 2 — 外部数据源（2–3 周）

- [ ] OAuth 本地回调流程 + keyring 存储（只读 scope）
- [ ] Gmail / Calendar / Drive / Notion connector
- [ ] APScheduler 定时增量同步
- [ ] 前端 `/settings/connectors`：连接状态与同步进度
- [ ] 日历另存结构化 SQL 表
- [ ] 对应卡片与查看器（EmailCard / EventCard）

**验收**：跨源提问可同时命中论文、笔记、邮件、日程并正确标注来源。

### 阶段 3 — 查询理解与 Agent（2 周）

- [ ] 引入 LangGraph，替换线性管线
- [ ] `understand` 节点：问题 → `StructuredQuery`
- [ ] 路由：闲聊 / 检索 / 结构化查询（如「明天有什么会」直接查 SQL）
- [ ] 系统提示词注入当前日期与时区（否则「上周」「明天」无法解析）
- [ ] SqliteSaver checkpointer；节点 `timeout` / `error_handler`

**验收**：「下周和李四的会需要准备什么」能先查日程、再按参会人检索邮件并汇总。

### 阶段 4 — Actions + MCP Server（1–2 周）

- [ ] `draft_email` / `create_event` / `create_task` 工具（申请写权限）
- [ ] `interrupt()` 人工确认 + 前端确认卡片 + `POST /actions/{id}/confirm`
- [ ] `audit_log` 全量记录
- [ ] 提示词注入防护（检索内容标注为数据）
- [ ] MCP Server 上线（`mcp` 2.x，streamable HTTP，端点 `/mcp`）

**验收**：Claude Desktop / Cursor 可通过 MCP 检索 owlet；发邮件必须经确认卡片。

### 阶段 5 — MCP Client 与主动能力（持续）

- [ ] 接入外部 MCP Server（Obsidian / 文件系统等），包装成同一 `ToolSpec` 注入 `REGISTRY`
- [ ] 每日简报：今日日程 + 未回复重要邮件 + 到期任务
- [ ] 会前准备：会议前 N 分钟汇总相关邮件与文档
- [ ] 长期记忆：用户偏好、常用联系人
- [ ] 关联发现：双链 + 语义相似度推荐

注意：外部工具须标记来源，避免再次 expose 造成环路；批量索引仍走原生 API，MCP 不适合搬运数万封邮件。

### 阶段 6 — A2A Server

- [ ] `/.well-known/agent-card.json`（v1.0 的 `supportedInterfaces[]` 格式，`skills[]` 自 registry 生成）
- [ ] task 生命周期映射到 LangGraph checkpoint

MCP 是「Agent 调用工具」（纵向），A2A 是「Agent 之间对等协作」（横向）。价值要到有第二个 Agent 时才体现，但前置条件（稳定 task ID、可持久化状态、artifact、流式）已由阶段 3 的 checkpointer 提供。

---

## 13. 待定决策与风险

| 项 | 说明 |
|---|---|
| 依赖版本 | `pyproject.toml` 初稿不写版本上下界，首次 `pip install -e .` 解析后再锁定 |
| Reranker 选型 | `bge-reranker-v2-m3` vs Qwen3-Reranker，阶段 1 用评测集实测决定 |
| 模型分工 | config 分「对话/工具调用」与「摘要/批处理」两类；9B 本地模型多步工具调用可能不稳定，复杂推理可切云端，但须控制外发内容 |
| 向量库替换 | 超过数十万 chunk 再考虑 Chroma / Qdrant / LanceDB；已由 `VectorStore` 接口隔离，跨边界的只有 chunk id |
| Postgres 迁移 | **不预留设计**。真迁移时大概率顺带上 pgvector，属一次性整体迁移。仅 FTS5 部分需重写，已由 `DocumentStore` 接口隔离 |
| 标题识别 | 还剩约 7% 误报，全在插图内部的大字标签。再往下压需要做图区检测或列左边界 / 居中判定，收益有限，暂不做 |
| 切块参数 | 500/800/120/80 是起点不是结论，要靠评测集定；改了会触发全库重建，这是设计上刻意可见的 |
| 桌面伴侣 / iOS 快捷指令 | 阶段 5 之后再评估 |

---

## 14. 起步顺序

1. ✅ 仓库骨架：`.gitignore` · `pyproject.toml` · 目录树
2. ✅ `domain/` 契约 + `web/src/lib/types.ts` 镜像 —— 前后端据此并行
3. ✅ `config.py` + `config/default.yaml`
4. ✅ `store/` —— SQLite schema + FTS5 + sqlite-vec
5. ✅ `llm/` + `ingestion/` 增量索引
6. ✅ `/api/v1/chat` 走 SSE，前端对接联调
7. 评测集 —— 没有它，rerank 与切块参数都只能靠感觉调
