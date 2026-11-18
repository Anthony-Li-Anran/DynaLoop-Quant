# 有效因子的统计判定口径（Part A 核心）

更新：2026-11-15（补适用范围；三次修订同步通道一落地与通道标签状态）。本文定义「有效因子」这一肯定结论的判定口径，是 `docs/CORE_DESIGN.md` 中「统计保证」主线在 Part A 的落点。实现在 `src/dynaloop/research_engine/effectiveness.py`，端到端实证脚本在 `experiments/factor_stream/effective_assessment.py`。

## 零、适用范围与通道标签（必读，2026-11-15 二次修订）

本文的统计口径（因果隔离 + 族级错误率控制 + 跨期稳定性）**本身成立**，且是「**通道二 · 择时（单标的时序）**」的**权威判定口径**，不是待替换的临时方案。当前实现的判定对象是单只标的的时间序列标量预测：每个决策期一个预测值、一个收益目标，候选绑定单个标的代码（`FrozenCandidate.symbol`）。因此现有 `effective` 终态严格说是「**该标的的择时关系在冻结窗口上稳定可重复**」，应标为「**择时有效因子**」。

按 `docs/research_process.md` 的双通道设计，本项目**两条通道并列且均已实装**：通道一「选股（横截面）」问同一时点谁比谁更强，零假设、对照基线、样本结构与本文全不同，其权威口径是 **[横截面有效因子的统计判定口径](cross_section_factor.md)**、实现 `research_engine/cross_section.py`，**不得复用本文的零假设与基线**；现有代码不是缺陷。**两条通道禁止混进同一判定族、共用族级错误率控制或互相外推结论**（`channels.py::enforce_channel` 硬拒绝混族），各自预注册、冻结、晋升、出带指纹的证据条目。通道标签已落地：`research_engine/channels.py` 统一提供常量与中文标签，本判定器的 `EffectivenessReport` / `CandidateVerdict` / `spec` 均写入 `channel=timing`、`channel_label=择时有效因子`、断言与不宣称项；`evidence_from_report` 产出规范化带指纹的证据条目。2026-11-15 把本文实现中的重采样数学抽到 `resampling_tools.py` 后，**11-14 实证的族级 p = 0.9840 与指纹逐位复现**，旧入口语义与判定结果一概未改。

不得把本文结论写成对某个股票池、某个市场或后续 Part B 所消费的「横截面关系信息」的认证。2026-11-14 的真实数据实证只用了一只创业板指数基金、9 个决策期，其「有效因子 0 个」只对这一范围与通道二有效。

## 一、为什么不能照抄 Qlib / RD-Agent(Q)

一手核实：

- `microsoft/RD-Agent` 的 RD-Agent(Q)（NeurIPS 2025，arXiv 2505.15155，§2.4 Validation Unit）验证流程是：先与现有最优因子库算相关性去重（`IC_max >= 0.99` 判冗余），再与当前最优模型组合跑 Qlib 回测，用信息系数 / 排序信息系数 / 信息比率 / 年化收益等指标更新最优集合。
- 它**没有**对「产生这批候选的搜索规模」做多重检验校正，**没有**预注册冻结，**没有**给出「该因子有效」这一断言的错误率陈述，也没有把跨期稳定性作为独立必要条件。
- 第三方对 RD-Agent 排行榜的分析直接把它称作「多重检验发生器」：一个因子被反复评估 23 次，看到的是 23 次里最好的一次；并报告按预注册规则独立复测时头名未存活。须标注：这是第三方评测，不是官方结论。

所以「照抄」的终点是「信息系数高就进最优集合」——这恰恰是 White（2000）、Hansen（2005）、Harvey/Liu/Zhu（2016）指出会被数据窥探抬高的量。**我们的立场是统计学的：有效因子是一个带错误率陈述的肯定断言，不是一个高信息系数。**

## 二、真正的难点：自进化研究器是自适应分析

比「搜了很多因子」更深一层：自进化研究器每轮根据上一轮反馈改策略，等于**反复查询同一批数据**。Dwork 等人（Science 2015；NeurIPS 2015「可复用留出集」/ `Thresholdout`）证明：被自适应地反复查询的留出集本身会被过拟合，标准推断要求的「假设在看数据前已固定」不再成立。

