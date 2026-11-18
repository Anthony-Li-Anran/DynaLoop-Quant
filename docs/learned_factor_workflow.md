# 本地仿 Qlib 的「从数据学因子」工作流

更新：2026-11-16（当日完成与 Qlib 的一手对照核查，见第八节）。权威口径：`docs/factor_evaluation_baseline.md`（指标与门槛）、
`docs/CORE_DESIGN.md`（阶段边界）、`docs/research_process.md`（七层流程）。

## 一、为什么有这一层

Anthony 11-15 明确否决了手写模板 + 枚举筛选的路线：「随机生成一堆公式去跑验证
完全不高效」「模板也是屎」「因子不是一拍脑袋想出来的，是从数据里面学来的」，
并要求「原模原样按照 Qlib 来搭」，同时「别直接调接口，参考模仿自己本地写」，
因为后期要改一些地方。

据此确定的主线：**先验只允许 Alpha158 / Alpha101 这类标准特征库，由可训练模型
从数据里学出因子与预测关系**；模型输出的预测分数就是「学出来的因子」，
不是手写公式、不是随机枚举、不是遗传规划。旧路线（15 个手写模板、DEAP 文法
随机采样、乘性权重更新抽样概率、6 个已认证因子）全部降级为历史对照，
**不得当作研究能力或交付成果**。

**不 import `pyqlib`**。全部代码在 `src/dynaloop/learned_factors/`，
按 Qlib 的模块边界本地仿写，每一层可单独替换。

## 二、模块对照（逐项对齐上游）

| 本地模块 | Qlib 对应 | 职责 |
| --- | --- | --- |
| `provider.py` | `qlib.data.data` 的日历 / 成分 / 特征提供者 | 读 `*.day.bin`（首元素是起始下标）、校验归档清单、按时点成分区间给可用掩码 |
| `expression.py` | `qlib/data/ops.py`、`qlib/data/_libs/rolling.pyx` | 本地表达式求值器；滚动 `min_periods=1`、回归三算子的最小二乘等价实现 |
| `alpha158.py` | `Alpha158DL.get_feature_config` / `Alpha158.get_label_config` | 158 个标准特征与默认标签，配置结构（kbar / price / volume / rolling、窗口、include / exclude）原样复刻 |
| `handler.py` | `DataHandlerLP` | 特征与标签物化；`infer_processors=[]`、`learn_processors=[DropnaLabel, CSZScoreNorm(label)]` |
| `dataset.py` | `DatasetH` | `train` / `valid` / `test` 三段与 `prepare(segment, col_set, data_key)` |
| `model.py` | `qlib.contrib.model.gbdt.LGBModel` | 本地封装 `lightgbm.train`；`loss=mse`、`early_stopping_rounds=50`、`num_boost_round=1000` |
| `workflow.py` | `examples/workflow_by_code.py` + `SigAnaRecord` | 四环节编排与描述性信号指标（IC、Rank IC、信息系数比率、分组、多空） |
| `experiments/factor_stream/preregistered_learned.py` | 项目自有（Qlib 无此层） | 历史样本外预注册冻结与第五层认证 |

**默认标签**：`Ref($close, -2)/Ref($close, -1) - 1`（决策日次日买入、再次日卖出）。
负位移只允许出现在标签里，`assert_no_future_reference` 对特征库硬性拒绝任何未来 bar。

**默认特征数**：K 线 9 + 价格 4 + 滚动 29 算子 × 5 窗口 `[5,10,20,30,60]` = **158**。
处理器与三段划分按 Qlib 官方 `workflow_by_code.py` / `qlib/tests/config.py` 的结构。

与 Qlib 的**唯一有意差异**（工程确定性，不是自创架构）：显式固定 `seed`、
`deterministic=True`、`num_threads=1`，使冻结模型可逐位复现；Qlib 默认把随机性留隐式。
这些参数全部进冻结文件。

## 三、四环节主线

```
归档（清单校验）→ Alpha158 特征库 + 标签 → DataHandler / DatasetH
  → LGBModel.fit(train, early-stop on valid) → predict(test)
  → 描述性信号指标（不判定）
```

模型训练是真正的学习：158 个标准特征作为输入、可训练模型拟合标签、早停用验证段。
**学出来的因子 = 模型在验证期每个决策日的预测分数**，一个族成员，不是 158 个
候选里挑一个。

