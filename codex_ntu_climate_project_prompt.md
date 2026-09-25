你是这个项目的 Python 开发工程师、GIS 分析师和数据质量负责人。请直接在本地工作目录中实现下面的课程项目原型，实际获取数据、编写代码、运行分析、测试并修复问题，不要只给我方案或伪代码。

项目题目：
Digital climate-risk assessment for a university campus: GIS mapping, climate data, risk dashboard and scenario analysis

研究对象：新加坡 Nanyang Technological University（NTU）校园。
工程名称：ntu-climate-risk

## 1. 目标与边界

实现一个本地运行、可复现的校园气候风险筛查工具，覆盖四个部分：
- GIS mapping：真实的校园建筑、步道、研究范围和气象站地图。
- Climate data：公开天气观测的数据处理、统计与气候情景来源记录。
- Risk dashboard：天气条件、空间暴露代理指标和数据质量的交互展示。
- Scenario analysis：比较样本期天气、更热/更强降雨的假设条件，以及改善遮棚覆盖的假设方案。

优先级：真实数据二维 MVP > 数据质量与测试 > 情景比较 > 简化三维。
主线采用校园步行热暴露筛查，降雨事件分析作为辅助。第一版不做精细洪水模拟、CFD、完整数字孪生、模型训练或健康损失预测。

这是课程用工程原型与技术记录，不要代写可直接提交的课程最终报告、PPT或演讲稿。先读取目录内已有课程要求；若有更严格的生成式 AI 使用限制，遵守并记录。保留 AI 辅助开发记录，不声称代码或结果由人工独立完成。

先检查当前目录、README、AGENTS.md、已有代码、操作系统和 Python 环境。已有项目则增量修改；否则创建 ntu-climate-risk/。不要覆盖无关文件、删除用户数据、重置仓库或改系统配置。

## 2. 技术选择与执行方式

优先采用：
- Python，优先使用本机兼容版本及项目独立虚拟环境。
- Streamlit：本地界面。
- pandas、GeoPandas、Shapely、pyproj：数据与 GIS 处理。
- requests 或 httpx：HTTP 请求。
- Folium + streamlit-folium：二维地图。
- Plotly 或 Matplotlib：图表。
- pytest：测试。
- pydeck：仅在核心功能完成后用于可选三维。

不要同时搭建多套前后端。不要把 Docker、数据库服务器、GPU、付费地图、云部署或商业 API 作为必需依赖。QGIS 不必安装，但导出的 GeoPackage 应可供 QGIS 打开。

不得使用 sudo、全局升级包或修改系统 Python。优先使用 uv；没有 uv 时使用 venv + pip。检查当前官方文档与实际安装版本，不凭记忆调用可能已变更的 API。完成后记录并锁定验证过的依赖版本。

界面和图表标题使用英文，README 与技术说明可使用中文。重要术语同时给出英文。

先列出简短实施计划，然后立即实施。阶段完成后继续下一阶段，不需要就普通技术选择反复询问我。涉及权限、付费或破坏性操作时不自行越权；记录阻塞并继续可完成的部分。

## 3. 数据获取与来源核验

### 3.1 空间数据

首选 OpenStreetMap 数据。可以使用 Overpass 的小范围查询；失败时尝试 Geofabrik 区域下载或读取本地文件。

候选入口：
https://overpass-api.de/api/interpreter
https://download.geofabrik.de/asia/malaysia-singapore-brunei.html
https://www.ntu.edu.sg/life-at-ntu/visiting-ntu

初始检索框仅用于查找数据，不是官方校园边界：
west=103.670, south=1.335, east=103.695, north=1.365

优先查找并核验 OSM 中 NTU 的校园多边形。不能可靠取得时，使用上述可配置研究框，并在页面写明“Approximate study extent — not an official campus boundary”。保留范围内建筑与校园建筑的区别，不把周边建筑全算作 NTU 资产。

