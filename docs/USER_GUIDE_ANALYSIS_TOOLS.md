# 分析工具与 AI 助手使用手册（2026-10-15 更新）

本手册覆盖本次新增的 20 个分析工具、AI 助手路由规则、以及新加的上下文兜底机制。

## 一、入口与启动

1. 启动：双击项目根目录 `start.bat`（或手动 `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`）。
2. 浏览器打开 `http://127.0.0.1:8000`。
3. **改过后端代码必须重启服务**（启动命令未开 `--reload`），否则改动不生效  本次就出现过一次
   「graph 兜底已写好但服务未重启，看起来没效果」的情况。

## 二、新增「分析工具」面板

入口：顶部菜单栏 **工具  分析工具**（在"空间统计"下面一项）。

面板内 20 个工具分 4 组：

### 栅格分析（5 个，全部可用）
| 工具 | 用途 | 输入要求 |
|---|---|---|
| 栅格重分类 | 按映射表/等间隔/分位数重编码 | 上传的 GeoTIFF |
| 邻域统计 | 移动窗口 mean/median/min/max/std/range/majority | GeoTIFF，窗口 3/5/7 |
| 欧氏距离面 | 到最近源像元的距离 | GeoTIFF |
| 掩膜提取 | 按面图层裁剪栅格（可反选外部） | GeoTIFF + 面图层 |
| 填挖方 | 两期 DEM 方量对比 | **两个同网格 DEM**（网格不一致会明确报错，不静默算错） |

### 矢量与属性（5 个，全部可用）
| 工具 | 用途 | 注意 |
|---|---|---|
| 属性连接 join_field | **按键字段**连接两图层属性 | 与空间连接 `spatial_join` 的区别见下表 |
| 几何属性 | 面积/长度/周长/质心/包围盒入属性表 | 经纬度图层自动投影到 UTM 计算，返回值注明所用 CRS |
| 最小外接 | envelope / convex_hull / circle / oriented_bbox | 半径/边长单位为米 |
| 点串线 | 按分组字段把点连成线（可闭合） | 长度为米 |
| 沿线布点 | 按固定间距沿线生成点 | 间距单位 m/km，在线的投影坐标系上计算 |

### 空间统计（5 个，全部可用）
| 工具 | 用途 | 产出 |
|---|---|---|
| 空间权重矩阵 | queen / rook / knn | **文件产物** npz+json（不在地图上显示，路径在返回文本里） |
| 空间回归 | OLS + 残差 Moran's I | 数值文本（GWR 暂不支持，会明确提示） |
| 标准差椭圆 | 每组椭圆参数 + 椭圆图层 | 图层 + 数值 |
| 中心趋势 | 平均/中位中心、中心要素、标准距离、最近邻指数 | 数值文本 |
| OD 成本矩阵 | 路网多起点-多终点代价 | **文件产物** csv+json，单位米 |

### 转换与代价距离（5 个，**暂未实现**）
`feature_to_raster`、`raster_to_feature`、`create_fishnet`、`cost_distance`、`least_cost_path`
 面板里有入口，点击会报"工具不存在"，属预期。后续补齐。

## 三、AI 助手怎么选工具（路由规则）

对着 AI 说自然语言即可，助手按下面的规则选工具（这些规则已写入系统提示词）：

| 你说 | 助手应该用 | 不要误用 |
|---|---|---|
| "把 A 表按 id 连到 B 图层" | `join_field`（属性键） | `spatial_join` 是按空间关系 |
| "两个图层求交/叠加" | `spatial_join` / 叠加工具 | `join_field` 不看空间 |
| "把这个栅格分成 3 类" | `raster_reclassify` | `raster_calculator` 留给多波段任意表达式 |
| "北京-广州连线经过哪些省" | `datav_boundary` 拿省界 + `execute_python` 求交 |  |
| "两点间沿路网的时间/距离" | `network_analysis` / `od_cost_matrix` | `cost_distance` 是栅格代价面，不是路网 |
| "两个 DEM 算挖填方" | `surface_volumes` | 需同网格，不一致会报错 |

## 四、上下文兜底（本次新增，防"说到执行就没反应"）

### 现象
AI 说完"现在开始执行工具调用"后长时间无后续，多轮后任务看似卡死。

### 根因
Agent 多轮循环把工具输出整段回填上下文，输入 token 指数膨胀
（台账实测有 330 万 token 的案例），直到 420 秒时间预算才强制收尾 
期间一直在烧 token。叠加因素：单次数据源偶发失败（如 DataV 403）触发重试，
重试  大上下文 = 又慢又贵。

### 本次加的三道闸（在 `backend/services/graph.py`，均已生效）
| 闸 | 默认 | 环境变量 | 作用 |
|---|---|---|---|
| 工具输出截断 | 4000 字符 | `GIS_TOOL_OUT_MAX` | 单条超大结果（省界/搜索）只保留头尾 |
| 上下文压缩 | 15 万字符 | `GIS_CTX_MAX` / `GIS_CTX_KEEP_TOOLS` | 更早的工具结果压成一行摘要，保留最近 4 条原文 |
| 累计 token 预算 | 26 万 | `GIS_TOKEN_BUDGET` | 超预算立即"停止调工具、文字总结"收尾（早于 420s 时长闸） |

时间闸保持不变：`GIS_GRAPH_TIMEOUT`（默认 420 秒）。

### DataV 数据源兜底
`datav_service.py` 全部请求统一带浏览器 User-Agent（无 UA 请求该 CDN 会偶发 403）。

### 遇到"卡住"时怎么排查
1. 看 `logs/token_usage.jsonl` 最后一条 `in=` 是否异常大（>30 万） 大即上下文膨胀。
2. 看 `cache/tasks/<task_id>/task.json` 的 `current_step` 是否持续上涨  涨=还在循环。
3. 确认服务启动时间晚于最近一次代码修改（否则改动未生效）。
4. 若某数据源（如 DataV）持续失败，换数据源或稍后重试；Agent 会在预算内收尾并汇报。

## 五、其他本次修复

- `POST /api/tools/invoke` 曾被注册两次，FastAPI 只命中先注册者，导致所有手动面板
  的"结果图层回地图 + 处理历史"失效；已去重，并新增 `test_route_uniqueness.py` 防复发。
- 旧「栅格与地理工具」面板的"坐标转地址"不再误要求选图层（老 bug）。
- emoji 清理：前端字符符号改为内联 SVG（继承文字色，深浅主题均适配）。
- Schema 体积守卫从绝对上限 60000 改为随规模的预算（54000 + 620/工具）。

## 六、验证

```powershell
D:\python\python.exe -m pytest backend/tests/test_raster_gap_tools.py backend/tests/test_vector_gap_tools.py backend/tests/test_stats_gap_tools.py backend/tests/test_tool_registry.py backend/tests/test_route_uniqueness.py backend/tests/test_analysis_panel_wiring.py backend/tests/test_frontend_no_emoji.py -q --disable-warnings
```

完整改动清单见 `docs/CHANGE_THIS_SESSION.md`。
