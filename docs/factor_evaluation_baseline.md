# 因子评估口径：与 Qlib 及主流开源实践对齐

更新：2026-11-15。Anthony 明确要求「别自己想标准，严格参考 Qlib 和其他 GitHub 上的优秀实践」。本文是**评估指标与晋升门槛的权威来源**，优先于 `docs/cross_section_factor.md` 与 `docs/effective_factor.md` 中任何早期自定阈值；后两份文档仍负责通道隔离、防前视与错误率陈述。

一手核查于 2026-11-15，来源为上游仓库源码与文档，不是二手博客：

| 来源 | 位置 | 核查内容 |
| --- | --- | --- |
| Qlib（微软） | `qlib/workflow/record_temp.py` → `SigAnaRecord._generate` | 报告 `IC`、`ICIR`、`Rank IC`、`Rank ICIR`；`ana_long_short=True` 时另报多空年化收益与夏普 |
| Qlib | `qlib/contrib/eva/alpha.py` → `calc_ic` | 逐决策日 `groupby(date)` 内 `pearson` / `spearman` 相关；`calc_long_short_return` 返回 `(r_long - r_short)/2`；`pred_autocorr` 为相邻期预测截面相关 |
| Qlib | `qlib/contrib/evaluate.py` → `risk_analysis` | `mean`、`std`、`annualized_return`、`information_ratio = mean/std*sqrt(N)`、`max_drawdown`；回测报告含成本 / 不含成本并列 |
| Qlib | `examples/benchmarks` 的 `DatasetH.segments` | 标准 `train / valid / test` 三段划分（如 2008–2014 / 2015–2016 / 2017–2020） |
| alphalens-reloaded | `factor_information_coefficient`、`mean_return_by_quantile`、`factor_returns`、`quantile_turnover`、`factor_rank_autocorrelation` | 逐期 Spearman 排序信息系数、信息系数比率、分位组收益、多空、换手、排序自相关 |
| qweave | `docs/factor_evaluation.en.md` | 分组单调性用 **Kendall tau** 作为描述量；Newey–West 修正的 t 统计量；显式 `entry_lag`；明确「衡量因子是否有信息，而非策略赚多少」 |
| 数据窥探控制 | `arch.bootstrap` 的 `SPA` / `RealityCheck` / `StepM` / `MCS`；GitHub 上 AlphaForge、miniAladdin、Fin-RSI 的研究完整性清单 | White 现实检验、Hansen 优越预测能力、平稳区块自助、Deflated Sharpe、Purged+Embargoed 交叉验证、试验账本、成本后净收益作 headline |

## 一、核查结论：上游怎么判定「有效」

1. **Qlib 不做因子接受判定**。`SigAnaRecord` 只把 IC / 排序信息系数及其比率、以及可选的多空收益写进实验记录；源码里没有显著性阈值、没有「通过 / 拒绝」、没有单调性要求、没有多空双腿必须同号的规则。Qlib 是**评估与记录框架**，不是认证器。
2. **alphalens 同样只出撕页（tear sheet）**：逐期信息系数、信息系数比率、分组收益曲线、多空、换手与排序自相关。分组单调性是图表与描述，不是一票否决。qweave 把它明确实现为 Kendall tau 描述量。
3. 业界常用的**经验显著性判据**是信息系数的 t 统计量（常引用 t > 2）与信息系数比率；这些是报告值，不是库里的硬门槛。
4. **严谨实践额外要求的两件事**，恰恰是本项目已有统计层的价值所在，且不与之冲突：
   - 多重试验 / 数据窥探控制：White 现实检验、SPA、StepM、Deflated Sharpe、**试验账本**（记录全部尝试次数，包括被放弃的候选）；
   - 样本外卫生：训练 / 验证 / 测试划分、purge 与 embargo、成本后净收益作 headline、留存全部失败候选。
   本项目的「冻结族 + 全族共用时间索引路径的区块自助 + 最大统计量逐步下降」属于 White 现实检验 / SPA 家族；「预注册冻结 + 指纹 + 前序轮次登记」对应试验账本。这两层**保留**。

## 二、对齐表：指标、来源、身份

