# 因子研究系统重设计：状态与待办

更新：2026-11-16。Anthony 指令：此前登记的「有意差异」约束作废，按权威文献与项目重新设计因子自动挖掘研究系统。方法论依据 `docs/factor_research_foundations.md`，指标身份登记 `docs/factor_evaluation_baseline.md` 第八节。

## 设计目标

从「一次性认证一个学得因子」升级为**统计保证的因子生命周期研究系统**。七个组成部分：

1. 目标口径对齐（训练标签 = 下游评估目标）；
2. 试验台账记录全部搜索尝试（含失败）；
3. 评估升级：族级检验＋折价夏普＋回测过拟合概率＋残差信息系数；
4. 多窗口证据（滚动前进＋窗口敏感性扫描）；
5. 半衰期测量与滚动再认证；
6. 因子池＋冗余控制＋组合层评估；
7. 时点成分股数据底座升级。

## 已完成（本轮，工具层）

| 组件 | 文件 | 状态 |
| --- | --- | --- |
| 试验台账（追加写、拒绝重复/删除、N 与 V） | `research_engine/trial_ledger.py` | 完成 |
| 概率/折价夏普、CSCV 回测过拟合概率 | `research_engine/search_bias.py` | 完成 |
| 稳健去极值、横截面标准化、行业/市值中性化、残差信息系数 | `research_engine/neutralization.py` | 完成 |
| 信息系数衰减曲线与半衰期 | `research_engine/decay.py` | 完成 |
| 包导出与基线文档登记 | `research_engine/__init__.py`、`factor_evaluation_baseline.md` §8 | 完成 |
| 单元测试（15 项，含手算对照与性质检验） | `tests/test_factor_uncertainty.py` | 全部通过 |
| 研究引擎回归（162 项＋235 子测试） | 既有测试集 | 全部通过 |

数值正确性核对：PSR/DSR 与 mlfinlab 公式手算逐位一致；CSCV 在注入稳定信号列的收益矩阵上 PBO 显著低于纯噪声矩阵；中性化后残差与被剥离开的行业/市值正交且保留独立成分；半衰期从已知指数衰减曲线精确恢复 λ 与 ln2/λ。

## 目标口径对齐（2026-11-16 晚，工具层完成）

Anthony 定调（纠正了两种错误方向）：**不要机构式固定节拍，也不写死日/周/月决策网格—— opportunistic 触发，什么时候条件合适什么时候交易；但衡量效果仍用固定时间窗口（月/周）作为统计检验的"期"**。两层解耦：

- **评估窗口**（`WindowSpec`）：固定周/月节拍，每窗一个评分期，期数由此确定。
- **决策触发**（`TriggerSpec`）：`window_start`（窗内首个可交易日 T+1）或 `threshold`（窗内首个信号超阈值的时点，无则本窗不交易）。触发只能用触发时刻及之前的信息，规则在搜索期冻结。
- **标签**：`close[窗口末]/close[入场]-1`，严格落在单一评估窗口内，天然不跨 train/valid/test 边界（网格式 purging，按构造成立）。
- 权威依据：Qlib 默认 1 日标签是可替换默认值（A 股 T+1）；FactorBench 统一前瞻目标；Lopez de Prado (2018) 标签窗不跨切分。

实现：`src/dynaloop/learned_factors/label_alignment.py`，12 项测试全绿（窗连续性、触发语义、不得用窗口末信息、缺失端点为 None、跨段窗口不归属任何段）。

**已接入数据层（2026-11-17）**：
- `learned_factors/aligned_dataset.py` 的 `AlignedDataset`：复用物化的 158 特征帧，按窗口重采样为「触发入场时点特征 + 窗口末收益标签」，接口与 `DatasetH` 一致（prepare/fetch/feature_names/segments/handler），LGBModel 零改动可消费。
- `run_workflow(..., dataset=...)` 新增可选参数：传入 AlignedDataset 即用新口径，省略则保持默认日频行为（向后兼容）。
- `research_engine/diagnostic_report.py`：`build_diagnostic_report`（台账/折价夏普/PBO/衰减）＋ `attach_report`（附加时断言族级 p 值、指纹、终态、有效列表逐字不变）。全部仅报告。
- 测试：`test_aligned_dataset.py`（结构、阈值触发、标签公式、模型消费）、`test_diagnostic_report.py`（判定字段不被改写），连同目标对齐与不确定性共 59 项＋182 子测试全绿，compileall 干净。