最少获取：
- 建筑轮廓。
- 步行相关道路/步道，保留 highway、foot、access、covered、tunnel、bridge、layer 等可用原始标签。
- 气象站位置。
- 可用的名称/兴趣点。
绿地、水体、树木等仅在实际取得时作为补充图层。

尽量保留 OSM 元素类型、ID、名称和原始标签。若 Geofabrik 的简化格式丢失 covered 等标签，标为未知，不要推测。必要时读取 PBF 或补做小范围查询。

步行网络应排除明确禁止步行的道路；高架、隧道、室内通道不得仅因二维交叉就认定连通。第一版不必做导航。

保存原始响应、整理后的 GeoPackage 和供网页使用的 GeoJSON。用合适的米制投影计算长度/面积；先核验 CRS，不能在经纬度坐标下直接计算米。网页输出统一为 WGS84 经纬度。

不要抓取 Google Maps/Earth 的三维瓦片，也不要假定 NTU 官方互动地图或 Virtual Singapore 提供开放 BIM 下载。底图保留 attribution，遵守瓦片使用条款，不批量下载公共底图瓦片。

### 3.2 天气观测

优先使用 NEA/data.gov.sg 官方接口：
https://data.gov.sg/collections/1459/view
https://guide.data.gov.sg/developer-guide/real-time-apis
https://api-open.data.gov.sg/v2/real-time/api/air-temperature
https://api-open.data.gov.sg/v2/real-time/api/rainfall
https://api-open.data.gov.sg/v2/real-time/api/relative-humidity
https://api-open.data.gov.sg/v2/real-time/api/wind-speed

优先核验的站点：
station_id = S44
station_name = Nanyang Avenue
候选坐标：latitude=1.3458, longitude=103.6817

以上是检索线索，不是可以跳过验证的常量。实际读取各接口 station metadata，检查 S44 是否有相应变量、观测时间与位置；不要假定各变量的站点集合相同。

先测试最新数据和一个已结束的历史日，确认响应结构、date 参数、分页字段与单位；有 paginationToken 时必须读完所有页，再统计覆盖率。

时间范围：
- 默认先跑通最近 7 个完整本地日，再扩展到最近 30 个完整本地日。
- 以执行当天 Asia/Singapore 时间确定日期，不请求未来数据，不把当天未结束的资料算完整日。
- 支持 --start / --end 或配置文件，方便后续分析固定学期/年份。
- 把这段数据称为“observational sample period”，不得称为多年气候常态，也不得据此宣称长期变暖趋势或暴雨重现期。

历史资料补充入口：
https://www.weather.gov.sg/climate-historical-daily/

如果 S44 某变量不可用，先记录缺失，再按真实元数据比较其他站点的距离与覆盖率。任何替代站点都必须显示自己的名称、位置和替代理由；不得改名为 S44 或暗中拼接。

必要时可核验 Open-Meteo 历史再分析作为单独备用来源：
https://open-meteo.com/en/docs/historical-weather-api

只有确认当前接口、许可和所需变量可用后才接入。再分析是独立数据模式，必须显示模型、网格尺度与坐标，不能冒充校园实测。不要把日数据展开成伪小时观测。

HTTP 下载必须设置超时、有限次数重试、指数退避、限速和本地缓存；尊重 Retry-After。支持从环境变量读取可选 API key，不把密钥写进代码、日志或版本库。下载失败不能返回“成功”的空文件。

### 3.3 气候情景来源

核验并记录官方入口：
https://ccrs.weather.gov.sg/climate-projections/

查找其链接的 V3 官方说明，记录可访问的资料、变量、基准期和未来时段。只记录真正读到的来源，不编造论文、投影数值或下载权限。

第一版的 +1°C、+2°C、降雨 +10%、+20% 都属于自设 sensitivity scenarios，不得写成 V3 对某年份的预测。