| 指标 | 上游来源 | 本项目实现位置 | 身份 |
| --- | --- | --- | --- |
| 逐期排序信息系数 | Qlib `calc_ic` 的 Spearman 序列 | `cross_section.py` `_rank_ic` | **主统计量** |
| 排序信息系数比率（均值 / 标准差） | Qlib `SigAnaRecord` 的 `Rank ICIR` | `cross_section.py` 诊断 `rank_icir` | 报告 |
| 信息系数 t 统计量（普通） | 业界惯例（t > 2） | 诊断 `ic_t_stat` | 报告 |
| 信息系数 t 统计量（纽维–韦斯特修正） | Newey & West (1987)；qweave `t_nw`；`strategy-tail` HAC 规范 | 诊断 `ic_t_stat_hac` / `hac`（Bartlett 核） | **仅报告** |
| 分位组平均超额收益 | alphalens `mean_return_by_quantile` | 诊断 `mean_group_excess_returns` | 报告 |
| 分组单调性 | qweave Kendall tau / alphalens 图表 | `quantile_monotonicity`（Spearman）、`quantile_monotonicity_kendall` | **仅报告** |
| 多空毛 / 净价差 | 认证层按 alphalens 分组超额收益给**全价差**（最高组超额 − 最低组超额），成本后并列；Qlib `calc_long_short_return` 的**半价差** `(r_long−r_short)/2` 另在 `learned_factors.signal_analysis` 报告，两者相差 1/2 因子、均为描述性 | `gross_long_short_spread` / `net_return`；信号分析层 `long_short_return` / `long_average_return` | **仅报告** |
| 年化收益与信息比率 | Qlib `risk_analysis`（月频 `ann_scaler=12`） | `long_short_annualized_return`、`long_short_information_ratio` | 报告 |
| 换手、成本 | alphalens `quantile_turnover`、Qlib 成本参数 | `mean_turnover`、`mean_cost`，毛净并列 | 报告 |
| 因子数值 / 因子秩自相关（滞后 1 期） | Qlib `pred_autocorr` / alphalens `factor_rank_autocorrelation` | `evaluation_metrics.py` → 诊断 `factor_autocorrelation` | **仅报告** |
| 时序通道预测与改善量滞后 1 期自相关 | Qlib `pred_autocorr` 在单标的时序上的对应形式 | 择时 `stability.series_diagnostics` | **仅报告** |
| 族级错误率控制 | White 现实检验 / Hansen SPA / StepM（`arch`） | `resampling_tools.py` 共用时间路径 + 逐步下降 | **晋升门槛** |
| 分段一致性、留一法 | GitHub 实践的子期稳健性 / PBO | `_stability` 的 `block_agreement`、`leave_one_out_positive` | **晋升门槛** |
| 期数下限、功效警示 | 短窗口不确定性 | `min_periods`、少于 24 期警示 | **晋升门槛** |
| 后期衰减比 | **无上游依据（本项目旧版自创）** | `decay_ratio` | **降级为区间诊断，不再否决** |

## 三、本次修正具体废除了什么

旧版把以下四项设计成**独立于显著性的一票否决**，一线核查后确认它们不是 Qlib / alphalens / qweave 的标准：

1. 分组单调性 ≥ 0.9（上游只把单调性作为描述量，且用 Kendall tau）；
2. 多空两条腿必须各自方向正确（A 股不可卖空时短腿本来就是诊断性相对收益）；
3. 扣成本后净价差必须为正才允许晋升（上游要求**报告**毛净并列，不把它写成信息含量的判据）；
4. 后半段排序信息系数不得低于前半段的一半（上游以「区间 / 状态拆分」报告稳健性，不设该硬阈值）。

修正方式：`CrossSectionConfig.report_only_gates = True`（默认）。这四项仍逐项计算、写进 `diagnostics.checks`，并在结论理由里以「描述性诊断低于阈值（非否决）」显式列出；`diagnostics.passed` 只由 `complete_periods_sufficient` 决定。设 `False` 可恢复旧版否决行为，仅供历史对照。

这**不是**放松统计门槛：族级错误率控制、分段一致性、留一法、期数下限、防前视、决策与成交分离、标签成熟、全参数留痕指纹一寸未动。移除的是**没有上游依据的额外否决**，把晋升判定交还给有统计依据的族检验。

## 四、保留的额外统计层及理由

| 层 | 为什么保留 | 上游对应 |
| --- | --- | --- |
| 一次性预注册冻结 + 指纹 | 冻结族与全部参数在接触验证数据之前固定 | Qlib `train/valid/test` 三段；GitHub 实践的预注册与试验账本 |
| 全族共用时间路径的区块自助 + 最大统计量逐步下降 | 搜索过很多候选时，单次 t 检验会虚报 | White (2000)、Hansen (2005)、Romano–Wolf；`arch.bootstrap.SPA/StepM` |
| 前序轮次登记、消耗窗口清单 | 反复换窗口试会让跨轮错误率膨胀 | 试验账本 / Deflated Sharpe 的 `n_trials` 要求 |
| 因果隔离为**流程隔离**而非「等未来数据」 | 用户 2026-11-15 定调：历史样本外即可，不要求物理上未来到达 | Qlib 的历史 `test` 段 |
| 成本、换手、毛净并列**报告** | 上游要求成本后净收益作 headline | Qlib `risk_analysis` 含 / 不含成本；Fin-RSI 研究完整性清单 |

## 五、不宣称