**仍未做**：未写进 `preregistered_learned.py` 的冻结配置、未跑真实 58 期窗口。真实 provider 初始化约 44 秒（948 只股票解压），全量物化更慢，故端到端只用合成帧验证管线接通。真正启用须开新预注册轮次，不动已查看窗口。

## 两块串联架构（2026-11-17 晚）

Anthony 定调终局结构：**先选股（组合），再在选中的股上择时；每块研究和执行分开**。权威一致性：Qlib 官方 `nested_decision_execution`（周频组合生成＋日频订单执行）、双动量（横截面相对动量选股＋时序绝对动量决定进出）都是这个结构。

实现 `orchestrator/two_stage.py`，用**类型强制**而非约定来落实研究/执行分离：
- 第一块：`SelectionResearch` 只吃已认证 `effective` 的证据（真实 `FactorEvidence` 可直接驱动，duck typing 不改判定层）→ 冻结 `SelectionRule`（因子 ID＋证据指纹＋TopK＋指纹）；`SelectionExecution` 构造函数**只接受** `SelectionRule`，产出等权目标持仓。
- 第二块：`TimingResearch` 只吃冻结的 `SelectionRule`＋选中标的 → 冻结 `TimingRule`（进出阈值＋冻结成员清单＋两部分指纹）；`TimingExecution` **只接受** `TimingRule`＋持仓，产出 enter/exit/hold，并拒绝冻结清单外的标的。
- 执行阶段拿不到判定器、原始报告或研究数据集——构造签名里没有入口。改规则必须重开研究轮次、换指纹。

测试 `test_two_stage.py` 11 项全绿（含真实 FactorEvidence 驱动、拒绝 insufficient/refuted 证据、拒绝冻结清单外标的、两块串联端到端、双指纹链接）；compileall 干净。

**占位已全部替换为实装（2026-11-17 深夜）**，四块闭环打通：

- **组合权重** `research_engine/portfolio_weights.py`：可插拔 `WeightConfig`（equal / score-softmax / inverse-vol，含 qlib topk-dropout 换手控制），纯函数、确定性 tie-break、非有限值丢弃、权重归一。权重方案进 `SelectionRule` 指纹——改方案必须换指纹、重开轮次。`SelectionExecution.target_weights` 委托它，不再写死等权。`WeightConfig` 的 top_k 与规则一致由 `__post_init__` 强制。
- **择时规则学习＋认证** `research_engine/timing_learning.py`：阈值从成本假设推出（entry 必须 ≥ round-trip cost，不是测试集挑），purged walk-forward 学 mu_on（每个块只用块前样本估），稳定性门槛筛掉噪声候选；冻结短list后在**更晚的历史窗口**用择时通道 `assess_effectiveness` 做族级检验，只有 `effective` 候选能经 `TimingResearch.from_certified` 冻结成 `TimingRule`（带认证指纹，改阈值会报错）。验证数据全程不参与学习。
- **统计更新闸门** `research_engine/update_gate.py`：项目核心差异点——统计证据同时决定「采信哪些因子」和「何时更新」。逐期配对损失差的单向区块自助检验，p 值与置信下界必须同时过线才晋升；独立随机流盐，与两个 Part A 通道不共用；样本不足保守拒绝。点估计「误差更低」不再足以晋升。
- **回测接线** `orchestrator/two_stage_strategy.py`：`TwoStageStrategy` 只消费两块冻结规则＋决策时点信号（调用方保证无前视），引擎 `NEXT_BAR` 强制时点；目标权重与进出动作翻译成带符号订单，成本/换手/毛净全进 `BacktestResult`，指纹可复现。
- **端到端编排** `orchestrator/two_stage_pipeline.py`：`run_two_stage_pipeline` 串起 ①选股研究 ②选股执行 ③择时学习认证冻结 ④择时执行＋回测 ⑤审计指纹链；无认证候选时拒绝冻结择时规则；可选挂更新闸门。全部为纯逻辑，不读真实归档、不重算已查看窗口。