只有实际取得可追溯的 V3 数值，且核对变量、空间尺度、基准期、未来时段和 SSP 后，才能另建“V3-derived”情景；不能把不同基准期的温升直接叠到最近样本上而不说明处理方法。受限门户不可绕过，不得让其阻塞 MVP。

### 3.4 数据质量和溯源

建立机器可读的数据清单，至少包含：
source_url、provider、retrieved_at、query_parameters、license_or_terms_url、local_path、sha256、data_kind、station_id、variable、unit、time_range、row_count、quality_notes。

明确区分：observed、reanalysis、derived、assumed、synthetic。派生结果同时关联原始数据及假设配置。

天气处理要求：
- 保存原始时间戳，规范到带时区时间，并按 Asia/Singapore 聚合。
- 按 source + station + variable + observation_timestamp 去重。重复请求不等于新观测。
- 读取真实单位；风速若为 knots，再显式转换为 m/s 并保留原值。
- 降雨接口若标为 5 分钟累计 mm，则按不重叠区间求和。不能把它直接叫 mm/h，也不能把缺测当零降雨。
- 核验时间戳代表的观测区间，避免整点附近跨日/跨小时聚合错位。
- 温度/湿度/风速与降雨分别处理，不能把所有变量直接 resample().mean()。
- 输出每变量、每站点、每小时/日的有效覆盖率。完整性门槛可配置，默认 80%，说明它只是工程筛选标准。
- 缺失和可疑值保留标记。默认不插值降雨，不跨长缺口补温度，也不把可疑极值直接删除。
- 不完整的累计量必须标“partial”，全缺测汇总应为缺失而非零。

测试用合成数据只能放在 tests/fixtures 或显式 synthetic demo 模式中。不得在真实数据获取失败后静默生成随机天气、随机建筑或随机风险分数。

## 4. 最小分析模型：透明的步行热暴露代理

不要构造声称经过验证的“校园真实风险分数”。第一版采用可检查公式的 screening proxy，分别展示天气危险性、步行空间与遮棚信息不确定性。

### 4.1 天气部分

基础指标包括气温分布、日最大气温、湿度曲线、完整时段累计降雨、样本内最强降雨事件，以及可用的风速。

热条件指标使用：
H = Σ max(T_t - T0, 0) × Δt_hours

T0 默认 30°C，可配置。这是探索性分析阈值，不是医学或官方预警标准。积分只覆盖合格观测区间，不跨长缺口。输出 H、有效时长、覆盖率及 H/有效时长，明确单位和时间范围。

对统一时间网格采用明确的代表值/积分方法，并测试缺口处理，不能把同一观测反复前向填充成完整数据。

只凭温度/湿度不得声称计算了完整 WBGT；第一版不必加入 Heat Index、UTCI 等额外指标。

### 4.2 空间部分

使用固定 100 m 网格汇总步行线长度，网格大小可配置。避免因 OSM 一条路被切成多条而重复计量或改变分析单位。

每格记录已标注 covered=yes、covered=no 和 covered 缺失/不明的长度；解析特殊值并保留不确定性。只依据真实标签，缺失不等于 uncovered。树冠与建筑投影形成的时变阴影不在这个最小模型中。

定义一个明确属于假设模型的有效未覆盖长度：
L_eff_i = L_covered_no_i + q_unknown × L_covered_unknown_i
P_i = H × L_eff_i

q_unknown ∈ [0,1] 表示未知覆盖部分被假设为未覆盖的比例。默认同时给出 q=0、0.5、1 的敏感性结果；0.5 不能作为实测事实。

页面名称可用“Potential unprotected walking heat-exposure proxy”。说明：
- P 是温度超阈值与潜在未覆盖步行长度的乘积，不是中暑概率、人体热负荷、实测人口暴露或经济损失。
- covered 标签只是固定覆盖线索，不代表完整树荫/太阳辐射条件。
- 有遮棚的步道仍可能很热；排除该长度只表示不计入这个“未覆盖部分”的代理量，不代表其热风险为零。
- 没有实际人流、使用时段或弱势群体数据，不能编造这些权重。
- S44 提供共同天气背景，不能由单站画出伪造的逐栋建筑温度差异。