- 不宣称跨轮序贯 / 自适应错误率控制（多轮预注册均逐轮登记，跨轮不合并）。
- 不宣称共形覆盖、盈利、可交易性、因果、未来持续。
- 不宣称商业级时点成分股（幸存者偏差未消除）、行业 / 市值中性化、去极值、容量扫描已实装。
- 纽维–韦斯特修正 t 值与因子自相关**只作描述性诊断**，不参与族级检验、稳定性判据或终态；普通 t 值仍并列保留。自动带宽是有限样本的经验规则，不宣称最优带宽。
- Qlib / alphalens 本身**不提供**因子认证；本项目的认证器是在其评估指标之上，叠加数据窥探控制与预注册冻结，这一层是本项目自己的设计，已单独标注来源与假设。

## 六、口径变更后的实证对照（2026-11-15）

`experiments/factor_stream/reassess_baseline.py` 对**已冻结的三轮**在不改族、不改参数、不改成本、不改验证数据的前提下按新口径重算，原 `certification.json` 全部保留，新增 `baseline_certification.json` 与 `baseline_summary.json`。

| 轮次 | 标的池 / 窗口 | 期数 | 族级 p | 旧口径有效数 | 对齐后有效数 |
| --- | --- | --- | --- | --- | --- |
| 1 | 沪深 300 时点成分，冻结 2021-12-31，验证 2022–2026 | 58 | 0.0120 | 0（全被自创门槛拦下） | **4** |
| 2 | 中证 500 时点成分，冻结 2023-12-31，验证 2024–2026 | 34 | 0.1039 | 0 | **0**（族级未过 α=0.10） |
| 3 | 中证 500 全历史有价格标的，冻结 2021-12-31，验证 2022–2026 | 58 | 0.0010 | 1 | **2** |

第二轮在族级检验未过显著水平时**仍然给出否定结论**，是本次修正没有放松统计层最直接的证据：移走的只是四项上游不存在的额外否决，族级错误率控制、分段一致性、留一法、期数下限、防前视与全参数留痕一寸未动。

通道二（择时）另有 44 期完整预注册：`experiments/factor_stream/preregistered_timing_20261115/` 中 5 个冻结候选全部 `refuted`、族级 p=1.0，一致差于零预测与历史均值基线。这是搜索期过拟合的真实否定结果，未再通过调整选族规则去争取肯定结论；该通道的改进方向是嵌套验证 / 正则化与试验账本，而不是放宽判定。

所有轮次均逐轮登记冻结族、冻结指纹、污染接触与前序消耗窗口；**跨轮序贯错误率不宣称**，任何单轮肯定结论都不得外推为跨轮稳定或未来持续。

## 七、收尾补齐的两项描述性指标（2026-11-15）

核查结论见第一节；这里记录实现口径，避免以后再被当成「自己想的标准」。

**实现位置**：`src/dynaloop/research_engine/evaluation_metrics.py`，两通道共用纯数学函数。每个返回值都带 `promotion_role = "report_only"`；模块的文档字符串明确禁止把它们变成否决项。

1. **纽维–韦斯特修正 t 值**。对逐期排序信息系数序列（择时通道是损失改善量序列）计算
   `长期方差 = γ₀ + 2·Σ_{l=1..L}(1 − l/(L+1))·γ_l`，`t = 均值 / sqrt(长期方差 / n)`；样本自协方差用 `ddof=1`，因此 `L=0` 时与普通 t 统计量**逐位相等**（有测试锁定）。滞后阶默认用 Newey & West (1994) 自动带宽 `floor(4·(n/100)^(2/9))`，实际取值写进产物；也允许显式传 `lag` 做敏感性分析，且会留痕。**长期方差非正、方差为零或期数不足时返回空值并标注原因，绝不回退成普通 t 值**——这条纪律来自 `strategy-tail` 的 HAC 规范。普通 t 值并列保留，便于对照。

2. **因子自相关（滞后 1 期）**。Qlib `pred_autocorr` 用**原始分数值**做相邻期截面的皮尔逊相关；alphalens `factor_rank_autocorrelation` 用**因子秩**做斯皮尔曼相关，作为换手 / 信号衰减代理。本项目两者都算，且只比较**相邻两期共同存在的标的**，时点标的池发生变化时不凭空制造观测。附带报告 `(1 − 平均秩自相关)/2` 换手代理，并显式注明**它不是成本模型算出的实际组合换手**。择时通道没有横截面，对应实现为预测序列与改善量序列的滞后 1 期自相关。

**关键不变量**：这两类指标只写进诊断字典与 `spec` 的来源登记，**不进配置、不进指纹、不进族检验、不进稳定性判据、不进终态**。因此按新增指标后重算三轮冻结认证，族级 p 值、调整后 p 值、有效因子列表与指纹都必须逐位不变；这一条在收尾验收里实测核对。新增覆盖：纯函数 15 项测试、两通道集成 5 项断言。