测试：`test_portfolio_weights`(13)、`test_timing_learning`(9)、`test_update_gate`(8)、`test_two_stage`(11)、`test_two_stage_strategy`(5)、`test_two_stage_pipeline`(6) 连同目标对齐/对齐数据集/诊断/不确定性/学得因子共 **111 项＋182 子测试全绿**；研究引擎核心 `test_research_engine/test_cross_section_factor/test_effective_factor` 另 **125 项＋53 子测试全绿**；compileall 干净。

**边界**：这是**可执行的工程闭环**，但规则参数仍须在新预注册轮次冻结后才能用于真实数据；合成数据上的认证演示不构成真实有效性结论，不宣称盈利、可交易性或未来持续。

## 真实数据工程闭环实例（2026-11-17）

Anthony 要求「用真实数据测」。在 `experiments/factor_stream/two_stage_real_20261117/` 跑通**真实数据端到端**，严格区别于因子认证：

- **数据源**：真实 Qlib 归档 `qlib_20261112.tar.gz`（571MB，2000-01-04 至 2026-11-12，6508 交易日，948 标的，含 OHLCV+vwap），dolt/investment/qlib 三方提交哈希可核。
- **消费已认证因子，不重算认证**：用冻结模型（`frozen_model.txt`，sha256 `58a9105e...`，与 `preregistration.json` 一致）在真实 158 特征上物化出 **144,423 条真实预测**（113 万行特征）。已消耗的 58 期横截面认证（family p=0.0060）与 44 期择时认证**均未重算、未触碰**。
- **两块规则**：真实 `FactorEvidence`（fingerprint `3c8cd070...`）→ 冻结 `SelectionRule`（Top10、equal 权重、qlib topk-dropout drop=2）；择时通道在单标的 sh600000 的**未消耗早期窗口**（2015-2019 学、2020-2021 验）做 purged walk-forward——本轮 `n_candidates=0`，真实数据上简单动量信号被稳定性门槛全部拒绝，系统**如实回退零阈值、拒绝硬凑择时规则**。这是诚实的真实结果，不是缺陷。
- **真实回测**：2022-01 至 2023-12 真实多标的行情，NEXT_BAR 成交、A 股成本、决策-成交分离；16.7 万 bar、484 决策 bar、286 成交、2 笔现金不足被真实拒绝（进审计台账）；时钟对齐误差 0。结果：总收益 −19.86%、最大回撤 −31.95%、累计换手 10.99（drop 生效）。**这是消费因子的执行演示，不是有效性或盈利结论。**
- **可复现**：两次独立运行 full_fingerprint 逐位一致（`fd47b2b3...`）、回测指纹/指标/配置指纹全一致，`replay_verification.json` 记录 `replay_identical: true`。

**过程中修复一个真实 bug**：`TwoStageStrategy` 原本把「非决策日空分数」误当成「目标空集→清仓」，导致每月换手虚高（43.6）；改为 `scores` 为空即持有不动，换手降至 10.99，并补回归测试 `test_no_decision_bar_holds_book_without_turnover`。

所有产物标注 `purpose=engineering_closed_loop_demo` / `no_new_effectiveness_claim=true`。**不宣称新因子有效性、盈利、可交易性或未来持续。**

## 证据输出层（2026-11-17）

按架构图补齐「证据与不确定性 / 量化策略输出」上屏。开工前核对上游实践：Qlib `SigAnaRecord` 保存 IC、Rank IC、ICIR、Rank ICIR 与多空/等权收益；Alphalens 完整报告分为收益、信息系数、换手、分组四类；ML4T Diagnostic 的迁移指南要求把样本与口径、描述性统计、显著性结论分层展示，缺失值显示不可用而不是零。本层只投影仓库已有字段，不新增指标、不新增门槛、不重算任何统计。

