# 精确像素区域编译器与手性物理后端 v0.3

将二维二值矩阵转换为 COMSOL 的连续平面区域，再整体拉伸为薄层。文件夹及 Python 包名沿用 smooth-metasurface / smoothmeta，算法已重写。

v0.3 已接入 Mode-CY.mph 的9项本构方程改写，并通过实际COMSOL非零κ/零κ对照。几何继续使用v0.2精确区域合并，未重新引入高斯平滑。验证见 [CHIRAL_VALIDATION.md](CHIRAL_VALIDATION.md)。

后续110×110编码论文图案已测到约20.18 GHz的反交叉分裂，同厚度κ=0残余频差约0.141 GHz，并观察到偏振混合。详细数据、模型和未收敛限制见 [ENCODED_GAP_TEST.md](ENCODED_GAP_TEST.md)。这是含外加材料κ的结果，不证明高度编码本身产生手性。

## 现在做什么

1. 每行提取连续材料区间。
2. 将相邻行中端点相同的区间纵向合并为矩形分块。
3. 在整数像素坐标下取并集，消除材料内部公共边，得到外轮廓与孔洞。
4. 只删除共线顶点，保留所有真实锐角、台阶、单像素凸起及孔洞；最后统一换算为 nm。
5. COMSOL 用 Polygon / Difference 表示区域，一次 Extrude 生成薄层；不为每个像素建立一个三维方块。

不做高斯滤波、上采样、圆角或容差简化。矩形分块不声称是全局最少矩形覆盖。默认算法不改变几何，因此也不改变目标设计的物理形状。像素化圆的台阶属于真实输入边界，默认全部保留。

## 运行

