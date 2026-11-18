# Project instructions

更新：2026-11-15。此文件只保留日常开发所需约束。

## 0. Scope and sources

- 用户当前要求优先于仓库文档。项目定位是创新且可靠的 QUANT × AI 开源工程，以可运行、可复现、可验证和可扩展为目标，不以发表论文为目标；交易执行指模拟撮合。
- 架构、算法、评估和论文主张相关任务先读 `docs/CORE_DESIGN.md`：它定义终局分层与**当前阶段目标（产出高质量的有效因子，作为后续决策的「身体」）**，并如实标注现状与该目标的差距。涉及「因子是否有效 / 如何判定 / 统计保证口径」时**必须再读 `docs/factor_evaluation_baseline.md`**（评估指标与晋升门槛的权威来源，逐项对齐 Qlib / alphalens / `arch` 并标明来源）、`docs/effective_factor.md`（择时通道）与 `docs/cross_section_factor.md`（选股通道），后两者分别是各通道隔离与错误率口径的权威来源，不得互相套用。**禁止自创阈值**：新增指标或门槛必须先在上述基线文档登记上游依据。历史神经路径是暂缓实现的阶段外记录，不代表放弃该方向。当前实现契约见 `docs/system_contract.md`，其中早期盘点仅为历史快照。
- **本项目做中低频，面向个人研究**；涉及研究流程、数据底座、因子实现、评估或晋升的任务**必须再读 `docs/research_process.md`**（流程与验收口径的权威来源）。日线数据、决策周期日 / 周 / 月量级、默认持有期 21 个交易日；决策与成交分离、标签成熟后评分；频率 / 持有期 / 调仓间隔进规格与指纹；分钟或小时数据不得混入同一判定族凑样本量。流水线 L0–L6 各层的个人版裁剪标注见规范第四节，L5 是各通道「有效」断言的唯一出口；中低频功效靠宽度或时间长度补，**禁止**为提高功效提频、缩短间隔或放松门槛。
- **机构标准只作参照系，不作合规要求**：可裁剪容量扫描、借券融资与冲击成本精细建模、制度化上线治理、商业级时点成分股重建（须标注幸存者偏差未消除）、正式立项系统；**不可裁剪**时点数据、防前视、预注册冻结、族级错误率控制、稳定性与留一法、全参数留痕、成本与换手显式且毛净并列。分组单调性、多空双腿方向、净价差按 Qlib / alphalens 口径**只作描述性报告，不是晋升否决**（见 `docs/factor_evaluation_baseline.md`）。**禁止**以「面向个人研究 / 灵活处理」为由放松统计正确性门槛——个人没有内控与同行评审，统计层反而更该硬。
- **Part A 双通道并列，均已实装**：**通道一 选股（横截面）** 实现 `research_engine/cross_section.py`、权威口径 `docs/cross_section_factor.md`；**通道二 择时（单标的时序）** 实现 `temporal.py` / `effectiveness.py` / `catalog.py`、权威口径 `docs/effective_factor.md`。两者都是合法研究对象，**不是缺陷、不是要推倒重来**。零假设、基线、样本结构全不同，**禁止**混进同一判定族、共用族级错误率控制或互相外推结论；各自预注册、冻结、晋升、出带指纹的证据条目（`channels.py` 的 `enforce_channel` / `evidence_from_report` 强制校验，混族直接抛错）。输出结论**必须带通道标签**「横截面有效因子 / 择时有效因子」，**已写入两份判定器的报告、逐候选结论与 `spec`**。合成两类证据属 Part B。六项工程默认值（标的池、节奏、通道二合并、撮合参数、L4 边界、A→B 接口）已于 2026-11-15 定稿于 `docs/research_process.md` §8，改动只对新轮预注册生效、不得回头改已冻结轮次。评估指标与晋升门槛的权威来源是 `docs/factor_evaluation_baseline.md`（开工必读），**新增指标或门槛必须先登记上游依据，禁止自创阈值**；附加纯报告指标不得升 `schema_version`（会经配置序列化进入冻结指纹）。
- 修改数据源、回测接入或图表时读 `docs/data_ui_contract.md`，其他任务不必加载。
- 区分已实现能力、实验结果与研究目标；统计保证必须说明适用假设，不能仅凭方法名称宣称成立。
- 本阶段交付物是**经得起检验的有效因子本身**（只读索引 `experiments/factor_stream/effective_factor_registry.json`），验收准则是「同一套预注册流程可重复执行，并如实给出肯定或否定结论」。已认证出有效因子**不等于每轮都必须出**：族级不显著、全族证伪、证据不足都是**合法的统计结论**，不得为凑肯定结论而改族、换窗口、调参数或放松门槛；「稳定产出」指流程可重复，不宣称跨轮稳定或未来持续。不得把研究报告、`provisional`（暂时通过）、`exploratory`（探索性）或描述性区间当作有效因子交付。`docs/factor_research.md` 中的限制声明描述当前实现，不得改写以冒充已达成。
- **通道二**判定「择时有效因子」必须走 `research_engine/effectiveness.py`，**通道一**判定「横截面有效因子」必须走 `research_engine/cross_section.py`：两者都遵守**因果隔离（一次性冻结 + 冻结日之后的历史样本外数据一次性验证，冻结动作发生在接触验证数据之前）+ 抗数据窥探的族级检验（全族共用时间索引路径的区块自助法 + 最大统计量逐步下降，数学工具在 `resampling_tools.py`，族与零假设各自独立）+ 跨期稳定性与留一法**，三者缺一不可。评估指标（排序信息系数、信息系数比率、t 统计量、分组收益、多空毛净、换手、信息比率）与「哪些是门槛、哪些只报告」**以 `docs/factor_evaluation_baseline.md` 为准，不得自创阈值**；分组单调性、多空双腿方向、净价差为描述性诊断，不再一票否决。**禁止复用另一通道的零假设与基线**（通道一零假设是无相对排序能力、基线随机排序 / 等权；通道二零假设是不胜过零预测与历史均值）。**禁止**用高信息系数、单次留出通过、排行榜名次或描述性区间替代；**禁止**放松显著性水平、稳定性门槛或期数要求来凑出肯定结论；某轮验证窗口被查看后即**消耗**：再搜索 / 调参必须开新族、用新的未消耗区间，并在产物里登记全部前序轮次与消耗窗口；跨轮序贯错误率明确不宣称。`diagnose_cross_section` 只用于回顾性 / 诊断性窗口，本就结构上不能出结论。宣称保证时必须同时写明条件与不宣称项（跨轮序贯、共形覆盖、盈利、因果）。**评估指标必须严格对齐 Qlib / alphalens，但仅凭「信息系数高即入选」不算认证**：认证层必须叠加族级错误率控制与预注册冻结。
- **搜索侧主线（Anthony 11-15 明确指令，开工必读 `docs/learned_factor_workflow.md`）**：**原模原样按 Qlib 搭**——先验只允许 Alpha158 / Alpha101 这类标准特征库，由**可训练模型从数据里学出因子与预测关系**；模型输出的预测分数就是学得因子。**禁止**随机生成一堆公式去跑验证（低效）、**禁止**拿固定模板乱套、**禁止**自创架构或自作主张加花俏层、**禁止**再自己拍脑袋定因子。代码在 `src/dynaloop/learned_factors/`，按 Qlib 模块边界**本地仿写、不 import `pyqlib`**（后期要改），逐层可替换：`provider` / `expression` / `alpha158` / `handler` / `dataset` / `model` / `workflow`。旧路线（15 个手写模板、`factor_search.py` 枚举筛选、DEAP 文法随机采样、乘性权重抽样、6 个已认证因子）**只作历史对照，不得当作研究能力或交付成果**；统计保证只保护结论、不证明搜索侧能力。评估指标与晋升门槛仍以 `docs/factor_evaluation_baseline.md` 为准，第五层认证出口不变。
- 三段角色分工（见 `docs/CORE_DESIGN.md`）：**Part A 量化研究员**（当前阶段，稳定产出有效因子的自进化研究器，优先复用 qlib / RD-Agent(Q) 等成熟实践，不强制醒睡机制）→ **Part B 量化策略**（参照 Kronos 类 K 线基础模型，消费 A 的因子作为额外信息，醒睡机制与组合优化在本层）→ **Part C 量化交易员**（拿信号做交易决定，模拟撮合）。A 未达成前不得声称 B / C 已交付；A→B 接口已定稿为带通道标签与指纹的 `FactorEvidence` 加只读注册表，B→C 接口留待 Part B 设计，不得由现有实现倒推。
- 遇到研究瓶颈，先检索原始论文、公开基准和复现代码，明确对照与失败判据后再改算法。

