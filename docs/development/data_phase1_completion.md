# DynaLoop Data Phase 1 — Completion and Verification

日期：2026-11-01
范围：完成 Data Phase 1 遗留领域实现，清除学习阶段临时内容，执行测试与独立复核。
结论：**Data Phase 1 已完成，可冻结为领域模型与引用边界基础。** 这不代表采集、存储、处理执行或发布流水线已经实现。

## 1. 完成的遗留任务

### DatasetVersion

- 事件时间范围端点必须同时存在或同时缺失；提供时必须是 timezone-aware `datetime`。
- 构造时将端点转换为 UTC **仅用于比较**，要求结束瞬时严格晚于开始瞬时；保存的原始 datetime 不转换、不替换。
- `validate_content` 验证传入 Dataset 类型及 Dataset ID。
- 验证一个版本中的 partition ID 和逻辑分区键唯一。逻辑键按键值集合比较，不受 pair 顺序影响；DataPartition 本身拒绝重复键名。
- DatasetVersion 声明事件时间范围时，每个分区都必须声明范围，且分区范围必须包含在版本范围内。左右边界遵循 `[start, end)`。
- `supersedes` 只能指向同一 Dataset，不能指向自身。opaque version ID 和创建时间不用于推断版本先后，也不解析被引用目标是否存在。
- 不验证记录级 uniqueness rule，因为当前对象不包含记录内容。

### DatasetSnapshot

- 新增不可变 `SnapshotPartitionSource`。它将 Dataset 范围内的逻辑分区键映射到明确的 `DatasetVersionReference` 和具体 `partition_id`。
- Snapshot 成员引用必须恰好等于其分区来源映射实际使用的版本引用；拒绝重复成员和重复逻辑分区来源。空 Snapshot 表示空视图。
- 验证仅使用调用方传入的 DatasetVersion 候选对象；拒绝重复候选引用、缺失成员、缺失分区、版本内部无效分区 ID/逻辑键/时间边界，以及 Dataset ID 或逻辑键与来源分区不匹配。
- 同一 Dataset 的不同版本可以共同组成 Snapshot。历史修正通过显式映射选择修正版分区，同时保留旧版本中未修正的分区；不按版本 ID、创建时间或隐含优先级解决冲突。
- Snapshot 保持 manifest/reference 边界，不复制数据、不访问 Storage/Repository、不解析外部注册表。

### ProcessingLineage

- 将身份骨架补为不可变的一次处理记录：显式 lineage ID、操作名及 opaque 操作版本、一个或多个输入版本引用、一个或多个输出版本引用、时区感知执行时间和参数。
- 定义关系语义：列出的每个输出都由指定操作对完整输入集合产生；不承担执行处理、分配版本或解析引用目标的职责。
- 输入/输出集合均拒绝空集合和重复引用，同一版本不能同时出现在输入与输出中。
- 参数采用不可变键值对，键唯一；值限于字符串、整数、有限浮点数、布尔值或 `None`。嵌套/可变参数结构不属于本阶段模型。

## 2. 文件变更及原因

| 文件 | 变更 |
|---|---|
| `src/dynaloop/data/domain/models.py` | 完成 DatasetVersion 时间/分区/supersedes 校验；新增 Snapshot 分区来源映射和验证；补全 ProcessingLineage；强化参数及重复逻辑键校验。 |
| `src/dynaloop/data/domain/__init__.py` | 导出 `SnapshotPartitionSource`。 |
| `src/dynaloop/data/__init__.py` | 在 Data 公共入口导出 `SnapshotPartitionSource`。 |
| `src/dynaloop/data/interfaces/protocols.py` | 将只输出记录的 `DataReader` Protocol 类型变量改为协变，满足类型规则。 |
| `src/dynaloop/data/facade.py` | 仅整理参数校验格式；公共方法和行为保持不变。 |
| `tests/test_data_domain.py` | 将领域对象、时间边界、分区引用、历史修正 Snapshot、跨 Dataset 组合及 lineage 行为纳入正式测试；保留原有正式测试并补充回归覆盖。 |
| `README.md` | 更新 Data 能力描述，移除已完成学习任务的状态说明。README 在本任务开始前已是工作树中受跟踪的修改文件。 |
| `docs/development/data_domain.md` | 新增长期有效的领域边界、时间语义、Snapshot 来源规则、Lineage 参数限制及暂缓能力说明。 |
| `docs/development/data_phase1_completion.md` | 本工程交付与验证报告。 |
| `docs/development/data_learning_tasks.md` | 删除已完成的教学任务/提示文档；其长期有效约束已迁移到 `data_domain.md`。 |
| `tests/test_data_learning_tasks.py` | 删除只为练习保留、依赖 `NotImplementedError` 的临时验收测试；实际行为覆盖已迁入 `test_data_domain.py`。 |