在本目录执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_demo.py --output runs/my-benchmark
.\.venv\Scripts\python.exe -m smoothmeta prepare examples/demo.json --output runs/my-geometry
.\.venv\Scripts\python.exe -m smoothmeta solve examples/demo.json --output runs/my-solve
.\.venv\Scripts\python.exe validate_chiral_backend.py --output runs/my-chiral-check
```

每次使用新的输出目录。COMSOL 6.4 及 RF 许可证用于建模/求解；仅转换几何不启动 COMSOL。依赖见 pyproject.toml；现有 .venv 已可运行。

## 输入与优化接口

```json
{
  "encoding_file": "structured_220.npy",
  "geometry": {"period_nm": 550},
  "solver": {"thicknesses_nm": [165.9], "mesh_level": 4, "cores": 4, "num_modes": 6},
  "chiral": {
    "enabled": true,
    "medium_index": 1.45,
    "epsilon_imag": -0.0001,
    "mu_real": 1,
    "mu_imag": -0.00001,
    "kappa_real": 0.00012,
    "kappa_imag": -0.00003
  }
}
```

encoding_file 相对配置文件解析，支持 .npy（二值矩阵、禁止 pickle）及 JSON 数组；也可直接使用 encoding 二维数组，二者必须选一。矩阵行沿 +y、列沿 +x，整个矩阵映射为边长 period_nm 的正方形；支持矩形像素阵列。旧版 sigma_nm / upsample / tolerance_nm 配置会明确报错，不能静默改变含义。

```python
from smoothmeta import prepare_geometry, export_geometry, load_spec
from smoothmeta.comsol import evaluate_design
r = prepare_geometry(matrix, period_nm=550)
export_geometry(r, 'runs/candidate_geometry')
# 重复调用时可传同一个已启动的 mph.Client，避免重复启动开销。
report = evaluate_design(load_spec('candidate.json'), 'runs/candidate_solve', client=client)
```

输出 geometry.json（轮廓、孔洞、压缩统计、指纹）、工程单位 nm 的 geometry.geojson、encoding.npy。求解另存模型、各厚度结果、进度日志及状态。当前无自动恢复或硬超时。

`chiral.enabled=true` 时，薄膜上方及孔内物理介质使用 εr=medium_index²+i·epsilon_imag、μr=mu_real+i·mu_imag、κ=kappa_real+i·kappa_imag。薄膜、基底和上下PML不启用手性方程；上PML采用折射率medium_index的普通介质。参数默认值对应Mode-CY保存的介质设置。

方程逐字来自Mode-CY，仅把命名空间ewfd改为emw：Dx/Dy/Dz、Hx/Hy/Hz及dHdtx/dHdty/dHdtz。构建和求解后都会验证9项锁定表达式与当前Equation View一致；选择域必须排除薄膜和PML。求解时额外验证D、B和H时间导数的本构恒等式。输出`equation_audit.json`和每点`chiral_diagnostics`供检查。

零手性对照请保留enabled=true，只将kappa_real和kappa_imag设为0，以保留相同介质及损耗。省略chiral或enabled=false则沿用旧版空气/普通介质后端，便于历史配置复跑；它与“同介质κ=0”不是同一个对照。随项目提供的demo.json与paper_chiral_110.json已显式启用手性。

H通过B=-curl(E)/(iω)含有1/ω。启用手性时自动生成求解器并把非零本征参考频率设为f_search，避免默认零参考频率下的矩阵组装除零。随后直接运行已配置的sol1。该设置参考Mode-CY，不通过削减本构项绕过除零。

## 验证与适用范围

run_demo.py 的三个 220×220 输入直接在原生网格上生成，不是 9×9 放大。每例与独立的“每个材料像素一个矩形再取并集”实现比较。内部还检查共线合并前后对称差面积、面积和连通分量/孔洞数。基准时间是 Python 几何阶段的单次实测，不代表端到端 FEM 加速倍数。

结构化大区域可大幅减少 CAD 数据；随机噪声、棋盘格保留大量边界，精确压缩无法消除真实复杂度。二维点接触不等于有限宽桥梁：转换器可导出并标注，当前 COMSOL 后端拒绝零宽对角接触以及相对边材料迹线不匹配的输入。后者属于当前后端限制，不能据此认定该周期图案物理上无效。

物理后端为 n=2.4 薄层、n=1.45 基底、可选手性介质、上下 PML、正入射 Floquet 边界及二阶电场单元。默认请求335 THz附近6个本征模，保留COMSOL实际返回的全部模式；输出频率、Q、场积分及本构诊断，并验证体积。尚未在通用后端实现指定TE/TM模对跟踪，gap返回空值，不能把任意相邻频率差作为耦合gap。

runs 下旧 sigma 系列为 v0.1 历史实验，保留供追溯，不作为 v0.2 的结果。新验证见 VALIDATION.md。

## 论文图案 gap 验证

当前`paper_gap.py`统一使用上述新后端，不再载入20260526.mph的wc1。它将论文图案按指定分辨率编码、合并并扫描厚度；`--zero-control`可同时运行同介质κ=0，`--prepare-only`只生成几何，`--build-only`只构建模型。新示例为examples/paper_chiral_110.json。其周期、材料与κ取自Mode-CY参考，但网格及空气/PML高度采用本项目配置，不声称与作者原几何模型数值完全相同。

```powershell
.\.venv\Scripts\python.exe paper_gap.py --resolution 110 --thicknesses 165.9 --zero-control --output runs/my-paper-chiral
```

历史20260526/wc1实验和大型MPH文件仅保留本地；本仓库提供当前后端、输入和轻量验证结果。新编码图案的独立扫描见 [ENCODED_GAP_TEST.md](ENCODED_GAP_TEST.md)。

已发布结果在 [results/encoded-gap-v3](results/encoded-gap-v3)，可直接重画：

```powershell
python analyze_encoded_gap.py results/encoded-gap-v3
```

新环境请先在本目录安装 `python -m pip install -e ".[comsol,test]"`。COMSOL计算需要本机安装和许可证；读取结果与重画不需要COMSOL。