因此：

- 在自适应回路内部硬套固定族的多重检验，**不宣称**成立；
- 项目内 `statistical_uncertainty_engine/resampling.py` 针对「同一冻结窗口内的自适应回路」明确写 `fwer_control_claimed=False`，这是**正确的**，本文不改它；
- 我们不去硬控跨轮序贯错误率，而是用金融时序独有的结构把问题搬走。

## 三、口径：三根支柱，全部落在冻结后的独立窗口

### 支柱 0｜因果隔离（用设计消除自适应，不是用更强的检验）

- 生成、调参、反馈、策略更新等**全部自由度只作用于搜索期**。
- 在某个声明的截止日 `cutoff`，候选族与**每一个参数一次性冻结**，附数据与源码指纹（现有 `holdout_lock.json` 已是这一机制）。
- 验证期是 `cutoff` 之后的**历史样本外**数据，一次性评分；冻结族与全部参数在接触验证数据之前固定并落指纹，验证期信息不可能倒流进搜索，因此「自适应分析有效性」这个一般性难题被转化为标准的**预注册族假设检验**，无需可复用留出集的差分隐私机制。隔离是流程 / 信息隔离，不是等未来数据物理到达；窗口被查看即消耗，再搜索须开新族与新区间。评估指标与门槛见 `docs/factor_evaluation_baseline.md`。
- 隔离由 `_check_isolation` 强制：日期越界、未冻结候选、候选间验证网格不一致、期数不足，一律 `IsolationError`，**绝不静默降级**。

这是本口径最关键、也是与其它项目最不一样的一点：**不是换更强的模型或更多因子，而是重新安排「结论的因果位置」。**

### 支柱 1｜抗数据窥探的族级检验（校正「我们搜了很多」）

- 检验对象是**冻结族里最好的那个**，不是某个预先指定的单因子。
- 逐期损失差分定义为 `d = min(零预测误差, 历史均值误差) − 因子预测误差`。逐期取两条基线中较优者，等价于要求**每一期都同时胜过两条基线**，比「整段汇总后比最小值小」更严格（旧 `holdout.py` 用的是汇总口径）。
- 观测统计量：`sqrt(n) × mean(d) / 样本标准差`，取全族最大值。
- 零分布：Politis–Romano（1994）平稳区块自助法（`arch.bootstrap.StationaryBootstrap`，可切循环区块）。**每个重放复制对所有候选共用同一条时间索引路径**，同时保留序列相关与候选间横截面相关；按各候选样本均值重新中心化，构造「无优越性」零假设。
- Romano–Wolf / Westfall–Young 最大统计量逐步下降，给出每个候选的调整后 p 值与拒绝决策。

**口径必须精确**：学生化尺度固定在观测值上、不按复制重估，也不数据依赖地剔除劣质候选。因此这是**保守的现实检验风格变体，不是完整的 SPA 检验**；`spec["spa_simplification"]` 明确写出了这一点，不得对外宣称完整 SPA。

### 支柱 2｜稳定性与可重复性（独立必要条件）

显著不等于「有效」。还须同时满足：

- 验证期切成不相交的连续块，至少 75% 的块改善为正（方向一致）；
- 去掉贡献最大的那一期后，整体改善仍为正（不允许单期运气撑起结论）；
- 预测与实际收益的平均同向性为正。

块级精确符号检验 p 值**只作诊断报告**；块数少时功效低，明确**不宣称**独立的显著性保证。

### 肯定结论与错误率陈述

一个候选为 `effective` 当且仅当 **支柱 1 的调整后 p ≤ alpha 且支柱 2 三项全过**。否则为 `insufficient_evidence`；若稳定地差于两条基线则为 `refuted`。族状态为 `effective_factors_found` 或 `insufficient_evidence`。

每个肯定结论都附带如下分层陈述（写进 `error_statement` 与 `spec`）：