## 1. Working agreements

### 1.2 Responsibility

AI 负责授权范围内的设计、实现、测试与文档，不安排用户编程练习。`practice/` 和旧 learning-tasks 文档仅作历史参考。

### 1.3 Before changes

先检查相关代码与现有变更，简述修改理由；用户已经授权的修复直接执行。保留无关改动，不因文件未跟踪而删除它。

### 1.6 Delivery

报告实际改动、运行过的验证及结果、剩余限制。无需固定分工口号或重复检查表。清理本任务的临时文件和进程，保留交付物。

## 2. Engineering

- 模块内部职责单一、组件可替换；模块间通过包级公开接口直接组合。优先复用已有能力和成熟库，不复制逻辑或为解耦另建平行实现。
- 不为未来愿景扩展当前任务范围；不留假实现或把占位逻辑当完成。
- 数据与结果应可追溯；记录配置、种子、版本和实际窗口，避免未来信息泄漏、静默丢数据及伪造缺失值。
- 对行为变化添加有意义的回归测试，运行受影响测试和必要构建；未运行或失败的检查如实说明。
- 用户界面统一英文、规范术语，涨红跌绿。原始数据、派生指标、引擎结果、视图配置保持明确边界。

## 3. Environment

- Python / pip 只使用 `E:\anaconda\envs\dynaloop\python.exe`；环境不可用时报告，不改用其他解释器。VS Code 保持同一解释器。
- 安装 Python 包前核对 `sys.executable` / `sys.prefix`；缓存和安装临时文件留在该环境内，不用 base、系统 Python 或 `--user`。
- 前端依赖在 `frontend/` 用本地 npm 管理，不全局安装。
- 测试使用独立状态目录（`DYNALOOP_STATE_DIRECTORY`），不要触碰用户日常数据库。

