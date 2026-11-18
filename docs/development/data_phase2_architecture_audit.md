# DynaLoop Data Phase 2.0 — 架构差异审查

审查日期：2026-11-01
审查类型：只读架构差异审查。除本报告外未修改其他文件。
审查依据：当前工作树中的源码、测试、配置和文档；不把 Protocol 或历史报告当作已运行能力。

## 1. 执行摘要

**结论：Data Phase 1 的领域模型与只读引用边界基本成立；Data Phase 2 的核心生命周期尚未实现，当前不能安全执行真实数据的采集、处理、质量检查、持久化或版本发布。**

实际已实现的是七类领域对象、部分领域不变量、三项只读 Protocol 和一个只读 DataFacade。它们能表达 Dataset/Version/分区/Snapshot/Lineage/质量报告的身份与引用关系，但没有 connector、processor、checker、repository 实现、存储适配器、写入入口、发布流程或端到端导入能力。

最重要的架构差距：

1. `DataPartition` 只描述逻辑分区和记录数，未引用实际存储内容；没有任何存储 manifest 或 reader 实现弥补这个映射。目标架构规定逻辑分区引用实际内容，当前尚无完整、可替换后端的解析边界。
2. 没有隔离暂存、完整性核验、原子发布或并发冲突处理；当前没有“已发布版本”的运行时生命周期保证。
3. Domain 有 `DatasetVersion.validate_content` 和 `DatasetSnapshot.validate_members`，但没有发布服务确保它们必然在提交前执行。
4. DataFacade 只有 Dataset/Version 查询和单分区读取；没有写入、Snapshot 读取、批量或条件访问。
5. 时间角色已区分，但没有表达时间粒度、到达频率，也没有 acquisition/checkpoint 能力。

Phase 1 对领域边界的冻结结论不应推翻。Phase 2 应在其上添加最小应用服务和适配器，并优先解决发布隔离与分区内容定位。无需新增平行领域模型、通用 ETL 引擎或分布式设施。

优先级含义：

- **P0**：在任何真实写入/发布生命周期投入使用前必须完成。
- **P1**：形成第一个可用的通用 Data 生命周期必须完成。
- **P2**：重要但可待真实消费者或更新语义明确后实现。
- **P3**：未来能力。

## 2. 现有架构概览

### 2.1 代码事实

- `src/dynaloop/data/domain/models.py` 定义七类核心对象，以及 `DatasetVersionReference`、`TemporalField`、`SnapshotPartitionSource` 和相关枚举/校验辅助逻辑。
- `src/dynaloop/data/domain/errors.py` 定义 Data 通用、定义、未找到、版本校验和 Snapshot 校验异常。
- `src/dynaloop/data/interfaces/protocols.py` 仅定义 `DatasetRepository`、`DatasetVersionRepository`、`DataReader` 三个只读 Protocol；当前没有实现类。
- `src/dynaloop/data/facade.py` 的 `DataFacade` 提供 `get_dataset`、`get_dataset_version` 和 `read_partition`。
- `src/dynaloop/data/__init__.py` 与 `domain/__init__.py` 导出领域值、异常、Protocol 和 Facade。
- 当前 `src/dynaloop/data/` 没有 acquisition、processing、quality checker、repositories、storage adapter 或 services 的实际实现。
- `tests/test_data_domain.py` 测领域对象与部分边界；`tests/test_data_facade.py` 测只读 Facade。没有 Data 生命周期的集成或端到端测试。
- `pyproject.toml` 要求 Python `>=3.11`，运行时 `dependencies = []`。
- README 与 `docs/development/data_domain.md` 将 Data 描述为领域模型/读取入口，并明确采集、存储、执行处理、持久化、质量评估仍未实现。`data_phase1_completion.md` 是 Phase 1 完成记录，不构成当前运行能力。
- `ARCHITECTURE.md` 保留既定 12 个顶层模块；Data 代码没有导入其他顶层业务模块。跨模块搜索未发现其他模块直接依赖 Data 内部实现。

### 2.2 实际依赖方向

`domain/models.py` 依赖标准库和 Data 自身异常；`interfaces/protocols.py` 依赖领域类型；`facade.py` 依赖领域值及 Protocol。Domain 未依赖文件系统、数据库、Pandas、NumPy 或其他业务模块。当前这种依赖方向应保留。

