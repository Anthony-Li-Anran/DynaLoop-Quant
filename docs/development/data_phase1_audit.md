# DynaLoop Data Phase 1 — Independent Implementation Audit

审查时间：2026-10-31  
审查类型：只读代码审查；本报告文件是本次唯一新增文件。  
总体结论：**有条件通过**。领域骨架、模块边界和学习任务保留方式整体符合当前阶段目标；没有发现任务 A/B/C 的核心实现被辅助代码偷偷完成。发现一项确定的时间范围校验缺口：`DatasetVersion` 接受反向或零长度的事件时间范围。另有一项 Snapshot 重叠策略被测试/学习说明预先固定，但它不是已冻结架构明确规定的规则，宜作为设计风险而非代码正确性缺陷处理。

本审查不是发布就绪或数据平台完整性认证。学习任务 A/B 仍未实现，相关验收测试按设计失败；没有对这些失败作“通过”解释。

## 1. 审查范围及实际检查文件

直接检查了工作树中的实际文件：

- `ARCHITECTURE.md`、`PROJECT.md`、`README.md`、`pyproject.toml`
- `src/dynaloop/data/__init__.py`
- `src/dynaloop/data/domain/__init__.py`
- `src/dynaloop/data/domain/errors.py`
- `src/dynaloop/data/domain/models.py`
- `src/dynaloop/data/interfaces/__init__.py`
- `src/dynaloop/data/interfaces/protocols.py`
- `src/dynaloop/data/facade.py`
- `tests/test_data_domain.py`
- `tests/test_data_facade.py`
- `tests/test_data_learning_tasks.py`
- `docs/development/data_learning_tasks.md`
- Infrastructure 相关实现：`src/dynaloop/infrastructure/__init__.py`、`resources.py`
- Market Environment 相关实现：`src/dynaloop/market_environment/definitions.py`

同时检查了 Data、Infrastructure、Market Environment 之间的导入关系、Python 版本、依赖声明、包结构、Git 状态、受跟踪差异和未跟踪文件。

### Git 基线说明

审查开始时，`git status --short` 为：

```text
 M README.md
?? .gitignore
?? ARCHITECTURE.md
?? docs/
?? pyproject.toml
?? src/
?? tests/
```

`git ls-files` 显示仓库当前仅跟踪 `LICENSE`、`PROJECT.md`、`README.md`。因此 Data 源码、测试、架构文件、pyproject 和学习文档在本次审查开始前均已是未跟踪文件；对这些文件无法依据 Git HEAD 作逐行差异审查，本报告依据工作树实际内容审查。开始时唯一受跟踪差异是 README 的既有修改。开始时 `git diff --check` 未报告问题。

## 2. 架构一致性检查表

| 项目 | 结论 | 证据与理由 |
|---|---|---|
| 1. Data 职责边界 | 通过（限定于 Phase 1） | `ARCHITECTURE.md` 保留既定 12 个顶层模块；Data 当前只有数据源、Dataset/版本、逻辑分区、manifest、lineage 身份和质量报告模型，以及读取边界。没有把因子研究、策略回测、统计校准或实验记录实现放入 Data。实际能力见 `src/dynaloop/data/domain/models.py:44-298`。采集、处理、持久化等尚未实现，README 对此有说明。 |
| 2. 与 Infrastructure / Market Environment 边界 | 通过 | Data 源码没有导入这两个模块；Infrastructure 只导出自身配置、日志、运行环境和资源接口；Market Environment 的 `ArtifactReference` 仍是外部身份引用，未被 Data 替代。两个方向均未出现跨模块实现依赖。 |
| 3. Domain 独立于 Storage | 通过 | `domain/models.py` 只依赖 dataclasses、datetime、enum 和 Data 自身异常；没有文件、数据库、Pandas、NumPy 或 Storage import。没有存储后端类。 |
| 4. Dataset / Version / Partition / Snapshot 概念 | 通过，存在有意未完成部分 | `Dataset` 表达逻辑身份；`DatasetVersionReference` 以 dataset/version 两个 ID 表达版本；`DatasetVersion` 持有不可变版本描述；`DataPartition` 明确为逻辑分区；`DatasetSnapshot` 是版本引用 manifest。引用解析和组合校验明确留在任务 A/B。 |
| 5. 逻辑分区与物理存储 | 通过 | `DataPartition` 文档明确不是物理文件；协议和 Facade 只按逻辑分区 ID 读取，没有把路径、文件格式或存储位置塞入领域对象。 |
| 6. 数据更新与 Dataset Version | 无法判断运行时行为；概念表达通过 | 没有更新、发布或写入服务，因而无法审查“更新何时形成新版本”的操作语义。当前稳定 Dataset ID 与显式、opaque version ID 分离，且版本对象冻结；没有错误地把更新时间推导成版本号。 |
| 7. Raw / Processed / Lineage | 存在有意未完成部分 | `DataLayer.RAW/PROCESSED` 能区分版本层次；`ProcessingLineage` 当前仅有身份，尚无输入输出关系，也没有 DatasetVersion 到 lineage 的引用。此缺口对应任务 C，不是被隐藏的已实现能力，但目前不能声称已保留 transformation lineage。 |
| 8. QualityReport 对版本及规则版本的关联 | 通过（引用层面） | `QualityReport` 保存 `DatasetVersionReference`、rule-set ID/version、检查时间和状态；不管理规则或版本，也不因 FAILED 自动阻止发布。 |
| 9. 四类时间语义 | 部分通过 | `TemporalFieldRole` 分开表达 event、ingestion、availability、processing；分区及版本范围只使用 event-time 字段。时间值要求 aware datetime。已确认 `DatasetVersion` 没有检查其自身范围端点的先后顺序，详见问题 #1。 |
| 10. 抽象、职责和循环依赖 | 通过 | 当前仅有三个读取 Protocol 和一个 Facade；没有空的 services/repositories/adapters 层。Data 内部导入方向为公共入口 → Facade/interfaces/domain，domain 不依赖 Facade 或接口；未见循环依赖。 |

