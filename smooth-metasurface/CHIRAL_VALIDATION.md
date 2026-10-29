# v0.3 Mode-CY手性本构接入验证

后续编码论文图案已完成初步反交叉测试，见 [ENCODED_GAP_TEST.md](ENCODED_GAP_TEST.md)；下文保留方程接入阶段的验证记录。

日期：2026-10-29。几何仍为精确像素区域合并；新增的是物理方程、材料配置和求解器参考点。没有重新启用旧的高斯平滑。

## 已完成的实际求解

命令：

```powershell
.\.venv\Scripts\python.exe validate_chiral_backend.py --output runs/chiral-v3-validation-v3
```

对同一220×220原生编码（34,090个材料像素，最终16条轮廓边）计算非零κ与κ=0；两例均启用手性后端，保持相同介质折射率、损耗、几何和网格设置。COMSOL 6.4、4核。

- 两例成功求解，网格均7,713个体单元。
- 每例请求6个模，COMSOL实际返回12个，全部保留，没有选任意相邻频率作为gap。
- 非零κ求解约12.68秒；零κ约10.62秒；含启动、建模和保存的验证脚本共约52.56秒。单次计时不作为严格性能对照。
- 构建和求解后均确认9个当前Equation View表达式及锁定值完全正确。
- 此例手性作用域为域4，薄膜域3，PML域1/5；集合不相交。代码使用命名选择，未硬编码这些编号。
- 薄膜体积通过输入几何面积×厚度核对。

以薄膜上方及孔内手性介质为积分域，计算电磁交叉项的相对平方范数：

```text
Rcross = ∫|D - epsilon0*epsilon_r*E|² / ∫|D|²
```

| 检查 | 非零κ | κ=0 |
|---|---:|---:|
| 所有返回模式中最大的Rcross | 1.0335e-8 | 8.6609e-33 |
| D、B及H时间导数本构恒等式的最大相对平方残差 | 2.9812e-32 | 3.1301e-32 |

该结果验证交叉项会随κ开关，且以下关系实际用于求解后的场：

```text
D = epsilon0*epsilon_r*E - i*kappa*H/c0
B = mu0*mu_r*H + i*kappa*E/c0
dH/dt = i*omega*H
```

上述10^-32是代数本构恒等式在浮点运算中的残差，**不代表本征频率、场或gap具备该精度**。这组测试不是指定TE/TM模对的反交叉扫描，gap仍返回空值。

## 接入方式

- `smoothmeta/mode_cy_equations.json`：从Mode-CY的Equation View提取的9个原始表达式，作为包数据随项目携带。
- `smoothmeta/pasteur.py`：仅将ewfd命名空间替换为本项目的emw；按显式occurrence=0写入9个分量并回读。若当前COMSOL的定义布局不匹配，立即报错。
- `smoothmeta/comsol.py`：建立独立的chiralwave波动方程特征，只选择薄膜上方及孔内物理介质。薄膜、基底及PML保留普通关系，禁止手性域混入薄膜/PML。
- 材料使用Mode-CY参数：εr=1.45²-1e-4i，μr=1-1e-5i，κ=1.2e-4-3e-5i。JSON中均可调。
- H通过B=-curl(E)/(iω)含有1/ω，必须把本征线性化参考频率设为非零f_search。实际回读为eigref=f_search、transeigref=on。没有改大κ，也没有删掉含1/ω的表达式绕开组装问题。
- 同介质零手性对照保留enabled=true，κ实部和虚部都置零。enabled=false则是历史空气/普通介质后端。

域差集使用COMSOL官方Difference选择的add/subtract属性，API依据见[COMSOL 6.4 model.selection文档](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_general.47.56.html)。

## 论文图案入口也已切换

`paper_gap.py`现统一调用上述后端；历史20260526/wc1代码保留为`paper_gap_legacy_20260526.py`。新入口不会再复制旧弱贡献。

已实际运行：

```powershell
.\.venv\Scripts\python.exe paper_gap.py --resolution 110 --prepare-only --output runs/chiral-v3-paper-prepared
.\.venv\Scripts\python.exe paper_gap.py --resolution 110 --build-only --output runs/chiral-v3-paper-build
```

110×110论文图案精确合并后有184条轮廓边；构建成功并保存含9项改写及非零本征参考点的MPH。**这里只完成构建，没有对这个编码后的论文图案重新做gap厚度扫描**。Mode-CY原始解析图案此前出现20.27 GHz分裂的结果，不能直接当成本项目编码图案的gap。

## 验证与文件

`python -m pytest tests -q`：36项通过，包括原有几何精确性、论文图案及新增的9方程来源比对、命名空间映射、参数合法性、零κ保持同介质和旧配置兼容性。

- `runs/chiral-v3-validation-v3/validation.json`：最终验证统计。
- 同目录 `nominal/point_000/solution.mph`：220×220结构化编码、非零κ的完整解。
- 同目录 `zero/point_000/solution.mph`：同一编码、同介质κ=0的完整解。
- 两例的`equation_audit.json`：9方程、域选择及本征参考点回读。
- `runs/chiral-v3-paper-build/nominal/model.mph`：110×110论文图案的已构建模型，尚未求解。
- `examples/demo.json`及`examples/paper_chiral_110.json`：显式启用手性的示例。

前期API适配失败记录保留在`chiral-v3-build`、`chiral-v3-validation`及`chiral-v3-validation-v2`，状态为failed，不作为成功结果。最后一例揭示默认零本征参考频率的除零问题，已按上述方式修正。
