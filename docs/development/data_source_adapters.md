# Data 外部数据源接入（通用 adapter 设计）

本轮交付的是**「允许接入」这个能力本身**，不包含任何具体数据源实现。接什么 API、用哪家供应商由用户在页面填写；填一次保存后即可反复取数。页面组织见「页面结构：数据源是顶层」，配置链路见「运行时接入一个数据源」。

## 设计内核

核心只认三样东西：**原始字节、不透明游标、lineage**。URL、鉴权、分页、响应格式、时间语义全部归 adapter。契约越瘦，能接的源越多；一旦把 HTTP 或 JSON 写进核心，就只能接一类 API。

两个正交协议（笛卡尔积，不是继承层级）：

| 协议 | 职责 | 关键成员 |
|---|---|---|
| `SourceAdapter` | 取数，输出**未解析**字节 | `source_type` / `adapter_version` / `supported_modes` / `capabilities` / `fetch(request) -> FetchResult` |
| `FormatAdapter` | 解码成规范字节 + 记录数 | `format_id` / `supported_modes` / `decode(chunks, mode)` |

值对象（`data/domain/models.py`）：

- `FetchRequest`：`source_type`、JSON 可序列化的 `spec`、`mode`、opaque `cursor`。构造时把 `spec` 规范化成纯 JSON 数据，保证能落进 lineage。
- `FetchResult`：`chunks`（惰性字节块）、`boundary`（adapter 自命名，如 `byte-offset:` / `page-token:` / `vintage:`）、`cursor_start` / `cursor_end` / `next_cursor`、`metadata`。

## 数据流

```
POST /api/data/import/source
  -> normalize_spec(spec)           # reject credential fields
  -> registry.create(source_type)   # explicit key, no entry_points
  -> adapter.fetch(request)         # transport/auth/paging stay here
  -> format.decode(chunks, mode)    # optional; raw bytes pass through untouched
  -> publish_version(...)           # unchanged: staging, SHA-256, Head CAS
  -> quality_policy                 # unchanged: report_only / gate_on_fail
  -> AcquisitionRecord              # boundary + spec + adapter id + fetched_at + next_cursor
```

`AcquisitionService.import_source` 是通用编排器；`import_files` 保留为薄包装，把本地路径转成 `FetchRequest(source_type="local_file", spec={"path": ...})`，旧调用与旧测试不变。`DataFacade.import_source` 复用同一套质量门（抽出 `_apply_quality_gate`）。

## 可复现与凭据

外部源会变（复权回溯、修订、限流），所以这里的「可复现」= **可审计 + 可冻结**，不是「重发请求得到相同字节」。冻结的是本次响应字节；lineage 记录 `spec:<partition>:<key>`、`source_adapter`、`boundary`、`fetched_at`、`next_cursor` 与 adapter 自定义 metadata。

`spec` 绝不携带密钥：`normalize_spec` 拒绝 `api_key` / `token` / `authorization` 等字段（敏感字段集合可调用方覆盖），凭据由 adapter 自行从环境／凭据提供者解析，只把引用名写进 spec。

## 注册表

`AdapterRegistry` 是纯 key → factory → descriptor 容器，不含 adapter 语义。`build_default_registries()` 注册三个内置的零依赖实现：`local_file`（source，支持 batch/incremental）、`csv` 与 `kline-json`（format，均支持 batch）。`GET /api/data/adapters` 返回目录；注入自定义注册表时 `create_app` 会同步给 facade，目录与实际导入不会不一致。

## K 线 JSON → 表格

`KlineJsonFormatAdapter`（`format_id = kline-json`）把腾讯 `fqkline/get` 的响应解码成表格记录：从 `data.<symbol>` 中挑出行数组，每行映射为 `date / open / close / high / low / volume` 六列，输出与 `CsvFormatAdapter` 相同的 JSON-lines 记录布局。因此预览、列分布、质量门无需改动；`api.py` 用 `RECORD_FORMAT_IDS` 判定哪些格式属于「记录型」，前端 `DatasetPreviewPage` 用同一集合决定是否发列统计请求。