Repository、Adapter、Service 等目录或实现不存在；因此目前不能声称已实现分层持久化或生命周期协调。

## 3. 七个领域对象逐项审查

| 对象 | 当前实现与不变量 | 不可变性与跨对象一致性 | 缺失语义/建议 |
|---|---|---|---|
| `DataSource` | `models.py:147-161`：显式 source ID、名称、类型和可选描述；文本身份非空且去除首尾空格。没有凭据字段。 | frozen/slots dataclass；字符串和可选字符串不可变。Dataset 的 `source_ids` 尚无注册表来解析或校验。 | 定义保留。连接能力、采集配置、状态和凭据不属于该领域对象；凭据不应存入其中。 |
| `Dataset` | `models.py:164-192`：稳定 ID、名称、source ID 列表、可选 uniqueness rule、temporal fields、描述。 | `source_ids`、`uniqueness_rule` 转 tuple；TemporalField 为冻结值。当前不校验 source IDs 是否存在，也不对 Dataset 做持久化注册。 | 定义保留。注册/更新冲突策略在 Dataset 管理服务/持久化层完成；具体规则需由使用场景驱动。 |
| `DatasetVersion` | `models.py:230-291`：dataset/version ID、创建时间、raw/processed 层、分区、成对 schema ID/version、可选 `supersedes`。时间边界必须成对、aware，使用 UTC instant 比较且 end > start。`validate_content` 检查 Dataset ID、分区 ID/逻辑键唯一、分区时间边界及 supersedes 同 Dataset/非自引用。 | 分区输入复制成 tuple，DataPartition 冻结；但构造不自动运行 `validate_content`，也没有发布服务保证提交前运行。没有持久化状态、内容摘要或已发布标记。 | 定义保留。Phase 2 写入发布前必须调用并测试校验；发布不可变性由存储提交协议保证，不能仅靠 frozen dataclass 推断。 |
| `DataPartition` | `models.py:195-227`：逻辑分区 ID、分区键值、可选事件时间范围和非负记录数；拒绝重复键，时间范围为 aware 且严格递增。 | frozen/slots；键值对转为 tuple，时间值为 datetime。其内没有 physical reference/content ID。 | **需要补齐与存储内容的关联。** 目标架构要求逻辑分区引用其实际存储内容；当前只有逻辑 ID，无法从领域清单确定数据内容。可以使用不绑定后端的 opaque content reference 或定义稳定的 manifest 映射，但必须有明确的解析契约。 |
| `DatasetSnapshot` | `models.py:345-453`：不可变成员引用与 `SnapshotPartitionSource`；构造时拒绝重复成员、重复 Dataset-scoped 逻辑键，并要求 members 与来源映射使用的版本完全一致。`validate_members` 对调用方给出的候选版本查找明确分区，并校验版本分区/时间边界及键一致。 | 输入集合复制成 tuple，来源值冻结。可组合不同 Dataset/Version，无 ID/创建时间优先级；空 Snapshot 合法。没有 Snapshot Repository、持久化、创建服务或读取实现。 | 当前显式映射设计符合目标，应保留。生命周期层需保证 validate 成功后所引用版本不可变/可读，并实现按 Snapshot 来源读取；不要重做其来源规则。 |
| `ProcessingLineage` | `models.py:494-536`：非空操作身份/版本、一个或多个输入/输出引用、aware 执行时间、标量不可变参数；拒绝重复引用及输入输出相交。 | 输入输出复制成 tuple；参数限定为字符串、整数、有限浮点数、布尔值或 None，避免嵌套可变对象。未解析引用存在性，也没有与版本发布事务关联。 | 定义可满足最小追溯基础，应保留。Processor 执行、失败语义及输出版本和 lineage 的持久化关联尚未实现；更丰富执行上下文可后延。 |
| `QualityReport` | `models.py:540-561`：明确 DatasetVersion reference、规则集 ID/version、检查时间、PASS/WARNING/FAIL 状态和 findings。 | findings 转不可变 tuple；引用与状态为不可变值。 | 报告对象适合保存结果，但规则定义/版本注册、检查执行、报告持久化和发布策略都不存在。当前目标是“特定目标”时，现对象只覆盖 DatasetVersion；首个生命周期按 Version 评估可直接使用，若 Snapshot 也需成为质量目标，应先明确目标范围再扩展，不能臆造领域对象。 |

