# 高度编码 COMSOL 批量接口

输入 JSON 编码，输出可追溯的本征模候选数据。可以直接由 Python、命令行或 MCP 调用，不需要逐根操作几何节点。

## 输入

每个案例包含 `case_id`、`geometry`、`materials`、`tuning`、`study`、`mesh`、`runtime`。矩阵的行沿 +y、列沿 +x，元素是 `height_levels_nm` 的索引；也可以用相对于案例 JSON 的 `encoding_file` 指定纯 JSON 矩阵。

```json
{
  "cases": [{
    "case_id": "my_code",
    "geometry": {
      "rows": 2, "cols": 2,
      "pillar_width_nm": 100, "pitch_nm": 150,
      "height_levels_nm": [100, 200],
      "encoding": [[0, 1], [1, 0]]
    },
    "tuning": {"parameter": "height_offset_nm", "values": [0, 10]},
    "study": {"type": "eigenfrequency", "search_frequency_THz": 335, "number_of_modes": 6}
  }]
}
```

支持 1–25 行/列、正高度多级编码；柱宽须小于中心距，所有调谐高度须保持正值并低于空气/PML 界面。未识别字段直接报错，避免静默忽略拼写错误。当前只实现共同柱高偏移扫描，不接受任意 Java/Python 表达式。绝对模型路径和复杂 CAD 不属于这一模板的输入。

默认：柱宽 100 nm，中心距 150 nm，基底厚 500 nm、n=1.45，上方空气 750 nm，方柱 n=2.4，上下 PML 各 400 nm；无材料手性和吸收。沿 x/y 的 Floquet 波矢为零。PML 典型波长固定为搜索频率对应的介质波长，不依赖未知本征频率。外侧默认 PEC 位于 PML 后方，不代表裸露的金属盖板。

## Python

在仓库根目录或安装了该包的环境下：

```python
from comsol_batch import validate_manifest, build_case, run_batch, start_batch
from comsol_batch import get_batch_status, cancel_batch, collect_results

# 阻塞运行，逐案例排队；每个案例在独立 COMSOL/JVM 子进程中运行。
result = run_batch("manifest.json", "runs/test01")

# 训练/优化程序更适合使用非阻塞入口。
job = start_batch("manifest.json", "runs/test02")
state = get_batch_status(job["run_dir"])
# cancel_batch(job["run_dir"])
# data = collect_results(job["run_dir"])
```

`build_case(case_spec, output_dir)` 只构建与保存模型，不求解。第一次导入库和校验输入均不会启动 COMSOL。

## CLI

```powershell
python -m comsol_batch validate manifest.json
python -m comsol_batch run manifest.json --output runs/test01
python -m comsol_batch start manifest.json --output runs/test02
python -m comsol_batch status runs/test02
python -m comsol_batch cancel runs/test02
python -m comsol_batch collect runs/test02
```

取消先写入请求，父进程终止自己拥有的工作进程并等待其退出后，才报告 `cancelled`。超时按每个调谐点计算；建模阶段也有超时限制。每批次只同时运行一个工作进程，默认 4 核、最大 6 核。不同输出目录的批次不会自动互斥，请勿在内存不足时同时提交多个批次。

同一输出目录再次执行相同 manifest 会复用已完成调谐点，校验输入哈希、有限频率数据和已保存场解。未完成点重算；不同 manifest 拒绝覆盖。中断发生在写入完成标记之前的结果不算完成。

若父进程被操作系统强制终止，可能留下 `runner.lock`；接口不会自动删除它或声称运行已完成。确认进程已退出后再人工清理锁。正常退出、取消与超时会自动释放锁。

## 输出

```
run_dir/
  manifest.json        # 完整展开的输入快照
  status.json          # 批次终态与完成计数
  results.json         # 已完成点及所有候选模式
  modes.csv            # 适合后续数据集处理的扁平表
  case_id/
    spec.json
    state.json
    worker.log
    model.mph          # 可编辑的本征频率模板
    point_000/
      input.mph
      solution.mph     # 完整复数场解，可供之后采样和模式追踪
      progress.log
      result.json
```

每个模式保留 COMSOL 解索引、复频率的实虚部、`Q_abs=abs(Re f)/(2 abs(Im f))`、柱区 |E|² 积分占比。复频率不丢弃虚部，也不把负虚部自动修正。对无耗散模式 Q 不写 JSON Infinity，而写 null。柱区场占比不是严格的电磁能量参与率。

这些是 **候选本征模**，可能包括 PML 模式及辐射域模式。`classification=unclassified`、`tracked_mode_id=null`、`gap=null` 是有意设计。小阵列粗网格测试仅验证接口，不证明存在目标 TE/TM 模式、手性或反交叉。后续需增加：物理模筛选、共同采样点上的复模场重叠、模式身份追踪、PML/网格收敛，再提取目标 gap。

## MCP

`src/tools/batch.py` 是薄适配层，提供 `batch_validate`、`batch_start`、`batch_status`、`batch_cancel`、`batch_collect`。已在本仓库副本的 `src/server.py` 注册，并将包纳入 wheel。

部署或更新此版本后需要重启 MCP 服务，客户端才能加载这些工具；运行中的服务不会热加载源码修改。独立 Python/CLI 接口不依赖 MCP 服务启动。

COMSOL 运行环境需安装 MPh、JPype、NumPy，并具备 COMSOL 6.4/RF 许可。Windows 下父子进程使用底层 Python 可执行文件启动，避免虚拟环境转发进程造成取消后遗留 JVM。

官方 PML 说明：https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_definitions.21.137.html