- 行数组的键由「频率 + 复权」决定，九个键全部支持：`day / qfqday / hfqday`、`week / qfqweek / hfqweek`、`month / qfqmonth / hfqmonth`。早期版本只认 `qfqday / day`，选周线、月线或后复权会被误报 `has no daily rows`。
- 空字节、非法 JSON、`code != 0`、空 `data`、空行数组、列数不足一律抛 `DataDefinitionError` —— 不发布空版本。空行数组的报错会明确指出「检查标的、日期区间（start 必须早于 end）与频率」，不再把所有原因压成一句兜底信息。
- 原始字节仍走 `Raw bytes` 冻结，不预览；两者都是同一条发布链路，只是 `format_id` 不同。
- 前端 Fetch 表单的 `Data format` 里对应选项是「A-share K-line (JSON to table)」；`Per-request parameters` 留空则用数据源保存的 `param`，填写时格式为 `symbol,frequency,start,end,limit,adjust`。

## 接一个新 API 要做什么

只写一个 adapter 文件并注册，**不改核心、不加核心依赖**：

```python
class FredAdapter:
    source_type = "fred"
    adapter_version = "1.0"
    supported_modes = frozenset({AcquisitionMode.BATCH})
    capabilities = frozenset({"vintage"})

    def fetch(self, request: FetchRequest) -> FetchResult:
        # Resolve credentials from the environment, never from request.spec.
        raw = call_http(request.spec)                # paging lives here
        return FetchResult(
            chunks=(raw,),                           # unparsed response bytes
            boundary=f"vintage:{request.spec['vintage']}",
            next_cursor=None,
            metadata=(("transport", "https"),),
        )

registry.register("fred", FredAdapter, descriptor={...})
```

需要 HTTP 客户端或 SDK 时走 optional extras + 延迟导入，`pyproject.toml` 核心依赖不动。流式源可用同一个 `fetch` 返回惰性 `Iterable[bytes]`，但在线通道应按 session/segment 追加日志、结束后再冻结版本，不要每 tick 发一个 Snapshot 版本。

## 运行时接入一个数据源（无需写代码）

用户填一份配置，保存后立刻成为一个可导入的 source adapter：**不改核心、不写插件、不重启服务**。配置有两类，`kind` 决定用哪个实现：

- `kind="api"` → `ConfiguredHttpAdapter`，标准库 `urllib.request` 发请求（零新增依赖）。
- `kind="local"` → `ConfiguredLocalAdapter`，把保存的文件路径委托给内置的 `LocalFileAcquisitionAdapter`。

```
Data management 面板（Local / API 两块）
  -> POST/PUT /api/data/api-sources   # 配置落盘到 state_directory/api_sources.json
  -> register_api_sources(...)        # 即时注册，按 kind 分派
  -> POST /api/data/import/source     # 原有链路，不改
  -> publish / quality gate / Snapshot / AcquisitionRecord
```

`ApiSourceConfig` 字段：`key` / `name` / `url`（API 端点或本地路径）/ `kind` / `method` / `query` / `headers` / `body` / `credential_value` / `credential_env` / `credential_name` / `credential_in` / `cursor_param` / `timeout`。`request.spec` 覆盖或追加查询参数；凭据可直接填值或给环境变量名，只保存在服务端，`GET` 时打码 `***`，**永不进入 spec、lineage 或 Snapshot**。HTTP 源 `boundary` 为 `http:<status>:sha256:<digest>`，本地源为 `byte-offset:<n>`。

`create_app` 启动时会重新注册已存配置，所以跨重启保留。插件式 adapter 仍保留在代码层，供签名鉴权 / WebSocket / SDK 这类无法用配置描述的源使用，但不在页面上暴露。

## 页面结构：数据源是顶层

Operations 即 **Data management**，只有两级：

1. **数据源**分「Local sources」「API sources」两块。每块可新增、编辑、删除；每条源可 Fetch data 发布一个新版本 —— 表单里可指定 **Dataset ID / Dataset name**，默认按 `param` 里的标的代码派生（`sh000688` → `ds-sh000688` / `sh000688 daily`），同一 ID 发新版本、不同 ID 建新数据集；手动改过就以填写值为准。Local 块里另有固定的「Uploaded files」行，承接浏览器上传的 CSV。
2. **数据集**挂在所属源下面（按 `api-<key>` / `local-<key>` / `local-upload` 归属）：**数据集名本身是链接**，点击进入独立预览页 `/data/datasets/:datasetId/preview`（版本、列概览、分布、样本行、Missing-value policy），返回按钮回 `/data?view=operations`；改（Rename 元信息）、删（Archive 软删；Archived 区可 Restore 或二次确认后 Delete permanently）、增（Fetch / Upload）仍在子层级内联完成，没有额外按钮或弹层。
   - 预览只对**记录型**数据集开放（`csv` 与 `kline-json`）；`raw-bytes` 这类按原始字节冻结的数据在预览页明确显示「Preview not supported yet」，不发列统计请求。
   - **A 股腾讯接口是 API 数据源，不是数据集**：出现在 API sources 块里。取数时在 `Data format` 选「A-share K-line (JSON to table)」即可发布成可预览的六列表格；选 Raw bytes 则只冻结字节、不预览。同一 dataset_id 换格式前需先 Archive（复用归档 ID 会替换描述性定义并恢复可见）。