地图至少能显示步行长度、覆盖信息缺失比例、P 的假设值与范围。没有可用天气时保留空间地图，但相应天气/代理指标显示 unavailable，不能用随机值补上。

若覆盖信息非常稀疏，要直说结果主要反映步行长度与假设，并把“补充实地核验”作为技术待办；不能包装成高精度热风险地图。

降雨模块只做事件和阈值敏感性分析；没有可靠地形和排水数据时，不输出道路积水深度、洪水概率或受灾建筑数量。

## 5. 情景分析

实现以下可复现情景：
A. Observed-sample baseline：样本期观测驱动，空间未知参数明确标注。
B. Warming +1°C：仅改变 T，其他条件不变。
C. Warming +2°C：同上。
D. Rainfall +10% / +20%：仅缩放观测到的降雨事件，不填补缺测，不改变事件频率。
E. Shelter intervention：用户选择网格，假设其中潜在未覆盖长度降低 25% 或 50%，并重新计算 P。

E 是规划敏感性试验，不是已设计并验证的工程措施。不得把“P 下降 25%”写成“实际温度下降 25%”或“健康风险下降 25%”。该代理量随覆盖改善下降是公式内建性质，不是因果效果的实验证据。

支持组合情景，例如 +2°C 与选定区域覆盖改善。所有数值和区域 ID 存入配置文件，不修改原始数据。

不同情景使用相同观测时间掩码、空间范围、指标定义及色标。不得为每个情景重新 min-max 归一化制造改善或恶化；处理全零基线、并列值与除零。

展示绝对值、相对变化、数据缺失以及 q_unknown 的敏感性区间。区间是设定范围，不是统计置信区间。

统一增温可能只改变数值而不改变空间排序，要如实展示，不人为制造排名变化。

## 6. Dashboard

至少包含四个页面/标签：

Overview / Campus map
- 研究范围、真实建筑、步道、站点及筛查网格。
- 点击网格查看面积、步行长度、覆盖标签完整性、代理量及来源。
- KPI 显示观测期、有效覆盖率、实际纳入网格/步道数量等真实统计。
- 明确显示 observed / reanalysis / synthetic 数据模式和 hypothetical scenario 状态。

Weather & Quality
- 气温、湿度、降雨及可用风速图表。
- 站点、变量、日期筛选。
- 数据缺口和完整性统计；最新读数显示其实际时间，不能暗示缓存是实时。

Scenario Explorer
- 基线/情景对比地图和图表，使用共同色标。
- 温升、降雨倍率、未知覆盖比例、改造区域及改造比例控件。
- 导出情景配置、汇总 CSV 和空间结果。

Sources & Methods
- 数据来源、许可、获取时间、单位、覆盖情况。
- 模型公式、假设、缺失处理、限制和验证状态。
- 已核验的 V3 来源，以及“官方投影”和“自设敏感性情景”的区别。

页面使用缓存的整理数据，不因每次滑块变化重新下载。首次下载成功后，核心分析应能离线运行；在线底图失效时仍显示本地矢量轮廓，图表不依赖外部 CDN。

界面简洁，图例和单位清晰，未知值有独立样式，不要塞满装饰组件。

## 7. 三维：仅在核心功能完成后尝试

用真实建筑轮廓做轻量拉伸展示。高度优先采用可核验的 height 标签，其次使用楼层数乘明确标注的假设层高。两者均缺失时可保留二维或使用标为 assumed 的统一展示高度，不能随机生成高度。

每栋楼保留 height_source、height_is_assumed。三维仅供浏览，不宣称是官方 BIM，不据此计算精细风场、太阳阴影或积水。

