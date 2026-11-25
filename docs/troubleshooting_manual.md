# 《灵魂潮汐》Live2D & Spine（含 Unity 粒子 Submodel）制作问题排查与避坑手册

> 沉淀来源：`欧若拉 · 童话心绘 (Aurora_S4)` 及全量 **`182` 套 Live2D + `175` 套 Spine（`54` 套 `原皮` + `11` 套纯战斗缺失补齐皮肤 + `110` 套换装时装，含补建 `梦咲音月/此情无垢`）= `357` 套模型包** 全链路构建、热区视觉校准、背景对齐、v2 复合插层、无缝粒子与语音路由排障  
> 适用范围：全量 **`182` 套 Live2D** 与 **`175` 套 Spine** 成品（含 `欧若拉/童话心绘`，已解除只读限制，全舰队统一维护、排错与定向验收）  
> 更新日期：2026-11-25（已收录 v2 统一复合单骨架插层、零交叉淡化无缝粒子、隐藏背景动画零重影、尼柯莱特无限帧率路灯、Live2D/Spine 按键触发全链路修复 `#36–#42`、11 套纯战斗 Spine 补齐与手部热区重校准 + `梦咲音月/此情无垢` 无限帧率微风桃枝重构 `#43`、`.lpk` 原生多语言融合红线 `#44`、Live2D `VarFloats` 全量持久化待机动作切换 `#45`、全量 `56` 份多语言 `.lpk` 打包验收通过及**增量改动强制定向验收规范**）

---

## 快速定位索引

