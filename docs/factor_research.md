# 时间推进的因子研究

定位：产出可追溯的因子研究证据，供未来预测/交易模型使用。不是已有盈利保证的交易产品。

## 组件与流程

1. Data 的真实行情快照输入 `FactorTape`；原 TemplateCandidateGenerator 枚举公式，FactorFrame 计算因果序列。OHLCV 和5/10/20/60窗口组合产生128个不同公式。
2. `TemporalResearch.step(i)` 仅读取 i 当时成熟的次日开盘到21日后开盘收益。每21个bar推进，504bar跨度中取24个不重叠标签；后12个验证，前段拟合且清除跨区间未成熟标签。评分使用实际预测误差对零/历史均值的改善及两倍标准误惩罚，局部IC不再驱动搜索。
3. 原 ExplorationPolicy 和 RewardWeightedUpdater 更新模板概率，保留10%均匀探索。全部不合格时概率向均匀回退。基于已兑现提案预测与实际收益的关系反转调整探索；波动告警只作独立诊断。两种告警均没有统计误报保证。
4. Sleep 回放已成熟历史，近期回放对照用相邻历史，Sleep均匀保留更久历史。旧斜率须与近期方向兼容，且改善近期验证误差，才能混入模型；否则拒绝。每轮48次模型评价预算，包含无足够历史时的失败尝试，不保证相同样本行数或CPU时间。
5. 决策冻结后，实验层追加未来证据、成本回测与因子卡片。只有当时已成熟的证据才能供后续系统消费；完整报告不可直接回填历史特征。

原固定窗口 LoopOrchestrator 保留。时间模式为同一个 Research 模块的公开接口和实验CLI，不依赖历史神经大脑。当前 Web 页仍是原固定窗口入口，新增时间研究通过CLI运行；不宣称已经完成专用网页工作台。

## 运行

使用现有 `experiments/full_loop/fetch_data.py` 获取或核验快照。指定环境：

```powershell
& E:\anaconda\envs\dynaloop\python.exe experiments/factor_stream/negative_control.py
& E:\anaconda\envs\dynaloop\python.exe experiments/factor_stream/run.py --output experiments/factor_stream/run_reproduction
& E:\anaconda\envs\dynaloop\python.exe experiments/factor_stream/repair_controls.py
& E:\anaconda\envs\dynaloop\python.exe experiments/factor_stream/repair_report.py experiments/factor_stream/run_reproduction
& E:\anaconda\envs\dynaloop\python.exe experiments/factor_stream/evidence_review.py experiments/factor_stream/run_reproduction
& E:\anaconda\envs\dynaloop\python.exe experiments/factor_stream/follow_factors.py experiments/factor_stream/run_reproduction
```

`evidence_review.json` 记录单个公式覆盖的日期数、按日期等权的误差改善、移除贡献最大日期后的结果，以及固定同一批候选时历史回放对排序和接纳的影响。固定候选的比较无法估计回放对后续搜索策略的影响。

`factor_followup.csv` 和 `factor_followup.json` 按标的和公式跟踪首次入选后的表现。多种子同日入选取最小种子，冻结首次入选的全部参数，排除入选当期，并记录每期标签成熟日期。前两个连续六期窗口分别比较零预测和当时可计算的历史均值。不同公式可能共用同一时期的行情，双窗口胜出仅供探索，不构成认证。

留出验收先从跟踪结果冻结候选及评分规则，再下载研究截止日之后的不复权行情。输出保留请求信息、行情指纹、冻结文件指纹和逐期结果。前两个连续六期窗口都齐全才判定通过或失败。通过仅代表满足这项筛选规则。冻结文件与输出目录要求新路径，续评使用原冻结文件和新的输出目录。

```powershell
& E:\anaconda\envs\dynaloop\python.exe experiments/factor_stream/holdout.py freeze experiments/factor_stream/run_v4 experiments/factor_stream/holdout_lock_new.json
& E:\anaconda\envs\dynaloop\python.exe experiments/factor_stream/holdout.py score experiments/factor_stream/holdout_lock_new.json 2026-11-12 experiments/factor_stream/run_holdout_reproduction
```

已有冻结文件和截至 2026-11-12 的结果见 [留出验收记录](../experiments/factor_stream/HOLDOUT_RESULTS.md)。

输出目录必须不存在，避免覆写证据。完整配置、数据指纹、源码与协议指纹保存于manifest.json。每个标的/种子/方法保存trace、checkpoint和基准成本账本。checkpoint含策略、随机状态、数据前缀指纹；restore拒绝历史被改写的输入。追加数据后可继续调用step。

`evidence.csv` 是逐期未来证据；`factor_library.json` 是带公式、覆盖日期数、标的、误差和重复性信息的研究库，不是已认证的生产因子库。`decision_ic.json` 汇总实际不重叠决策上的关联，`backtests.csv` 包含成本敏感性。短窗口重叠标签IC只作诊断，随机游走也会产生很高的该指标。

## 使用限制

当前筛选不再强制选出赢家，支持insufficient_evidence；暂时通过者仍为provisional，不提供多重搜索错误率保证。全量滚动参考评价更多候选，不能伪称等预算。有限模板搜索不代表无限符号表达式探索。因子重复性只是与当轮其他候选的历史相关性，不是已经证实对任意下游组合模型的边际贡献。小样本因子卡不发放显著性认证。v3和更早运行的源码在其source_snapshot中归档；v2检查点拒绝旧v1状态，避免静默改变运行语义。

三只存续ETF、不复权价格、未提供现金分红和退市结算；不承诺个股生存偏差控制。手续费和固定滑点已计入辅助模拟，无法保证现实开盘可成交。后续新闻输入与大模型提取不在当前实现中。