## 5. Revision

2026-11-11：按用户要求精简重复规定、固定话术与历史流水账；保留项目方向、模块边界、环境和验证要求，数据 / UI 细则改为按需读取。AI 全权实现的安排不变。

2026-11-14：确立 Part A 的统计学判定口径（不照抄 Qlib / RD-Agent(Q)）。新增 `docs/effective_factor.md` 为「有效因子」权威口径，`research_engine/effectiveness.py` 为实现，`experiments/factor_stream/effective_assessment.py` 为真实数据实证；`docs/CORE_DESIGN.md` 将「判定口径尚未拍板」改为已定稿。§0 增列冻结窗口三支柱与禁止绕过的条款。本轮未改动既有生产模块语义（`temporal.py` / `holdout.py` / `catalog.py` / `factor_research.md` 限制声明均保持原样）。

2026-11-15：Anthony 定调「项目做中低频，整个流程要像量化机构那种」。新增 `docs/research_process.md`（七层投研流水线、频率口径、现状对照、不可绕过清单、待拍板点、一手依据）；`docs/CORE_DESIGN.md` 增列中低频定位与机构级流程一节，如实标注「当前研究单元是单标的时序、不是横截面」这一结构性差距；`docs/effective_factor.md` 补适用范围声明；§0 增列中低频与流程必读条款。本轮只动文档，未改任何生产代码。

2026-11-15（三次修订，Part A 通道一落地）：按 Anthony「把 Part A 做完并验收通过」补齐第二条通道。新增 `docs/cross_section_factor.md` 为**横截面有效因子**权威判定口径（零假设 = 无相对排序能力，基线 = 随机排序 / 等权；宽度只降每期测量噪声、不制造独立期数；三道独立门槛；宣称与不宣称分层）。新增 `research_engine/channels.py`（通道常量、中文标签、带指纹证据条目、混族硬拒绝）、`resampling_tools.py`（两通道共用的数学工具，通道盐隔离随机流）、`cross_section.py`（L1–L4 诊断 + L5 冻结族级检验，以及**只出诊断不出判定**的 `diagnose_cross_section`）。`effectiveness.py` 重构为转调共用数学工具并补通道标签，**11-14 实证族级 p=0.9840 与指纹逐位复现**。`tests/test_cross_section_factor.py` 57 项 + 12 子测试全绿，后端全量 624 passed / 132 subtests，`compileall` 干净、前端源码中文字符数 0。`experiments/factor_stream/cross_section_assessment.py` 产三份产物：合成正控制（1 有效 + 噪声未通过）、真实 qlib 归档 259 个月末横截面的 **L1–L4 诊断且认证标记 WITHHELD**（所有冻结前可得窗口均视为已消耗）、面向 2026-11-13 之后真实到达数据的一次性预注册冻结文件。§0 与本文档、`docs/CORE_DESIGN.md`、`docs/research_process.md`、`docs/effective_factor.md` 同步现状。**统计层一寸未让**：真实数据至今仍无有效因子被认证。
> **状态注记（2026-11-15 五次修订补）**：本条记录的是**当时**的状态，不得当作现状阅读。其中的「三道独立门槛」已被四次修订废除（无上游依据）、「WITHHELD / 等未来真实到达」已被四次修订判为口径错误、「真实数据至今无有效因子」已被四次修订的认证结果取代。现状以 `docs/factor_evaluation_baseline.md` 与 `experiments/factor_stream/effective_factor_registry.json` 为准；此处保留原文只为审计沿革。