| 编号 | 症状关键字 | 所属环节 | 根因速览 |
| --- | --- | --- | --- |
| [#1](#1-spine-人物与背景特效比例严重失调9-倍差) | 人物极小、背景/特效大出近 10 倍 | Spine / Submodel | Submodel 不继承父级 `scale_factor` |
| [#2](#2-spine-人物相对背景上下左右明显错位) | 人物浮空或沉到画面外 | Spine / Submodel | Submodel 不叠加父级 `position_x/y`；Prefab 换算未用完整乘积 |
| [#3](#3-live2d-默认自动动作覆盖原版表情与待机互相打架) | 脸部僵硬眨眼、待机动作抽搐跳变 | Live2D 控制器/Idle | 开启了自动眨眼/呼吸/ExtraMotion；`Idle` 含多个动作 |
| [#4](#4-live2d-与-spine-触摸热区错位或部件名字误导) | 点脚部触发腰部/衣服、热区点不到 | HitAreas 核验 | 游戏部件命名与实际贴图脱节（如 `L_Foot1` 实为腿部阴影） |
| [#5](#5-非原皮触摸混入原皮语音或聊天语音丢失) | 点皮肤触发旧台词、闲聊语音失踪 | Live2D 路由规则 | `MoodActionID` 混入触摸组；`TYPE_TO_GROUP[1201]` 冲突 |
| [#6](#6-打开或翻页交互式语音菜单时反复触发其他动作) | 开菜单/点分类/翻页人物就做 `greet2` | Live2D 菜单/热键 | 菜单项绑定了动画而非零曲线 `menu_silent`；`KeyTrigger` 键码用错 |
| [#7](#7-unity-batchmode-截图全黑无图像或卡死无输出) | 导出的粒子序列全空/卡住不退 | Unity 命令行 | 加了 `-nographics` 导致无 GPU 渲染上下文；`BuildAndCaptureAll` 参数误用 |
| [#8](#8-粒子中心爆出纯白大圆球或边缘出现虹色噪点锯齿) | Additive 光晕糊成实心白块、黑边变霓虹 | PMA 预乘着色器 | EX 默认 `DefaultPMAShader` 叠加下二次除 `alpha/maxRgb` 导致过曝 |
| [#9](#9-星空粒子挤成单条竖线、射线粒子不变长、序列动画错乱) | 背景星辰一条线、2×2/4×3 贴图闪整张图 | Unity 粒子模块导出 | 漏导出 `ShapeModule.m_Rotation`、`StretchedBillboard` 与 `UVModule` 曲线 |
| [#10](#10-贝壳项链等触发特效在-t0-抢跑炸开并过早截断) | 动作刚开始项链就炸出并在 2 秒消失 | 粒子时序/材质/帧率 | 漏导 `startDelay`、录屏截断、误判 `Alpha Blended`、子 Clip FPS 不一致 |
| [#11](#11-jsonutility-反序列化-null-子对象将速度锁死为-0) | 漫游粒子全空 `0` 帧或速度归零 | Unity DTO 反序列化 | `JsonUtility` 将 JSON `null` 实例化为默认对象（`scalar=0`），须显式布尔门控 |
| [#12](#12-特效根节点父级逆缩放与合法缩小-10-混淆) | 粒子超大飞出屏幕或缩放 10 倍消失 | Prefab 坐标缩放 | Root 仅在 `max(\|sx\|,\|sy\|) > 1.05` 时归 `1`（清除逆缩放），保留 `<1.0` 原值 |
| [#13](#13-initialmodulerotation3d-与分轴旋转漏导导致侧向粒子消失) | `Local` 公告板粒子 90° 侧对相机全空 | 3D 旋转/分轴曲线 | `rotation3D`（`startRotationX/Y/Z`）与 `RotationModule.separateAxes` 必须完整导出 |
| [#14](#14-多路并行加速时的-unitypy-流竞态与-unity-工程锁冲突) | 多线程包错乱或第二路 Unity 秒退 | 批处理并发控制 | `UnityPy` 读取加 `asset_lock`；Unity 多路录制通过 `--unity-workers` 复制隔离工程 |
| [#15](#15-主背景候选误选偏移图或窄天空条导致画面整体偏位) | 背景与粒子整体偏移、顶部或单侧出现大块透明留白 | 背景画布定位 | 改用居中全宽底图（`w >= 1400`）并融合垂直相邻/重叠图层包围盒 |
| [#16](#16-scalingmode--1-按-100-倍放大与-gravitymodifier-缺失) | 局部大圆环/光斑遮满全屏、雨雪烟花粒子不按重力下落 | UI 比例与粒子物理 | `ui.ab` 对应 `37.5 UI px/unit`，局部缩放 `> 5.0` 保持 `1.0x`；导出并绑定 `gravityModifier` |
| [#17](#17-rateovertime-mode3-退化与-forcenoiserotbyspeedm_flipprewarm-缺失) | 粒子密度与官方不一致、缺风力/扰动/翻转与首帧空场 | C# 曲线与模块绑定 | 修复 `HasCurveData` 对 `mode=3`（`keys=[]`）与 `mode=2` 识别，补齐全部物理与渲染模块 |
| [#18](#18-粒子前后景穿插失真画质锯齿及首尾重影) | 前后景全盖在人物前、0.4x 锯齿、loop 衔接双倍密度 | 分层与画质升级 | 升至 `0.6x` + `MSAA 4x` + `4096` 图集 + `0.35s` smoothstep；按配额拆分 `fx_back` / `fx_front` |
| [#19](#19-多语言-i18n-全分片驻留内存飙升libsndfile-vorbis-崩溃与创意工坊预览图限制) | 三语分片撑爆内存、`libsndfile` 崩 `.ogg`、工坊封面超限 | 多语言与 `.ogg` 瘦身 | 按需流式提取 I18N；去重 + 多路 FFmpeg `libvorbis`；封面 `< 1 MB` |
| [#20](#20-assetindexer-全包常驻引发-17-gb-内存飙升与持久化索引cache失效) | 加载 `dressspine` / `dressbackground` 时 Python 涨至 `17.17 GB` | AB 索引缓存 | `_LazyCabObjMap`（16 包 LRU 驱逐）+ 持久化 JSON 缓存，峰值降至 `1.35 GB` |
| [#21](#21-live2d-hitareas-误绑-body-part-id前缀遮蔽与非标准-hitarea-漏绑) | `Body` / `Body2` 点不到或遮蔽热区、部分皮肤触控缺失 | Live2D 触控盒审计 | `CubismCore` 校验 Drawable，剔除隐藏 `Body2` 并补齐 `HitArea*`，`182/182` `Flagged: 0` |
| [#22](#22-spine-触摸区误绑隐藏骨骼道具发丝与-原皮-摸后强制打断待机) | 摸手点到掉落道具/发丝；摸 `原皮` 后强制切换动作卡顿 | Spine 热区与纯语音 | 163 套真实蒙皮截图校准（139 套精修）；54 套 `原皮` 设 `file: ""` 纯语音触发；删除 7 套 `原皮(立绘)` |
| [#23](#23-spine-背景前景-submodel-8-类缩放错位翻转与遮罩穿插问题) | 紫帘/挂杆拉伸反旋、人物放大 8~10 倍、花草裁偏、前后景顺序乱 | Spine BG/FG 对齐 | `patch_binary_root_transform`、`_is_censor_cloud`、`_read_sprite_rgba_untrimmed`、`bg_mid/fg_static`、`Mask`/`Limit` |
| [#24](#24-触摸语音跨部位串位官方动作组映射遗漏与-drees-拼写笔误) | 摸胸播牵手、摸腿播摸头、摸臀播挨打 `1401`、皮肤混入邻皮台词 | 语音路由与三语同步 | `CfgSoulActionGroupTable` 三信号融合 + `1401..1404 -> TouchSpecial` + `dre[es]s` 兼容，345 套 `0` 冲突 |
| [#25](#25-ex-工作室保存缩放后人物与背景严重偏离) | 工作室点保存缩放后人物缩成小点、背景原地不动或跑偏 | EX Studio 缩放机制 | `ApplyScaleAndPosition` 只写主 `.config.json` 不改 Submodel，且改坏 `file_loop`；全层归零居中并改由桌面端缩放 |
| [#26](#26-spine-4k-帧序列-fx-导致加载严重卡顿与云层穿帮) | 载入卡死数秒、背景很久才出、直降分辨率糊边、云飘到高楼/熊猫前 | Spine FX 与原版分层 | 13×4K 触发主线程 `Texture2D.Compress`；改方案一原生骨骼粒子 + 还原原版 `Layer_01`/`Layer_02` 遮挡 |
| [#27](#27-webp-默认-exactfalse-导致-spine-pma-画面出现红粉块与灰条纹) | 转无损 `.webp` 后熊猫发红、天空出现粉块/灰条纹和斜框 | WebP × Spine PMA | `libwebp` 默认 `exact=False` 篡改 `alpha==0` 的 RGB，PMA 直接叠加；必须 `lossless=True, exact=True` + 0-diff 校验 |
| [#28](#28-创意工坊-lpk-语音重复占用与音频格式兼容性陷阱) | 同角色多服装包体过大、转 `.opus` 无声 | 创意工坊 `.lpk` 音频 | EX 无 `bassopus.dll` 禁转 `.opus`；`STD2_0` 按 `MD5(FileInfo.FullName)` 去重，须用角色合集共用 `audio/` |
| [#29](#29-官方-spine-纹理集-etc2-44-压缩导致物件边缘杂色噪点与羽化斜虚线) | 手臂/花瓣外沿发绿发灰锯齿、关节/手指/樱花边缘暗灰点、羽化斜虚线 | Spine ETC2 纹理净化 | 手游包 ETC2 4×4 RGB/Alpha 分离压缩破坏 PMA（`RGB > A`、`A=0 & RGB>0` 与孤立压暗点）；用 V4.4 连续轮廓线稿保护脚本从原备份批量净化 279/327 张图集 |
| [#30](#30-uiab-残留旧版编辑器快照陷阱与-art_prefabsab--soulaction-官方运行时真相) | 人物/背景比例错位、漏掉 `bj_*` 动态层或位置与实机不符（波及 58 套） | 官方 Prefab 源头 | `MainUI.lua` 运行时加载 **`art_prefabs.ab`** 并动态挂载 `SoulAction` 至 `Point_Root/Spine_Scale`；`ui.ab` 内为过期美术预览快照（108/108 与正式包存在差异） |
| [#31](#31-原生骨骼粒子-fx_root-画布中心偏移遗漏与主骨骼居中平移未同步) | 原生粒子/滚屏背景向右下漂移裁切（如 `深海巡游` 海底画布）、手工居中皮肤子模型偏移 | 原生 Spine 骨骼粒子 | `convert_fx_to_native_spine.py` 将粒子坐标直接挂在 `(0,0)` 漏加 `fx_root = (bg_x+bg_w/2, bg_y+bg_h/2)`（影响全部 49 个）；手工居中主骨须同步平移所有子模型 |
| [#32](#32-unity-spriterenderer-艺术图层整类遗漏与实体内-z-深度-wz-前后景分流) | 缺失大幅远景/前景贴图（如山峦、云海、餐桌、昆虫图鉴，涉及 14 套 22 张图） | Unity 场景静态层 | 原管线仅扫 UGUI `Image` 漏扫全部 `SpriteRenderer`；须按 PPU/pivot/flip/color 与实体内 `-wz` 深度（`SoulSpineCell` 统设同 `sortingOrder`）提取并分流前后景 |
| [#33](#33-sortedcomponentorderorder-与-canvasm_sortingorder-优先级倒置) | 背景/中景/人物/前景层级颠倒（如 `小美人鱼的夏日`、`盛夏甜心` 等 13 套） | Unity 渲染排序 | `SortedComponentOrder` 运行时强制以 `rootCanvas.sortingOrder + Order` 覆写 `Canvas.m_SortingOrder`；排序键必须优先取 `SortedComponentOrder.Order` |
| [#34](#34-unity-9-宫格拉伸imagetypesliced按整图缩放导致天空黑洞与地平线错位) | 天空/背景顶部出现大块黑洞、地平线严重上移或边框拉伸畸变（7 套） | Unity UGUI 9-Slice | `Image.m_Type == 1 (Sliced)` 带有 `Sprite.m_Border = (L,B,R,T)`（如 `m_Border.y=1105`），直接整图缩放会错位；须用 `_render_nine_slice` 仅拉伸中间带、边框按比例保真 |
| [#35](#35-单层纯待机-fx-前后侧错置与-reload_bg-过期-remove_submodel-残留) | 单层粒子盖在人物前（8 套）或打包校验报 `reload_bg` 引用不存在的旧子模型 | Submodel 组装/校验 | 单层纯待机 `fx_*` 须按真实 `draw_key` 与主人物比较决定落位负序或正序；重建删减 `bg_mid`/`fg_static` 后须同步刷新 `reload_bg` 与 `add_spine_bg_toggle.py` |
| [#36](#36-ex-6-子模型上限截断丢弃层与-spine-38-复合单骨架插层) | 复杂换装丢弃 `bj_*`/后景/夹层 FX，或同骨架多 `ClippingAttachment` 嵌套黑屏 | Spine v2 复合合并 | EX 仅允许 `<= 6` 子模型；用 `spine38_binary_to_json.py` 无损解包合入 `scene_back/scene_front` 救回 38 `bj_*`/54 FX，遇嵌套裁切自动拆分槽位保持 `nested_clips=0` |
| [#37](#37-粒子贴图-clamp-环绕模式遗漏导致的边缘色条与-custom1xyzw-缺失) | 粒子区域边缘出现青色/亮色横条纹（如 `3301_Aoling_S2`）、溶解/自定义流向失效 | Unity Shader/贴图 | Unity 默认 `Repeat` 覆写了原版 `57` 张 `Clamp` 贴图；导出 `tex_wrap_modes.json` + Shader `_MainClamp/_MaskClamp/_Mask2Clamp` 并开启 `Custom1XYZW`（`TEXCOORD1`） |
| [#38](#38-粒子循环交叉淡化发暗闪烁与瞬间重生饱和节点空帧) | 循环粒子半程发暗重影、拖尾截断、单粒子饱和节点首帧空场或 8 通道彻底空白 | Unity v2 粒子循环 | 废除 `0.35s` 交叉淡化，改用精确整数 tick $K$-分身叠加 + $C^1$ 双相流 + 单粒子周期对齐/常驻保活，`blank_channels=0`、接缝比中位数 `0.99x`、`P95=1.42x` |
| [#39](#39-触摸命令-start_mtn-缺少-main-前缀导致特效漏匹配) | 触摸人物时对应 `fx_*_touch` 特效偶发或完全不播放 | Spine 触摸联动 | EX Spine 触摸子模型动画位于 `main` 组，命令必须带 `main:` 前缀（`start_mtn <id> main:fx_<eid>`）；全库批量修补 `3,567` 处后达成 `unmatched_start_mtn=0` |
| [#40](#40-原版隐藏背景动画多静态分带重影及滑门锚点与摩天轮偏心倒立) | 隐藏背景动画移走后原地留残影（爱莉莎/真子）、滑门错位、摩天轮偏心且车厢倒立 | 隐藏背景动画注入 | 按精确分带（`st_s03`/`st_s05`）原地剥离静态重复图、拆分车前立柱 `st_s05_front`、修正右边缘 `Door` 锚点及 `Layer_01 (-20,+27)` 轴心与车厢 `noRotationOrReflection` |
| [#41](#41-尼柯莱特窗外路灯-12-fps-序列帧卡顿与官方重复漏帧跳变) | `尼柯莱特/至深理欲` 窗外路灯肉眼明显卡顿掉帧、末尾顿挫跳变、边缘白条溢出 | 隐藏动画无限帧率重制 | 原版 12 FPS（近窗 `32 px/帧`）且官方 `57==58` 重复冻结 + 漏第 60 帧；用 3D 针孔透视拟合（`0.13 px` RMS）重制为原生 Spine 3 路灯接力骨骼，无限帧率且贴图 `-96%` |
| [#42](#42-live2d-与-spine-按键触发-keytrigger-无效与背景菜单reload_bg-静默失效) | 按 `A–G/H/M/N/R/F3` 无响应、Live2D 按 `R` 不换戒指、Spine 点背景开关选项无效、按 `R` 反而把背景删光 | Live2D & Spine 热键/菜单 | `lwtray.exe` 轮询 Windows `VK_*`（非小写 ASCII / Unity `284`）；EX `CKeyTrigger` 无 `Name` 字段且前置 `Command` 会被 `LastExpression()` 覆写；`group:name` 严禁写 `:0/:1`；`reload_bg` 须先 `remove_submodel` 后 `add_submodel` |
| [#43](#43-梦咲音月此情无垢-桃枝抽搐鬼畜与-11-套纯战斗-spine-手部热区偏移) | 前景桃枝高速抽搐撕裂边界；纯战斗补齐 Spine 点手触发偏移/点不到 | Spine FX 与战斗热区 | GPU `raodong_alphablended` 5× 超速+2× 振幅撕裂 `Clamp` 边界，重构为原生双骨软体网格无限帧率桃枝（`8.52 -> 1.09 MB`）；11 套战斗 Spine 须按 `Spine3_8` 真实槽位世界包围盒逐套重校准 `左手/右手` |
| [#44](#44-lpk-多语言适配陷阱同组混排掩盖change_model-重启丢模型与-translationdata-本地失效) | `.lpk` 切换 EX 语言后菜单/无台词动作消失、切隐藏语言配置重启白屏、云端翻译本地无效 | `.lpk` 原生多语言融合 | EX `GOGMCPNPIDK` 在 `langPool` 非空时直接抛弃 `defaultPool`（严禁同组混排）；`LMHAIGNNDFL` 仅认 `config.mlve` `cosList[]`；`TranslationData` 本地直接 `ret`；统一用 `""`=EN 兜底 + `"zhs"/"zht"/"ja"` 四语严格对称融合 |
| [#45](#45-live2d-菜单切换默认待机动作的-varfloats-持久化机制与-idle-条件写法) | Live2D 菜单想切换默认待机但切完马上跳回 `standby1`、重启忘记或变身贴图失效 | Live2D `VarFloats` / `Idle` | 须用 `CharData.varFloats["idle_mode"]` 落盘持久化（未初始化默认 `0`）；`Idle` 用 `Type:1 equal <k>` 互斥隔离，菜单项直指目标动画 + `Type:2 assign <k>`，变身主形态须完整继承原 `Command` |
| [#46](#46-spine-非婚皮无效誓约模式残留与主骨架内置背景家具物件slot_opacities隐藏机制) | 非婚皮菜单含无效誓约分组、隐藏背景后主骨架残留椅子/桌台 | Spine 菜单与物件隐藏 | 清理 84 套非婚皮 `誓约模式全动作`/`VK_M`；38 套换装主骨架内置背景物件采用 `slot_opacities lock/set` 三选一开关 |

---

## 一、Spine 与 Submodel 排版/比例问题

### 1. Spine 人物与背景/特效比例严重失调（~9 倍差）
- **实机表现**（`QQ20261118-152841.png`）：前景人物缩得很小放在底部，背景与前景粒子相对人物放大了约 `9.09` 倍。
- **根本原因**：Live2DViewerEX 加载 `add_submodel` 时，**Submodel 各自独立读取自身的 `options.scale_factor`，不会乘以主模型的 `scale_factor`**。此前主模型设 `0.11`，而背景/特效仍保持 `1.0` / `0.9622`。
- **排查与解法**：
  1. 确认主模型缩放基准 `base_scale`（如 `0.11`）；
  2. 所有 Submodel 的 `scale_factor` 必须按 `base_scale * prefab_relative_scale` 显式写死：
     - 1:1 匹配画布（`bg_static`、`fx_*`）：直接填 `base_scale`；
     - 游戏 Prefab 自带缩放的背景动态骨架（`bj_01` / `bj_02` / `bj_03`）：按 Prefab 里背景根节点与 `Point_Root * Spine_Scale * Person` 的比例乘以 `base_scale`。
- **预防检查**：打包校验脚本必须断言所有 Submodel `scale_factor` 均落在 `[base_scale * 0.5, base_scale * 1.5]` 合理区间，不允许出现 `1.0`。

---

### 2. Spine 人物相对背景上下左右明显错位
- **实机表现**（`QQ20261118-182315.png`）：人物相对背景与藤蔓明显向下沉偏约 `374 px`。
- **根本原因**：
  1. EX 对 Submodel **不叠加父模型 `position_x / position_y`**，若仅主模型有旧偏置 `(-0.357, -6.613)` 而 Submodel 在 `(0, 0)`，两者立刻错开；
  2. Prefab 层级 `Point_Root (0.86) -> Spine_Scale (0.1158) -> Person (5.97)` 三层缩放连乘漏算或原点算错。
- **排查与解法**：
  1. **主模型与全部 Submodel 的 `position_x, position_y` 统一设为 `(0.0, 0.0)`**；
  2. **严禁优先读 `ui.ab` 快照**：必须按《灵魂潮汐》官方运行时（`MainUI.lua` + `SoulSpineCell.lua`）从 **`art_prefabs.ab`** 解析 `<Dress>_Background` 正式预制体，并将 `CfgElementEntityTable` 指向的 `SoulAction` 实体动态挂载到 `Point_Root/Spine_Scale` 末端（`Vector3.zero`），以完整世界矩阵将 `bg_static`/`bg_mid`/`fg_static`、动态 `bj_*`、`fx_*` 的顶点坐标全部换算到主人物 Spine 局部坐标系（`ui_to_spine_rect`，详见 [#30](#30-uiab-残留旧版编辑器快照陷阱与-art_prefabsab--soulaction-官方运行时真相)）；
  3. 仅依赖 `position = (0, 0)` + 精确骨架内部坐标，确保 EX 中一键居中无需手工拖移。

---

## 二、Live2D 控制器、动作与菜单交互问题

### 3. Live2D 默认自动动作覆盖原版表情与待机互相打架
- **实机表现**（`QQ20261118-152950.png`、`QQ20261118-153001.png`）：出现机械周期眨眼、参数叠加抖动，待机时角色姿势来回跳变。
- **根本原因**：
  - `.motion3.json` 已烘焙原版眨眼与呼吸曲线，若 `.model3.json` 开启自动控制器会二次覆盖参数；
  - `Idle` 分组放入了多个动作（如 `standby1/2/3`），EX 切换轮播导致互斥跳变。
- **排查与解法**：
  - `Controllers.EyeBlink.Enabled = false`、`AutoBreath.Enabled = false`、`ExtraMotion.Enabled = false`；
  - **严禁无条件在 `Idle` 组堆叠多条动画**：基础基线保留单条默认待机（`standby1`）；如需支持玩家在菜单自由切换默认待机（含情绪循环与随机轮播），必须利用 EX 原生 **`VarFloats["idle_mode"]`** 条件互斥门控实现安全多 `Idle` 并持久化记忆（详见 [#45](#45-live2d-菜单切换默认待机动作的-varfloats-持久化机制与-idle-条件写法)）。

---

### 4. Live2D 与 Spine 触摸热区错位或部件名字误导
- **实机表现**：点击“脚部”却触发腿部阴影/裙摆；Spine `idle` 下人物热区框偏在半空。
- **根本原因**：
  - 原模型部件/贴图命名常与外观不符（例如 Aurora_S4 `.moc3` 中 `L_Foot1` 实际对应裙摆下腿部阴影、`L_Foot2/3` 与 `R_Foot1` 是花朵与蕾丝）；
  - Spine `idle` 骨骼求值未正确处理 `"transform": "noRotationOrReflection"` 继承标记，且部分骨架以 `y`、`z`、`z2` 作为偏移父骨，直接丢弃父骨会导致手指位置算偏。
- **排查与解法**：
  - **Live2D**：优先绑定 `.moc3` 内置 `DREFTouchBoxHead / Bra / HandL / HandR / Hip` 等标准隐形触控盒 + 核心躯干（如 `Body2`）；若要自建或细化热区，必须将 `.moc3` 部件网格 UV 渲染图（压缩至 `50%` 尺寸 + `quality=80` JPG）逐一肉眼核对后再绑定。
  - **Spine**：必须用完整骨骼链（含父骨继承标志）渲染 `idle` 骨骼包围盒预览图后再定 `hit_areas`。

---

### 5. 非原皮触摸混入原皮语音或聊天语音丢失
- **实机表现**（`QQ20261118-182252.png`）：换上时装皮肤后触摸身体会播原皮旧语音；部分日常聊天（`Type=1201`）语音找不到。
- **根本原因**：
  - 同一 `SoulActionGroup` 下既有皮肤专属 `SoulResAction`（对应特定 `SoulResId`），又有全皮肤共用 `MoodActionID`；直接遍历会把两者全部塞入 `Tap头/手/胸/臀部/躯干`；
  - 将闲聊 `1201` 路由到 `"Tap"` 会与交互式菜单占用的全局 `"Tap"` 组冲突被覆盖。
- **排查与解法**：
  - **严格分流**：仅 `SoulResAction[skin_res_id]` 及明确带皮肤标识的散落动作允许进入 `Tap头/手/胸/臀部/躯干`；其余 `MoodActionID` 与通用 CV 全部分入 `Greeting`/`Morning`/`Noon`/`Evening`/`Midnight`/`Festival`/`Gift`/`Food`/`Battle`/`Archive` 组；
  - `TYPE_TO_GROUP[1201]` 固定映射至 `"Greeting"`，全局 `"Tap"` 专用于呼出交互菜单。

---

### 6. 打开或操作交互式语音与动作菜单时反复触发其他动作（及快捷键无效）
- **实机表现**：按快捷键或点空白处打开 `"语音菜单"`、点击分类（`Menu_Cat_*`）、点翻页或“返回主菜单”时，角色每次都会播放一次 `greet2` 问候动作；部分字母热键无响应。
- **根本原因**（经读取 EX 运行时 `Assembly-CSharp.dll` 验证）：
  1. `GPALIHHOLBL.OKDGFCNDNMI`（`LoadMotionFiles`）**强制要求 `Motion.File` 非空**（为空或缺失则直接跳过不加载该条，导致菜单打不开）；但菜单节点此前绑定了 `CH_Aurora@Live2D_greet2.motion3.json`，导致每次切页都强行（`priority=9`）播放 `greet2`；
  2. `EGNEALCFPCP` 全局按键表使用的是 **Windows 虚拟键码（`VK_*`）**，而非小写 ASCII 码（例如 `109` 在 VK 中是小键盘 `-`，`118` 是 `F7`，而 `'M'` 应为 `77`、`'V'` 应为 `86`）。
- **排查与解法**：
  1. 生成专用零曲线静音动作 `motions/menu_silent.motion3.json`（`Meta.CurveCount = 0`, `Curves = []`, `Duration = 0.033`, `Loop = false`），所有菜单入口与分页节点（`Tap`、`语音菜单`、`Menu_Cat_*`、`Menu_Cat_*_p*`）统一绑定该文件且设 `"FadeIn": 0, "FadeOut": 0`；只有点选末端 `MenuPlay_***` 时才播放目标语音和动作；
  2. `KeyTrigger.Items` 全部使用标准 Windows 虚拟键码：`49`（`1`）、`77`（`M`）、`86`（`V`）、`82`（`R`）。

---

## 三、Unity 粒子特效离线重录与 Spine 打包问题

### 7. Unity Batchmode 截图全黑、空帧或后台卡死
- **根本原因**：
  - 加了 `-nographics`：Unity 不创建 D3D11 渲染设备，`Camera.Render()` 无法输出真实粒子像素；
  - 从其他目录复制测试资产或路径错误、`ExecuteMethod` 报异常后未退出进程会导致命令行挂死。
- **排查与解法**：
  - 命令行严格使用 **`-batchmode -quit`**（**禁止 `-nographics`**），并且始终加 `-logFile` 输出日志；
  - 长时间 Unity 后台任务必须配套监控日志（查看 `[AuroraFxRecorder]` / `UNITY_EXIT:0`）并设超时提醒，禁止盲等。

---

### 8. 粒子中心爆出纯白大圆球，或背景边缘出现虹色锯齿与紫色色块
- **实机表现**（`QQ20261118-190534.png`）：光晕中心过曝为实心白圆，半透明烟雾出现脏边与高饱和锯齿条纹。
- **根本原因**：
  - Live2DViewerEX 对 Spine（`tex_type = 0`）默认使用 **`DefaultPMAShader`（预乘 Alpha 着色器）**，其 `additive` 通道为 `Blend One One`（直接把纹理 `RGB` 加到屏幕上，不再乘 `A`）。
  - 旧脚本 `SaveRtPng` 错误地做了 **`RGB * 255 / maxRgb`** 与 **`RGB * 255 / A`** 的“反除预乘”处理，把原本只有 `alpha = 1~5` 的极微弱外圈光晕强行拉满到 `255` 纯白/霓虹色，在 EX `Blend One One` 下直接叠爆。
  - 同时，Unity 默认内置 Alpha Blended 着色器不向 RenderTexture 写入正确的透明 Alpha，导致 `normal` 通道透明背景无法抠出。
- **排查与解法**：
  1. `normal` 通道使用自定义 `SoulTide/ParticleAlpha` 着色器（`Blend SrcAlpha OneMinusSrcAlpha, One OneMinusSrcAlpha`）；
  2. **`SaveRtPng` 严禁反除**：`add` 通道保留黑底渲染的原始预乘 `RGB`，仅写入 `A = max(R, G, B)`；`normal` 通道直接输出预乘 `RGBA`（`SoulTideFxRecorder.cs` 旧版中仍残留 `/ maxRgb` 逻辑，后续批处理统一以 `AuroraFxUnityBuilderAndRecorder.cs` 实现为准）；
  3. 制作阶段编写模拟 EX `DefaultPMAShader` 叠加公式的离线合成预览脚本（压缩 `50%`、`quality=80` JPG）肉眼验收后再进打包。

---

### 9. 星空粒子挤成单条竖线、长条闪光不变长、纹理表闪整张图
- **实机表现**（`QQ20261118-190534.png`）：左侧背景星星排成一条直线；`FX_stra` 失去拉长拖尾；2×2 贝壳 / 4×3 爆点 / 3×2 闪光同时显示整个网格。
- **根本原因**：导出预制体参数时遗漏了粒子系统关键模块字段：
  - `ShapeModule.m_Rotation`（例如 `stra` / `shan_*` 原值 `(0, 90, 0)`，漏导后发射盒 X 宽度为 0 塌缩为竖线）与 `m_Position`；
  - `ParticleSystemRenderer.m_RenderMode`（`1 = StretchedBillboard` 及 `velocityScale` / `lengthScale` / `pivot`）；
  - `TextureSheetAnimationModule` 的 `rowMode`（随机行 `1` vs 自定义 `0`）和 `frameOverTime`（`RandomBetweenTwoConstants` 常量区间 vs 线性动画曲线 `0 -> 1`）。
- **排查与解法**：在规格提取器与 Unity C# 重建器中完整映射上述全部模块参数，并在合成预览中专项检查 `2x2`/`4x3`/`3x2` 帧切换与星空分布宽度。

---

### 10. 贝壳项链等触发特效在 `t=0` 抢跑炸开并过早截断（及同步倍速）
- **实机表现**（`QQ20261118-191633.png`）：触发 `touch1` 时贝壳项链在角色尚未抬手时就出现在原处，且不到 `2.4s` 就消失，与 `13.333s` 的人物语音动作完全脱节。
- **根本原因**：
  1. **遗漏 `StartDelay` 与时长截断**：原预制体中触发粒子存在精确延迟与长周期（如 `aixin` 延迟 `1.8s`、`beike` `2.0s`、`bao/xianglian/xianglian_glow` `4.5s` 且项链持续 `6.0s` 至 `10.5s`、`shan` `10.45s`）；此前捕获固定 `startDelay = 0` 且仅录 `2.4s`；
  2. **原生材质混合模式误判**：未查 `14_effect` 原材质，将原本是 `Alpha Blended` 的 `yinghuochong`/`beike`/`xianglian` 归入 `Additive`，或将 `Additive` 的 `smoke` 归入 `Alpha`；
  3. **多序列帧率不一致导致背景粒子卡顿/倍速**：`spine_fx_submodel_packer.py` 生成叠加动画（如 `fx_9008136`）时按当前 `seq.fps` 同步铺设背景常驻轨道 `fx_base_*`；若 `idle` 为 `15fps` 而触发动画用其他帧率，循环背景会出现速度跳变；
  4. **相机偏移 & 切动作残影**：CaptureCamera 须对准 `BG_CENTER_UI`（如 `(0, 11.44)`）而非写死 `(0, 0)`；未用到的 `fx_overlay_*` 槽位若不在 `t=0` 显式写 `name: null`，打断动作切换时上一帧颗粒会留在画面上。
- **排查与解法**：
  - 全量从预制体与 `14_effect` 原材质自动提取 `StartDelay`、真实 `shader` 类型与完整周期时长（`max(startDelay + duration + maxLifetime)`）；
  - Unity 录屏循环内 `f=0` 且 `warmup<=0` 时传 `Simulate(0f, false, true, false)`，从精确 `0.00s` 开始抓帧；
  - 同一 Submodel 内所有片段统一 **`12fps`**（保证循环无倍速差与合理图集页数）；
  - `spine_fx_submodel_packer.py` 自动对空 `fx_overlay_*` 槽位首帧插入 `null` 清空。

---

### 11. `JsonUtility` 反序列化 `null` 子对象将速度锁死为 `0`
- **实机/录制表现**：`2301_QuLing_S2/idle/normal`（`water` 节点）等未启用 `VelocityModule` 的粒子系统整段渲染为 `0` 像素；而手写探针能正常出图。
- **根本原因**：Unity 的 `JsonUtility.FromJson` 遇到 JSON 中的 `"velSpeedModifier": null` 时，不会保持 C# 字段为 `null`，而是会 `new MinMaxCurveDto()` 生成默认值 `scalar = 0f`；旧逻辑仅凭 `n.velSpeedModifier != null && !Approximately(scalar, 1f)` 判断，导致所有未开速度模块的粒子都被强行开启 `velocityOverLifetime` 且 `speedModifier = 0f`，彻底冻结初速度。
- **排查与解法**：所有可选模块必须在 JSON 中导出显式布尔开关（如 `velEnabled`、`rotOverLifeEnabled`、`trailsEnabled`），C# 侧严格只按该布尔值决定是否启用对应模块。

---

### 12. 特效根节点父级逆缩放与合法缩小 `< 1.0` 混淆
- **实机/录制表现**：`402_Freesia_S5`、`4501_RubyRose_S2` 出现异常放大/Z 轴畸变（`1.7753` / `2.50` 源自消除父级缩小的逆比例），但若无条件重置全部 Effect Root `localScale`，又会把 `702_Minerdwen_S3`（`(0.1, 0.1, 1.0)`）的 `huaban` 推到画幅上方 `Y=+734` 导致裁出屏幕外。
- **排查与解法**：`batch_fx_exporter.py` 中 `_node_local_tf(..., ignore_root_scale_rot=True)` 对 Root 始终清零 `rotation`，但 **仅当 `max(abs(sc.x), abs(sc.y)) > 1.05` 时才重置 Root `scale` 为 `(1, 1, 1)`**，保留 `< 1.0` 的作者原意缩小参数；同时 `eff_scale[2]` 若为 `0` 则保底 `1.0`。

---

### 13. `InitialModule.rotation3D` 与分轴旋转漏导导致侧向粒子消失
- **实机/录制表现**：`1003_HagakureRuri_S4/fx_9008133`（`xingxnig_zhuiluo`）全 `252` 帧为 `0` 像素；`402_Freesia_S5/fx_9008161`（`yumao`）及蝴蝶/花瓣类 `32` 个 `rotation3D`、`51` 个 `RotationModule.separateAxes` 节点姿态失真或侧立消隐。
- **根本原因**：部分粒子节点使用 `renderMode=0`（Billboard）+ `renderAlignment=2`（Local）且节点朝向旋转了 90°（`nz ≈ 0` 侧对正交相机），原作依赖 `InitialModule.rotation3D` 中的 `startRotationX/Y = 90°` 把单个粒子面片转回正面面向镜头；此外蝴蝶拍翅与飘落花瓣依赖 `RotationModule.separateAxes`（`x`/`y`/`curve`）。此前仅导出单轴 Z 旋转导致这些节点不可见或缺少 3D 翻滚。
- **排查与解法**：完整导出 `rotation3D`（`rotationX`/`rotationY`/`rotation`）与 `rotOverLifeEnabled`/`rotOverLifeSeparateAxes`/`rotOverLifeX`/`rotOverLifeY`，并在 C# 中正确绑定 `main.startRotation3D` 与 `rot.separateAxes`。另外多通道/Grid 背景 `inspect_bg_prefab_layout` 须优先匹配 `w >= 1600` 的全屏背景图像确定画布中心与宽高（修复 `402_Freesia_S5` 旧选小图偏移）。

---

### 14. 多路并行加速时的 `UnityPy` 流竞态与 Unity 工程锁冲突
- **表现与约束**：
  1. 多个 Python 线程若同时调用同一 `UnityPy.Environment`（如共享 `ui.ab`、`art_prefabs.ab`、`cv/*.ab`）的 `.read()`，会并发读写底层 `EndianBinaryReader` 流位置触发偏移错乱/异常；
  2. 多个 `Unity.exe -batchmode` 进程指向同一 `-projectPath` 会因 `Temp/UnityLockfile` 与 `.meta`/`Library` 写锁互相拒绝启动。
- **排查与解法**：
  - [batch_spine_builder.py](../core_pipeline/batch_spine_builder.py) 的 `--workers` 模式使用单把重入锁 `asset_lock` 仅包裹 AB/LuaRepo 读包取值，将耗时的 Pillow 缩放合成与 [spine_fx_submodel_packer.py](../core_pipeline/spine_fx_submodel_packer.py) Tight-Crop / zlib 压盘完全释放到锁外并发；
  - [batch_fx_exporter.py](../core_pipeline/batch_fx_exporter.py) 的 `--unity-workers N` 会自动复制 `Assets/Packages/ProjectSettings/Library` 至隔离的 `_unity_workers/worker_i` 目录按预估成本负载均衡并行录制，合并 `batch_unity_summary.json` 后自动清理。

---

### 15. 主背景候选误选偏移图或窄天空条导致画面整体偏位
- **实机表现**：`404_Freesia_S6`（`cam_x=-457.5`）、`2002_Ennis_S3`（误选顶部窄天空条 `Image_01`，顶部留出 `246 px` 透明带）、`502_Benten_S3`（`cam_y=+393`）、`3501_QingDai_S2`、`4401_Dora_S2`、`4402_Dora_S3` 等背景和粒子同步跑偏；大量 `1700x1131` 背景被硬塞进 `1768x1176` 框产生 `34px/22px` 四周黑边。
- **根本原因**：旧 `inspect_bg_prefab_layout` 机械偏好名称包含 `image_01/02` 且尺寸最接近 `1768x1176` 的节点，忽略了纯黑遮幅 `CAB`（`CAB-74b9d108c9d0a1a5256f5c9547791b74`）、遮罩/阴影图以及多层拼接背景（如天地拼接条）。
- **排查与解法**：剔除阴影/遮罩关键词（`shadow/lift/limit/mask/anim`）与黑边 `CAB`，优先筛选靠近原点的居中全宽底图（`w >= 1400`），并向下/向上融合相邻或重叠的全宽背景条包围盒（高限 `1700`）。全量重建后 `105/106` 套静态背景 `bg_*.png` 透明边距均控制在 `<= 20 px` 以内（多数为 `0~1 px`）。

---

### 16. `scalingMode == 1` 按 100 倍放大与 `gravityModifier` 缺失
- **实机表现**：`503_Benten_S4/idle/cahihonghuan`（原缩放 `59.3` 乘 `100` 变成 `5929.9` 飞出屏幕）、`1101_NicoletteLamel_S2/idle/glow2`（占屏 `82.6%`）、`601_Asuna_S6/idle/shine4`（光斑过曝铺满背景）；同时 `404_Freesia_S6`、`501_Benten_S2` 等 `47` 套皮肤中的下落/喷泉粒子失去抛物线重力。
- **根本原因**：核查 `ui.ab` 相机 `orthographicSize = 10` 与 `CanvasScaler = 750` 证实游戏内真实 UI 像素比为 **`750 / (2 * 10) = 37.5 px/unit`**，而非 `100`；且部分美术师已在 `Local` 模式下直接填入了 `> 5.0` 的 UI 像素缩放，再乘 `100` 导致百倍爆炸。
- **排查与解法**：`scalingMode == 1` 时若 `max(|sx|, |sy|) > 5.0` 则保持 `1.0x`，否则乘以 `37.5`；同步从 `InitialModule` 导出 `gravityModifier`（配合 `gravityScale = 37.5`）并在 C# `ToMinMaxCurve(..., mult)` 中绑定。

---

### 17. `rateOverTime mode=3` 退化与 `Force`/`Noise`/`RotationBySpeed`/`m_Flip`/`prewarm` 缺失
- **实机表现**：`35` 处随机发射率（`mode=3, RandomBetweenTwoConstants`）粒子始终按单常数发射；带风场曲线、独立轴向扰动、按速度旋转、贴图镜像翻转或预热开场的粒子失真。
- **根本原因**：`UnityPy` 导出的 `mode=3` 曲线 `keys` 数组为空列表 `[]`，旧 C# 仅判断 `keys.Length > 0` 导致全部退化为常数 `scalar`；`mode=2` 若缺 `minKeys` 亦未兜底。
- **排查与解法**：C# 新增 `HasCurveData`（`mode == 3 || ((mode == 1 || mode == 2) && keys.Length > 0)`）并在 `ToMinMaxCurve` 中为缺 `minKeys` 的 `mode=2` 补零曲线；完整导出并绑定 `ForceModule`（`x/y/z` 曲线 + `inWorldSpace`/`randomized`）、`NoiseModule`（`separateAxes` + `position/rotation/sizeAmount`）、`RotationBySpeedModule`、`ParticleSystemRenderer.m_Flip` 与 `main.prewarm`。

---

### 18. 粒子前后景穿插失真、画质锯齿及首尾重影
- **实机表现**：全量 `idle` 粒子中 `430` 个在人物后、`355` 个在人物前，全部压入 `+3` 会导致背景光效挡住角色；`0.4x` 录制且 `RenderTexture` 未开 MSAA 边缘有锯齿；`0.8s` 线性 crossfade 出现短时密度翻倍重影。
- **排查与解法**：
  1. 录制分辨率提升至 **`0.6x`** 并显式设 **`rt.antiAliasing = 4`**，idle 首尾淡化缩至 **`0.35s`** smoothstep，打包图集上限升至 **`4096×4096`**；
  2. 根据 `SortedComponentOrder.Order`、相对 `Person` 的层次遍历顺序以及配表 `EffectOrder` 标记节点 `back` / `front`；在总 `submodels <= 6` 且正负 order 充裕时自动拆分 `fx_back`（`order = -1`）与 `fx_front`（`order = +3`，接收 `start_mtn`），配额满的皮肤（如 `102_Colcher_S3`、`603_Asuna_S8`、`1503_Dreizehn_S4`、`3201_Dolores_S2`、`3402_Clotho_S3`、`4602_Clarice_S3`）自动将 `idle_back` + `idle_front` 按 PMA 合成单 FX 回退，严守 `[-3..-1, 1..3]` 唯一排序红线。

---

### 19. 多语言 I18N 全分片驻留内存飙升、`libsndfile` Vorbis 崩溃与创意工坊预览图限制
- **实机/工具链表现**：
  1. 若同时加载简中、英文、日文三语共 `312` 个 `CfgI18NTable_*.lua` 全量分片（超 `114 万`条文本）或令 `AssetIndexer(light=False)` 将 `03_prefabs` 重复加载并常驻 `111` 个 `dressspine/*.ab` 的 `UnityPy.Environment`，`python.exe` 工作集内存会飙升至 `17~21 GB`；
  2. Python `soundfile`（Windows 预编译 `libsndfile.dll`）在编码特定采样长度（如 `Andrea_7Daysaway.wav`）的 Ogg Vorbis 时会发生底层 C 段错误异常退出；
  3. Steam 创意工坊上传时若封面预览图 `>= 1 MB`，`ISteamUGC::SubmitItemUpdate` 会报错失败。
- **排查与解法**：
  1. **按需流式提取 I18N 与 AB 立即释放**：[build_i18n_and_ogg_fleet.py](../core_pipeline/build_i18n_and_ogg_fleet.py) 先扫描 `352` 套模型实际用到的 `8,085` 个音频 stem 与 `7,903` 条台词，逐个分片流式读取并在单分片结束后立即 `del txt` + `gc.collect()`，峰值内存控制在 **`< 150 MB`**；[batch_fx_exporter.py](../core_pipeline/batch_fx_exporter.py) 复用 `self.ui_env` / `self.art_env` 并在扫描 `dressspine/*.ab` 后立即 `del env`；
  2. **跨包去重 + 批量多输入 FFmpeg 编码 `.ogg`**：用原生 GPL 版 `ffmpeg -c:a libvorbis -q:a 5`（单次进程挂载 16 个输入/输出映射 × 12 线程并发）替代 `libsndfile`，仅对去重后的 `8,172` 个唯一音频编码一次并分发至 `29,275` 处引用，逐文件校验 `b"OggS"` 魔数头后清理原始 `.wav`，音频体积从 `21.70 GB` 缩减至 `~1.85 GB`；
  3. **创意工坊打包红线**：封面预览图严格控制在 `< 1 MB`（建议 `< 800 KB`），并按单人偶合集或单套动态时装分包上传。

---

### 20. `AssetIndexer` 全包常驻引发 `17 GB` 内存飙升与持久化索引缓存
- **实机/工具链表现**：在构建与修复脚本中启用 `AssetIndexer(light=False)` 加载 `ui.ab`、`art_prefabs.ab` 与 `dressbackground` / `dressspine` 时，`python.exe` 工作集内存飙升至 **`17.17 GB`**（接近物理内存上限触发严重换页卡顿）。
- **根本原因**：早期 `AssetIndexer` 在扫描全部 AB 包定位 `CAB` / 预制体映射时，将每个打开的 `UnityPy.Environment` 对象整包强引用常驻在字典内不释放。
- **排查与解法**（[batch_fx_exporter.py](../core_pipeline/batch_fx_exporter.py)）：
  - 引入 **`_LazyCabObjMap`**（基于容量上限 `16` 个 Bundle 的 LRU 懒加载与自动驱逐释放机制），扫描阶段仅提取轻量元数据后立即释放 `Environment`；
  - 将静态索引结果落盘为持久化缓存 **`_cab_index_cache.json`** 与 **`_dress_sda_cache.json`**，二次启动直接秒读缓存，`python.exe` 峰值内存由 **`17.17 GB` 降至 `1.35 GB`**。

---

### 21. Live2D `HitAreas` 误绑 `Body` Part ID、前缀遮蔽与非标准 `HitArea*` 漏绑
- **实机表现**：部分 Live2D 角色躯干/臀部点击失灵或互相抢占；部分角色存在隐藏 `Body2` 遮挡层，而 `伊汐尔/原皮_变身`、`和铃/原皮`、`和铃/古锦新韵` 等使用非标准 `HitArea*` 命名的原厂触控盒未被识别。
- **根本原因**：
  1. 误将 Part ID（而非真实 Drawable ID `ArtMesh`）填入 `HitAreas[].Id`，或受 Live2DViewerEX 前缀匹配影响导致 `DREFTouchBoxHip` 等存在命名遮蔽隐患；
  2. 原厂模型除常见 `DREFTouchBox*` 外，还存在 `HitArea` / `HitArea2..5` 专盒命名；同时 `7` 套模型（含 `安德莉亚` 3 套、`欧若拉` 3 套含 `童话心绘`、`爱莉莎/完美篇章`）挂载了多余隐藏 `Body2` 图层。
- **排查与解法**（[audit_live2d_touch.py](../core_pipeline/audit_live2d_touch.py)、[fix_live2d_touch_audit.py](../core_pipeline/fix_live2d_touch_audit.py)）：
  - 直接通过 `ctypes` 调用 `Live2DCubismCore.dll`（`csmGetDrawableIds`、`csmGetDrawableVertexPositions` 与纹理 Alpha 计算真实可点击多边形边界），校验所有 `HitAreas[].Id` 均为真实 Drawable 且通过胸部高于臀部、双手不叠头顶等解剖空间合理性断言；
  - 为 `伊汐尔/原皮_变身`（`HitArea/HitArea2..5`）、`和铃/原皮` 与 `和铃/古锦新韵`（`HitArea2` -> `Tap臀部`）绑定原厂专盒，移除 `7` 套隐藏 `Body2` 并将原 `Tap躯干` 条目平滑分流至 `Tap臀部/胸/手/头`，最终实现 **`182/182` 套 `Flagged: 0`** 全官方触控盒覆盖。

---

### 22. Spine 触摸区误绑隐藏骨骼/道具/发丝与 `原皮` 摸后强制打断待机
- **实机表现**（`QQ20261119-193830.png`、`QQ20261119-210903.png`、`QQ20261120-112325.png`）：
  1. 仅凭备份或简单包盒自动推算导致部分模型触摸框偏移（例如 `伊汐尔/原皮`、`月本柚/原皮` 绑定了飘动发丝、影子、`qunzi` 或背景骨；`月本柚/明媚之约` 将触摸框绑在脱手掉落的风铃道具上）；
  2. 点击 `54` 套 `原皮` Spine 时人物动作强行跳转到独立动作文件导致动作卡顿不自然（而 `原皮(立绘)` 与 `原皮` 功能高度重叠且存在 `7` 套冗余文件夹）。
- **排查与解法**（[render_spine_touch_previews.py](../core_pipeline/render_spine_touch_previews.py)、[update_spine_hit_areas.py](../core_pipeline/update_spine_hit_areas.py)、[batch_orig_spine_builder.py](../core_pipeline/batch_orig_spine_builder.py)）：
  - 基于 EX 同源 `Spine3_8` 运行时编写 C# 真实蒙皮+热区叠加渲染器 `_spine38_preview_renderer.exe`，为全量 `163` 套 Spine 输出可视化审核图，逐套人工/视觉排查并精修校准 **`139` 套** Spine `hit_areas`，同时在 [verify_batch_spine.py](../core_pipeline/verify_batch_spine.py) 增加黑名单拦阻误绑背景/影子/裙摆骨；
  - 反编译 EX 运行时 `OJFAIICIFOH` / `IPLHCGIIJLA::LICLPJKFNJN` 证实：当 Spine 动作条目的 `"file": ""` 为空字符串时，EX 会保留当前待机动作不被打断、同时正常播放 `"sound"` `.ogg` 语音与 `"text"` 字幕；据此将全部 `54` 套 `原皮` Spine 触摸组统一改为 `"file": ""`（`start` 组改为 `"file": "idle"`）；
  - 删除 `7` 套冗余 `原皮(立绘)` 目录并移除 `batch_orig_spine_builder.py` 的对应生成逻辑，确立最终 **`163` 套 Spine（`54` 原皮 + `109` 换装）** 清晰舰队口径。

---

### 23. Spine 背景/前景 Submodel 8 类缩放错位、翻转与遮罩穿插问题
- **实机/审计表现**（`QQ20261120-140829.png` 及 `bg_layout_audit_report.json`）：
  - 在 `163` 套 Spine 扫描中发现 `91` 套存在背景/前景对齐或图层顺序问题，集中表现为 **`8` 类系统性根因**（如 `叶隐琉璃/绵绵小懒虫` 紫帘与挂杆尺寸/位置错位、`阿卡赛特` 电视机内云雾溢出框外、`星见亚砂/盛夏游乐场` 人物放大 `8~10` 倍等）：
    1. **非均匀缩放/负缩放翻转/Z 轴旋转未烘焙进子骨架**：`bj_*` 节点存在 `scaleX != scaleY`、`scaleX < 0`（`initialFlipX/Y`）或 Z 旋转（审计发现 `33` 处 `bj_transform_mismatch`、`17` 处 `spine_rotated`、`3` 处 `spine_non_uniform_scale`、`1` 处 `spine_negative_scale`），仅靠单一 float `scale_factor` 无法还原；
    2. **和谐云雾过滤词误伤装饰云**：旧关键词 `"cloud"` 将正常装饰白云 `LightCloud`（光明云）一并剔除；
    3. **缺失 `Spine_Scale` 节点未兜底**：如 `Asuna_S9` 缺少中间 `Spine_Scale` 包装节点时 `person_scale` 计算退化，导致人物相对背景放大 `8~10` 倍；
    4. **Tight-Packed `Sprite` 裁掉透明边距**：直接取导出 PNG 尺寸而不还原 Unity `Sprite.m_Rect` / `m_Offset` 透明外边距，导致花草/门框图层偏位；
    5. **静态背景层与动态 `bj_*` / `Person` 穿插被扁平压到 `-3`**：如 `fg_static`（`56` 处）与 `bg_mid`（`40` 处）被全部塞入底景 `bg_static`，人物应被前景遮挡时却盖到前景之上；
    6. **多子模型顺序分配跨越 `0` 溢出到对侧**：负序（人物后）名额不足时误分配成 `+1..+3`（人物前）；
    7. **Unity `Mask` / `RectMask2D` 与 `Limit` 视口裁切缺失**：电视框、拱门内元素或超宽背景边缘溢出画布。
- **排查与解法**（[batch_fx_exporter.py](../core_pipeline/batch_fx_exporter.py)、[batch_spine_builder.py](../core_pipeline/batch_spine_builder.py)、[fix_all_spine_bg_layouts.py](../core_pipeline/fix_all_spine_bg_layouts.py)）：
  - 实现 `patch_binary_root_transform` 将 `bj_*` / `Person` 根骨非均匀缩放、负缩放翻转与 Z 旋转精确注入 Spine 二进制 `.skel`；改用 `_is_censor_cloud` 白名单放行 `LightCloud`；补全 `Spine_Scale` 兜底与 `SortingOrder` 同侧严格保序；实现 `_read_sprite_rgba_untrimmed`、`bg_static`/`bg_mid`/`fg_static` 三层按实需拆分、`Mask`/`RectMask2D` 及 `Limit` 边界裁切，并通过 [render_spine_composite_previews.py](../core_pipeline/render_spine_composite_previews.py) 对全部 `109` 套换装 Spine 完成前后对比图逐一肉眼验收。

---

### 24. 触摸语音跨部位串位、官方动作组映射遗漏与 `drees` 拼写笔误
- **实机表现**（`QQ20261120-140829.png`）：触摸人物胸部却播放“想要牵手也是可以的……”（手部台词）、摸腿却播放摸头台词、Live2D 摸臀部触发通用挨打台词（`1401..1404`），以及个别皮肤混入其他皮肤台词。
- **根本原因**：
  1. 换装 Spine 早期按固定下标取模切片分配 `头/胸/左手/右手/腿/足`，完全忽略官方 `CfgSoulActionGroupTable` 中定义动作与身体部位绑定的 **`Type`**（`801=head, 901=hand, 1001=chest, 1101=leg`）；
  2. Live2D 原皮脚本将通用反应动作 `1401..1404`（`Touch_Reaction` / `After_Marriage_Touch`）塞入 `Tap臀部` 而非 `TouchSpecial`；
  3. 游戏官表及音效命名在 `叶隐琉璃/绵绵小懒虫` 与 `不断的红线` 中存在 **`drees`（双 e 漏写 s）拼写笔误**（如 `drees4`），仅匹配 `dress` 导致跨皮肤泄漏过滤失效。
- **排查与解法**（[fix_spine_voice_routing.py](../core_pipeline/fix_spine_voice_routing.py) 及上游 `batch_spine_builder.py` / `batch_orig_spine_builder.py` / `batch_live2d_builder.py`）：
  - 构建“音频标签 + 中英语义规则 + 官方 `CfgSoulActionGroupTable` (`801/901/1001/1101`)”三信号融合分类器与跨部位否决规则（禁止含明显他部位语义台词进入错误触区），并将 Live2D `1401..1404` 统一移入 `TouchSpecial`、兼容正则 `dre[es]s\d+` 剔除跨皮肤串音；
  - 解除 `欧若拉/童话心绘` 只读保护后完成全舰队执行与三语配置同步，干跑复检全部 **`163` 套 Spine + `182` 套 Live2D 均达成 `0` 冲突**。

---

### 25. EX 工作室保存缩放后人物与背景严重偏离
- **实机表现**（`QQ20261122-120458.png`，`和铃/古锦新韵`）：在 EX 工作室调整大小/位置并点「保存缩放和位置」后，人物缩成一个小点落到左下角，背景却保持原尺寸留在右上方（16.8 倍落差）。
- **根本原因**（反编译 `exstudio.exe` 与 `lw.exe` 实证）：
  1. `EditorUIController::ApplyScaleAndPosition()` **只改写主模型 `.config.json`** 的 `options.scale_factor` 与 `position_x/y`（且顺带把 `"file_loop": true` 改写为 `"wrap_mode": 1`），**从不同步修改 `submodels/*/.config.json`**；而 `lw.exe` 对主模型与每个子模型各自独立读取 `options`。
  2. 诱因：原皮肤中心严重偏在 `(+4435, +1954)` 且默认占屏高 `218%`，迫使用户去工作室缩放。
- **排查与解法**：
  - 将主模型、`bj_*`、`bg_static` 与前后 FX 全层骨架统一归零居中至 `(0, 0)`，默认 `scale_factor` 校准到 `~108%` 屏高，所有 `position_x/y` 归 `0.0` 并恢复 `"file_loop": true`。
  - **使用避坑**：带 Submodel 的 Spine 如需缩放/拖动，请在 **Live2DViewerEX 桌面壁纸端**直接操作（桌面端同步缩放父代理节点，全层联动不错位），**切勿**在 EX 工作室点击「保存缩放和位置」。

---

### 26. Spine 4K 帧序列 FX 导致加载严重卡顿与云层穿帮
- **实机表现**（`QQ20261122-125201.png`、`和铃/古锦新韵`）：模型加载卡死数秒且背景延迟很久才出现；若直接降分辨率（0.45×）并硬裁 `alpha <= 3`，则光束出现硬边色带、小花瓣糊成马赛克；同时白云飘在摩天大楼与 3D 熊猫广告牌前方穿帮。
- **根本原因**：
  1. 原版两层 FX 录屏共 `13` 张 `4096×4096`（`49.61 MB` / `800 MB` 显存），`lw.exe`（`BHNCAHBOMMP::FKJLDFKKNFF`）在 Unity 主线程同步解码并调用 `Texture2D.Compress`（DXT5），直接卡死主线程数秒。
  2. 原打包把原版预制体 `HeLing_S2_Background` 的 `Layer_01`（蓝天 + 青绿底幕）与 `Layer_02`（天空与广告屏镂空的摩天大楼/亭子屋檐 `HeLing_S2_Background_01`）扁平压进同一张 `bg_static`，导致白云无法被建筑遮挡、且熊猫 3D 边框左下角露出立交桥栏杆外。
- **排查与解法**：
  - 新增 [SoulTideSpineParticleExporter.cs](../unity_fx_recorder/Assets/Editor/SoulTideSpineParticleExporter.cs) 走 **方案一（原生 Spine 3.8 骨骼粒子 + `ClippingAttachment`）**，保留原始小贴图直接输出 60/144Hz 骨骼时间轴（FX 显存由 `800 MB → 5 MB`，降幅 `99.4%`，0 画质损失）；
  - 按原版 Unity 层级拆分还原：`-3 bg_static`（蓝天 → 90.9s 无缝滚云 → 青绿屏幕底幕）→ `-2 bj_01`（3D 熊猫）→ `-1 fx_heling_s2_back`（原版 `1700×1131` 镂空建筑前景 → 15s 竹叶粒子）→ `0 MAIN` → `+3 fx_heling_s2_front`（18s 阳光/彩虹/花瓣/树叶），整包体积降至 `4.50 MB`（-92.3%）。

---

### 27. WebP 默认 `exact=False` 导致 Spine PMA 画面出现红粉块与灰条纹
- **实机表现**（`QQ20261122-135515.png`）：将 Spine/Submodel 纹理转为 `lossless=True` `.webp` 后，Live2DViewerEX 实机渲染中熊猫广告牌大面积发红、天空出现粉红方块、灰横条纹与斜向半透明灰框。
- **根本原因**：Pillow / `libwebp` 在 `lossless=True` 下**默认 `exact=False`**，会自动把 `alpha == 0` 透明像素的 RGB 覆盖成压缩预测垃圾值（实测 `bj_01` 达 `60.9%`、`fx_front` 达 `74.7%`）。但 Spine 3.8 默认走**预乘 Alpha（PMA：`Blend One OneMinusSrcAlpha`）**，即使 `alpha == 0` 仍会把非零 RGB 直接叠加到画面上！
- **排查与解法**：
  - 所有 Live2D / Spine `.webp` 编码**强制启用 `lossless=True, exact=True, quality=100`**，写出后立即回读并断言 `np.array_equal(src_rgba, dec_rgba)`（`max_diff == 0`），经 EX 自带 `libwebp.dll`（`WebPDecodeRGBA`）实测透明区异常 RGB 归零后问题彻底消失。
  - **额外坑点（Spine 3.8 JSON 生成）**：EX 的 `Spine3_8.SkeletonJson` 强制读取 `skeleton["hash"]`（缺失抛 `KeyNotFoundException`），且任何时间轴的**最后一个关键帧**严禁带 `"curve": "stepped"`（否则 `ReadCurve` 抛 `IndexOutOfRangeException`）。

---

### 28. 创意工坊 `.lpk` 语音重复占用与音频格式兼容性陷阱
- **问题表现**：182 套 Live2D 语音占 `1,455.8 MB`（56.2%），其中 `959.6 MB`（65.9%）为同角色多皮肤重复副本；若误将 `.ogg` 转 `.opus` 会导致 EX 静音；若用 NTFS 硬链接去重，打包上传 `.lpk` 后仍会还原成多份。
- **根本原因**（反编译 `lw.exe` 与 `exstudio.exe` 实证）：
  1. `lw.exe` 仅内置 `bass.dll` / `bassflac.dll`，无 `bassopus.dll`，不支持 `.opus`；
  2. `exstudio.exe` `STD2_0` 打包器（`EBEKBDCAOFB::HJFKBCALBLH`）以 **`MD5(UTF8(FileInfo.FullName))`** 去重：只有当同包多套服装指向**同一个规范化路径**的音频文件时，`.lpk` 才会去重为 1 份；独立文件夹内各自复制的 `.ogg` 路径不同，不会被去重。
- **排查与解法**：
  - 制定 [build_and_pack_workshop_lpks.py](../scripts/build_and_pack_workshop_lpks.py)：**人声完全不重编码**（100% 保留原始 `.ogg`），将 Live2D + Spine 服装合并打入同一个 `.lpk` 并通过 `../audio/<name>.ogg` 共用同一份 SHA-256 防撞名去重的 `audio/` 目录，跨皮肤/跨引擎语音重复体积直降 `74%+`。

---

### 29. 官方 Spine 纹理集 ETC2 4×4 压缩导致物件边缘杂色噪点与羽化斜虚线
- **实机表现**（`QQ20261122-210914.png`，`莉莉艾洛/花与剑的交织` 及全库 72.4% 主图集）：部件外沿（手臂、花朵、长发）出现发绿/发灰/发紫的 4×4 块状锯齿噪点；皮肤或脸颊等部件交接处出现笔直的绿/灰/白点状斜虚线。
- **根本原因**：
  1. 官方手游包提取的 Spine 图集大多经过 Unity **ETC2 RGBA8（4×4 块）**有损压缩：RGB 与 Alpha 完全分离压缩，且每个 2×4/4×2 子块仅共享 1 个 4/5-bit 基础色 + 单一灰度偏移 `ΔY`；
  2. 当 4×4 块跨过彩色主体与透明黑 `(0,0,0,0)` 时，给透明黑加负偏移会在 `A=0` 留下非零 RGB 幽灵点（PMA 混合下纯加法发光），并在半透明外沿与同色羽化接缝（如躯干 `Slot 96` 搭在手臂 `Slot 97` 上）产生严重 `RGB > A` 与色度偏离（发绿/发灰），将原本隐形的羽化接缝暴露成杂色虚线；
  3. **严禁直接套用 AI 超分/去噪模型**（不懂 PMA 与 Spine 紧凑多边形打包，会导致相邻部件边缘融合串色并破坏五官/细发丝）；且处理时**必须区分 Straight Alpha 静态层**（`bg_static` / `bg_mid` / `fg_static`）并**保护 1px 深色线稿与大面积半透明蕾丝薄纱**（避免把 1px 暗描边误当异常点拉亮打断）。
- **排查与解法**（工具已归档至 [README.md](../README.md)）：
  - 开发物理感知 **V4.4 双通道防黑洞 + 全 4×4 边块净化版边缘去噪工具** [spine_etc2_clean_v3.py](../scripts/spine_etc2_clean_v3.py)（配套 [export_spine_blend_masks.cs](../scripts/export_spine_blend_masks.cs) 校验全库 361 个骨骼 `0` 个 Additive/Screen 槽、[render_spine_compare.cs](../scripts/render_spine_compare.cs) 4×/6× 实机 Bilinear PMA 渲染验证）：
    1. 自动跳过干净无损图集与 Straight Alpha 静态层；
    2. 清除 `A=0 & RGB>0` 幽灵点、≤24px（长宽 ≤8px）悬浮碎噪与 EAC 拖尾（保护 1px 细线/竖琴弦）；
    3. **核心墨线验证真轮廓线稿 + 1px 彩色镶边双保护（Stage 1.5 + Stage 2）**：实色暗线保护半径扩至 `dist_trans ≤ 4.6px`（对齐 Stage 2 块对角线），结合 `min(sdL_init, signed_dL_pure)` 与核心暗度门控（含深底极暗线 `L≤65`、纯白底浅描边 `L≤190 & dL≤-55` 与 2~4px 窄羽尖 `keep_tip`）以及 `true_color_trim`（连续 1px 高色度金边/彩边），彻底淘汰亮花瓣/肉色肤边误判（T4）并 100% 保护全部 1px 连续深色描边与彩色细边；
    4. **全 4×4 边块双向精修（Stage 2）**：引入 `broad_mixed_blk`（覆盖硬混合 + `a_min ≤ 238, span ≥ 20` 半混合 4×4 块）与 `dist_trans ≤ 4.6px`（覆盖 4×4 对角线 `4.24px`），参考纯净 `pure_interior`（加连通域+射线防跨透明沟保护）做双向精确 RGB 插值，根治无描边肘/肩/指关节灰紫虚线（T1a/b/c）与高 Alpha 正向亮过冲（T3），并彻底净化 Stage 3 锚点源头；
    5. **双通道防黑洞半透重建（Stage 3）**：严格隔离 `anchor_fill`（剔除 `true_dark_contour`）与 `anchor_dark`（仅限严格更近 TDC 且外侧低 A 抗锯齿，平局绝不选暗锚），叠加 Straight 亮度防黑洞门控（根治 V3.3 白羽/亮丝/白扇砸黑洞退化 T2）及 `has_local_anc` + 水彩跨色相保护（保护 `bj_01` 樱花水彩粉雾与大面积蕾丝薄纱）；严格 PMA 重编码并按原格式原子写回（支持 `--from-backup` 始终从 `E:\A灵魂潮汐\备份\spine_etc2_before_clean\` 原始备份一手重修，WebP `lossless=True, exact=True` 逐像素校验）。
  - **全库落地结果**（`spine_etc2_clean_report.json`）：扫描 `327` 张 Spine 图集（`163` 主图 + `164` Spine 骨骼子模型），从原始备份一手净化 **`279` 张**、跳过干净图集 `48` 张、`0` 错误；累计清零 **`1,077,772`** 个 `A=0 & RGB>0` 幽灵点、**`8,073,981`** 个 `RGB > A` 违例像素，修复 **`8,697,827`** 个 4×4 高 Alpha 边块像素与 **`2,574,968`** 个关节/花瓣伪装暗黑噪点，保护 **`10,435,371`** 个连续真线稿像素与 **`95,748`** 个 1px 彩色镶边像素。

---

### 30. `ui.ab` 残留旧版编辑器快照陷阱与 `art_prefabs.ab` + `SoulAction` 官方运行时真相
- **实机表现**（`QQ20261123-143049.png`、`QQ20261123-143019.png`、`QQ20261123-174944.png`）：全库大量换装 Spine 出现人物相对背景明显放大/偏位（如 `和铃/古锦新韵` 偏 `+895, +500` 且缩放差 `1.5×`）、静态底图尺寸位置不对、甚至遗漏动态背景层（如 `叶月雪/情满月盈` 缺失 2 个 `bj_*` 子模型）。
- **根本原因**（反编译《灵魂潮汐》官方 Lua 与 Prefab 实证：`MainUI.lua:54-64, 1461-1495`、`GirlDressShowUI.lua:182-207`、`SoulSpineCell.lua:155-218`、`MainUI.prefab`、`SoulSpineCell.prefab`）：
  1. 官方游戏在主界面与换装预览界面加载 `BgPrefabs` 时，均通过 `UIGlobalApi.GetElementPrefab` 走 **`art_prefabs.ab`（`assets/03_prefabs/art_prefabs/element/maincity_dress_bg/*.prefab`）**，**绝不读取 `ui.ab`**！
  2. `ui.ab` 中保留的 `108` 份同名 `*_Background` 实为美术制作期残留的**旧版编辑器预览快照**（内嵌静态占位 `SoulDress_*` 人物节点）；全量比对显示 **`108/108` 份与 `art_prefabs.ab` 均存在差异**，直接波及 **`58` 套皮肤**（`34` 套人物位置/缩放差异、`20` 套静态 `Image` 差异、`14` 套 `bj_*` 差异、`19` 套 FX 差异）。
  3. 官方真实运行时装配链：在 `art_prefabs.ab` 的干净背景预制体（`109/109` 均无内嵌人物占位，只有 `Point_Root/Spine_Scale`）加载完成后，`SoulSpineCell` 将自身 `SetParent(Point_Root, false)` 挂载至 `Point_Root` 子节点末尾，用 `Point_Root/Spine_Scale.localScale`（缺省 `(0.1, 0.1, 1.0)`）覆写 `goSpineRoot.localScale`，再通过 `ShowUIElement(entityId, CfgSoulSpineActionControlTable.SoulAction, 0, goSpineRoot, Vector3.zero)` 动态生成 `CfgElementEntityTable.PrefabName`（即 `SoulDress_*.prefab` 实体）。
- **排查与解法**：
  - 永久修正上游 [batch_fx_exporter.py](../core_pipeline/batch_fx_exporter.py)（新增 `soul_action_prefab`、`resolve_bg_prefab_root` 强制优先 `art_prefabs.ab` `art_container`、`resolve_soul_action_entity`）与 [batch_spine_builder.py](../core_pipeline/batch_spine_builder.py)（`_find_main_skel_unit` 与 `_extract_unity_scene_layers` 在 `Point_Root` 末尾动态合入 `SoulAction` 实体）；
  - 开发并执行 [rebuild_spine_scenes_from_art_prefabs.py](../scripts/rebuild_spine_scenes_from_art_prefabs.py)，对全库 **`109/109` 套换装 Spine** 完成基于 `art_prefabs.ab` + `SoulAction` 的无损重建（`rebuild_art_prefabs_report.json`，`0` 错误）。

---

### 31. 原生骨骼粒子 `fx_root` 画布中心偏移遗漏与主骨骼居中平移未同步
- **实机表现**（`QQ20261123-174944.png`，`阿卡赛特/深海巡游`）：`BG01` 海底流动水纹底图整张向右下偏移并被裁切掉左上大片区域；全库所有已转换原生骨骼粒子的 `fx_*` 均存在不同程度的整体偏位。
- **根本原因**：
  1. 帧序列版 `fx_*` 贴图坐标由 `bg_static` 的世界矩形 `[bg_x, bg_x+bg_w] × [bg_y, bg_y+bg_h]` 定位，中心在 `(bg_x + bg_w/2, bg_y + bg_h/2)`；但早期 [convert_fx_to_native_spine.py](../scripts/convert_fx_to_native_spine.py) 导出原生骨骼粒子时，Unity 相机坐标系（原点为画布中心 `(0, 0)`）直接挂在 Spine `root (0, 0)` 下，漏掉了画布中心偏移 `(bg_x + bg_w/2, bg_y + bg_h/2)`，波及全部 **`49` 个**原生粒子子模型（`47` 个批量 + `2` 个手工）。
  2. 特殊案例 `和铃/古锦新韵` 曾手工将主骨架 `root` 偏移 `(-4435.25, -1954.25)` 实现居中（见 [#25](#25-ex-工作室保存缩放后人物与背景严重偏离)），重建或重导其 4 个子模型（`bg_static` / `bj_01` / `fx_heling_s2_back` / `fx_heling_s2_front`）时若不施加相同的 `(-4435.25, -1954.25)` 平移量，就会与主人物脱节。
- **排查与解法**：
  - 在 `convert_fx_to_native_spine.py` 中新增专用定位父骨 `{"name": "fx_root", "parent": "root", "x": round(bg_x + bg_w/2, 2), "y": round(bg_y + bg_h/2, 2)}`，将所有 UV 滚屏与粒子骨骼父级统一挂载至 `"fx_root"`，并新增 `--force` 参数全量重导出 `47` 个批量原生 FX；
  - 对 `和铃/古锦新韵` 4 个子模型同步施加 `(-4435.25, -1954.25)` 偏移，最终全库 `fx_missing_fx_root == 0`、`off-canvas == 0/109`。

---

### 32. Unity `SpriteRenderer` 艺术图层整类遗漏与实体内 Z 深度（`-wz`）前后景分流
- **实机表现**：`天音祈/青霄和歌` 缺少远山云海两张大图（`1700×711` + `1700×341`）、`青蒿/拂雁青尘` 缺失 `1700×840` 远景、`德莱洁恩/心宿良栖` 缺失 `1144×1137` + `1321×1152` 装饰图、`爱瑞妮/昆虫观察` 缺失 `1529×641` 图鉴底图，以及 `萨缇娅/魔王晚宴`、`路易莎/甜美时光` 等共 **`14` 套皮肤 / `22` 张高分辨率艺术图层**完全消失。
- **根本原因**：
  1. 旧版 `_extract_unity_scene_layers` 仅扫描 UGUI `Image`（`MonoBehaviour`）与 `SkeletonGraphic`/`SkeletonAnimation`，完全忽略了场景及 `SoulAction` 实体内大量使用的普通 Unity `SpriteRenderer` 组件；
  2. 根据 `SoulSpineCell.lua:192-218`（`ShowSpineSuccess`），运行时会把 `SoulAction` 实体下全部 `Renderer`（含 `MeshRenderer` 与 `SpriteRenderer`）的 `sortingOrder` 强行统一成 `Point_Root` 的 `Canvas.sortingOrder`，因此实体内部各骨架与 `SpriteRenderer` 之间的遮挡关系完全取决于世界深度 **`-round(wz, 3)`**。
- **排查与解法**：
  - 升级 `batch_spine_builder.py` 的 `get_sprite_image_and_meta`（返回 `(im, ppu, piv_x, piv_y, border)`）与 `_extract_unity_scene_layers`，完整提取全部活跃 `SpriteRenderer`（精确换算 `PPU`、`pivot`、`flipX/Y`、`color` 乘色与旋转缩放），并将实体内组件统一按 `(sortingOrder, -round(wz, 3), sibling_order)` 排序，正确分流至 `bg_static` / `bg_mid` / `fg_static`。

---

### 33. `SortedComponentOrder.Order` 与 `Canvas.m_SortingOrder` 优先级倒置
- **实机表现**：`叶隐琉璃/小美人鱼的夏日`（`Mid` 节点 `Canvas.m_SortingOrder=1012`，但 `SortedComponentOrder.Order=3`）、`薇姬娜/盛夏甜心`、`星见亚砂/盛夏游乐场`、`密丝特/湖上芭蕾` 等 **`13` 套皮肤**在 `art_prefabs.ab` 中出现前后景遮挡完全颠倒。
- **根本原因**：预制体中旧的 `Canvas.m_SortingOrder` 常残留美术临时数值（如 `1012`），而官方运行时由挂载在节点上的 `SortedComponentOrder` 组件（`UIRootCanvas = mainCanvas`）在初始化时把 `Canvas.sortingOrder` / `Renderer.sortingOrder` 强制覆写为 **`rootCanvas.sortingOrder + SortedComponentOrder.Order`**。此前排序脚本误以 `Canvas.m_SortingOrder` 优先，导致层级错乱。
- **排查与解法**：在 `batch_fx_exporter.py` 与 `batch_spine_builder.py` 中统一确立优先级铁律：**若节点或其祖先存在活跃 `SortedComponentOrder`，一律优先使用 `SortedComponentOrder.Order`，仅在无该组件时回退读取 `Canvas.m_SortingOrder` / `Renderer.m_SortingOrder`**。

---

### 34. Unity 9 宫格拉伸（`Image.Type.Sliced`）按整图缩放导致天空黑洞与地平线错位
- **实机表现**：`叶隐琉璃/小美人鱼的夏日`（`Image_Sky_01` 原图含 `m_Border.y = 1105` 巨大底边）背景上方出现大块黑洞、海天交界线严重错位；同类问题波及 **`7` 套皮肤**（`叶隐琉璃/小美人鱼的夏日`、`薇姬娜/盛夏甜心`、`萨缇娅/魔王晚宴`、`星见亚砂/虹光子弹`、`梦咲音月/春竹贺晓`、`九华/与猫逐浪`、`爱莉莎/幻想时刻`）。
- **根本原因**：Unity UGUI `Image` 当 `m_Type == 1`（`Image.Type.Sliced`）且绑定 `Sprite.m_Border = (L, B, R, T)` 非零时，四个边角与边框像素保持原尺寸（仅随组件世界缩放 `abs(wsx), abs(wsy)` 等比缩放），**只拉伸中间未受边框锁定的区域**；旧版背景合成器把所有 `Image` 一律按 `Simple` 整图缩放，直接破坏了 9 宫格比例与地平线落点。
- **排查与解法**：在 `batch_spine_builder.py` 新增 `_render_nine_slice(im, target_w, target_h, border, sx, sy)`，检测到 `m_Type == 1` 且 `any(b > 0 for b in border)` 时严格按 Unity 9-Slice 规则分 9 块（含目标尺寸小于边框和时的按比例压缩兜底）重采样拼接，全库 7 套彻底恢复原版构图。

---

### 35. 单层纯待机 FX 前后侧错置与 `reload_bg` 过期 `remove_submodel` 残留
- **实机表现**：
  1. `叶隐琉璃/小美人鱼的夏日`、`薇姬娜/盛夏甜心`、`莉莉艾洛/清凉海滨`、`爱莉莎/幻想时刻`、`朵拉/雪绒暖夜`、`克拉丽丝/比翼双飞`、`朔耶真子/情系站缘`、`越一弥心/时尚同桌` 等 **`8` 套皮肤**的单层纯待机 `fx_*` 原本位于人物后方，却被固定放在 `+3` 盖住人物本体；
  2. 全量重建删减多余的 `bg_mid`/`fg_static` 后，个别皮肤（如 `伊汐尔/新春焰火`）主配置中 `reload_bg` 动作仍残留已删除子模型的 `remove_submodel bg_mid` 指令，被工坊打包校验拦下。
- **排查与解法**：
  1. 在 `rebuild_spine_scenes_from_art_prefabs.py` 中，根据 `art_prefabs.ab` 中该单层纯待机 FX 节点的真实 `draw_key` 与主人物 `Person` 比较，准确判定落位负序（人物后）或正序（人物前）；
  2. 重建结束后自动同步重跑 `add_spine_bg_toggle.py` 并全库清理/同步 `109/109` 套皮肤的 `reload_bg`（仅保留实际存在的子模型 ID，`0` 过期引用）。

---

### 36. EX 6 子模型上限截断丢弃层与 Spine 3.8 复合单骨架插层
- **实机表现**（`QQ20261124-141208.png` 等全库审查）：部分复杂换装皮肤同时包含多张穿插静态图、多个动态 `bj_*` 与前后夹层粒子；v1 按传统独立子模型平铺很快撞上 Live2DViewerEX `<= 6` 子模型槽位硬上限，被迫截断丢弃了 **`38` 个动态 `bj_*`、`15` 个后景 FX 与 `39` 个夹层 FX**，且个别直接粗暴合骨的原型出现两个 `ClippingAttachment` 互相嵌套导致整块画面消失或裁切异常。
- **根本原因**：
  1. EX 单模型最多仅挂载 `6` 个独立 Submodel（且受正/负 `order` 槽位约束），无法容纳 7~12 层细粒度穿插场景；
  2. Spine 3.8 运行时明确禁止嵌套 `ClippingAttachment`（前一个裁切未闭合前开启第二个 `ClippingAttachment` 会直接失效或互相吞噬）。
- **排查与解法**：
  - 编写完整无损解码器 [spine38_binary_to_json.py](../core_pipeline/spine38_binary_to_json.py)（全库 `149/149` 个二进制 `bj_*` 骨架 `0` 错误精确到达 EOF），由 [rebuild_all_scenes_and_fx_v2.py](../scripts/rebuild_all_scenes_and_fx_v2.py) 按 `art_prefabs.ab` 全局 DFS `draw_key` 将人物后方静态分带（`st_sXX`）、`bj_*`、原生粒子与 GPU 频段按精确 slot 顺序合入 `scene_back`（负序），人物前方合入 `scene_front`（正序），触摸特效独立拆分至 `fx_*_touch` / `fx_*_touch_back`；
  - 合并前严格检测 `ClippingAttachment` 区间：凡会发生嵌套裁切的图层自动拆分为独立安全槽位（如 `scene_back_2` 或保留独立 `bj_*`）。全库 `109` 套换装最终 `384` 子模型总计 `1,069.96 MB`，全部 `38` 个 `bj_*` 与 `54` 个后/夹层 FX 100% 救回，且 `order_violations=0`、`nested_clips=0`。

---

### 37. 粒子贴图 `Clamp` 环绕模式遗漏导致的边缘色条与 `Custom1XYZW` 缺失
- **实机表现**（`QQ20261124-165753.png`，如 `3301_Aoling_S2` 等皮肤）：特效层局部边界出现异常青色/亮色硬横条或竖条；部分依赖粒子自定义曲线偏移/溶解的特效无流动反应。
- **根本原因**：
  1. 从 Unity `AssetBundle` 提取 `.png` 重新在批处理录制工程中 `Texture2D.LoadImage` 加载时，Unity 默认将 `wrapMode` 设为 `TextureWrapMode.Repeat`；而原版工程中有 **`57` 张粒子/遮罩贴图**显式设定为 `Clamp`（`m_WrapU=1` 或 `m_WrapV=1`），在 UV 滚动/偏移越界时由 `Repeat` 卷回另一端边缘色素形成亮色条带；
  2. 原录制工程的 `ParticleSystemRenderer` 未绑定 `ParticleSystemVertexStream.Custom1XYZW` 到 `TEXCOORD1`，导致读取自定义流的官方材质效果失效。
- **排查与解法**：
  - 在 `batch_fx_exporter.py` 中导出全库贴图原版 `m_TextureSettings.m_WrapU/V` 至 `tex_wrap_modes.json`；
  - 在 `SoulTideBatchFxRecorder.cs`、`SoulTideParticleAdd.shader` 与 `SoulTideParticleAlpha.shader` 中完整支持按贴图设置 `wrapModeU/V` 与着色器级 `_MainClamp/_MaskClamp/_Mask2Clamp` 边界钳制，并为启用 `CustomDataModule` 的粒子自动开启 `TEXCOORD1`（`Custom1XYZW`）顶点流。重录后 57 张 `Clamp` 贴图边缘色条彻底消失。

---

### 38. 粒子循环交叉淡化发暗闪烁与瞬间重生饱和节点空帧
- **实机表现**：旧版 `0.35s` smoothstep 首尾交叉淡化录制出的循环 GPU 粒子，在接缝处出现明显半程发暗、双倍重影或周期频闪；v2 升级首轮全检时还发现 `8` 个特殊通道彻底空白（`1001_HagakureRuri_S2`、`1402_NankungLin_S3`、`1701_Juewa_S2`、`301_Lilyiro_S3`×2、`3901_Antonina_S2`、`4301_HeLing_S2`、`602_Asuna_S7`）及个别单粒子脉冲节点在 `f=0` 闪烁双倍亮度。
- **根本原因**：
  1. 线性或 smoothstep 交叉淡化对独立随机粒子场不满足能量/方差守恒（$0.5^2 + 0.5^2 = 0.5 \neq 1$），且无法衔接 `ringBufferMode` 连续拖尾；
  2. 对 `maxParticles <= 4` 且极高发射率（`rate = 50 ~ 100000`）的瞬间重生饱和单粒子节点，按常规采样会出现：① `emitSchedule` 漏采 `f=0` 的 `emittedTick0` 导致空场；② 静态 `ringBufferMode == 2` 占位节点被周期内重复 burst 覆盖重置；③ 稀疏长寿粒子（`lt > T`）在单周期探测窗内未触发导致整条通道全空；④ 带寿命调制曲线的单粒子若寿命未精准对齐周期约数，会在 `f=0` 发生新旧重叠双倍 Alpha 跳变。
- **排查与解法**（详见专题研究报告 `Unity v2 粒子循环无缝实现方案`）：
  - 在 `SoulTideBatchFxRecorder.cs` 中彻底废除 `0.35s` 交叉淡化，改用 **精确整数 tick $K$-分身零交叉淡化叠加** + **方差保持 $C^1$ 双相流（Dual-Phase Flow）**；
  - 针对饱和瞬间重生节点分类处理：子情况 A（静态/纯 UV 四边形）强制常驻保活（`duration=99999, loop=false, burst=(0, maxP)`）；子情况 B（随寿命调制节点）精准对齐 `targetLt = T / kCyc` 并回退 `1.5*subDt` 消除 `f=0` 双倍叠加；补齐 `f=0` 的 `emittedTick0`、保护 `rb == 2` 免被中途重置、并将 `ProbeSaturatedEmitSchedule` 探测窗扩至 `6` 个周期；
  - 全部 `38` 套受影响 GPU 皮肤重录并重建后，全库 `126` 个待机 GPU 通道终审达到 **`blank_channels = 0`（8 处死通道全部恢复）、接缝/步进比中位数 `0.99x`、`P90 = 1.14x`、`P95 = 1.42x`**。

---

### 39. 触摸命令 `start_mtn` 缺少 `main:` 前缀导致特效漏匹配
- **实机表现**：v2 将所有触摸特效拆分为独立纯触摸子模型（`fx_<skin>_touch` / `fx_<skin>_touch_back`）后，部分触摸动作触发时未播特效；自动化审查发现旧配置存在大量无分组前缀的裸 `start_mtn <id> fx_<eid>` 指令。
- **根本原因**：在 Live2DViewerEX Spine 运行时中，触摸子模型各触发动画均存放在 `motions.main` 分组下；`start_mtn` 指令的标准寻址格式为 **`start_mtn <submodel_id> main:<motion_name>`**（例如 `start_mtn fx_aurora_s4_touch main:fx_90011`），缺少 `main:` 前缀会导致 EX 找不到目标动作而静默跳过。
- **排查与解法**：在 `rebuild_all_scenes_and_fx_v2.py` 与 `verify_batch_spine.py` 中统一强制写入并校验 `main:` 分组前缀，全库三语配置累计修正 **`3,567` 处**引用，最终实测 **`unmatched_start_mtn = 0`**，且 `add_spine_bg_toggle.py` 全库达成 `A=54 / B=42 / C=67 / D=0`。

---

### 40. 原版隐藏背景动画多静态分带重影及滑门锚点与摩天轮偏心倒立
- **实机表现**（`Snipaste_2026-11-24_20-31-25.png`）：注入 4 套官方 Unity `AnimationClip` 隐藏背景动画后，物体移动离开原位时背景上仍残留一份一模一样的静止残影（爱莉莎小狗头、朔耶真子列车/立柱）；真子车厢滑门未贴合门框边缘；星见亚砂摩天轮绕错圆心偏心画圈且 20 个座舱随大轮倒转倒立。
- **根本原因**：
  1. **多静态分带未按目标分带原地剥离**：v2 将静态图层按深度拆分为多个分带（`st_s00/st_s03/st_s05/st_s07`），早期重影剔除仅替换首张底图，未能精准定位物体所在的静态分带（`2502_Alisa_S3` 的 `Layer_02/Anim/Image_02` 实际在 `st_s03`；`1802_SakuyaMako_S3` 的 `Image_04..08` 在 `st_s05`），且真子的站台立柱与长椅（`Image_05..08`）本应遮挡在列车前方却与车后底图（`Image_04`）合在了同一层；
  2. **Unity `RectTransform` 右边缘锚点与 `pivot` 误算**：真子滑门节点 `Door` 在预制体中使用右边缘锚点（相对中心实际为 `+293.3, -116.4`），其子图 `Image_Door_02` 的 `pivot = (1.0, 0.5)`（左移 `-46.0`），按默认中心锚点计算导致滑门整体错位；
  3. **父节点偏移漏算与骨骼旋转继承**：`604_Asuna_S9` 摩天轮父节点 `Layer_01` 存在 `(-20, +27)` 偏移，漏算导致轮毂中心偏离真实世界坐标 `(797.0, 371.5)`；20 个 `chexiang` 车厢子骨默认继承父骨旋转，未设不继承旋转标记导致车厢随大轮转到上方时上下颠倒。
- **排查与解法**（固化于 [patch_hidden_bg_anims_and_bone_fx.py](../scripts/patch_hidden_bg_anims_and_bone_fx.py)）：
  - 新增精准分带原地重烘函数 `_replace_static_band_texture`：对 `2502_Alisa_S3` 精准从 `st_s03` 剔除 `Layer_02/Anim/Image_02` 并将 `alisa_anim_s` 插至 `st_s03` 前方；对 `1802_SakuyaMako_S3` 保留 `st_s00` 不动、将 `st_s05` 拆为车后 `st_s05`（`Image_04`）与车前 `st_s05_front`（`Image_05..08`），并精确换算 `Door` 右边缘锚点与 `Image_Door_02` `pivot=(1.0, 0.5)`；
  - 对 `604_Asuna_S9` 计入 `Layer_01 (-20, +27)` 定位真轴心 `(797.0, 371.5)` 使 `motianl` 轮毂 `(0.0, 0.0)` 零偏心，并为全部 20 个 `chexiang` 骨骼写入 **`"transform": "noRotationOrReflection"`** 保证座舱全程水平直立；
  - 经 `SPINE_ANIM_TIME` 多时间点（`t=0s / 2.0s / 5.5s / 10.0s / 15.0s / 21.0s`）离线 `Spine3_8` 合成渲染复检，全部零重影、零错位。

---

### 41. 尼柯莱特窗外路灯 12 FPS 序列帧卡顿与官方重复漏帧跳变
- **实机表现**：`1102_NicoletteLamel_S3`（`尼柯莱特/至深理欲`）播放窗外飞驰路灯时（原版手游同样存在该缺陷），路灯近窗高速掠过时肉眼明显卡顿掉帧，且每个循环末尾会出现一次顿挫停滞加瞬间跳变；初版还原时还因未加裁切遮罩导致白色天空略微溢出 `st_s00` 窗框外缘。
- **根本原因**（逐帧解析官方 60 帧序列图 `ActionBg` 实证）：
  1. 官方采用 **12 FPS** 序列帧播放，路灯贴近车窗瞬间每帧水平位移高达 **`32 px/帧`**，低帧率大步进导致严重频闪卡顿；
  2. 官方原版序列帧本身存在两处制作瑕疵：**第 `57` 帧与第 `58` 帧像素完全一致**（造成 `167 ms` 画面冻结），紧接着**漏掉了第 `60` 帧**（循环衔接瞬间产生 `+61.7 px` 突变跳帧）。
- **排查与解法**（固化于 [patch_hidden_bg_anims_and_bone_fx.py](../scripts/patch_hidden_bg_anims_and_bone_fx.py)）：
  - **层级与裁切**：将窗外路灯层严格置于 `st_s00` 车厢窗框后方，并施加与 `st_s00` 矩形精确对齐的 `nico_actionbg_clip`（`nested_clips=[]`）杜绝白边溢出；
  - **精确 3D 针孔透视拟合 + 原生 Spine 无限帧率重制**：提取原版 60 帧中全部 `116` 个路灯轮廓样本拟合精确 3D 针孔相机运动模型（高度 `h rms = 0.55 px`、底边 `bx(h)` 二次拟合 `rms = 0.13 px`、`by(h) rms = 0.34 px`、倾角 `rms = 0.09°`，纯色 `#F9F9F9` 天空），从原帧中色键抠出 1 根 `113×371` 直立高清路灯与 1 块 `16×16` 天空贴图，构建 **3 路灯连续相位接力原生 Spine 骨骼动画（`nico_lamp_0..2`，`T_loop = 16.0s`、`T_lamp = 5.33s`、`120` 密采样关键帧线性插值）**；
  - **最终收益**：彻底消除官方 12 FPS 卡顿、重复冻结帧与漏帧跳变，在任意刷新率（60/120/144/240Hz）下均无限帧率丝滑掠过，同时窗外图集体积从 3 张序列帧 WebP 共 **`548.5 KB`** 暴降至单张 **`22.1 KB`（`-96%`）**；`t=0.0s / 1.8s / 3.6s / 15.98s` 实测首尾逐像素精准衔接。

---

### 42. Live2D 与 Spine 按键触发（`KeyTrigger`）无效与背景菜单/`reload_bg` 静默失效
- **实机表现**：
  1. Spine 模型按 `A–G / M / N / H / F3 / R` 全部失效（其中误按 `F3` 会触发 `reload_bg`，而小键盘 `1–8 / - / .` 才会误触）；
  2. Spine 换装打开 `背景菜单` 后点击「隐藏背景」或「恢复完整背景」无任何反应；按 `R`（`reload_bg`）反而把 `bj_01` 等子模型删掉；
  3. Live2D 27 套誓约戒指皮肤按 `R` 键毫无反应，无法穿脱戒指；
  4. 在 EX Studio（`exstudio.exe`）预览窗口测试热键无反应，或在 EX 桌面端（`lw.exe`）关闭热键/未聚焦桌面时按键不响应。
- **根本原因**（反编译 `lwtray.exe`、`lw/Assembly-CSharp.dll` 与 `exstudio/Assembly-CSharp.dll` 全链路字节码实证）：
  1. **键码体系必须为 Windows 虚拟键码（`VK_*`）**：EX 桌面端通过消息 `1016` 将 `KeyTrigger.input` 发给 `lwtray.exe`，由 `LWTray.VirtualKeyInput` 周期调用 Win32 **`GetAsyncKeyState(vKey) & 0x8000`** 轮询（合法表见 `BIIJAAHAGED::ALMAMHJCFMD()`）。旧 Spine 配置误写了小写 ASCII（`97..103` 实为 `NUMPAD 1..7`、`104` 实为 `NUMPAD 8`、`109` 实为 `NUMPAD -`、`110` 实为 `NUMPAD .`、`114` 实为 `F3` 劫持了 `F3`）与 Unity `KeyCode.F3 = 284`（`> 255` 非法 VK，`GetAsyncKeyState(284)` 恒返回 `0`）；
  2. **Live2D `CKeyTrigger` 无 `Name` 字段 + 前置 `Command` 表情覆写陷阱**：`Model3ConfigData/CKeyTrigger` 与 `ModelConfigData/KeyTrigger` 仅含 `Input/input`、`DownMtn/down_mtn`、`UpMtn/up_mtn` 三个字段，旧配置 `{"Input": 82, "Name": "佩戴誓约戒指"}` 反序列化后 `down_mtn == null` 彻底无效。此外在 `IPIMLPLPGOJ/DKFCIPAOAJM::AJCCOODHKII` 中，前置 `Command` 先执行，若动作未指定 `Expression` 会紧接着用预存的 `LastExpression()` 将表情回写覆盖；必须改用动作结束回调 **`PostCommand: "next_exp"`**（经 `BNHNAHIPKDL::CFLABOHCIDE` 调用 `Live2DModelProxyBase::SetNextExpression(1)`，同步更新 `CharSave.expression` 实现 `ring_on` ↔ `ring_off` 持久化切换），且配合 `MotionDuration: 50`（ms）确保零曲线静默动作 `menu_silent.motion3.json` 触发计时完成；
  3. **动作寻址 `group:name` 严格按字符串精确匹配 `motion.name`**：`HLGNFAFIPOA::DJFDLHGKDMA` 遍历 `motions[group]` 仅比较 `motion.name == name`，**不支持数字下标**，因此旧版 `背景菜单` 的 `"背景开关:0"` / `"背景开关:1"` 全部静默返回 `null`；
  4. **`reload_bg` 命令顺序倒置与旧 v1 路径残留**：`Live2DModelProxyBase::RemoveSubModel` 同步销毁并移除 `BFPMDIFELDD`，`AddSubModel` 按 `jsonFilePath` 去重实例化；旧版 `rebuild_all_scenes_and_fx_v2.py` 将新 v2 `add_submodel` 拼在旧 v1 `remove_submodel` 之前，导致按 `R` 先加载 `bj_01` 再立刻删除它，并携带大量不存在的旧 v1 路径；
  5. **EX 运行环境前提**：`exstudio.exe` 预览窗本身**从未调用 `OnKeyDown`**，按键触发仅在 EX 桌面端（`lw.exe` + `lwtray.exe`）生效；且需确认 EX 设置中的快捷键模式（`hotkeyEnabled == 0` 禁用、`1` 需先点击一次桌面使壁纸获焦、`2` 全局响应）。
- **排查与解法**（固化于 [fix_all_key_triggers.py](../scripts/fix_all_key_triggers.py)、[add_spine_bg_toggle.py](../scripts/add_spine_bg_toggle.py) 与全部上游构建/验收脚本）：
  - **Spine 全库（`163` 套 / `489` 份配置、`5,058` 项）**：全部改为标准 Windows `VK_*`（`A..G=65..71`、`H=72`、`M=77`、`N=78`、`R=82`、`F3=114`）；`109` 套换装（`327` 份配置）的 `背景菜单` 选项改为精确 `"背景开关:hide_bg"` 与 `"背景开关:show_bg"`，`reload_bg` 统一重建为先 `remove_submodel`（含当前全部子模型与 `touch_only`）再 `add_submodel` 的无残留序列；
  - **Live2D 全库（`27` 套誓约戒指皮肤 / `81` 份三语配置）**：注入 `"誓约戒指切换"` 静默动作组（`File: "motions/menu_silent.motion3.json", FadeIn: 0, FadeOut: 0, MotionDuration: 50, PostCommand: "next_exp"`）并将 `VK_R(82)` 绑定为 `{"Input": 82, "DownMtn": "誓约戒指切换"}`；
  - 链接 Live2DViewerEX 原生 `lw_Data\Managed\Assembly-CSharp.dll` 对全库 `576` 份 Live2D 主配置 + `7` 份 `sub_henshin` + `489` 份 Spine 主配置实机反序列化校验 **`0` 错误**，并在 [verify_batch_live2d.py](../core_pipeline/verify_batch_live2d.py) 与 [verify_batch_spine.py](../core_pipeline/verify_batch_spine.py) 固化强制回归校验。

---

### 43. `梦咲音月/此情无垢` 桃枝抽搐鬼畜与 11 套纯战斗 Spine 手部热区偏移
- **实机表现**（`QQ20261125-003551.png`、`QQ20261125-110642.png`、`QQ20261125-110713.png`）：
  1. 第 110 套补建换装 `梦咲音月/此情无垢`（`802_Netsuki_S3`）画面前景的 4 支桃花枝高频抖动抽搐，贴图边缘被严重拉扯撕裂；
  2. 新补齐的 11 套纯战斗 Spine 皮肤在实机点击手部时，部分角色的 `左手`/`右手` 触摸框偏向武器/长袖外缘或左右手定位失准。
- **根本原因**：
  1. 原版前景桃枝由自定义 Unity 材质 `FX_qqc/raodong_alphablended` 驱动噪声 UV 扭曲；离屏录制重演时因材质参数换算产生约 **5× UV 滚动超速** 与 **2× 振幅偏移**，在 `Clamp` 边缘触发剧烈拉伸鬼畜，且 12 FPS 录屏导致 `scene_front` 贴图膨胀至 `8.52 MB`；
  2. 战斗 Spine（`23_spine/battle/character/`）的骨骼命名与手臂/手掌/武器挂载结构比换装 Spine 更杂乱，仅凭骨骼名称正则自动推断极易误绑上臂、武器或长袖末端。
- **排查与解法**：
  - **无限帧率原生 Spine 双骨软体网格桃枝**（固化于 [build_netsuki_s3_spine.py](../scripts/build_netsuki_s3_spine.py)）：彻底弃用 GPU 扰动录屏，直接提取原版 4 张静态桃枝高清贴图，在 `scene_front` 中为每支桃枝构建 **根骨（锚定画布外沿固定不动）+ 端骨（6~8s 错相低幅微风正弦摆动）的权重网格（Skinned Mesh）**；根治抽搐撕裂并在 60/120/144Hz 下无限帧率丝滑摇曳，同时将 `scene_front` 贴图从 **`8.52 MB` 暴降至 `1.09 MB`**；
  - **11 套战斗 Spine 手部热区逐套真骨重校准**（固化于 [build_missing_battle_spines.py](../scripts/build_missing_battle_spines.py)）：调用 EX 同源 `Spine3_8` 渲染器导出全部 11 套皮肤的真实槽位世界坐标包围盒与叠加审核图，逐套肉眼核验并精确重校准全部 **`22` 处 `左手`/`右手`** 触摸骨，同步更新全部 **`33` 份**三语配置。

---

### 44. `.lpk` 多语言适配陷阱（同组混排掩盖、`change_model` 重启丢模型与 `TranslationData` 本地失效）
- **问题场景**：将中/英/日三语源码打包为单份 `.lpk` 时，常见的三种直觉做法都隐藏致命引擎陷阱：
  1. 在同一动作组内只给“带台词的动作”加 `Language` 标签、把无台词菜单导航/静音项留空不打标签；
  2. 在包内藏入 3 套 `.bin3`/`.bin` 配置并用菜单指令 `change_model` 切换语种；
  3. 寄希望于官方 `TranslationData`（`getTranslation.jsp`）做本地 `.lpk` 翻译。
- **根本原因**（反编译 `lw_Data\Managed\Assembly-CSharp.dll` 全链路字节码实证）：
  1. **语言解析与 `langPool` 整池替换规则**：`Live2DModelProxyCommon::get_Language` 映射静态表 `CJKJHFDHDBH::KCEJPNMDLKD = ["", "en", "zhs", "zht", "ja", "ru"]`（`ModelSetting.languageId <= 0` 跟随 `SettingData.langId + 1`，其中 `en_US=0, zh_CN=1, zh_HK=2, ja_JP=3, ru_RU=4`，`>= 6` 退回 `""`）；`BNHNAHIPKDL::GOGMCPNPIDK` 与 `GCDCHIPNIOK` 过滤动作组时，一旦精确匹配当前语言的 `langPool.Count > 0`，就会**整池丢弃 `defaultPool`（空/未打标签项）**！因此同组内只要混排带标签与无标签异名动作，切换到该语言后无标签项会瞬间“蒸发”；
  2. **`change_model` 隐藏配置重启丢模型 Bug**：重启恢复已加载模型时，`Live2DModelProxy::IEHMBIDBIPE` → `NKAKGLMDGPP` → `HJLAFJDNOKK::LMHAIGNNDFL(lpkData, charData.jsonFilePath)` 仅遍历 `config.mlve` 的 `cosList[]` 匹配路径；任何未登记在 `config.mlve` 中的隐藏语言配置会直接返回 `null`，造成**本地 `.lpk` 重启直接丢失模型（白屏）**，工坊 `.lpk` 重启被强制重置回默认语言；
  3. **云端 `TranslationData` 本地直接跳过**：`Live2DModelProxy::NPJALMDMHIH` 入口即判断 `if (workshopItem == null) return;`，对本地导入 `.lpk` 完全不起作用且强依赖联网。
- **排查与解法**（固化于 [build_and_pack_workshop_lpks.py](../scripts/build_and_pack_workshop_lpks.py) 与 [verify_workshop_lpks.py](../scripts/verify_workshop_lpks.py)）：
  - **EX 原生 `Motion.Language` / `motion.language` 四语对称融合**：每套皮肤仅注册 1 条 `config.mlve` 服装，打包器自动读取同目录简/英/日三份配置并融合——**英文版省略 `Language`/`language`（`""`）作为全球默认兜底**，简中写 `"zhs"`、繁中写 `"zht"`（复写简中确保繁中用户命中中文）、日文写 `"ja"`；
  - **强制四语 `Name` 集合严格对称**：[verify_workshop_lpks.py](../scripts/verify_workshop_lpks.py) 内置 `check_multilang_group` 校验每个动作组 `{"", "zhs", "zht", "ja"}` 四支完全对等；同时合并 26 套誓约戒指 `Expressions[].Name` 为双语 `"佩戴誓约戒指 / Put On Oath Ring"`，并将 10 套变身皮肤 `Form_Switch_Main` 的 `change_model` 目标统一归一化指向融合后的单个 `.bin3`；
  - **实测效果**：100% 离线兼容本地 `.lpk` 与创意工坊 `.lpk`，切换 EX 语言零重载即时生效，压缩体积仅增 `+0.31% ~ +0.47%`；全库 55 单包 + 1 总集包均已通过 `56/56` 校验与 EX 原生 `Assembly-CSharp.dll` `357/357` `0` 错误实测。

---

### 45. Live2D 菜单切换默认待机动作的 `VarFloats` 持久化机制与 `Idle` 条件写法
- **问题场景**：希望玩家能在 Live2D 菜单里自由切换默认待机动作（包括全部 `standby*`、🔀 随机轮播以及全部情绪 `*_loop` 循环动作），且切换后一直保持、重启 Live2DViewerEX 依然记住当前选择，同时不破坏原有 `standby1` 默认体验与变身主形态贴图。
- **引擎底层实证**（反编译 `lw_Data\Managed\Assembly-CSharp.dll`）：
  1. `BNHNAHIPKDL::BBEBONKICBB` 在筛选动作（含 `Idle`）时先检查 `Motion.VarFloats` 中所有 **`Type == 1`** 条件项（支持 `equal`、`not_equal`、`greater`、`less` 等）；读取缺失变量时 `EMFAHGKJPDK` 自动返回 **`0f`**；
  2. 动作触发时的 `CNLFIJKNODB` 精确执行顺序为：**`VarFloats` 写操作（`Type == 2`，经 `KEFFFDJDLBN` 执行 `assign`/`add`/`sub`）→ `Command` → `HLGNFAFIPOA::AMJGDLEMFOE()`（调用 `SaveData()` 将 `CharData.varFloats` 按模型唯一 `Options.Id` 持久化落盘）→ `ShowTextBubble`**；
  3. 核验全库 `182` 套 Live2D 的 `Options.Id` 100% 唯一，每套皮肤的 `idle_mode` 互相独立、绝不串号，且重启 EX 自动还原。
- **排查与解法**（固化于 [add_l2d_idle_switch.py](../scripts/add_l2d_idle_switch.py) 与 [verify_batch_live2d.py](../core_pipeline/verify_batch_live2d.py)）：
  - **`Idle` 组条件互斥表**：为全部候选待机（`standby*` + 全部 `*_loop`）各生成 1 条带 `VarFloats: [{"Name": "idle_mode", "Type": 1, "Code": "equal <k>"}]` 的 `Idle` 记录（其中 `k = 0` 固定对应默认 `standby1`，未初始化自然命中）；另为 `standby*` 生成共享 `k = 99` 的多条记录，选中 `99` 时即启用原版多待机 🔀 随机轮播；
  - **菜单即点即切与永久记忆**：在 `Tap` 与 `语音菜单` 顶层注入「🔄 切换待机动作」（`Menu_IdleSwitch_p*` 分页子菜单），末端触发项 `IdleSet_<k>` 直接把 `File` 指向目标 `.motion3.json`（`FadeIn: 500, FadeOut: 0`）并挂载 `VarFloats: [{"Name": "idle_mode", "Type": 2, "Code": "assign <k>"}]` 与三语切换提示气泡，点选后立即平滑过渡且写盘永久锁定；
  - **变身主形态 `Command` 继承红线**：10 套变身皮肤的常驻变身主形态（如 `梦咲音月` `model_red` 依赖 `Idle` `Command: "replace_tex ..."` 维持黑化红发贴图）在展开多条 `Idle` 时，**每条 `Idle` 都必须完整继承原 `Idle[0]` 的 `Command`**，否则切换待机后变身贴图会回退；
  - **全库落地与验证**：已覆盖 **`181 / 182` 套 Live2D（`191` 组三语主形态 / `573` 份 `.model3.json`，每套 `10 ~ 24` 项，共 `2,911` 条 `Idle` 记录；仅跳过纯剧情无待机包 `露比·罗斯/原皮_艾妮斯剧情`）**，并更新 `verify_batch_live2d.py` 强制断言所有多 `Idle` 均带合法 `idle_mode` `Type: 1` 条件且必含 `equal 0` 默认入口（全库 `182/182` 通过）。

---

### 46. Spine 非婚皮无效「誓约模式」残留与主骨架内置背景/家具物件（`slot_opacities`）隐藏机制
- **问题场景**：
  1. **非婚皮冗余誓约菜单**：全库 `110` 套换装 Spine 中仅 **`26` 套真实婚皮**拥有 `*_marry` 骨骼动画，其余 **`84` 套非婚皮**（`252` 份三语配置）历史上误生成了空的 `誓约模式全动作` 分组及 `VK_M (77)` 快捷键，在 EX 动作菜单中显示无用入口；
  2. **人物主骨架自带背景/家具/悬浮摆件**：部分换装 Spine（如 `阿卡赛特/黏人心机` 左侧像素小人/扫地机黑猫/猫耳平板、`迦瓦娜/辉芒之子` 身后王座、`爱莉莎/幻想时刻` 4 张拍立得相框、`欧若拉/童话心绘` 3 只悬浮精灵、`薇姬娜/午夜蔷薇` 全屏荆棘藤蔓、`越一弥心/邂逅风纪` 护栏书包流浪猫等）将椅子、桌台、床榻、树干、灯笼、镜中倒影或独立悬浮道具直接做进了**人物主骨架**而非 Submodel，仅靠 `remove_submodel` 隐藏背景子模型后这些背景物件仍会残留在桌面上。
- **引擎底层实证**（反编译 `lw_Data\Managed\Assembly-CSharp.dll` `HLGNFAFIPOA::HJGODPFLFKM` → `JIMEAEABCLK` → `SpineModelBase::LockOrSetComponent` / `BeforeMeshUpdate`）：
  1. **`slot_opacities lock <csv> 0 0` 强力逐帧隐藏**：将目标槽位加入 `CFNDMDIHPEJ` 锁定表（`PNNJMBCGJHB=true, IMDANAKJHOO=true`）；每帧在 `AnimationState.Apply` 之后、`Mesh` 构建之前的 `BeforeMeshUpdate()` 中强制覆写 `slot.A = 0f`——**即使该槽位在动画中带有 `ColorTimeline`（透明度关键帧）也绝不会闪烁回显**；
  2. **严禁仅用 `slot_opacities unlock` 恢复！必须使用 `slot_opacities set <csv> 1 0`**：实证发现 `unlock` 仅移除锁定标志，对无 `ColorTimeline` 的静态槽位而言 `slot.A` 会永远滞留在 `0f` 变不回来；而 `slot_opacities set <csv> 1 0` 会先将 `slot.A` 置为 `1f`，并在第 1 帧由 `PKLJIHAICPA()` 自动返回 `true` 立即移出锁定表——**静态槽位稳定恢复 `1.0f`，带 `ColorTimeline` 的动态槽位无缝恢复原动画透明度曲线**；
  3. **多语言 LPK 原生透传**：`背景开关` 动作组在中/英/日三语中完全一致，打包时自动保持无语言标签通用条目，在散装目录与 `.lpk` 包内行为 100% 一致。
- **排查与解法**（固化于 [clean_spine_non_oath_menus.py](../scripts/clean_spine_non_oath_menus.py)、[add_spine_bg_toggle.py](../scripts/add_spine_bg_toggle.py)、[batch_spine_builder.py](../core_pipeline/batch_spine_builder.py) 与 [verify_batch_spine.py](../core_pipeline/verify_batch_spine.py)）：
  - **非婚皮清理**：清理全部 **`84` 套非婚皮（`252` 份配置）** 的 `誓约模式全动作` 与 `VK_M (77)`，完整保留 `26` 套真实婚皮，并在 `batch_spine_builder.py` 与 `verify_batch_spine.py` 固化防回流断言；
  - **全库 `110` 套换装主骨架双面板视觉实渲染普查与分级边界**：编写 C# `Spine3_8` 双面板离屏对比渲染器（左图仅绘待隐藏槽位防误伤头发/肢体，右图模拟 `slot.A=0` 核验无身体截断，并遍历 `idle`/`chat`/`greet`/`touch*` 全动画检查隐藏槽位可见性），严格执行**「仅额外隐藏椅子/桌台/床榻/护栏/景物/独立摆件等背景类元素；完整保留钢琴（`安德莉亚/键上舞影`）、脚镣（`菲洛多希/笼中神明`）、旋转木马、狮子、海豚、泳圈、狙击枪、油纸伞、武士刀、怀抱小怪、礼服丝带等人物服装与直接互动道具；剔除隐藏后会导致身体裁切的云朵/水洼」**准则，最终精准落地 **`38` 套换装皮肤**（具体槽位映射固化于 [add_spine_bg_toggle.py](../scripts/add_spine_bg_toggle.py) `EXTRA_HIDE_PROP_SLOTS`）；
  - **三选一菜单无损体验**：这 `38` 套皮肤按 `F3`/`H` 弹出三选一菜单——「隐藏背景（保留人物附带物件）」(`hide_bg` 附带 `slot_opacities set ... 1 0`)、「隐藏背景及附带物件（仅留人物）」(`hide_bg_and_props` 附带 `slot_opacities lock ... 0 0`)、「恢复完整背景」(`show_bg` 与 `reload_bg` 均附带 `slot_opacities set ... 1 0`)；并在 `verify_batch_spine.py` 中新增规则逐条核验 `slot_opacities` 引用的每一个槽位名均真实存在于对应 Spine 骨架中。

---

## 四、批量构建与增量交付标准验收检查表（Checklist）

> [!IMPORTANT]
> **增量定向验收铁律（严禁重复冗余全量验收）**：
> - 新增、补建或局部修改单套/少量 Live2D 或 Spine 模型后，**必须仅对本次经过修改的模型执行定向验收**，**严禁**重复扫描未改动的全库 `182` 套 Live2D / `175` 套 Spine：
>   - **定向 Spine 验收**：`python -u E:\A灵魂潮汐\tools\verify_batch_spine.py --only "角色/皮肤"`（支持英文逗号分隔多个，如 `--only "梦咲音月/此情无垢,阿卡赛特/黑鲨信号"`；定向模式下自动跳过覆写全库报告）；
>   - **定向 Live2D 验收**：`python -u E:\A灵魂潮汐\tools\verify_batch_live2d.py --only "角色/皮肤"`（支持英文逗号分隔多个）；
>   - **定向视觉预览**：`render_spine_touch_previews.py --only "角色/皮肤" --no-manifest` 与 `render_spine_composite_previews.py --only "角色/皮肤" --with-hits --emit-meta`；
>   - **定向 EX DLL 实机反序列化校验**：仅遍历本次改动模型目录的 `*.config.json` / `*.model3.json`。
> - 无 `--only` 的全量扫描命令**仅在全库批量重构或跨舰队统一迁移脚本运行后**执行一次，日常单套/小批改动一律禁止全量重跑！

每次新增或修改模型交付前，对**本次改动范围内的模型**逐项核对以下条款：
1. [ ] `soultide.db` 字节数（`83,886,080`）与 `mtime` 未被任何脚本改动；
2. [ ] Live2D 默认 `Idle` 锚定 `standby1`（`FadeIn: 0`），开启全量待机切换菜单的皮肤（`181/182` 套 / `191` 组主形态）每条 `Idle` 均携带 `VarFloats["idle_mode"]`（`Type: 1 equal <k>`）条件互斥且必含 `equal 0` 默认项（变身主形态完整继承原 `Command`）；`EyeBlink / AutoBreath / ExtraMotion` 均为 `false`；带变身角色根目录均含三语常驻主形态配置及 `Form_Switch_Main` 菜单入口；
3. [ ] Live2D `Tap` / 菜单页 / `誓约戒指切换` 全部指向零曲线 `menu_silent.motion3.json` 且 `FadeIn/FadeOut == 0`；`KeyTrigger` 全部为标准 Windows `VK_*` 且每项均绑定有效 `DownMtn`（`49/77/86 -> 语音菜单`，誓约戒指皮肤 `82 -> 誓约戒指切换` 且含 `MotionDuration >= 50` + `PostCommand: "next_exp"`）；
4. [ ] Live2D 全量 `182/182` 套 `HitAreas` 均绑定 `.moc3` 原厂 `DREFTouchBox*`/`HitArea*`（`audit_live2d_touch.py` `Flagged: 0`，无隐藏 `Body2` 或 `Body` Part ID），非原皮不混入原皮基线语音，`1401..1404` 归入 `TouchSpecial`，`100%` `.ogg`（`OggS` 头，严禁 `.opus`，且 `0` 残留 `.wav`）均可点播；
5. [ ] 全量 **`182` 套 Live2D** 均含方案 A 三语配置 `.model3.json` / `model_en.model3.json` / `model_ja.model3.json`；全量 **`175` 套 Spine（`54` 原皮 + `11` 纯战斗补齐皮肤 + `110` 换装时装、`0` `原皮(立绘)`）** 均含 `.config.json` / `config_en.config.json` / `config_ja.config.json`，三语无未解析 `{$br}` / `I18N` 标记且条目长度/命令完全对齐；
6. [ ] Spine `54` 套 `原皮` 及 `11` 套纯战斗皮肤触摸动作组均严格为 `"file": ""` 纯语音触发（`start` 组为 `"file": "idle"`，纯战斗皮肤另附 `战斗与动作` 独立分组）；全部 `175` 套 `hit_areas` 经 `_touch_audit_previews/` 真实蒙皮预览图核验校准，未误绑隐藏/阴影/背景/道具骨；
7. [ ] Spine v2 换装场景（`110` 套，含补建 `梦咲音月/此情无垢`）严格基于 **`art_prefabs.ab` + `SoulAction` 动态挂载**解析（严禁回退 `ui.ab` 快照），遵循 `SortedComponentOrder.Order` 优先、提取全部活跃 `SpriteRenderer`（实体内按 `-wz` 分流）、正确渲染 `Image.Type.Sliced` 9 宫格，按全局 DFS `draw_key` 合入 `scene_back*`/`scene_front*` 复合单骨架（`real_issues=0`、`order_violations=0`、`nested_clips=0`、`unmatched_start_mtn=0`、全部 `start_mtn` 带 `main:` 前缀），且主模型与全部 Submodel 坐标归 `(0.0, 0.0)`、`off-canvas == 0`、单皮肤子模型严守 `<= 6`（实测恒 `<= 5`）；
8. [ ] 全部原生骨骼粒子均包含正确 `fx_root` 居中偏移骨骼（`fx_missing_fx_root == 0`），且手工居中皮肤（如 `和铃/古锦新韵`）各子模型与主骨架偏移保持一致；
9. [ ] 全部 `175` 套 Spine 均已对齐 [fix_all_key_triggers.py](../scripts/fix_all_key_triggers.py)、[clean_spine_non_oath_menus.py](../scripts/clean_spine_non_oath_menus.py) 与 [add_spine_bg_toggle.py](../scripts/add_spine_bg_toggle.py) 标准（v2 全纯触摸架构：`A_orig_or_battle_skip=65, B_pure_bg=42, C_pure_touch=68, D_shared_touch_only=0`）：`84` 套非婚皮已清除无用 `誓约模式全动作` 与 `VK_M (77)`（仅 `26` 套真婚皮保留）；`key_trigger` 全量使用标准 Windows `VK_*`（`A..G=65..71, H=72, M=77, N=78, R=82, F3=114`）；`背景菜单` 选项精确指向 `背景开关:hide_bg` / `背景开关:show_bg`（含 `38` 套主骨架自带背景/家具/独立悬浮摆件的换装皮肤额外提供 `背景开关:hide_bg_and_props` 三选一菜单，其 `slot_opacities lock <csv> 0 0` / `set <csv> 1 0` 所列全部槽位均经 `verify_batch_spine.py` 逐槽校验存在）；`reload_bg` 严守先 `remove_submodel` 后 `add_submodel` 且 `0` 过期引用；
10. [ ] 所有 `.webp` 纹理必须以 `lossless=True, exact=True` 编码并通过 `max_diff == 0` 与 EX `libwebp.dll` 解码验证（`stray_pngs == 0`，透明区 `alpha == 0` 无异常 RGB），且手写/生成的 Spine 3.8 JSON 含 `skeleton.hash` 且末帧无 `curve` 字段；
11. [ ] 创意工坊 **`55` 份独立多语言 `.lpk` + `1` 份全角色多语言总集 `.lpk`（共 `56` 包）** 均通过 [verify_workshop_lpks.py](../scripts/verify_workshop_lpks.py)（`56/56` 通过，含四语言 `{"", "zhs", "zht", "ja"}` 严格对等与多 `Idle` `VarFloats` 校验），共享 `audio/` 经内容 SHA-256 防撞名、封面图 `< 1 MB`、`bgm/*.ogg` 保持原立体声，且超 2 GiB 总集包经 EX 原生 `Assembly-CSharp.dll` + `ICSharpCode.SharpZipLib.dll` 实测 Zip64 **`55` 角色 / `357` 服装 `0` 错误**全量可读；
12. [ ] **仅对本次改动模型执行定向验收**：使用 [verify_batch_spine.py](../core_pipeline/verify_batch_spine.py) `--only <角色>/<皮肤>` 或 [verify_batch_live2d.py](../core_pipeline/verify_batch_live2d.py) `--only <角色>/<皮肤>` 验证 `failed_count == 0`（严禁对未改动模型重复全量扫盘；全量无 `--only` 验收仅限全库批量重建后执行一次）；
13. [ ] Spine PMA 图集（主图与 `bj_*`/`bg_*` 骨骼子模型）已完成 V4.4 ETC2 边缘净化（`A=0 & RGB>0 == 0`、`RGB > A == 0`，彻底清剿肘/肩/指关节 4×4 灰紫虚线与暗锚黑洞，且未误处理 Straight Alpha 静态层、1px 连续深色描边、1px 彩色镶边与水彩薄纱）；
14. [ ] Spine v2 GPU 粒子与隐藏动画专项验收通过：原版 `Clamp` 贴图已还原无边缘色条、`Custom1XYZW` 已绑定；待机 GPU 通道零交叉淡化无缝审计达成 `blank_channels == 0`、`seam/step` 中位数 `≈ 1.0x`（`0.99x`）、`P95 <= 1.5x`（`1.42x`）；4 套隐藏背景动画（`2502_Alisa_S3`、`1802_SakuyaMako_S3`、`604_Asuna_S9`、`1102_NicoletteLamel_S3` 无限帧率路灯）与 4 套 `BoneFollower`（`1503_Dreizehn_S4`、`2201_Andrea_S2`、`2901_EtsukazuMiko_S2`、`3001_TsukinoMiyo_S2`）均经 `SPINE_ANIM_TIME` 多时间点离线渲染核验零重影、零偏心、无临时目录残留（`leftover_temp_dirs == 0`）；