可以调查 GlobalBuildingAtlas，但先查覆盖、许可和下载量；不要为了三维下载全球大文件。三维失败不得影响二维 MVP。

## 8. 工程交付与测试

合理组织目录，至少包含：
app.py
src/ntu_climate/
scripts/
configs/
data/raw/
data/processed/
data/metadata/
outputs/figures/
outputs/tables/
outputs/maps/
tests/
README.md
DATA_SOURCES.md
METHODS.md
VALIDATION.md
AI_ASSISTANCE_LOG.md
PROGRESS.md
.env.example
.gitignore
依赖声明及验证过的锁定版本

不强制创建无用空目录。大型原始数据和密钥不入版本库。

提供可直接运行的获取数据、处理、分析、启动和测试命令；例如最终实现与下列入口等价的命令：
python scripts/fetch_data.py --days 7
python scripts/build_dataset.py
python scripts/run_analysis.py --config configs/default.yaml
streamlit run app.py
pytest -q

这些命令必须确实存在并验证，不要在 README 写未实现命令。提供 --offline 或等效选项，使用已缓存的真实资料复现结果。

必须覆盖的测试：
- 最新/历史 API 响应解析、分页读取、重复观测去重。
- 时区、跨日边界、缺失与有效覆盖率。
- 降雨累计与温度均值不同处理，全缺测不变成零降雨。
- 单位转换、有效几何、米制长度、GeoJSON 坐标顺序。
- 不把 covered 缺失当成 covered=no。
- 固定其他条件时，+2°C 的 H 不小于 +1°C，也不小于基线。
- 所选区域 L_eff 降低时 P 不增加，未选区域不受改造影响。
- 所有情景共用时间掩码和色标；零基线不会除零。
- 原始数据未被情景计算改写；synthetic 数据不进入真实数据结果。
- 下载失败、缺少变量或底图离线时页面仍能给出明确状态。

单元测试可使用明确标记的 fixture；另外必须独立执行真实数据端到端检查。测试通过不等于科学模型验证通过，VALIDATION.md 要区分两者。

启动页面做 smoke test。浏览器工具可用时实际打开，检查图层、图表、交互和错误，并保存截图；不可用时明确记录未完成视觉验收，不能伪称看过页面。

导出至少：校园图、天气时间序列、数据完整性、基线与增温对比、假设覆盖改善对比，以及对应 CSV。图上标明来源、样本期、单位和假设；数据不支持的图不造数，记录缺项。

## 9. 实施顺序与完成条件

按以下顺序实际执行：
1. 检查环境与现有项目，写简短计划。
2. 用小请求核验 OSM 和天气接口，保存真实原始样本与来源清单。
3. 跑通 7 天数据、二维地图和一个基线分析。
4. 扩展到 30 天可用观测，加入情景、质量页面和导出。
5. 运行测试及页面检查，修复问题。
6. 核心功能稳定后再做三维；更新技术记录。

PROGRESS.md 持续记录已完成事项、实际命令、产物路径、失败原因和下一步，便于中断后恢复。记录项目的范围定义、采集、建模、实现、验证与维护事项，但不代写正式课程报告。

联网或权限受限时，有限次数尝试后记录具体错误；继续完成离线代码与测试，并明确哪些模块尚未接入真实数据。绝不能通过自动切换合成数据来宣称真实数据 MVP 已完成。

最终回复我：
- 已实现功能及未完成部分。
- 实际获得的地图要素数、天气站点、观测范围、各变量记录数与覆盖率。
- 启动方式和准确的本地访问地址。
- 实际执行的测试命令与结果。
- 输出文件位置。
- 仍需人工核验的数据、假设和课程使用权限。

验收重点：真实且可追溯的数据、可运行的二维原型、透明的代理指标、可复现的情景比较、诚实的数据质量说明。不要用复杂架构、漂亮的假图或未执行的测试代替这些内容。现在开始检查目录并实施。