### Snapshot 与 Version 一致性专项判断

- Snapshot 的分区来源是显式的、Dataset scoped 的，测试覆盖历史修正替换及跨 Dataset 同键场景；没有基于版本排序的推断。
- `validate_members` 校验传入成员版本的分区唯一性、分区边界、来源 Dataset 和逻辑键，不能解析候选版本之外的存储内容。
- Snapshot 构造校验和候选版本校验分开；这并非自动发布能力。实际发布/读取服务必须在持久化和消费时调用校验。
- Snapshot 将各分区唯一来源映射到逻辑清单，但当前无 content reference，因此来源能定位逻辑 partition，不能在当前代码里定位数据字节。
- `DatasetVersion.validate_content` 是可调用的方法，不等于发布保护。未经服务层调用的候选定义仍可被创建并传入任何潜在写入者。

## 4. 数据生命周期能力矩阵

| 能力 | 当前状态 | 代码证据 | 差距 | 优先级 |
|---|---|---|---|---|
| 数据源身份描述 | 已实现（领域值） | `models.py:147-161` | 无连接器/凭据/访问配置；本对象不应承担这些职责。 | P1 |
| 可替换数据源连接器 | 未实现 | Data 下无 connector Protocol/实现；`protocols.py` 只有只读存储接口。 | 没有统一的 batch 入口或不同能力边界。 | P1 |
| 连接器能力描述 | 未实现 | 无能力类型/契约。 | 未表达 batch、incremental、polling、streaming 差异；Phase 2 MVP 只需 batch。 | P2 |
| 批量采集 | 未实现 | 无 acquisition service/adapter。 | 不能从本地历史文件创建数据候选。 | P1 |
| 增量采集 | 未实现 | 无 cursor/checkpoint 或增量边界。 | 后续需定义更新语义；首个 batch MVP 不需要提前做。 | P2 |
| 采集元数据/来源追溯 | 部分实现 | `DataSource` 和 `DatasetVersion` 身份存在。 | 缺少实际源文件/批次信息与版本的持久关联。 | P1 |
| Cursor/Checkpoint | 未实现 | 无对应字段/接口。 | 不影响单次完整历史 batch 导入；增量消费前需设计。 | P2 |
| 采集失败报告 | 未实现 | `errors.py` 只有通用定义/查找/校验错误。 | 没有行号、字段、阶段、可恢复性等导入错误上下文。 | P1 |
| 逻辑 Dataset/Version 定义 | 已实现（领域值） | `models.py:164-291` | 无注册/创建服务或持久化。 | P1 |
| 版本内容边界校验 | 部分实现 | `DatasetVersion.validate_content`，`models.py:280-341` | 没有服务保证发布前调用；不校验物理数据字节。 | P0 |
| 逻辑分区 | 已实现（领域值） | `DataPartition`，`models.py:195-227` | 未引用实际内容或物理清单。 | P0 |
| 数据内容持久化 | 未实现 | Data 下无 storage adapter/backend。 | 没有可读写数据存储。 | P1 |
| 元数据持久化 | 未实现 | 三个 Repository 都仅为 Protocol。 | Dataset/Version/Source 等定义重启后无从查询。 | P1 |
| 物理引用与逻辑分区分离 | 未实现完整映射 | DataPartition 无 physical/content reference；无 manifest 实现。 | 不能将 `partition_id` 解析为内容，无法验证后端替换是否透明。 | P0 |
| 暂存与原子发布 | 未实现 | 无写侧接口、staging 或 commit 实现。 | 部分写入可能被未来读取实现误当成版本；没有安全发布点。 | P0 |
| 内容完整性摘要/校验 | 未实现 | 无 checksum/hash/验证逻辑。 | 无法发现截断、缺块或存储后损坏。 | P0 |
| Dataset/Version 注册与不可覆盖发布 | 未实现 | `DatasetRepository`/`DatasetVersionRepository` 只有 `get`。 | 无发布冲突、幂等或并发写语义。 | P0 |
| Data Update 与发布分离 | 仅有概念基础 | Dataset/Version 身份区分；无更新或发布操作。 | 首个服务需明确候选更新到发布的提交边界。 | P0 |
| Snapshot 来源映射 | 已实现（内存领域校验） | `DatasetSnapshot`/`SnapshotPartitionSource`，`models.py:345-492` | 无存储、创建/查询服务和 Snapshot read。 | P1 |
| Processing 执行 | 未实现 | 无 Processor Protocol/Service。 | 不能由 raw 生成 processed version。 | P1 |
| ProcessingLineage | 已实现（领域记录） | `ProcessingLineage`，`models.py:494-538` | 无实际执行、持久化或与发布的事务关联。 | P1 |
| Schema 标识 | 部分实现 | Version 有成对 `schema_id`/`schema_version`。 | 无 schema 定义、解析/编码、校验或演进契约。 | P1 |
| 质量规则与版本 | 未实现 | `QualityReport` 仅保存 rule-set ID/version。 | 无规则集、规则接口或版本加载能力。 | P1 |
| Quality Checker 执行 | 未实现 | 无 checker Protocol/实现。 | 无法产生真实质量结果。 | P1 |
| QualityReport | 已实现（领域值） | `QualityReport`，`models.py:540-561` | 无报告持久化；finding 是文本；当前只关联 Version。 | P1 |
| Quality 与发布策略分离 | 已实现（对象语义）/未实现（流程） | `QualityStatus` docstring、Report 模型。 | 尚无流程消费 FAILED 并执行显式策略。 | P1 |
| 物理内容质量检查 | 未实现 | 无哈希/计数/重读核验。 | 语义质量报告无法替代存储完整性检查。 | P0 |
| 固定 Version 分区读取 | 部分实现 | `DataReader.read_partition`、`DataFacade.read_partition`。 | 无 Reader 实现、数据后端或有效分区内容；未实现批量一致读取。 | P1 |
| 条件查询 | 未实现 | Facade 只有单分区读取。 | 暂不影响第一批分区式消费。 | P2 |
| 增量读取 | 未实现 | 无游标/水位线接口。 | 需等 late-data/增量消费语义明确。 | P2 |
| Snapshot 读取 | 未实现 | Snapshot 仅领域对象。 | 研究消费者不能按固定 manifest 读取可复现视图。 | P1 |
| 未来流式订阅 | 未实现 | 无 subscription API。 | 当前无实时消费者，不应提前实现。 | P3 |
| 时间角色 | 部分实现 | `TemporalFieldRole`，`models.py:97-104`。 | 有角色和值字段映射基础，但没有按记录采集/持久化。 | P1 |
| 时间粒度、到达频率 | 未实现 | `TemporalField` 只有 role 和 field_name。 | 不能显式描述 granularity 与 arrival frequency；不要混用两者。 | P1 |
| Append/revise/backfill/replace/late arrival | 部分概念支持 | opaque Version、`supersedes`、显式 Snapshot 来源。 | 没有操作语义/版本提交流程；首个 batch MVP 不需一次实现所有更新类型。 | P1（最小发布语义）；P2（其余操作） |
| 并发与幂等发布 | 未实现 | 无写侧实现/冲突协议。 | 潜在覆盖或重复发布。 | P0 |

