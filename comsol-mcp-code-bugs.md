# comsol-mcp 代码层缺陷清单（实测审计版）

> 审计对象：`C:/Users/mioer/Documents/Codex/comsol-mcp`
> 审计方式：源码阅读 + 本机 COMSOL 6.4 会话实测
> 日期：2026-10-07
> 证据强度：✅ = 源码+报错双证据；⚠️ = 报错反推（源码未逐行核对）；💡 = 设计缺陷

---

## 0. 结论速览

| 编号 | 类型 | 严重度 | 一句话 |
|---|---|---|---|
| B1 | 功能性 bug | P0 | property_info() 无条件调 .properties()，node_* 对 physics/studies 全崩 |
| B2 | 功能性 bug | P1 | study_create 的 step_properties 不校验属性名，文档还教错（freq 不存在） |
| B3 | 功能性 bug | P0 | study_create 用「属性是否失败」决定「创建是否成功」，误报 false 诱发重复创建 |
| B4 | 一致性问题 | P1 | 同一操作两条路径行为矛盾 |
| B5 | 接口问题 | P1 | 错误返回结构两套形状，无法统一提取 error_id |
| B6 | 健壮性 | P2 | results_evaluate 缺结果尺寸上限 |
| D1 | 设计缺陷 | P2 | resolve() 中 plotgroups 特判脆弱 |
| D2 | 设计缺陷 | P2 | set_properties rollback 不完整 |
| D3 | 设计缺陷 | P2 | physics_get_available 混淆「类型存在」与「本机已授权」 |
| E1 | 环境问题（非代码） | — | 本机未授权 ht / emw / ewfd / ec |

---

## 1. B1　property_info() 假设所有节点都有 .properties()

**位置**：`src/tools/nodes.py`

```python
def property_info(node, key):
    names = [str(p) for p in node.properties()]        # 第 75 行，无条件调用
    if key not in names:
        raise KeyError(Unknown property + key + ; use node_list_properties)
    ...
```

同文件路径解析器允许 physics / studies 作为路径段：

```python
COLLECTIONS = {
    components:component, geometry:geom, features:feature,
    materials:material, property_groups:propertyGroup, physics:physics,
    selections:selection, mesh:mesh, studies:study, solvers:sol,
    ...
}
```

解析 `components/comp1/physics/c` 得到 `PhysicsClient`，它没有 `.properties()`。

**实测 1**

```
node_set_property(path="components/comp1/physics/c", ...)
→ AttributeError: com.comsol.clientapi.physics.impl.PhysicsClient
                 object has no attribute properties
```

调用栈：

```
File ".../src/tools/nodes.py", line 158, in node_set_property
    return set_properties(path,{key:value},model_name)
File ".../src/tools/nodes.py", line 96, in set_properties
    before={k:property_info(node,k) for k in properties}
File ".../src/tools/nodes.py", line 75, in property_info
    names=[str(p) for p in node.properties()]
```

**实测 2**

```
node_list_properties(path="studies/freq1")
→ AttributeError: com.comsol.clientapi.impl.StudyClient
                 object has no attribute properties
```

调用栈：

```
File ".../src/tools/nodes.py", line 138, in node_list_properties
    return {success:True,properties:[{key:str(k),
            type:str(node.getValueType(str(k)))} for k in node.properties()]}
```

**影响面**：node_get_property / node_set_property / node_set_properties / node_list_properties 对全部物理场接口节点与全部研究节点不可用。

**修复建议**

```python
def property_info(node, key):
    if not hasattr(node, properties):
        raise TypeError(
            f{type(node).__name__} 不支持通用属性访问；
            f物理场请用 physics_set_property，研究请用 study_set_property
        )
    ...
```

或从 COLLECTIONS 中移除 physics / studies，强制这些路径只走专用工具。

---