- 只读目录 `src/dynaloop/research_engine/certification_catalog.py`：`CertificationCatalog` 读取 `experiments/factor_stream/*/certification.json`，`ExecutionCatalog` 只读 `audit.json` / `replay_verification.json`，不加载 37 MB 的 `backtest_result.json`。无效文件标记为 `unreadable`，不猜测数值。
- 接口 `src/dynaloop/interaction/api.py`：`/api/evidence/rounds`、`/api/evidence/rounds/{round_id}`、`/api/evidence/executions`、`/api/evidence/executions/{demo_id}`。字段分「判定字段 / 仅报告描述字段 / 口径与边界」三组，缺失统一为 null。
- 前端 `frontend/src/pages/EvidencePage.tsx`：轮次选择、候选表、描述性指标、披露边界与执行演示；`Sharpe` / `Annualized volatility` 等缺失值显示 `N/A`。所有界面文案保持英文。
- 测试：新增 `tests/test_evidence_catalog.py`（目录投影、审计摘要、空值与接口）与 `frontend/src/pages/EvidencePage.test.tsx`（判定/描述分层、空值、空目录、错误状态）。

**边界**：该页是已冻结产物的只读视图，不构成新有效性结论；不宣称盈利、可交易性、未来持续或跨轮序贯错误率。真实执行演示仍标 `no_new_effectiveness_claim=true`。

**量化策略输出补齐（同日续）**：审计摘要此前只把规则指纹上屏，冻结规则明细未展示。新增 `_frozen_strategy` 只读投影：择时阈值、冻结标的池长度、回退标记（由落盘的 `DEMO_FALLBACK_ZERO_THRESHOLD` 派生）、Qlib `risk_analysis` 对齐的风险指标（收益/回撤/换手/夏普/波动/对账误差）。派升值仅限数组长度与落盘标记，非统计重算；选股参数从未随审计摘要落盘，保持 `null` 并在界面显示 `N/A · not persisted in audit summary`，不编造。前端证据页新增「Frozen strategy」区块，明确 `Fallback` 含义（无认证择时规则、零阈值）与「report only」口径。真实产物投影结果：`is_fallback=true`、158 个冻结标的、夏普/波动 `null`。

**量化策略输出强化（同日再续）**：把「Quantitative strategy」从只有阈值/指纹补成完整可读视图。根因是 `run_real_pipeline.py` 构造了完整 `SelectionRule`（factor_ids / top_k / weight_config / evidence_fingerprints）却只落盘指纹。两处修复：
1. 后端 `_reconstruct_selection_rule`：从已落盘的 `consumed_factor` + 固定工程旋钮（equal / top_k=10 / drop=2）确定性重建规则，**仅当重建指纹等于 `selection_rule_fingerprint` 才投影明细**（真实产物指纹 `80f358d0...` 逐位吻合，`verified=true`）；指纹不符或被篡改则明细全部 `null`，绝不编造。
2. `run_real_pipeline.py` 未来重跑直接落盘 `selection_rule` / `timing_rule` 明细；这两字段是已指纹内容的无损展开，加入指纹排除表，故重放身份 `fd47b2b3...` 不变，`verify_replay.py` 无需改动。
3. 执行指标投影补齐初始/期末权益、bar 数、成交/拒绝数、期末持仓数；Qlib `annualized_return` / `information_ratio` 未随审计落盘，保持 `null`。前端区块改为「Quantitative strategy」，分 selection / timing / execution 三段展示。

## 滚动前进多期真实数据验证（2026-11-17 再续）

按架构图「多做几期真实数据测试」推进，开工前核对上游最优实现：Qlib rolling retraining（应对市场动态的滚动重训）、ML4T Diagnostic `WalkForwardCV`（train/test/embargo 参数）、Lopez de Prado purged walk-forward（AFML ch.7/12，标签净化与禁运）、`qlib-platform` 的 `research_matrix` 多轮对比报告（缺失指标保持缺失、不代理填充、输入身份不可静默改变）。据此确立合规路线：**一次性预注册全部折 → 每折独立重训冻结 → 各自样本外一次性验证 → 全部如实报告，不合并跨折错误率**。