## 5. 数据访问接口审查

### 公开 Facade

`src/dynaloop/data/facade.py:21-79` 的 `DataFacade` 当前有：

- `get_dataset(dataset_id)`：查询 Dataset，校验返回值 ID。
- `get_dataset_version(reference)`：查询不可变版本，校验返回引用。
- `read_partition(reference, partition_id)`：先查版本，再把引用委托给 Reader。

这是一条小型、稳定的读取入口，适合保留。它不是 acquisition API、Dataset manager 或完整数据访问层。当前 `read_partition` 不直接检查 partition ID 是否在 Version 的 partition 清单中；Reader Protocol 文档约定未知分区需报告 `DataNotFoundError`，但当前没有实现来证明该行为。

### 内部 Repository/Reader Protocol

`src/dynaloop/data/interfaces/protocols.py:15-40` 定义：

- `DatasetRepository.get`
- `DatasetVersionRepository.get`
- `DataReader.read_partition`

Protocol 只说明结构化契约，不代表能力已运行。现有接口可支持固定 Version 的单分区读取；反复调用可能构成调用方批量读取，但没有批次一致性或 Snapshot 原子视图保证。接口没有查询谓词、游标、水位线、订阅或写入方法。

| 访问方式 | 当前判断 |
|---|---|
| 固定 Version 单分区读取 | **部分可表达**：Facade/Protocol 已有，但没有 reader 或物理内容映射实现。 |
| 批量读取 | **未定义为稳定能力**：可以重复单分区读取，但无批量一致性契约。第一版可先以分区粒度组成批量消费。 |
| 条件查询 | **未实现**：无 query 条件/查询语义，不是首个发布 MVP 必须。 |
| 增量读取 | **未实现**：无 cursor/watermark；待增量需求明确后设计。 |
| Snapshot 读取 | **未实现**：Snapshot 校验是领域方法，不等于 Reader 支持 manifest。 |
| 未来流式订阅 | **未实现且当前不需要**：无订阅消费者或 streaming backend。 |