## 3. 七个领域对象逐项审查

### 3.1 DataSource

- 位置：`src/dynaloop/data/domain/models.py:94-108`
- `source_id`、名称、来源类型和可选描述足以表达来源身份与基本描述；ID/必需文本非空且去除首尾空格。
- 是冻结 dataclass，只有字符串/None 字段，不存在外部可变集合。
- 它不是 connector，也不执行采集；这符合当前“领域对象骨架”范围。
- 来源 ID 是否必须指向一个登记过的 DataSource，当前没有注册表或跨对象验证，属于有意未提供的能力。

### 3.2 Dataset

- 位置：`src/dynaloop/data/domain/models.py:111-139`
- 稳定 `dataset_id` 与名称明确；source IDs、uniqueness rule 和 temporal fields 有显式字段，没有把这些核心约束全部藏入 metadata。
- 入参 list 会复制成 tuple；TemporalField 自身冻结，source IDs 与 uniqueness keys 是不可变字符串，当前不存在可从外部修改内部集合的明显路径。
- `source_ids` 可含重复值、`uniqueness_rule` 可含重复键或空 tuple、`temporal_fields` 可有重复定义；当前没有已冻结规则规定这些一定非法，不能作为确定缺陷。实现数据处理时需要结合真实 schema/consumer 再决定其约束。
- Dataset 记录自身定义，不代表数据版本或物理位置。

### 3.3 DatasetVersion

- 位置：`src/dynaloop/data/domain/models.py:177-233`
- Dataset ID 与 opaque version ID 分开；创建时间要求时区感知；DataLayer 是枚举；分区集合转换为 tuple；schema ID/version 成对出现；supersedes 使用显式 `DatasetVersionReference`。
- 分区对象本身冻结，故转换成 tuple 后不会因外部修改原列表或分区对象而变化。
- **确定问题**：事件时间边界只检查两个端点成对出现并分别为 aware datetime，没有比较 `event_time_end > event_time_start`。因此反向和零长度的 DatasetVersion 时间范围会被构造接受。`DataPartition` 对应范围已有 UTC 瞬时比较，但 DatasetVersion 没有同等校验。见问题 #1。
- `validate_content` 只有明确的 `NotImplementedError`，没有调用其他辅助函数进行隐藏校验；这是任务 A 的显式练习入口。
- 发布状态、数据内容、存储、内容哈希和历史修正流程均不在此对象中；当前范围不要求它们。

### 3.4 DataPartition

- 位置：`src/dynaloop/data/domain/models.py:142-174`
- 明确是逻辑分区；有分区 ID、逻辑键值、可选 event-time 范围和非负记录数。
- `partition_values` 会深拷贝 pair 集合，内层也转换为 tuple；端点 aware，并转换为 UTC 后比较真实时间顺序，但保存原始 datetime，不修改输入。
- 时间范围必须成对提供且严格递增；record_count 排除 bool、负数及非整数。
- 当前允许重复逻辑键名的 pair（例如一个 `partition_values` 内出现两次 `symbol`）。冻结要求没有明确写明构造单个 partition 时重复键必须被拒绝；但这会使逻辑分区表达含糊，作为低优先级风险/待决不变量记录，不作为确定的必修缺陷。任务 A/B 对重复 partition identity / key 的验收还应区分对象内重复键与跨分区冲突。
- 字符串化的分区键值简单、轻量，但不能表达原生数值/日期类型；当前没有指定类型化 partition value 契约，因此属于待真实 consumer 决定的设计取舍。