- 脚本 `experiments/factor_stream/walkforward_learned.py`：两阶段纪律。`freeze` 阶段在任何验证数据物化前把 5 折定义与复用配置写入带指纹的 `walkforward_preregistration.json`；`run` 阶段逐折独立训练与认证，`check` 阶段做只读可复现契约校验（冻结指纹、复用配置逐字一致、汇总与各折一致、主轮次认证文件哈希在案）。
- 折由规则生成（expanding fit、valid 标签成熟后设 cutoff、互不重叠 2 年 test），不手工挑窗：2012–13 / 2014–15 / 2016–17 / 2018–19 / 2020–21，各 23 期。特征库、模型超参、认证口径、成本模型**逐字复用** `preregistered_learned_20261115` 冻结配置，只换时间窗；每折族大小 = 1。
- 产物 `experiments/factor_stream/walkforward_learned_20261117/`：**2 折有效（1、3），3 折证据不足（2、4、5），0 折证伪**。族级 p 依次 0.0050 / 0.0390 / 0.0020 / 0.1508 / 0.3756；月度排序信息系数 +0.0744 → +0.0735 → +0.0663 → +0.0458 → +0.0350。**稳健性未通过**，结论如实保留，未改族、未换窗、未调参。折 2 的 p 虽 < α 但分段一致性未过，仍判证据不足——证明判定层未放水。
- 证据页接入：`WalkforwardCatalog` 只读投影 `walkforward_summary.json` + `walkforward_audit_note.json`，接口 `/api/evidence/walkforward`、`/api/evidence/walkforward/{directory}`，前端新增「Walk-forward robustness」区块（折对比矩阵、排序信息系数序列、功效警示、污染补充披露、上游依据）。缺失显示 `N/A`，不合并 p、不宣称新有效性。
- 审计附注如实写明：5 折 test 窗口（2012–2021）与主轮次训练段（2008–2018）、早停段（2019–2021）时间重叠，不是物理未观察数据；隔离是**流程/信息隔离**（每折独立重训、族参数逐字复用不重调、全折定义先冻结、标签一次性评分不回流），不是物理非检视。每折 23 期 < 24，附低功效警示；排序信息系数单调下降只作描述性观察，未预注册趋势检验，不附显著性、不构成衰减结论。

**边界**：这是对**一个冻结族机制**的跨期稳健性诊断，不是 5 次独立确认；跨折训练窗口重叠、结论相关，故 p 值不合并、不宣称跨轮序贯错误率、未来持续、盈利或因果。主轮次 58 期认证文件哈希 `2ab1ec77...` 逐字未变。

## 架构图补全：公共数据层 / 主观分析 / 决策对比（2026-11-18）

Anthony 要求按架构图补全缺失的主观策略与策略对比，并接新闻舆情为公共数据层、量化侧参考 QBX、主观侧实际接大模型。开工前一手核对四个参考源：QBX 论文（ICAIF 2026，arXiv:2610.41689，时间可用性效应 + Merkle 身份 + 分阶段诊断，明确声明只保有效性之外的审计性质）、`a-share-sentiment-cycle`（MIT，纯规则 L1/L2/L3 情绪周期，无训练、无回测）、公众号文章（实为「研究路径坍缩与独立验证」，并不主张新闻做公共数据层——已如实告知用户）、WorkBuddy 云服务 LLM SDK（keyless、仅流式、需 system 消息置顶、Origin 绑定）。

**定位**：这一轮全是**工程与数据能力接入**，不是有效性声明。没有新增因子、没有改判定层、没有碰任何冻结产物。