建议维持公开 Facade 与内部 repository 的区分；Phase 2 先实现 Version/Partition 与 Snapshot 的稳定读取，再按实际消费者增加 query/batch 能力。不要要求所有 Adapter 实现后端不支持的访问方式。

## 6. 存储与一致性审查

### 当前状态

- Domain 不依赖 Storage，**领域层依赖方向正确**。
- `DataPartition` 仅逻辑 key/ID/时间/行数，没有实际内容 reference。
- 没有实际数据内容存储、元数据存储或二者的适配器。
- 没有内容格式、schema 编解码、内容摘要、manifest 文件或 Version 目录。
- 没有 staging、commit、原子发布或删除残留 staging 的行为。
- 没有并发写冲突、compare-and-set、唯一 Version ID 保证、发布幂等或恢复策略。
- frozen dataclass 保证 Python 对象字段不能重赋值，不保证磁盘内容不可被改写。
- Snapshot 的对象值不可变，但引用的版本/partition 内容当前没有存储后端，因此“并发更新期间保持可读且稳定”只成立于内存引用描述，不成立于数据生命周期。

### 后端可替换性

Domain 没有硬编码后端，未来在架构方向上可以替换存储；但当前还不能证明**实际存储可替换**：尚无明确的 content reference/manifest contract，也没有任何两个 adapter 可验证协议稳定性。

不应把物理文件路径直接加入 `DataPartition` 或公开 API。应先定义最小、不依赖具体 backend 的内容引用/manifest 边界，使 partition ID 到实际内容的映射由 Storage Adapter 管理并可校验。若目标架构坚持由 DataPartition 直接引用内容，则应扩展该已有对象的 opaque reference，而非新建无必要的持久化领域对象；此选择须在首次存储实现前定清。

### 必须遵守的发布不变量

任何 Phase 2 写入实现，在允许 Repository/Reader 发现版本前，至少要：

1. 把候选数据和元数据写入对读者隔离的 staging；
2. 检查完整写入、分区清单、schema/计数和内容完整性；
3. 调用 DatasetVersion 与 Snapshot 相关领域校验；
4. 通过一个不覆盖既有版本、可检测冲突的提交边界使其可见；
5. Reader 只从已提交的版本索引读取。

这是 P0 生命周期正确性，不代表必须建设分布式事务或恢复平台。

## 7. 依赖关系与模块化审查

### 通过项

- Domain 仅依赖标准库和自身异常；无 Data→Infrastructure/Market Environment/Model/Research 等跨模块实现依赖。
- Protocol 参数/返回值使用领域值和标准库 Iterable，没有暴露文件路径或数据库实体。
- Facade 依赖抽象 Protocol 而非具体 Repository，实现依赖倒置。
- 代码没有空的 Service/Adapter/Manager 体系；当前抽象数量少且与 Phase 1 目标相符。
- `pyproject.toml` Python 3.11+、无运行时依赖，符合轻量标准库方向。

### 需要补足而非重构的层

- 新增实际实现时，Service 应负责一次业务流程的协调；Repository/Storage Adapter 负责持久化；Connector 负责外部来源解码；Processor/Checker 分别负责处理和检查。
- 当前 Protocol 集中在单文件是合理的；新增接口只在有调用点与可测试实现时增加，不为每个名词创建空接口。
- 公开 DataFacade 与内部 Repository 要继续分开；调用者不应直接知道 staging 路径、文件格式或 Adapter 类型。
- `DataSource`/`Dataset`/`DatasetVersion`/`QualityReport` 目前均无持久化实现，不应在报告中称为“已经管理”。

