# 大脑工程说明

定位：创新且可靠的开源工程。第一里程碑是可复现的真实反馈学习通路，不以收益或论文主张作为已完成的证据。

## 已实现的路径

`model.LoopedTransformer` → `training_engine.WakeLearner` → `orchestrator.brain.run_brain` → 现有 `FactorSignalStrategy` 与回测引擎。

- CPU/CUDA 上运行的小型共享参数 Transformer，默认 width=128、heads=4、blocks=2、loops=4、window=64。每轮注入输入；无跨窗口隐藏状态，无 dropout。真实数据实验采用 width=64、blocks=1、loops=3、window=32，并记录实际配置和参数量。
- 输入是固定模式的数值特征窗口。逐窗口按特征标准化，不拟合未来统计量。该标准化会丢掉窗口绝对水平信息；其适用性需要真实数据对照。
- 每个时间步先预测，再用该步成熟的历史标签更新。标签为 H 个观测后的 close-to-close 简单收益。H 不是日历间隔。
- Huber loss（delta=0.01）、AdamW、梯度裁剪；每次训练包含最新成熟样本与有界历史随机回放。
- 完整检查点保存模型、优化器、输入窗口、待成熟标签、回放库、随机状态及版本。单个 learner 由一个调用者串行拥有，不支持并发 observe/save。
- 输入必须为单标的、严格递增且同一时区的规范时间戳。拒绝重复时间、非有限值、混入标的和特征模式变化；不填充缺失值。
- 每个预测记录预测版本、更新后版本和成熟标签来源。末尾未成熟标签保留，不以零收益补齐。
- 回测复用已有策略，强制 next-bar 成交；训练目标是 close-to-close 预测误差，与含成本的执行收益分别报告。

## 运行

PyTorch 是可选依赖：`pip install -e ".[brain]"`。基础平台无需导入 PyTorch；在本仓库使用 AGENTS 指定的解释器安装和运行。CPU 官方源也可用于安装 PyTorch。

```powershell
& E:\anaconda\envs\dynaloop\python.exe -m dynaloop.orchestrator.brain --records bars.json --features close volume --symbol TEST --output brain-run.json --checkpoint brain.pt
```

`bars.json` 是现有 Data 接口导出的冻结 OHLCV JSON 数组（date/open/high/low/close/volume），可以额外包含已经按当时可用信息计算的因子列。特征显式选择，不把全部数值列自动送入模型。快照需至少包含 window+horizon 行。

输出包含输入摘要指纹、配置、PyTorch 版本、参数量、逐步事件、成熟预测 MAE、待成熟标签数及已有回测报告。首次运行从随机初始化开始，其收益不能被当成训练完成后的能力评估。预测前预计算的因子也必须因果有效；接口无法识别调用者传入的任意列是否偷看未来。

未提供来源元数据时，报告只标记为调用者提供的快照，不默认宣称真实市场数据。Python 接口可传入 `source_metadata` 记录来源、快照版本及合成标记。跨 PyTorch 版本或硬件的逐位一致性不作保证；数值训练异常时应停止并从最近成功检查点恢复。

```python
from dynaloop.training_engine import WakeLearner
learner = WakeLearner.load("brain.pt")
# 仅输入检查点最后时间之后的新观测；特征集合与顺序由模型配置固定。
event = learner.observe("2026-11-13", 12.5, {"close": 12.5, "volume": 1000}, symbol="TEST")
learner.save("brain.pt")
```

## 验收状态与后续

1. 已完成三只 ETF 的训练/开发/前向测试分离、三个随机种子、简单预测与 GRU/普通 Transformer/冻结/Wake/Sleep 对照。519 项后端测试与 4,320 个评分位置的结果审计通过，但模型未通过预设效果标准。见 [实验报告](../experiments/full_loop/RESULTS.md)。后续需要改善并重新验证预测能力，不能把已看过的测试区间继续称为独立测试。
2. Sleep 已实现独立条件扩散生成器、真实回放混合训练和候选晋升闸门，见下节；历史代理 Sleep 仍是另一条路径。统计保证尚未建立。
3. LLM 新闻分析的**时间对齐纪律仍然有效**：记录发布时间、抓取时间、模型结果可用时间、来源与模型/提示版本；按结果真正可用时间对齐，不能按原新闻发布时间回填。更换特征模式创建新模型版本。
4. **主观分析侧已于 2026-11-18 实际接入 WorkBuddy 大模型接口（keyless）**，作为架构图「主观策略」分支的人类辅助解读：`alternative_data` 公共数据层提供四类输入（A 股数据、新闻、舆情周期、策略库），前端 `/subjective` 用 `@tencent-ai/workbuddy-cloud-sdk` 真实调用并流式呈现。严格边界：**模型输出是主观解读，不是因子、不是判定、不是投资建议，不进冻结指纹、不进族级检验、不宣称有效或收益**；默认不联网抓取新闻，真实源 best-effort、缺失明确标不可用。此处「实际接入 LLM」与「神经大脑（醒睡自进化）主线暂缓」是两件事，后者状态不变。