Qlib 到此为止（记录指标，没有接受 / 拒绝规则）。本项目在此之上接已有的
**第五层认证出口**：把学得分数按月频时点横截面组织，走
`research_engine/cross_section.py` 的族级错误率控制、分段一致性与留一法，
落「有效 / 证据不足 / 证伪」三终态并出带通道标签的证据条目。
描述性指标（单调性、双腿方向、净价差、后期衰减、修正 t 值、因子自相关）
**只报告不否决**，依据见 `docs/factor_evaluation_baseline.md`。

## 四、因果隔离与一次性冻结

沿用历史样本外预注册，**不是**等未来数据物理到达：

1. **搜索期（截止日及以前）**：`materialise_until=cutoff`，只物化、只训练到截止日；
   验证期切片与统计一个都不构造。训练段与早停验证段的标签也必须在截止日前成熟。
2. **冻结**：族（学得模型）、158 个表达式、特征库指纹、模型超参与模型文本哈希、
   三段区间、成本、决策频率 / 持有期 / 成交时点、晋升规则、随机种子、数据清单
   一次性写进带指纹的 `preregistration.json`，**文件先落盘**。
3. **验证期（冻结日之后的历史数据）**：恢复冻结模型、一次性预测、一次性评分。
   冻结后不再重训、不调参、不改族；窗口被查看即消耗，再搜索须开新族、用新区间并登记前序轮次。

验证期特征只用当日及之前的 bar（滚动算子），标签只在评分时读取；
验证期信息不参与族生成、筛选与调参。隔离是**流程 / 信息隔离**，
产物里如实登记归档曾被描述性查看、日历区间与前序轮次重叠，
并明确**不宣称**跨轮序贯错误率、未来持续、盈利与因果。

## 五、后期可改的地方（这正是本地仿写的目的）

| 想改什么 | 改哪里 | 是否要重开预注册轮次 |
| --- | --- | --- |
| 换标准特征库（Alpha101、自定义标准库） | `alpha158.py` 的 `feature_config()` | 要 |
| 加 / 减滚动算子、改窗口 | `expression.py` 白名单 + `DEFAULT_CONFIG` | 要 |
| 换处理器（中性化、去极值、标准化） | `handler.py` 的 processors | 要 |
| 换模型（其它可训练模型） | `model.py`，保持 `fit` / `predict` 接口 | 要 |
| 改标签、持有期、决策频率 | `alpha158.label_config()` 与冻结里的 `decision_process` | 要 |
| 改三段区间 | 冻结文件里的 `segments` | 要 |
| 改数据归档 | `provider.py` + 归档清单 | 要 |

任何一项改动都会改变冻结指纹，必须开新轮次、用新的未消耗窗口并登记前序轮次；
**禁止**看到验证结论后回头改这些参数凑肯定结论。

## 六、不宣称

- 不宣称模型发现了「新公式」：Alpha158 是标准先验，学得的是特征到预测的关系。
- 不宣称可交易性、盈利、因果、未来持续；A 股逐笔撮合约束未建模。
- 不宣称时点成分股是商业级（现标 `approximate`，幸存者偏差未消除）。
- 不宣称跨轮序贯错误率；单轮族级错误率陈述附条件成立。
- 描述性指标不构成晋升依据，也不能反过来推翻族级结论。

## 七、验收

`tests/test_learned_factors.py`：158 项特征确定性、标签与回归算子同最小二乘逐位
一致、全特征可求值、防前视硬拒绝、二进制解码边界、三段不泄露、横截面标签标准化、
冻结前硬隔离、模型训练 / 恢复可复现、描述性指标无终态、学得分数可接入第五层认证。
端到端产物见 `experiments/factor_stream/preregistered_learned_20261115/`。

