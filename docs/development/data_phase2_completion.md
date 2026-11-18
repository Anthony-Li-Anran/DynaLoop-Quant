# DynaLoop Data Phase 2 — Completion and Verification

日期：2026-11-04（Phase 2.1 质量门补记于 2026-11-05）
范围：对照 `data_phase2_architecture_audit.md`（2026-10-31）的 P0 发布不变量、§9 建议修改事项与 §10 延后清单，逐项核对 Phase 2 本地 batch 生命周期实现，并执行完整测试。
结论：**Data Phase 2 本地 batch MVP 已达成，可冻结。** P0 发布不变量全部满足；§9 十项中十项已落地（第 6 项质量门于 2026-11-05 以 Phase 2.1 补齐，见 §4）。

## 1. P0 发布不变量核对（§6）

| # | 不变量 | 实现 | 状态 |
|---|---|---|---|
| 1 | 候选数据写入对读者隔离的 staging | `infrastructure/filesystem_storage.py`：`write_staged` 经 `tempfile.mkstemp` 写入 root 下 `.staging/`，句柄按实例私有跟踪 | ✅ |
| 2 | 完整写入、分区清单、内容完整性核验 | `validate_staged`（SHA-256 + size）；`commit_staged` 重哈希比对 `ContentReference`；commit 后逐分区 `verify_content`；发布服务强制 partition_ids 与候选完全一致（missing/unexpected 均拒绝） | ✅ |
| 3 | 提交前调用 DatasetVersion / Snapshot 领域校验 | `services/publishing.py`：`complete_version.validate_content(dataset)` 先于 commit 执行；分区补齐 `content_reference` 后以完整版本重建，不发布无引用候选 | ✅ |
| 4 | 不覆盖既有版本、可检测冲突的提交边界 | 存储层 `os.link` + `FileExistsError` 路径：内容寻址同址冲突逐字节比对，不同内容拒绝替换；元数据层 `publish_candidate` 仅允许 `candidate → published` 转移，Head 按 `expected_head` CAS 比对，冲突抛 `DatasetVersionPublishConflictError` | ✅ |
| 5 | Reader 只读已提交版本 | `infrastructure/sqlite_repository.py`：全部版本读取 SQL 带 `status = 'published'` 过滤（get/list/head/内容路径共 5 处）；未提交候选对 Reader 不可见 | ✅ |

## 2. §9 建议修改事项逐项核对

| # | 事项 | 实现位置 | 状态 |
|---|---|---|---|
| 1 | partition → 内容稳定引用/manifest 契约（P0） | 领域对象 `ContentReference`（backend_id / storage_key / hash_algorithm / content_hash / size_bytes），opaque、不含物理路径；`DataPartition.content_reference` 承载；`backend_id = "dynaloop-local-file-sha256-v1"` 标识存储格式 | ✅ |
| 2 | staging / 完整性核验 / 不可覆盖提交（P0） | `filesystem_storage.py` 全量实现（§1 第 1、2、4 条） | ✅ |
| 3 | Dataset/Version 注册与发布协调（P0/P1） | `services/publishing.py`：注册定义比对（`registered_dataset != dataset` 拒绝）、发布前领域校验、commit → save_candidate → Head CAS 的顺序保证；失败清理 staging 并以 `ExceptionGroup` 上报清理错误 | ✅ |
| 4 | 可替换 batch connector 与输入错误上下文（P1） | `LocalFileAcquisitionAdapter`（chunk 流式读取）+ `CsvFormatAdapter`（编码/分隔符自动识别、编码探测）；错误带行号与字段定位（`CSV row {line_num} ...`、`Malformed CSV near line {line_num}`）；connector Protocol 未虚构 streaming/polling 能力 | ✅ |
| 5 | 确定 Processing 路径并关联 lineage（P1） | `services/processing.py`：`standardize_records` / `align_records_by_time` 纯函数 + `ProcessingService.process`（注入式 transform、读输入版本、发布输出、持久化 `ProcessingLineage`）；Facade `process()` 不单独暴露底层 Processor | ✅ |
| 6 | 质量规则执行、报告关联、显式发布策略（P1） | `SchemaQualityChecker`（规则集 ID/version 显式）、`QualityService.check_version`、PASS/WARNING/FAIL 三态报告持久化均可用；Phase 2.1 补齐显式门：`DataFacade.import_files` 必填 `quality_policy`，`gate_on_fail` 在 FAILED 时撤回版本并保留失败报告（详见 §4） | ✅ Phase 2.1 |
| 7 | 固定 Version 与 Snapshot manifest 读取（P1） | Facade `read_version` / `read_snapshot`（按 `partition_sources` 显式映射逐分区读字节）/ `read_incremental`（显式 byte-offset cursor）/ `query_json_lines`；Snapshot 持久化经 `SnapshotRepository` | ✅ |
| 8 | 时间粒度/到达频率最小描述（P1） | `Dataset.time_granularity: str | None`（`models.py:215`，可选、向后兼容）；到达频率由 `AcquisitionRecord` 的 cursor/boundary/mode 表达，未新建平行时间对象 | ✅ |
| 9 | 增量/polling/checkpoint（P2） | `AcquisitionMode.INCREMENTAL` + byte-offset cursor 已具备最小形态；polling/streaming/checkpoint 状态存储按计划延后 | ⏸ 延后 |
| 10 | 条件 Query / 增量 Read / Streaming（P2/P3） | `query_json_lines`（精确等值过滤）与 `read_incremental` 已满足当前消费者；streaming 按计划延后 | ⏸ 延后 |