2026-11-15（二次修订，当晚）：Anthony 定调「面向个人的研究，不必严格遵守机构那套，选股和具体股的择时可以两方面都有」「好，我们可以灵活处理！你做吧」。把 `docs/research_process.md` 重写为**个人研究版双通道**规范：新增「可裁剪（规模 / 合规驱动）vs 不可裁剪（统计正确性驱动）」分层；确立**通道一 选股（横截面，待建）**与**通道二 择时（单标的时序，已实装）**并列，两者零假设 / 基线 / 样本结构不同，禁止合并判定族或共用族级错误率控制，输出必须带通道标签；七层流水线逐层标注个人版裁剪；现状对照由「结构性差距 / 需横截面化」改为「通道二已实装（不是缺陷）/ 通道一待建」；不可绕过清单补 2 条，待拍板补 3 项。同步 `docs/CORE_DESIGN.md`、`docs/effective_factor.md` 零节与 §0 必读条款。**统计层一寸未让**：可省的是成本，不是证据。本轮只动文档，未改任何生产代码。

2026-11-15（四次修订，口径纠偏 + 对齐上游实践）：Anthony 两条纠正——①「产出有效因子是用过去数据做的，没让你真在未来去验证」；②「别自己想标准！严格参考按照 Qlib 和其他 GitHub 上的优秀实践来」。据此：
- **因果隔离改为历史样本外预注册**：搜索期 / 冻结日 / 验证期三段全在历史数据内，冻结文件先落盘、之后才允许构造验证期数据，隔离是流程 / 信息隔离而非等未来数据物理到达。窗口被查看即消耗，再搜索须开新族、用新区间并登记前序轮次；删除「被查看过就永不认证」「等待预注册窗口真实到达」等错误绝对化条款。`docs/CORE_DESIGN.md`、`research_process.md`、`effective_factor.md`、`cross_section_factor.md` 与 §0 共 26 处同步。
- 新增 **`docs/factor_evaluation_baseline.md` 为评估指标与晋升门槛的权威来源**：一手核查 Qlib `SigAnaRecord` / `calc_ic` / `risk_analysis`、alphalens-reloaded、qweave、`arch.bootstrap` 的 SPA / StepM 及 GitHub 研究完整性清单，逐项列表标明来源与「门槛 / 仅报告」。**废除四项无上游依据的自创否决**（分组单调性 ≥ 0.9、多空双腿必须同号、净价差必须为正、后期衰减比 ≥ 0.5），降级为描述性诊断；`report_only_gates=True` 默认，设 `False` 可恢复旧行为。新增排序信息系数比率、信息系数 t 统计量、Kendall 单调性、多空年化收益与信息比率等 Qlib 标准指标。**禁止自创阈值**：新增指标或门槛必须先在该基线文档登记上游依据。
- 新增 `research_engine/factor_search.py`（只用搜索期数据自动挖族并一次性冻结、带指纹、结构上拒绝跨截止日的切片）、`experiments/factor_stream/preregistered_cross_section.py` / `preregistered_timing.py`（两阶段命令行，冻结先落盘）、`reassess_baseline.py`（已冻结轮次按新口径重算，族与数据不变）。
- 实证：三轮独立预注册 + 一轮重算。第一轮族级 p=0.012 → 4 个有效、第三轮 p=0.001 → 2 个有效；**第二轮 p=0.1039 未过 α=0.10 仍 0 个有效**，证明移除的是无依据的额外否决、统计层未放松。通道二 44 期完整预注册 5 个候选全部 `refuted`（族级 p=1.0），如实记录为搜索期过拟合，未再调规则凑肯定结论。
- `effectiveness.py` 同步把 `alignment_positive` 降级为方向诊断；11-14 实证族级 p=0.9840 与指纹**逐位复现**。
- 验收：后端 **643 passed + 132 subtests**、前端 **42 tests 全绿** + `tsc -b` 干净、`compileall` 干净、`frontend/src` 汉字 0。