- **公共数据层 `src/dynaloop/alternative_data/`**：`NewsRecord` 带发布时间/抓取时间/可用时间/来源/模型与提示版本；`align_to_available_time` 只放行 `available_at <= decision_time` 的记录（防合同级前视）。真实新闻 provider 用 akshare `stock_news_em`，可用时间取抓取时间、绝不按发布时间回填；网络失败返回 `available=False` 与原因，不编造。默认接口不联网，需 `live_news=true` 才拉真实源。已实测拉到真实新闻并正确标注两层时间。
- **情绪周期状态机 `sentiment_cycle.py` / `indicators.py`**：忠实移植参考仓库的 L1/L2/L3、20 日滚动基线（当日分数用追加前基线，防自反馈）、两日退潮确认、T0-T5 仓位档；修复其记录的炸板连板数恒为 0、最高档不可达、无龙头恒告警等缺陷。纯计算、无网络、21→13 项目测试覆盖；报告性信号，不进判定层，沿用「无回测/无参数显著性」的诚实边界。
- **QBX 审计外壳 `research_engine/alpha_audit.py`**：实现时间可用性效应 φ（Qlib 外部语法 `Ref(x,N>0)`=过去、φ≤0 准入；负 lag=未来、φ>0 拒绝）、Merkle 内容身份、Normalize/Graph/Availability 分阶段诊断。保证明确是**相对注册合约**，不是零回测泄漏；不宣称提升 alpha 有效性，不进冻结指纹。
- **主观分析 `/subjective`**：前端 `@tencent-ai/workbuddy-cloud-sdk` 实际调用大模型（已激活云服务 `wbapp_Zq5nt6cjMg2e619ofnUfVm`），四类输入由 `/api/subjective/inputs` 聚合；system 消息强制「不得当作已验证因子或投资建议」，流式收集，输出仅人工审阅。
- **策略库 + 决策对比 `/decision`**：`alternative_data/strategy_library.py` 登记 4 个候选（QuantsPlaybook、cross-sectional-multi-factor、a-share-sentiment-cycle、a-share-quant-v9）为只读元数据，上游收益声明一律不继承。人类裁定 `DecisionLedger` 只记录选择/理由/双方指纹并落指纹审计轨迹，不自动决策、不宣称正确。
- 依赖 akshare/baostock 已声明进 `pyproject.toml`；文档 `brain.md`、`CORE_DESIGN.md` 的「不调用 LLM」表述已按事实更新，并强调与「神经大脑主线暂缓」是两件事。

**边界**：主观大模型输出与情绪周期分数都是主观/报告性内容，不是因子、不进族级检验、不宣称有效或收益；web LLM 通道 Origin 绑定，仅用于本应用。

## 活的策略库：采集—索引—经验闭环（2026-11-18 晚）

Anthony 纠偏：此前 `alternative_data/strategy_library.py` 的 4 条静态元数据登记，以及拟议的 Dirichlet 数学贝叶斯，都偏离真实意图。真实意图是**原架构图主观策略分支的"LLM with Bayesian Thinking"**——贝叶斯是"看到新证据→修正对策略信念"的认知更新隐喻，不是概率公式。用户原话要点：大模型每天联网搜索补充最新有效策略（举例香港投资人策略方法），建好**策略库索引和触发获取机制**，主观决策时参考 → 同步模拟撮合 → 积累经验、像人类从市场投资中学习。用户拍板：**每日定时补库 + 决策时检索**；**经验星级**（按模拟撮合真实结果积累信念）。

**定位**：纯工程与报告能力。没有任何新因子、没有改判定层、没有碰冻结产物。 harvested 策略与其经验星级都不是有效性结论、不是收益预测。