## 3. §10 延后清单确认

以下按审计结论未实施，也不属于本 MVP 的完成条件：polling/streaming connector 与调度（Orchestrator 职责）、通用 connector 插件注册、处理 DAG/工作流引擎、规则 DSL、分布式设施、多市场金融对象、Snapshot/Lineage 专用读模型、Schema Registry。当前唯一活跃消费者是 interaction API 的 CSV 导入/预览/分布读取，固定版本分区读取契约已满足其需要。

## 4. 质量门接线（Phase 2.1，2026-11-05 已关闭）

审计 §9 第 6 项与 §11 第 5 步要求"质量失败由调用流程显式 gate"。Phase 2.0 的缺口在 Phase 2.1 关闭，设计如下：

- `DataFacade.import_files` 新增**显式必填**参数 `quality_policy`（`"report_only" | "gate_on_fail"`，无默认值，非法值抛 `DataDefinitionError`）。
- `gate_on_fail`：发布成功后运行配置的 `QualityService`；`FAILED` 时调用 `DatasetVersionRepository.retract_version` 撤回该版本（删除版本行、Head 恢复为 `expected_head` 或删除 Head 行，事务内完成），保留已提交的 content-addressed 孤儿内容与持久化的失败报告作为审计轨迹，随后抛 `QualityGateError`（API 映射 409）。`WARNING` 视为通过。
- `report_only`：保持 Phase 2.0 行为，不自动检查。
- 撤回仅用于显式运维反转（当前唯一调用点是质量门）；`retract_version` 对未发布/已撤回版本返回 `False`（幂等）。
- 前端 Import 表单新增 Quality policy 选择（默认 `gate_on_fail`）。

已知边界：`DataFacade.process` 的输出版本发布不经质量门（处理输出的质量语义由调用流程自行约定）；CSV 导入路径无 schema 时质量检查最多达到 `WARNING`。撤回与重新发布之间存在极小的时间窗（本地单进程下可忽略）；如需严格原子门，未来应将质量检查改为对 candidate 内容执行，属于 P2 增强。

## 5. 测试与验证

在 `E:\anaconda\envs\dynaloop\python.exe`（Python 3.11.18）执行：

| 检查 | 结果 |
|---|---|
| 完整后端套件 `python -m unittest discover -s tests` | **210 项通过，0 失败，0 错误**（Phase 2.1 新增 7 项：retract 语义 2、生命周期门控 3、API 策略 2） |
| 相关测试分布 | publishing 24、lifecycle 10、persistence 22、csv 10、facade 5、interaction API 17、distribution 15、domain 26 |
| 前端套件 `npx vitest run` | 16 项通过（CsvImportForm 断言 qualityPolicy 透传） |
| 前端类型检查 `npx tsc -b` | 通过 |
| 端到端实测 | 导入 `bank-additional-full`（41,188 行 / 21 列）→ 发布 → preview / JSON Lines 查询 / 列分布全链路可用；`quality_policy=gate_on_fail` 接受、非法策略 422、`gate_on_fail` 的 FAIL 撤回路径由生命周期测试覆盖 |

## 6. 冻结判断

**Data Phase 2 可冻结为"本地 batch 生命周期 MVP"**：采集（CSV/TSV ≤10 MiB）→ 处理 → 质量检查 → 原子发布 → Snapshot/固定版本读取的闭环真实可用、P0 不变量全部有实现与测试支撑，Phase 1 领域模型未推翻、公开 Facade 保持单一入口。

冻结同时明确两点边界：

1. 质量门（§4）已覆盖 `import_files` 导入路径；`DataFacade.process` 的处理输出发布不经质量门，消费该路径的调用方仍需自行约定质量语义。质量检查在发布后执行，撤回与重新发布之间存在极小窗口，严格原子门列为 P2 增强。
2. §10 延后清单（增量采集语义完善、条件查询、streaming 等）按消费者出现顺序再评估，不因本次冻结而承诺时间表。

`data_phase2_architecture_audit.md` 保留为 2026-10-31 历史审查记录；其 R1–R9 风险中 R1/R2/R3/R4/R5/R7 已由本次实现关闭，R6 以最小可选字段关闭，R8/R9 按 P2 延后。