2026-11-15（五次修订，Part A 收尾）：Anthony「你继续，你来决定！最后把这部分做好后报告我」。AI 全权收尾，范围与决定如下。

- **补齐最后两项上游对齐指标**：`research_engine/evaluation_metrics.py` 实现 Qlib `pred_autocorr` / alphalens `factor_rank_autocorrelation` 的滞后 1 期因子数值与因子秩自相关（只比较相邻期共同标的），以及 Newey & West (1987) Bartlett 核 HAC 修正 t 值（1994 自动带宽 `floor(4(n/100)^(2/9))`、长期方差非正返回空值不回退朴素 t）。两通道都接上，**严格只报告**：不进配置、指纹、族检验、稳定性判据与终态；依据与身份登记在 `docs/factor_evaluation_baseline.md` §7。普通 t 值并列保留。
- **踩坑并修正**：曾把两判定器 `schema_version` 由 1 升 2，发现它经 `config.to_dict()` 进入冻结报告指纹、会让全部历史指纹漂移，已回退到 1、常量旁加警示注释、`research_process.md` 不可绕过清单增列第 11 条。**附加纯报告字段属向后兼容扩展，不升版本号**。
- **一次性验证纪律**：通道二 `preregistered_timing_20261115/certification.json` 是冻结窗口的一次性证据，脚本按设计拒绝二次验证，故**不为补描述性字段重跑**；该轮族级 p=1.0、5 个候选全部 `refuted` 的否定结论不受影响，新增指标对未来轮次生效。
- **交付物落地**：`experiments/factor_stream/effective_factor_registry.py` 生成 `effective_factor_registry.json`——确定性、带指纹的**有效因子注册表**，汇总 6 个横截面有效因子（表达式、通道标签、断言、调整后 p、族级 p、排序信息系数、HAC t、因子秩自相关、冻结与报告指纹、证据路径、不宣称项），并如实登记 1 个族级不显著轮次与 1 个通道二全证伪轮次；轮次**不合并**、跨轮序贯错误率不宣称。附 `--check` 确定性校验与 6 项契约测试。
- **六项工程默认值定稿**（`docs/research_process.md` §8）：默认指数成分历史区间池 + `all_listed` 并列对照、月频 21 交易日、Part A 通道二不允许多标的合并、维持简化成本并显式标注未建模 bar 级撮合、L4 只做描述性诊断且组合优化归 Part B、A→B 接口为带通道标签与指纹的 `FactorEvidence` + 只读注册表。每项写明理由与可回退性；**是工程默认值不是统计门槛**，只对新轮预注册生效。
- §0 澄清：验收准则是「流程可重复执行并如实给出肯定或否定结论」，族级不显著 / 全族证伪 / 证据不足都是合法结论，**不得为凑肯定结论改族、换窗口、调参或放松门槛**；「稳定产出」不宣称跨轮稳定或未来持续。第三次修订记录补状态注记，避免旧结论被当现状读。
- 验收：后端 **669 passed + 138 subtests**、前端 **42 tests 全绿** + `tsc -b` 干净、`compileall` 干净、`frontend/src` 汉字 0；三轮冻结认证族级 p / 指纹 / 状态 / 有效列表重算**逐位复现**；11-14 通道二实证族级 p=0.9840 与指纹逐位复现；注册表 `--check` 通过。

2026-11-15（六次修订，搜索侧主线改版）：Anthony 否决手写模板路线并追加「别直接调接口，我们后期要改一些地方的！参考模仿自己本地写！」。**新主线 = 结构照 Qlib、代码全本地写、不 import `pyqlib`**。