### 3.5 DatasetSnapshot

- 位置：`src/dynaloop/data/domain/models.py:236-260`
- `snapshot_id` 与成员引用集合明确；只持有 `DatasetVersionReference`，不复制数据、不加载目标。
- 入参 list 被转换为 tuple，引用对象本身冻结；不可通过原始 list 修改 Snapshot。
- 构造函数不拒绝空成员、重复成员或不存在的目标；目标存在性必须由 `validate_members` 在调用方给出候选版本时判断。这些缺失与任务 B 对应。
- `validate_members` 明确仍抛 `NotImplementedError`，没有隐式解析或全局查询。
- 测试与学习文档把“同一 Dataset 的多个版本重复覆盖同一逻辑分区键”规定为拒绝规则。这个策略不是顶层架构中明确冻结的事实，可能是合理的一致性约束，但也可能限制 Snapshot 组合历史修正版的用法；应作为任务 B 的待确认语义，而不是把该策略当作已确定项目要求。

### 3.6 ProcessingLineage

- 位置：`src/dynaloop/data/domain/models.py:263-274`
- 当前只有显式 lineage ID 和基本文本校验；未出现输入、输出、operation、参数或执行时间字段。
- 因而没有预先替开发者决定多输入/多输出关系表示。其唯一字段属于结构骨架，不是“偷做”任务 C。
- 也意味着当前代码尚不能追溯 processed DatasetVersion 的来源；这是清楚标记的阶段缺口。

### 3.7 QualityReport

- 位置：`src/dynaloop/data/domain/models.py:277-298`
- 绑定明确的数据版本引用和质量规则 ID/version；检查时间要求 aware datetime；status 以枚举表达；findings 深度转换成 tuple 字符串。
- FAILED 是报告状态，不触发发布决策；符合质量失败不必然阻止发布的架构原则。
- 不验证 dataset version 或规则对象存在，这是仅引用、不接管产物生命周期的正确边界。

## 4. DatasetVersion 学习任务完整性审查

检查入口 `DatasetVersion.validate_content`（`models.py:228-233`）及其构造函数、字段校验辅助函数（`models.py:10-42,195-218`）：

| 能力 | 实际状态 | 证据 |
|---|---|---|
| 数据集身份匹配 | 未实现 | `validate_content` 直接抛 `NotImplementedError`。 |
| 分区身份重复检查 | 未实现 | 构造函数只确认每个成员为 DataPartition 并冻结集合；未比较 partition_id。 |
| 逻辑 partition key 一致性 | 未实现 | 没有辅助函数或其他调用路径做该检查。 |
| 分区与版本 event-time 边界一致性 | 未实现 | 构造函数只验证版本范围端点成对/aware，不将分区端点与版本端点比较。专门验收测试将失败。 |
| supersedes 数据集一致性/自引用校验 | 未实现 | 构造函数只确认该字段是 DatasetVersionReference；不比较 dataset_id/version_id。 |
| opaque ID 排序/递增 | 未实现且未发现违规实现 | 版本字符串未作时间解析或排序。 |
| 记录级 uniqueness rule 校验 | 不可能由当前对象完成 | 版本对象不持有记录值；学习文档已说明不应声称仅凭元数据检查实际记录唯一性。 |

**结论：没有发现通过辅助函数、属性、构造函数或其他路径提前完成任务 A 核心逻辑。** 当前构造函数实现的是结构性类型、成对字段、时区与浅层引用类型校验；不等于内容边界验证。

测试覆盖方面，`test_duplicate_partition_identity_is_rejected` 检查重复 partition ID；没有单独的 DatasetVersion 级“不同 ID 但逻辑键相同”用例。任务 A 文档要求重复逻辑键测试，但当前具体验收测试没有覆盖该场景，属于测试覆盖缺口。

## 5. DatasetSnapshot 学习任务完整性审查

检查入口 `DatasetSnapshot.validate_members`（`models.py:255-260`）、构造函数（`models.py:246-253`）和其他 Data 辅助逻辑：