| 项目 | 口径 |
|---|---|
| 冻结族内族级错误率 | **宣称 ≤ alpha**，条件是：隔离成立、区块自助法保持依赖结构、零假设近似枢轴 / 对称、验证期内损失差分平稳 |
| 跨轮自适应 / 序贯错误率 | **不宣称**；自适应由隔离消除，不是被检验约束 |
| 共形覆盖保证 | **不宣称** |
| 盈利能力 / 可交易性 | **不宣称**；成本回测只是辅助诊断 |
| 因果性、关系在未来持续 | **不宣称** |
| 小样本 | 验证期少于 24 期时自动附 `power_note`：功效低，不拒绝只是弱证据，绝不等于证明无效 |

可追溯性（公式、冻结参数、截止日、逐期日期、数据/源码指纹、全参数 `spec`、同输入同 `fingerprint`）是**必要条件，不是替代品**。

## 四、与项目其它部分的关系

- `docs/factor_research.md` 描述的是**现有研究器实现**及其限制（「不强制选出赢家」「不提供多重搜索错误率保证」），**不得改写其限制声明来冒充已达成**。本文是**新增的独立判定层**，消费研究器的冻结输出，不修改 `temporal.py`、`holdout.py` 或 `catalog.py` 的任何既有语义。
- `research_engine/temporal.py` 仍是搜索器，产出 `provisional` / `insufficient_evidence`；新判定器的终态是 `effective` / `insufficient_evidence` / `refuted`。两者**并存、职责不同**。
- 醒睡机制、生成器偏差控制、组合优化属于 Part B，不在本层。

## 五、验收与实证

单元与对照测试：`tests/test_effective_factor.py`（25 项 + 12 子测试）。覆盖：真信号能给出肯定结论、纯噪声多种子零虚报、单期运气被留一法拦截、隔离违规硬拒绝、口径陈述精确、同输入同指纹、逐步下降单调性、`rows_from_frozen_tape` 适配器与公式失配拒绝。

真实数据实证（2026-11-14）：

```powershell
& E:\anaconda\envs\dynaloop\python.exe experiments/factor_stream/effective_assessment.py `
    --output experiments/factor_stream/effective_assessment_20261114
```

输入：`holdout_lock.json` 的 3 个冻结候选（均为创业板 ETF，2020-09-15 首次入选，参数全冻结）+ 截止 2026-11-12 的独立留出行情。适配器逐期结果与 11-13 独立留出实验**零差异**（`max_target_diff=0`、`max_squared_error_diff=0`）。

结论：验证期 9 期、族规模 3、族级现实检验 p = 0.9840、逐步下降拒绝 0、**有效因子 0**；3 个候选中 1 个证据不足、2 个被证伪；`small_window=True`，已附功效警示。这与 `HOLDOUT_RESULTS.md`「通过数为零」一致，**说明防假发现生效，不是判定器失效**。

**如实标注**：本阶段目标「稳定产出有效因子」尚未达成。当前这批真实候选经得起检验的答案就是「无效」。下一步应改进搜索侧或扩大验证窗口与标的，而不是放松判定口径——放松口径只会退回「排行榜第一」那种假发现。

## 六、一手依据

- White, H. (2000), *A Reality Check for Data Snooping*, Econometrica；Hansen, P. (2005), *A Test for Superior Predictive Ability*, JBES。
- Politis & Romano (1994), *The Stationary Bootstrap*, JASA。
- Romano & Wolf (2005) 逐步下降族级错误率控制；Westfall & Young (1993) 最大统计量重采样。
- Harvey, Liu & Zhu (2016), *… and the Cross-Section of Expected Returns*（因子动物园多重检验，t 值门槛应约 3.0；Bailey & López de Prado 的折减夏普比率属同一族方法）。
- Dwork, Feldman, Hardt, Pitassi, Reingold, Roth (2015), *The Reusable Holdout / Generalization in Adaptive Data Analysis and Holdout Reuse*, Science / NeurIPS。
- `microsoft/RD-Agent` RD-Agent(Q), NeurIPS 2025, arXiv 2505.15155, §2.4（对照，说明差异而非引用其结论）。

上述均为方法学依据，不构成本项目对其在自适应回路下有效性的背书；本口径的保证范围严格限于本文第三节所列条件。