- **契约 `live_strategy/contracts.py`**：`StrategyEntry`（作者/方法/适用情境标签/来源链接/三层时间/内容指纹）、`ExperienceEvent`（决策 ID + 被参考策略 ID + 二元结果，用于归因）、`ProviderReport`（显式可用/不可用，失败不静默为零）。**关键纪律**：`available_at` 一律取采集时间，绝不回填到 `published_at`——一条晚采集却标早期发布日的策略若被回填，就是合同级前视；测试 `test_retrieve_is_point_in_time_safe` 专门守这条线。
- **采集器 `live_strategy/collector.py`**：可插拔协议，默认 `NullStrategyCollector` 不联网且显式 unavailable；`StructuredCandidateCollector` 只校验/规范化定时任务产出的结构化候选，本身不联网、不编造。结构化抽取的 schema 参考 OneKE（WWW 2025）、Knowledgator Text2Json 的 schema 引导实践。曾在此层发现并修复一个真实前视 bug（把 published_at 回填进 available_at），已补回归测试。
- **索引检索 `live_strategy/index.py`**：Okapi BM25（k1=1.5、b=0.75 为文献默认，非本场景调参）叠加情境标签重合度，按当前情境取相关策略；硬性 `available_at <= decision_time` 门控。几百到几千条不引入向量库，用纯标准库实现。
- **经验星级 `live_strategy/experience.py`**：成功/失败计数 + 半衰期衰减（默认 30 天，调用方可显式覆盖）+ Wilson 下界（Evan Miller 2009；z=1.96 为标准 95% 分位）。冷启动天然保守：单次成功只给约 0.2 分而非满分。依据来自 Jøsang 信誉系统与评分排序文献。**明确不是显著性检验**，分数为报告性、可审计、不进任何冻结指纹。
- **门面与接口 `live_strategy/service.py`、`interaction/api.py`**：`LiveStrategyLibrary` 串采集/存储/检索/经验；新增 `/api/strategy-library`（快照）、`/api/strategy-library/refresh`（落库结构化候选）、`/api/strategy-library/retrieve`（决策时检索）、`/api/strategy-library/experience`（经验回流）。主观输入 `/api/subjective/inputs` 新增 `strategy_query`，决策时把检索到的策略注入大模型上下文（源标记 `living_library`，无查询时回退旧静态库 `static_registry`）。
- **每日定时**：平台自动化「DynaLoop 每日策略库补库」（每天 08:30，工作目录本仓库）负责联网搜索 + LLM 结构化抽取；落库入口 `scripts/collect_strategies.py` 只做校验与存储、不联网，缺输入时显式不可用。已用真实联网结果演示：罗威（用户举例"罗伟森"的公开可溯源方法，多周期 KD + 布林轨道）、港股估值分层、长桥基本面流程共 3 条落库，并演示一次经验回流（成功 2/失败 1 → 星级 1.04/5，保守下界 0.208）。
- **前端 `SubjectivePage.tsx`**：Living strategy library 面板展示被参考策略的方法/情境/来源/经验星级，明确"report-only experience stars，not a factor/verdict/return claim"。

**边界**：harvested 策略与方法来自外部公开来源，其收益/有效性声明一律不继承；经验星级是描述性信誉分，不是统计显著性、不是因子认证。主观建议同步模拟撮合（非真实下单），结果回流只更新经验分。旧 `strategy_library.py` 保留为无查询时的回退来源，`candidates` 采用新旧兼容渲染。

**验收（conda dynaloop）**：后端 **842 passed + 320 subtests**（新增 test_live_strategy 12 项、test_strategy_library_api 5 项）；前端 **62 项全绿** + tsc -b 干净 + 源码汉字 0；冻结认证哈希 `2ab1ec77...`、滚动冻结指纹 `c22f70ce...`、注册表契约（6 因子）逐字未变。**尚需在浏览器实机点生成，确认大模型返回与来源校验。**

## 尚未完成（下一阶段工程）

1. **目标口径对齐的脚本接入**：把 `WindowSpec`/`TriggerSpec` 写进预注册冻结与 handler 标签物化，只能在**新预注册轮次**落地（工具层已就绪，见上节）。
2. **接入预注册脚本**：把台账、折价夏普、PBO、残差信息系数作为报告字段写进 `preregistered_learned.py` 的认证产物；不动已冻结窗口。
3. **中性化真正生效**：在新轮次把处理器写进冻结配置，而不是只作事后诊断。
4. **窗口敏感性扫描**：在滚动前进基础上再做训练 12/24/36/60 月 × 测试 1/3/6 月的敏感性（须开新预注册族，不能复用已消耗窗口）。
5. **半衰期驱动**：由 IC 衰减曲线定评估窗口与调仓频率，建立滚动再认证与降权/退役规则。
6. **因子池与组合层**：多因子产出＋冗余控制（相关性／语法树去重）＋组合评估，对齐 FactorBench 三层结构。
7. **数据底座**：商业级时点成分股、退市停牌处理、幸存者偏差处置。

## 纪律边界

- 所有新指标为**仅报告**，不进冻结指纹、不进族检验、不进终态；已冻结轮次的族级 p 值、指纹、结论逐位不变。
- 已查看的验证窗口一次性消耗，禁止拿它重算换结论；任何改动须开新族、新未消耗区间、登记前序轮次。
- 不宣称跨轮序贯错误率、未来持续、可交易性、盈利、因果。