| 能力 | 实际状态 |
|---|---|
| Snapshot reference 到候选 DatasetVersion 的解析 | 未实现；方法显式 `NotImplementedError`。 |
| 未找到成员引用 | 未实现；有失败验收测试。 |
| Snapshot 重复成员检查 | 未实现；构造函数保存重复引用，验收测试覆盖。 |
| 候选版本重复/引用歧义检查 | 未实现；验收测试覆盖。 |
| 同一 Dataset 多版本逻辑分区冲突 | 未实现；验收测试覆盖。 |
| 其他位置的旁路解析/验证 | 未发现。没有 repository、registry 或 Storage 查询。 |

**结论：任务 B 的引用解析和组合逻辑没有被提前完成。** 但当前测试及学习文档已固定同 Dataset 重复逻辑键必须拒绝的策略。这可能是可接受的清晰行为规格，也可能过早替开发者解决了组合语义设计；现有架构资料无法判定，应在任务 B 开始前确认。

## 6. ProcessingLineage 学习任务完整性审查

`ProcessingLineage`（`models.py:263-274`）只保存 lineage ID。全 Data 源码和公共 API 中未发现输入/输出引用、映射关系、operation version、参数、执行时间或 lineage 校验辅助实现。

**结论：仍然是必要骨架，没有预先规定多输入、多输出关系模型。** 这符合任务 C 的设计挑战要求。需注意，README 将它称为“身份骨架”是准确的，不能据此宣称 provenance 已可用。

## 7. 测试执行结果

使用 Python 3.11.18（`E:\\anaconda\\envs\\dynaloop\\python.exe`），从仓库根执行：

| 测试项 | 命令 | 结果 |
|---|---|---|
| Data Domain | `python -m unittest discover -s tests -p test_data_domain.py` | 13 项运行，13 通过，0 失败，0 错误。 |
| Data Facade | `python -m unittest discover -s tests -p test_data_facade.py` | 5 项运行，5 通过，0 失败，0 错误。 |
| Data 学习验收 | `python -m unittest discover -s tests -p test_data_learning_tasks.py` | 10 项运行，0 通过，0 失败，10 错误。 |
| 完整套件 | `python -m unittest discover -s tests` | 96 项运行；86 通过、0 失败、10 错误。 |

学习验收测试的 10 个错误全部源于明确的 `NotImplementedError`：

1. `DatasetSnapshotLearningAcceptanceTests.test_duplicate_candidate_reference_is_ambiguous_and_rejected` — `DatasetSnapshot.validate_members` 尚未实现。
2. `DatasetSnapshotLearningAcceptanceTests.test_duplicate_snapshot_member_is_rejected` — 同上。
3. `DatasetSnapshotLearningAcceptanceTests.test_missing_referenced_version_is_rejected` — 同上。
4. `DatasetSnapshotLearningAcceptanceTests.test_same_dataset_versions_cannot_claim_the_same_partition_key` — 同上。
5. `DatasetSnapshotLearningAcceptanceTests.test_valid_references_from_multiple_datasets_compose` — 同上。
6. `DatasetVersionLearningAcceptanceTests.test_dataset_identity_mismatch_is_rejected` — `DatasetVersion.validate_content` 尚未实现。
7. `DatasetVersionLearningAcceptanceTests.test_duplicate_partition_identity_is_rejected` — 同上。
8. `DatasetVersionLearningAcceptanceTests.test_partition_must_fit_declared_version_event_time_boundary` — 同上。
9. `DatasetVersionLearningAcceptanceTests.test_supersedes_reference_must_be_valid_for_this_dataset` — 同上。
10. `DatasetVersionLearningAcceptanceTests.test_valid_version_content_passes` — 同上。

这些是预期的学习任务错误，不是断言失败；但完整测试命令当前确实以非零状态结束，若 CI 将其当作全绿门禁会失败。代码和学习文档均明确披露该状态，没有使用 skip、弱化断言或假实现伪装通过。

测试质量总体可用：正常构造、错误类型、深层集合冻结、UTC 时间顺序、Facade 查找及缺失行为都有明确断言。已发现的覆盖不足包括：DatasetVersion 自身反向/零长度事件时间范围没有用例；任务 A 的逻辑键重复用例不完整；Snapshot 空成员集合的合法性仍未决定。测试使用固定输入是单元测试常规做法，不构成不当硬编码。

## 8. 工程质量问题

### 已确认问题

1. **DatasetVersion 范围缺少顺序校验（中等）**  
   `src/dynaloop/data/domain/models.py:189-218` 只验证端点成对及 aware，没有拒绝 `end <= start`。Partition 已做相同类型的 UTC 实际时间比较，版本层边界却没有。可能使无效范围进入 Snapshot 或后续消费者。