未发现需要改变 12 个顶层模块、引入跨模块反向依赖或把 Research/Backtesting 责任转入 Data 的证据。

## 8. 架构风险与设计冲突

### R1 — 没有物理内容定位与完整性边界（高，P0）

`DataPartition` 只有逻辑身份与 record_count；Repository/Reader 没有实现。即便可构造 DatasetVersion，也无法证明其逻辑 partition 对应哪份内容，或内容完整、可复读。与“DataPartition 引用实际存储内容”和可替换 Storage 的目标存在差距。

### R2 — 不存在安全发布路径（高，P0）

当前没有写侧 Protocol/服务。没有 staging、校验、非覆盖 commit 或已发布版本索引，无法保证不完整数据不可见、并发发布不覆盖、Version 发布后内容不可变。Domain 的 frozen dataclass 不提供这些存储保证。

### R3 — 候选对象校验没有强制发布调用点（高，P0）

`DatasetVersion.validate_content` 与 Snapshot 的 `validate_members` 是显式调用方法；当前没有服务/仓库将其设为提交前置条件。后续写入实现若绕过它们，可把分区冲突、越界时间或引用不匹配的定义发布。

### R4 — 只有只读查询，没有管理生命周期（高，P1）

Dataset/Version/Source 没有注册；没有 Version candidate、发布、Snapshot 持久化/读取或 update/revise 操作。第一条真实数据路径无法开始。

### R5 — Processing/Quality 只有声明对象（高，P1）

Lineage 和 QualityReport 可记录结果，但无 Processor、Quality Checker、规则版本解析、执行服务或持久化关联。不能据此声称 raw→processed 或质量检查已存在。

### R6 — 时间描述未覆盖粒度与到达频率（中，P1）

TemporalField 区分四种时间角色，但模型未表达 time granularity 与 arrival frequency。前者描述记录时间精度/桶宽，后者描述数据进入频率；两者不可互相替代。若通用 Dataset 定义要作为消费者契约，需补充最小描述字段或明确其元数据来源。

### R7 — Snapshot 和 Version 的内存有效性未形成持久化一致性（中，P1）

Snapshot 显式映射实现合理且测试充分，但没有固定的 committed-version resolver/reader。若版本被覆盖或实际内容被修改，Snapshot 对象本身无法提供可复现性。

### R8 — 质量目标限定在 DatasetVersion（待明确，P2）

QualityReport 当前只能指 DatasetVersion。对首个“版本发布前质量门”足够；若目标架构要求对 Snapshot 或其他数据视图直接出报告，则属于范围差异，需要以消费者需求决定是否扩展，不应在本审查中强行新增 target 对象。

### R9 — Connector 能力及失败上下文未表达（中，P1/P2）

不存在 connector 或失败报告。Batch 是首个数据导入必需；incremental/polling/streaming 的差异化能力及 cursor/checkpoint 可后续实现，不应要求每个 connector 提供所有能力。

## 9. 建议修改事项