界面上不出现 adapter、format_id、source_type 等内部术语；这些只在代码层存在。数据源被删除后，它已发布的数据集不会消失，统一归到「Uploaded files」行下（只读分组，仍可查/改/删）。「改数据」永远是发布新版本，不是原地修改；归档只在 `dataset_archive` 里记一个 ID（隐藏标记），定义、版本、内容对象一律不动。所有判断「某个数据集 ID 是否占用」的链路都必须走 `DataFacade.visible_datasets()`，不要各自过滤；归档 ID 被重新 Fetch 时可以复用，此时只替换描述性定义（名称 / 源 / 格式）并清除隐藏标记，旧版本仍留在版本链上。

**归档 ≠ 删除，彻底删除是另一条独立链路**：Archived 区每行有 `Restore` 与 `Delete permanently`，后者必须二次确认（`Yes, delete forever`）才会调用 `DELETE /api/data/datasets/{id}/purge`。护栏与语义：

- 只允许删除**已归档**的数据集（未归档返回 409，不存在返回 404），避免误删在用数据。
- 一个 SQLite 事务内删掉定义、`dataset_heads`、全部版本（含 candidate）、归档标记，以及归属该数据集的 quality report / acquisition record；若还有 snapshot 或 lineage 引用它则**拒绝删除**，避免静默破坏跨数据集溯源。
- 事务提交后才按内容哈希做引用计数：仅当没有任何存活版本引用同一 `storage_key` 时才 unlink 字节文件 —— 两份数据集取到相同内容时，删一份不会动另一份的字节。
- 执行结果返回 `deleted_versions / deleted_objects / deleted_bytes / deleted_metadata`，前端展示在提示条里。删除不可逆，`restore` 对已删除 ID 返回 404。

## 端点

- `GET|POST /api/data/api-sources`、`PUT|DELETE /api/data/api-sources/{key}` — 数据源增删改查，密钥打码。
- `GET /api/data/adapters` — 内部目录（调试用，前端不展示）。
- `GET /api/data/datasets` — 可见数据集；`GET /api/data/datasets/archived` — 已归档。
- `PATCH /api/data/datasets/{id}` — 改名称/描述；`DELETE /api/data/datasets/{id}` — 归档；`POST /api/data/datasets/{id}/restore` — 恢复；`DELETE /api/data/datasets/{id}/purge` — 不可逆彻底删除（仅已归档，级联元数据与未共享字节）。
- `POST /api/data/import/source` — 取数并发布；`POST /api/data/import/csv` — 上传 CSV。

## 明确不在本轮范围

任何具体数据源（FRED / yfinance / 交易所流 / 学校订阅库）的内置实现、模拟盘与订单链路、真钱交易。

## 验证

```
E:/anaconda/envs/dynaloop/python.exe -m unittest discover -s tests -p "test_*.py" -q
cd frontend && npm run test && npx tsc -b
```

正式测试见 `tests/test_data_source_adapters.py`（模拟 REST adapter 验证 opaque boundary、spec lineage、凭据拒绝、format 组合）、`tests/test_api_sources.py`（配置持久化、两种凭据、游标、重启后仍可用、打码与编辑保留、删除注销）、`tests/test_data_management.py`（本地文件源发布、PUT 编辑保留密钥、数据集改名/归档/恢复、归档 ID 换格式复用、彻底删除定义/版本/字节、未归档拒绝、共享字节保留）与 `tests/test_kline_json_format.py`（六列映射、qfqday、空/坏负载拒绝、注册表、端到端发布 + 预览 + 列分布、raw-bytes 仍 415）。前端见 `DataManagement.test.tsx`（Local/API 分组、数据集挂在源下、CRUD 与取数、K 线格式选项）与 `DatasetPreviewPage.test.tsx`（记录型格式可预览、raw-bytes 明确不支持）。