### 潜在风险 / 需要确认的设计取舍

2. **Snapshot 重叠策略未见上位架构决策（低至中）**  
   `tests/test_data_learning_tasks.py:136-147` 和学习任务说明为不同版本间相同逻辑 partition key 规定了冲突失败。这可能正确，但不是明确冻结的规则；尤其历史修正、覆盖版本的 manifest 语义未定义。先确认规则再把测试当作不可变规格。

3. **学习测试导致全套 unittest 非零退出（低，已披露）**  
   这是本阶段特意保留的学习测试；有意如此并非实现 bug。后续可在课程/CI 流程明确分开“已实现基线”与“学习验收”命令，避免误报，但本次不做修复。

4. **Snapshot 为空的语义未定义（低）**  
   构造函数允许空 manifest，当前没有契约说明空 Snapshot 是合法空输入还是误配置。任务 B 文档也将此留为边界判断。

5. **领域对象表达不了实际记录级质量/唯一性（范围限制）**  
   目前 DatasetVersion 不持有记录载荷；`uniqueness_rule` 只能声明，不能在纯 domain model 中检验实际记录重复。文档正确区分了这一点。实现 Data processing/quality consumer 时应负责真实内容检测。

### 已核实无问题的工程项

- 当前环境 Python 为 3.11.18；语法和使用的标准库满足 `requires-python = ">=3.11"`。
- `pyproject.toml` 声明 `dependencies = []`；未发现 Data 的第三方运行时依赖。
- Data 子包均有 `__init__.py`；顶层公共入口导出模型、异常、Protocol 和 Facade。
- Data 依赖只指向标准库和自身模块；未发现 Infrastructure、Market Environment、Model、Inference 或 Statistical 模块反向/横向依赖。
- Protocol 仅包含 DataFacade 当前读取职责所需的 Dataset 查询、版本查询和分区读取；未机械创建 Storage、Acquisition、Processing、Quality 或 Snapshot 等空接口。
- 文档如实声明阶段边界、开发者任务和测试失败原因；未发现与实现相反地声称任务 A/B 已完成。
- 本次没有运行格式化或修复，也没有新增依赖。

## 9. 风险等级排序

| 排序 | 等级 | 发现 | 分类 |
|---|---|---|---|
| 1 | 中 | DatasetVersion 可接受反向或零长度 event-time 范围 | 已确认正确性问题 |
| 2 | 低-中 | Snapshot 对同一 Dataset 跨版本重复逻辑 partition key 的拒绝策略没有上位架构依据 | 设计待确认，不是已确认 bug |
| 3 | 低 | 完整 unittest 当前有 10 个预期学习任务错误 | 已披露的阶段性工程风险 |
| 4 | 低 | 空 Snapshot 是否合法没有明确契约 | 待确认边界 |
| 5 | 低 | 逻辑 partition key 值仅以字符串表示，且单个 partition 的 key 名可重复 | 当前简单性取舍；待真实数据/consumer 决定 |

## 10. 是否建议进入开发者学习阶段

**建议进入，但将其定位为领域模型学习阶段，不作为生产可用 Data 能力。** Data 的核心 ID、版本引用、不可变基础对象、逻辑分区/manifest 边界和最小读取入口已足以支持练习；没有发现学习任务已被代码绕过或替做。

建议开发者首先完成**任务 A：DatasetVersion 内容边界与引用校验**。原因：

1. 它是 DatasetVersion 的基础一致性边界，也是 Snapshot 消费版本前的前置领域约束。
2. 开始时应先确认/实现版本事件时间边界的左右端点顺序及 UTC 比较，并补上当前缺失的回归测试。
3. 再处理 Dataset identity、partition identity/key、分区范围及 supersedes 关系；opaque version ID 不做递增推断。
4. 在进入任务 B 前，先讨论并确认“同一 Dataset 不同版本重复覆盖同一逻辑 partition key”的 Snapshot 策略，避免把未冻结的业务语义当作既定事实。
5. 任务 C 应继续先做关系模型设计评审，再编码；当前骨架没有妨碍该学习目标。

## 11. 最终判断

Data Phase 1 **整体有条件通过**：架构边界与轻量实现路线基本合格；任务 A/B 核心逻辑仍清晰留给开发者，任务 C 未被预先定型。进入学习阶段是合理的，但不能把 10 个学习验收错误报告为通过，也不能在当前状态下宣称 Data 模块具备可发布数据、可解析 Snapshot 或完整 lineage 能力。首先应解决 DatasetVersion 时间边界的有效性，并在任务 B 前确认 Snapshot 重叠语义。