Smoke tests 使用明确的合成夹具，只验证工程行为，不证明金融预测有效。测试：`python -m unittest discover -s tests -p test_brain.py`。

## 当前验证（2026-11-12）

在项目指定 Python 3.11 环境、PyTorch 2.6.0+cpu 上，10 个大脑验收测试通过：共享参数与梯度、标签成熟顺序、历史回放容量、未来数据隔离、恢复一致性、重复运行一致性、输入拒绝、训练失败保护，以及 CLI 报告/检查点和下一根 bar 接入约束。默认双特征配置有 405,761 个参数，前向与反向 smoke 检查通过。未做真实市场效果评估，不据此声称在线更新有效或优于基线。

最终完整后端回归：509 项全部通过，耗时 43.685 秒，无跳过；`compileall` 通过。本轮未修改前端，未重跑前端构建。

上述 509 项为首版 Wake 验收记录；完整 Sleep/CUDA 扩展的最终验收以完整闭环实验报告为准。

## 完整神经闭环

运行入口：`python -m dynaloop.orchestrator.full_loop --phase development --device cuda --output experiments/full_loop/my-development`。数据获取：`python experiments/full_loop/fetch_data.py`。训练/验证/测试区间及验收标准见 `experiments/full_loop/PROTOCOL.md`。测试阶段使用新输出目录，禁止覆盖既有实验。`--wake-lr` 只在开发区间选择，最终测试前固定。

`ConditionalDiffusion` 使用条件 DDPM：输入真实过去 20 步对数收益率（百分数），去噪生成后续 window+horizon 步收益率。32 步 cosine 噪声调度，小型 MLP 同时接收有噪路径、条件与时间嵌入，训练目标为噪声 MSE。尺度和异常幅度边界仅由首次真实训练路径拟合。反向采样对重建路径幅度设界，并拒绝非有限值与退化/极端波动路径，记录接受率及生成/真实标准差比值。该诊断不等于完整分布校准。

从同一生成路径重建正价格，统一使用 `price_features` 计算收益率、5/20 步动量、20 步波动率和回撤，再计算 horizon 步收益标签。真实和合成样本调用同一套特征函数；训练集拟合的 `FeatureScaler` 固定用于后续数据。实验关闭模型逐窗口标准化以保留波动水平，避免对因子再次消除其绝对水平信息。

`SleepController` 每 63 步尝试创建候选：最近最多 512 条已成熟真实路径更新生成器，生成 128 条替代路径；候选训练 25 个小批次，loss=真实 Huber+0.2×合成 Huber。Wake 回放永远只存真实样本。候选与 incumbent 接受同样的后续真实更新；只有创建候选之后实际记录的预测参与影子评分。32 个影子预测标签成熟后，候选 MSE 更低则晋升，否则丢弃；晋升只影响后续预测。记录每次父版本、候选编号和服务模型谱系。

`SleepController.save(new_directory)` 保存 incumbent、活动候选、生成器/优化器/RNG、影子评分、特征尺度和日志；写完后才创建 complete.json。`SleepController.load(directory, device=...)` 恢复。Wake 检查点支持 CPU/CUDA 迁移，扩散随机状态精确续跑要求与保存时相同的 CPU/CUDA 后端。跨硬件逐位一致不作保证。

基线包含零预测、训练均值、验证集选择正则强度的 ridge、GRU、普通 Transformer、冻结循环模型、Wake-only、额外真实回放和完整 Sleep。额外真实回放使用同一候选训练/闸门预算、合成损失权重为零，以检查收益是否仅来自额外更新。独立测试之前冻结配置；测试标签成熟后的在线更新属于预先规定的在线评估，不是离线调参。

算法参考：[DDPM](https://arxiv.org/abs/2006.11239)、[Improved DDPM](https://proceedings.mlr.press/v139/nichol21a.html)、[TimeGrad](https://proceedings.mlr.press/v139/rasul21a.html)。这里实现的是小型条件数值路径模型，不声称复现 TimeGrad 的网络与结果。

2026-11-13 完整验收：519 项后端测试通过（47.089 秒，无跳过），真实 GPU 检查点恢复通过。正确不复权数据的最终实验约 540 秒，72 次 Sleep、40 次晋升、32 次拒绝；效果验收未通过。源请求审计发现的空复权参数覆盖错误已修复，旧试验保留 INVALID 标记，未计入结果。影子日志里的 MSE 使用小数收益平方，汇总预测报告使用百分数收益平方。