**真实数据一次性冻结验证（2026-11-15）**：中证 300 时点成分，训练 2008–2018、早停 2019–2021（标签在截止日前成熟），冻结 2021-12-31，验证 2022-01-28～2026-11-12 共 **58** 个时点横截面、宽度 297–300。训练 768479 行、模型早停第 10 轮。族级 p = **0.0060**、调整后 p = 0.0060、月度排序信息系数 +0.0362、信息系数比率 0.270、普通 t = 2.06、HAC 修正 t = 2.69；四块一致性全正、留一法正、无后期衰减 → 终态 **「横截面有效因子」**，证据带通道标签与双指纹。日频 Qlib 风格描述指标 IC 0.0119 / Rank IC 0.0100、单调性 1.0、双腿皆正、毛价差 0.01386、净 0.00378、换手 0.772 **只报告不否决**。

这一结论证明的是**学得因子在冻结样本外通过了族级检验**，不证明可交易性、盈利、未来持续或跨轮序贯；成分近似、幸存者偏差未消除、无中性化去极值、无逐笔撮合均如实登记在产物 `limitations` / `not_claimed` 中。产物另登记 `implementation_retry`：首次验证因指纹禁止 NaN 中断、未输出任何统计量，修复只换缺失标记，数值输入与冻结族 / 模型 / 参数逐位不变。

## 八、与 Qlib 的一手对照核查（2026-11-16）

可复跑资产（都不 import `pyqlib`、都不重算任何预注册产物）：

- `experiments/factor_stream/qlib_alpha158_reference.json`：由 Qlib 自己的 `Alpha158DL.get_feature_config` 机械生成的 158 项名称 / 顺序 / 表达式清单，独立于本地实现。
- `experiments/factor_stream/audit_qlib_alignment.py`：默认离线比对参考清单并做数值语义检查；带 `--refresh` 会重新拉取 Qlib 源码刷新清单。
- `experiments/factor_stream/qlib_alignment_report.json`：审计结果，**158 项 0 差异、名称顺序一致、标签一致、10 项数值语义全通过**。
- `tests/test_learned_factors.py` 的 `TestQlibAlignment` 把这份对照固化为回归测试。

核查覆盖的 Qlib 源码：特征与标签（`loader.py` / `handler.py`）、算子（`ops.py`、回归三算子的 `rolling.pyx`）、处理器（`processor.py` 的 `DropnaLabel` / `CSZScoreNorm` / `zscore`）、三段（`dataset.py` / `config.py`）、模型（`gbdt.py`）、信号记录（`record_temp.py` 的 `SignalRecord.generate_label` 用 `DK_R` 原始标签、`SigAnaRecord`）、信号指标（`eva_alpha.py` 的 `calc_ic` / `calc_long_short_return`）。

**核查后修正的四处**（都不改 158 项表达式）：

1. `Rsquare` 对滚动标准差接近 0 的窗口置空（`ops.py::Rsquare._load_internal`，atol=2e-05）。
2. `Slope` / `Resi` 在价格恒定窗口返回 0 而非空值：Qlib 的 Cython 实现只需 x 分母有效；此前本地把三个回归量一起置空了。
3. 描述性信号分析对齐 Qlib：`calc_long_short_return` 是**半价差** `(top−bottom)/2` 并另返回全池均值；逐日相关只剔除缺失**对**、不丢整天。认证层自己的分组全价差是另一套诊断，两者相差 1/2 因子、均只报告（已在 `docs/factor_evaluation_baseline.md` 标注）。
4. 冻结模型改为二进制写入，避免 Windows 文本模式把 LF 转成 CRLF、使文件字节与冻结清单里的哈希不一致；验证阶段同时接受历史产物的两种表示。

**有意保留的差异（不是不一致）**：训练标签是 Qlib 默认日频 `T+1→T+2`，认证层观察网格是月频月末→下月末（工程默认值，两条都在冻结文件里登记）；族级错误率控制、预注册冻结、`materialise_until` 信息隔离是本项目自有的上位设计，Qlib 没有对应组件；Qlib 的 `DataHandlerLP` 维护 `DK_R` / `DK_L` / `DK_I` 三份副本，`DropnaLabel.is_for_infer()=False` 只作用于学习副本，本地 handler 保留一份帧并对两个视图都丢掉缺标签行——由于 `Alpha158` 默认 `infer_processors=[]`，特征值完全相同，差别只在推理副本的行数。

**对已冻结轮次的影响**见 `preregistered_learned_20261115/alignment_note.json`：核查逐项统计了真实归档里受修正影响的行，并区分训练段与验证期决策日；**不拿已查看的验证窗口重出结论**。