- 一手核准 Qlib 源码（只读）：Alpha158 默认 158 项、`Ref($close,-2)/Ref($close,-1)-1` 标签、处理器与 `LGBModel` 默认超参、三段结构、回归三算子的最小二乘等价式（`rolling.pyx`）。
- 新建 `src/dynaloop/learned_factors/` 七模块逐层对应 Qlib，另有 `docs/learned_factor_workflow.md`（含后期可改点表）、`experiments/factor_stream/preregistered_learned.py` 两阶段预注册、`tests/test_learned_factors.py`；`pyproject.toml` 声明 `lightgbm>=4.0`。**本地 `research_engine/expressions.py` 未改**（防前视语义与 Qlib 数据加载器不同，另写一套是职责隔离）。
- 冻结纪律不变：`materialise_until=cutoff` 硬隔离 → 158 表达式 / 特征库指纹 / 模型文本哈希 / 全部超参 / 三段 / 成本 / 决策频率 / 晋升规则 / 前序轮次 / 污染披露**先落盘** → 一次性验证，且 `verify` 拒绝二次评分。
- **真实数据认证结论**（`preregistered_learned_20261115/certification.json`）：学得因子 `learned_alpha158_lgb`，58 期冻结样本外、宽度 297–300，族级 p=**0.0060**、调整后 p=0.0060、月度排序信息系数 +0.0362、信息系数比率 0.270、HAC t=2.69，四块全正 / 留一法正 / 无后期衰减，终态 **「横截面有效因子」**。日频 Qlib 风格描述指标 IC 0.0119 / Rank IC 0.0100 只报告不否决。旧 6 因子注册表降级历史对照、产物未删。
- 踩坑：`canonical_json` 禁止 NaN/Infinity，缺失标签必须用项目标准 `None`；首次 verify 在报告指纹处中断（未输出任何统计量），修复只换缺失标记、数值输入与冻结族 / 模型 / 参数逐位不变，已在产物登记 `implementation_retry`。
- 验收：后端 **686 passed + 320 subtests**（新增 17 项 + 182 子测试）、前端 **42 tests 全绿** + `tsc -b` 干净、`compileall` 干净、`frontend/src` 汉字 0；冻结指纹与模型哈希校验通过；历史注册表 `--check` 仍通过。

2026-11-16（七次修订，清理代码 + 与 Qlib 逐项对照）：Anthony「清理代码，同时对照 Qlib 再检查！确保逻辑一致！」。

- **一手对照资产**：`experiments/factor_stream/qlib_alpha158_reference.json`（由 Qlib 自己的 `Alpha158DL.get_feature_config` 机械生成，独立于本地实现）、`audit_qlib_alignment.py`（默认离线比对，`--refresh` 重拉 Qlib 源码）、`qlib_alignment_report.json`。结论：**158 项名称 / 顺序 / 表达式 0 差异、标签一致、10 项数值语义全通过**；`tests/test_learned_factors.py::TestQlibAlignment` 固化为回归测试。核查覆盖 `loader.py` / `ops.py` / `rolling.pyx` / `processor.py` / `dataset.py` / `config.py` / `gbdt.py` / `record_temp.py` / `eva_alpha.py`。
- **修正四处口径不一致**（158 项表达式未改）：① `Rsquare` 平坦窗口置空（`ops.py` atol=2e-05）；② `Slope` / `Resi` 常数窗口返回 0 而非空值（Cython 只需 x 分母有效）；③ 描述性信号分析对齐 `calc_long_short_return` 的**半价差** `(top−bottom)/2` 与全池均值，逐日相关只剔缺失对、不丢整天；④ 冻结模型改为二进制写入，避免 Windows 文本模式 CRLF 让文件字节与清单哈希不符，验证阶段兼容历史两种表示。基线文档第 37 行同步澄清"认证层全价差 vs Qlib 半价差"相差 1/2 因子、均只报告。
- **影响评估与纪律处置（重要）**：真实归档里共 951 个常数窗口行，其中**训练 + 早停段 59 行**、**验证期决策日 0 行**；用修正后实现重训得到**不同的模型哈希**，因此 `preregistered_learned_20261115` 的「横截面有效因子」结论**只对冻结时的实现版本 v1 与冻结模型成立**。**不拿已查看的验证窗口重出结论**，v2 实现须另开新族 / 新未消耗区间的新预注册轮次；完整登记见产物 `alignment_note.json`。
- **清理**：删除未用导入与魔法字符串、`feature_importance` 保留浮点增益、临时重训目录全部删除；注册表因基线文档哈希变化重新生成（6 个因子与所有结论不变，`--check` 通过）。
- 验收：后端 **691 passed + 320 subtests**、前端 **42 tests 全绿** + `tsc -b` 干净、`compileall` 干净、`frontend/src` 汉字 0；`audit_qlib_alignment.py` 全绿、冻结模型在新哈希校验下可恢复（10 棵树）。