| 项目 | 为什么需要修改 | 涉及已有文件/接口 | 改变公开 API | 新增领域对象 | 可独立实施 |
|---|---|---|---|---|---|
| 1. 定义 partition 到内容的稳定引用/manifest 契约（P0） | 让逻辑 partition 能定位、校验实际内容，并让后端替换不泄漏路径。 | `domain/models.py:195-227` 的 `DataPartition`；`interfaces/protocols.py` 的 Reader；新增 Storage Adapter/manifest 实现。 | 若引用增加到 DataPartition 或公开 manifest 会改变领域构造 API；若以内部 manifest 解析 partition ID 可保持现有领域 API，但需明确契约。 | 不必新增持久化领域对象；优先扩展现有 DataPartition 或使用 Adapter 内部 manifest。 | 可独立先定义/评审；端到端验证需要存储适配器。 |
| 2. 建立候选版本 staging、完整性核验和不可覆盖提交（P0） | 直接满足不暴露半成品、版本不可变、并发发布不静默覆盖。 | 新增写入/发布边界；复用 `DatasetVersionRepository` 与 `DataReader` 的 committed-only 读取语义；`DataFacade` 可以保持 API 不变直到写用例接入。 | 内部 Protocol 可不改既有读 API；加入写入 Facade 方法才改变公开 API。 | 不需要新领域对象；staging/manifest 属于存储实现。 | 可独立于 CSV 采集先用内存/临时内容测试提交协议，但最终需结合真实 adapter。 |
| 3. 新增最小 Dataset/Version 注册与发布协调用例（P0/P1） | 保证 `validate_content` 在提交前执行，并统一身份冲突、已存在版本和发布顺序。 | `models.py:280-291`；只读 `DatasetRepository`/`DatasetVersionRepository`；新增发布 Service/写侧接口。 | 内部实现可不改；对外提供导入/发布入口时扩展 DataFacade。 | 不需要新增领域对象。 | 可与存储提交契约共同实施；不能只实现一个脱离 commit 的 service。 |
| 4. 实现可替换的 batch connector 与输入错误上下文（P1） | 第一个可用生命周期需要获取外部数据，且错误须定位来源、行/字段；connector 能力不可虚假统一。 | 新增 acquisition Protocol/CSV Adapter 和相应错误；`DataSource` 继续只作为身份描述。 | 通用 Facade 若公开导入操作会增加 API；connector Protocol 属内部扩展。 | 不需要新增持久化领域对象；可使用非持久化 request/result 数据结构。 | 可独立于 storage 先实现 parser/映射单测。 |
| 5. 实现确定的 Processing 路径并关联 lineage（P1） | `DataLayer.PROCESSED` 与 `ProcessingLineage` 当前只是描述，未产生处理输出。 | 新增 Processor 边界/处理 service；复用 `DatasetVersion`、`ProcessingLineage`。 | 是否改变公开 API 取决于是否通过 Facade 暴露导入流程；推荐不要单独暴露 Processor。 | 不需要新增领域对象。 | Processor 纯逻辑可独立测试；生命周期集成依赖版本读取/发布。 |
| 6. 实现质量规则执行、报告关联和显式发布策略（P1） | QualityReport 当前没有实际生成者；Quality FAIL 需报告但不能静默决定发布。 | 新增 Quality Checker/规则配置边界；复用 `QualityReport` 与 `QualityStatus`；发布 Service 消费 gate。 | 内部实现可不改公开 API；必要时 Facade 导入请求增加显式质量策略。 | 首版无需新领域对象。 | Checker 可独立测试；发布策略需与版本提交集成测试。 |
| 7. 支持固定 Version 和 Snapshot manifest 读取（P1） | 固定 Version 读取已有接口但无实现；Snapshot 是明确可复现视图，却无法消费。 | 实现 `DataReader`/Resolver；扩展 Facade Snapshot 查询/读取入口，保持单分区方法兼容。 | 添加 Snapshot 读取入口会扩展公开 API。 | 无需新领域对象；复用 Snapshot 与来源映射。 | Version reader 可独立实施；Snapshot reader 依赖 manifest/content reference。 |
| 8. 补全通用时间描述与采集时间语义（P1） | 已有角色枚举但缺少粒度/arrival frequency，后续通用消费者无法区分。 | `TemporalField`、`Dataset` 定义；采集 manifest/request 中的 ingestion/availability 实际来源。 | 改领域构造字段会改变 API（可通过可选字段向后兼容）。 | 不需要另建时间领域对象；优先向已有定义添加最小可选语义。 | 可独立评审/实现，但时间字段落地需与 connector/schema 契约一起验证。 |
| 9. 增量、polling、checkpoint、幂等重试（P2） | 对反复更新/late data 很重要，但首个完整 batch 生命周期尚未存在；提前统一会虚构所有 connector 能力。 | 按具体 connector 增加能力 Protocol/状态存储；DatasetVersion/`supersedes`/Snapshot 继续复用。 | 可能增加特定导入接口；不要求所有 connector 支持。 | 只有 checkpoint 需要实际持久状态时再判断，不预先新建通用领域对象。 | 可在 batch MVP 后独立实施。 |
| 10. 条件 Query、增量 Read、Streaming Subscription（P2/P3） | 由真实消费模式决定；当前没有 query/订阅消费者。 | 未来扩展 Reader Protocol 与 DataFacade，按后端能力分离。 | 会扩展公开 API。 | 不需要当前新增领域对象。 | 各自可按 consumer 独立实施；Streaming 为 P3。 |