`docs/development/data_phase1_audit.md` 保留且未修改，作为 2026-10-31 的历史审查记录。其指出的 Snapshot 组合规则待决事项已由本任务的明确分区来源映射决策解决；时间范围问题也已实现修正。该文件记录的是当时状态，不作为当前实现状态报告。

## 3. 测试、静态检查与依赖

在 `E:\anaconda\envs\dynaloop\python.exe`（Python 3.11.18）执行：

| 检查 | 命令/方法 | 结果 |
|---|---|---|
| Data Domain | `python -m unittest discover -s tests -p test_data_domain.py` | 26 项通过。 |
| Data Facade | `python -m unittest discover -s tests -p test_data_facade.py` | 5 项通过。 |
| 完整套件 | `python -m unittest discover -s tests` | 99 项通过，0 失败，0 错误。 |
| Python 语法/字节码编译 | `python -m compileall -q src tests` | 通过。 |
| Data 公共导入 | 导入 `dynaloop.data` 的 Snapshot、来源映射、Lineage、Facade | 通过。 |
| 依赖一致性 | `python -m pip check` | No broken requirements found。 |
| Data 源码 Pylance 诊断 | workspace Pylance diagnostics | Data models、Facade、interfaces、公共导出没有诊断。 |
| Patch whitespace | `git diff --check` | 通过。新增/更新 Python 与 Markdown 文件另作行尾空白检查，通过。 |

项目 `pyproject.toml` 没有 mypy/pyright/ruff/flake8 等类型检查或 lint 配置；当前终端也没有这些独立命令，因此没有宣称运行了不存在的检查器。Pylance 对 Data 测试文件的 `dynaloop.data` import 报 `reportMissingImports`：实际工作区分析设置 `python.analysis.extraPaths` 为空，且 Pylance 当前环境仍为系统 Python 3.11，而终端测试明确使用 dynaloop Conda 环境。终端环境的包导入和完整测试均通过。Workspace 还报告 Infrastructure `resources.py`、Market Environment `definitions.py` 的已有类型诊断；这两个冻结模块未作修改。

未新增或更改运行时/开发依赖；`pyproject.toml` 仍声明 `dependencies = []`。

## 4. 清理结果

- 删除学习任务文档和专用学习验收测试，不再有预期 `NotImplementedError` 导致完整 unittest 失败。
- 任务 A/B/C 的实际行为现在由正式测试覆盖。
- 搜索 Data 源码、正式 Data 测试、README 和领域参考文档，未发现学习任务标记、相关 TODO、`NotImplementedError` 或已删除文档引用。
- 长期有效的 Snapshot、Lineage、时间和引用语义迁移到 `docs/development/data_domain.md`。
- 保留审查记录，不清理无关模块或工程文件。

## 5. 独立复核结论

实现后再次逐项复核了 DatasetVersion、Snapshot、Lineage、错误类型、不可变集合和公开导出，并重新运行完整测试。复核确认：

- Snapshot 的每个逻辑分区只有一个显式来源；不同 Dataset 使用各自的逻辑键命名空间。
- 同一 Dataset 跨版本的修正不依赖时间或 ID 顺序；测试包含时间较早但 ID 排序不同的修正版选择。
- DatasetVersion 和 Snapshot 的校验没有绕过引用模型访问 Storage 或全局注册表。
- ProcessingLineage 仅记录引用及处理声明，没有调用或内嵌数据处理执行。
- DataFacade 公共 API 未改变；Infrastructure、Market Environment 和其他顶层模块未修改。
- 未发现新的越界职责或阻止冻结的 Data 模块实现缺陷。类型检查覆盖仍受上述 Pylance workspace 路径配置限制。

## 6. 剩余范围与冻结判断

仍未实现且不属于本次领域模型收尾的能力：数据采集、物理存储、数据转换执行、发布/回滚生命周期、记录级质量检查、外部引用的仓储解析与序列化。这些能力需要真实消费者、持久化或生命周期契约后再设计。

**Data Phase 1 可以冻结为不带采集、持久化和执行能力的领域模型与显式引用基础。** 后续实现应通过新增的正式行为和接口扩展，不应把当前对象解释成已经提供完整数据平台。