**一条踩过的坑，如实登记**：收尾时曾把两判定器的 `schema_version` 从 1 升到 2，以为「加了字段就该升版本」。但该版本号经 `config.to_dict()` 进入冻结报告指纹，升版本会让**全部历史指纹漂移**、历史认证无法逐位复现。已当场发现并回退到 1，两处常量旁加了警示注释，`docs/research_process.md` 不可绕过清单增列第 11 条。结论：**附加纯报告字段属于向后兼容扩展，不升版本号**；只有改变既有字段语义或判定逻辑时才允许升，且必须同时声明历史产物如何迁移。

**通道二产物保持原样**：`preregistered_timing_20261115/certification.json` 是冻结窗口的一次性验证证据，脚本按设计拒绝二次验证。为补几个描述性字段而重跑该窗口会违反「一次性验证」纪律，因此**不重算**；该轮族级 p=1.0、5 个候选全部 `refuted` 的否定结论不受影响，新增指标对未来轮次生效。

## 八、搜索强度与衰减的量化工具体系（2026-11-16）

Anthony 要求此前登记的「有意差异」约束作废，按权威文献与项目重新设计因子研究系统。一手调研的逐条来源与结论见 **`docs/factor_research_foundations.md`**。本节只登记新增指标的身份，避免再次被当成自创标准。

**核心立场变化**：一个因子的显著性不是它自己的属性，而是「因子＋产生它的搜索过程」的联合属性；不报告搜索强度的显著性没有解释力。因子必然衰减，评估窗口与调仓频率应由测得的半衰期决定，而非既定常数。

| 指标 / 工具 | 上游来源 | 实现位置 | 身份 |
| --- | --- | --- | --- |
| 概率夏普比率（PSR） | Bailey & López de Prado (2014)；mlfinlab `backtest_statistics.probabilistic_sharpe_ratio` | `search_bias.py` `probabilistic_sharpe_ratio` | **仅报告** |
| 折价夏普比率（DSR） | 同上，`deflated_sharpe_ratio`；基准 `SR₀=√V[(1−γ)Φ⁻¹(1−1/N)+γΦ⁻¹(1−1/(Ne))]` | `search_bias.py` `deflated_sharpe_ratio` | **仅报告**，N 与 V 必须来自试验台账 |
| 回测过拟合概率（PBO/CSCV） | Bailey, Borwein, López de Prado & Zhu (2014/2017) | `search_bias.py` `backtest_overfitting_probability` | **仅报告**，评估的是选择过程而非单个策略 |
| 试验台账 | DSR 的 `n_trials` / GitHub 研究完整性清单 | `trial_ledger.py` | **研究过程留痕**，记录全部尝试含失败，追加写不可删改 |
| 稳健去极值 / 横截面标准化 | Qlib `RobustZScoreNorm`（median/(MAD·1.4826)，clip）、`CSZScoreNorm` | `neutralization.py` | **仅报告 / 预处理选项**，未来轮次进冻结 |
| 行业 / 市值中性化残差因子 | 每日横截面 OLS：因子 ~ 行业哑变量＋log 市值，取残差再标准化 | `neutralization.py` `neutralise_cross_section` | **仅报告 / 预处理选项**，控制项由假设决定 |
| 残差排序信息系数 | FactorBench：剥离风格后残差信息才代表增量信息 | `neutralization.py` `residual_information_coefficient` | **仅报告** |
| 信息系数半衰期 | `IC(h)=corr(Factor_t, Ret_{t+1+h})`；指数拟合 `ln2/λ`，线性插值并列 | `decay.py` `ic_decay_curve` / `ic_half_life` | **仅报告**，用于定窗口与再认证节奏 |

**关键不变量（与第七节一致）**：上述全部返回值带 `promotion_role = "report_only"`，**不进配置、不进冻结指纹、不进族检验、不进终态**。因此把它们接入后，所有已冻结轮次的族级 p 值、指纹、终态必须逐位不变。中性化 / 去极值要真正改变因子值，只能在**新预注册轮次**里作为处理器写进冻结配置；禁止拿已查看窗口重算后换结论。

**试验台账的纪律**：`TrialLedger` 追加写、拒绝重复 trial_id、拒绝删除；`n_trials` 排除 `aborted` 但包含 `refuted` 与 `failed`。这是 DSR / PBO 唯一合法的输入来源，禁止事后估计「大概试了多少次」。

**当前实现状态**：工具层已落地并有 15 项单元测试（含与 mlfinlab 公式的手算对照、CSCV 注入信号检出、中性化正交性、半衰期指数恢复）。**尚未接入预注册脚本产物**，也尚未做目标口径对齐与因子池化；这些属于下一阶段工程，见 `docs/factor_research_foundations.md` 第六节。