## 10. 延后实现的能力

以下差距不应阻止首个安全、可复现的 batch MVP：

- Incremental/Polling/Streaming connector、cursor/checkpoint 与实时到达调度：先完成 batch 数据路径；Orchestrator 负责调度。
- 条件 Query、增量读取、流式订阅：当前只有固定版本分区读取消费者契约。
- 通用 connector 插件注册、处理 DAG/工作流引擎、规则 DSL、通用 ETL 平台。
- 分布式数据库、Kafka、数据湖、跨节点事务、分布式锁和复杂恢复平台。
- 多市场专用对象、金融算法/因子逻辑、研究标签、回测、校准和实验生命周期。
- 若当前只对 DatasetVersion 执行质量门，不需立即让 QualityReport 支持 Snapshot/任意 target。
- 通用 Schema Registry、复杂 schema migration；首批数据只需有明确、可复现的 schema/codec 版本。
- 自动删除坏数据/重复行、隐式 UTC、自动推断版本顺序。
- 未有独立消费者前不新增 Snapshot、Lineage、QualityReport 专用 Repository Protocol 集合。

## 11. Phase 2 建议实施顺序

按“先定义可发布数据是什么，再写入，最后扩展消费者”的顺序，保留 Phase 1 能力并尽量减少改动：

1. **锁定存储内容引用和记录/schema 契约（P0）**：决定 partition ID 到物理内容的后端无关映射；确定 canonical record 编解码、schema 版本和时间/粒度描述。不要把本地路径或某个 CSV 名称写入 Domain。
2. **实现本地 Storage Adapter 的 staging/commit 和 read-only adapter（P0）**：临时写入、内容完整性验证、不可覆盖提交；只让已提交 manifest 被现有 Repository/Reader 看见。明确同一文件系统原子提交边界及失败后行为。
3. **实现 Dataset/Version 发布协调（P0）**：写入前调用 `DatasetVersion.validate_content`；检查显式引用、已有版本冲突；调用 Adapter commit 后再使 DatasetVersionRepository 可见。读接口保持当前签名。
4. **实现 batch acquisition（P1）**：连接器能力只定义当前所需的 batch；输入映射、时间解析与错误定位独立于 Domain。以通用数据记录协议测试，不将股票字段变成核心领域类型。
5. **实现第一条 Processing 与 Quality 路径（P1）**：明确操作身份/版本、输入/输出引用、质量规则版本；QualityReport 关联候选版本；质量失败由调用流程显式 gate。
6. **通过 DataFacade 暴露完整导入用例并验证端到端（P1）**：现有只读 API 保持兼容；追加新 API 需实际外部消费者需要。覆盖采集/处理/质量/提交任一失败均不暴露不完整版本。
7. **接入 Snapshot 持久化与读取（P1）**：在 Version 存储和 content reference 稳定后，持久化显式映射并按映射读取；验证固定 Snapshot 在后续发布/修订期间保持相同内容。
8. **再按消费者增加更新及查询能力（P2+）**：依次评估 late-arrival/backfill、incremental acquisition、query、checkpoint；Streaming 最后处理。

### 本次测试结果

已实际执行完整测试套件：

```powershell
E:\anaconda\envs\dynaloop\python.exe -m unittest discover -s tests
```

结果：**99 项通过，0 失败，0 错误**。此结果验证当前已有领域和基础设施测试，不验证任何未实现的 acquisition、storage、processing、quality 或发布流程。

## 最终判断

- **可以进入 Phase 2 实施，但目前不能将 Data 用于真实数据写入/发布。**
- 第一阶段应先解决 P0：内容引用/manifest、原子隔离发布、版本冲突和发布前领域校验。
- Phase 1 七个核心领域对象整体应保留。最明显需要补齐的是已有 `DataPartition` 到实际存储内容的引用关系；是否以对象字段或 Adapter manifest 表达，应在首个 Storage 实现前依据既定“Partition 引用内容”原则明确，而不是新增一套平行领域架构。
- Snapshot 的显式映射、Version opaque identity、Domain/Storage 解耦、QualityReport 不决定发布等现有设计应继续沿用。
- Phase 2 可先只实现本地 batch MVP；增量、查询、streaming 及分布式能力按优先级延后。
