# 全量脚本核心原理、工作流程与注意事项详解

本文档系统拆解本仓库 **`core_pipeline/`（29 个）**、**`scripts/`（25 个）**、**`unity_fx_recorder/`（4 个代码/Shader）** 以及 **`research_archive/`（5 大专题 / 199 个归档脚本）** 的底层实现原理、标准执行顺序与工程注意事项。

> [!IMPORTANT]
> **全链路通用红线（运行任意脚本前必读）**
> 1. **原始资产与数据库只读**：本工具链仅只读解析本地游戏 AssetBundle、反编译 Lua 配置与本地数据库，严禁向源数据写入或修改原包。
> 2. **执行顺序不可颠倒**：标准构建顺序为 **阶段 1 基础构建 → 阶段 2 语音/热区/布局校准 → 阶段 3 Unity 粒子导出录制与 v2 复合场景组装 → 阶段 4 隐藏动画/变身/待机菜单/背景开关/热键后处理 → 阶段 5 ETC2 净化与无损 WebP 压缩 → 阶段 6 多语言 `.lpk` 打包与校验**。
> 3. **Spine PMA 纹理红线**：凡涉及 Spine Premultiplied Alpha 贴图保存为 `.webp`，**必须强制 `lossless=True, exact=True`**；默认 `exact=False` 会改写 `alpha==0` 区域 RGB 并在 PMA 渲染下爆出红粉块与灰条纹。
> 4. **增量定向验收**：局部改动单个或少量皮肤后，优先使用 `--only "角色/皮肤"` 执行秒级定向验收，避免无意义的全库扫盘。
> 5. **本地路径适配**：部分脚本顶部包含默认本地数据路径常量，在新环境运行前需按自身目录结构统一调整 [`core_pipeline/soultide_common.py`](../core_pipeline/soultide_common.py) 与对应脚本顶部常量。

---

## 快速导航（按执行阶段）

- [阶段 0：公共底层库与通用引擎组件](#阶段-0公共底层库与通用引擎组件)
- [阶段 1：Live2D 与 Spine 基础包构建](#阶段-1live2d-与-spine-基础包构建)
- [阶段 2：视觉预览、触控热区校准、语音路由与布局审计](#阶段-2视觉预览触控热区校准语音路由与布局审计)
- [阶段 3：Unity 粒子导出/录制与 v2 统一复合单骨架组装](#阶段-3unity-粒子导出录制与-v2-统一复合单骨架组装)
- [阶段 4：隐藏背景动画、Live2D 变身/待机菜单、背景开关与热键修复](#阶段-4隐藏背景动画live2d-变身待机菜单背景开关与热键修复)
- [阶段 5：Spine ETC2 边缘净化与全库无损存储优化](#阶段-5spine-etc2-边缘净化与全库无损存储优化)
- [阶段 6：原生多语言 `.lpk` 角色合集打包与自动化验收](#阶段-6原生多语言-lpk-角色合集打包与自动化验收)
- [阶段 7：研发与逆向归档专题（`research_archive/01~05`）](#阶段-7研发与逆向归档专题research_archive0105)

---

## 阶段 0：公共底层库与通用引擎组件

### 0.1 [`core_pipeline/soultide_common.py`](../core_pipeline/soultide_common.py)
- **定位**：全仓库底层公共基础设施库（被大多数构建与校准脚本导入）。
- **核心原理**：
  - 封装 `UnityPy.load`（`load_ab`）、统一 UTF-8 JSON 写出（`write_json`）、FSB/AudioClip 转标准 PCM WAV 字节流（`extract_wav_bytes`），以及基于正则/状态机的轻量 Lua 扁平配置表解析器（`parse_lua_flat_table` / `LuaTableRepo`）。
  - 自动清洗游戏内嵌富文本标记（如 `{$br}` 换行符、颜色标签、I18N 引用键），使台词可直接被 Live2DViewerEX 气泡渲染。
- **工作流程**：提供纯函数与只读表仓库，供下游脚本按需按表名延迟加载（`CfgSoulTable`、`CfgDressTable`、`CfgSoulActionTable` 等）。
- **注意事项**：
  - 跨环境迁移时**最先检查本文件顶部的资源根目录常量**。
  - 严禁在多线程中并发共享同一个未经加锁的 `UnityPy` 环境对象（见下文 `batch_fx_exporter.py` 的锁机制）。

### 0.2 [`core_pipeline/spine38_binary_to_json.py`](../core_pipeline/spine38_binary_to_json.py)
- **定位**：Spine `3.8.79` 二进制 `.skel` 无损解码器与多骨架复合合并核心库（被 `rebuild_all_scenes_and_fx_v2.py`、`patch_hidden_bg_anims_and_bone_fx.py`、`clean_spine_non_oath_menus.py` 等依赖）。
- **核心原理**：
  - 完整实现 Spine 3.8.79 官方 `SkeletonBinary` 二进制协议解析（`_BinReader`）：包含变长整数 `varint`、字符串表、骨骼继承模式（`TransformMode`）、约束（IK / Transform / Path）、槽位与混合模式、`Region`/`Mesh`/`LinkedMesh`/`BoundingBox`/`Path`/`Point`/`Clipping` 附件顶点权重、以及全类型动画曲线（`stepped` / 贝塞尔 4 浮点控制点）。
  - **零重编码合并（`merge_spine38_into_composite`）**：将多个二进制 `bj_*` 子骨架的骨骼、槽位、皮肤与动画加上唯一命名空间前缀（`prefix_atlas_text` 同步改写 `.atlas.txt` 区域名），直接按精确 `draw_key` 插入复合骨架的 `slots` 描画列表，**完全复用原版无损 PMA `.webp` 贴图页与原始 UV 坐标，零像素损失**。
  - 通过 `_tile_keyframes` 将较短子骨架的循环动画自动平铺对齐至复合骨架总周期，避免多子模型周期不同步导致画面静止。
- **工作流程**：
  1. `spine38_binary_to_json(bytes)` 解析原始二进制骨架并保留 `skeleton.hash`；
  2. 计算子骨架坐标变换矩阵并挂载到复合骨架的对齐锚点骨；
  3. 同步合并动画关键帧与 `prefix_atlas_text`，输出可被 Live2DViewerEX 原生加载的 `.skel.json` + 合并 `.atlas.txt`。
- **注意事项**：
  - **末帧不可含 `curve` 字段**：Spine 3.8 运行时读取关键帧数组末尾元素时若残留 `curve` 会触发解析异常，解码器已内置剥离逻辑，手工编辑 JSON 时亦需遵守。
  - **严禁嵌套 `ClippingAttachment`**：同一复合骨架内若前一个裁切槽位未 `end` 就开启第二个裁切槽位，会导致 Live2DViewerEX 渲染黑屏；上游调用方（`rebuild_all_scenes_and_fx_v2.py`）须检测并自动拆槽隔离。

### 0.3 [`core_pipeline/spine_fx_submodel_packer.py`](../core_pipeline/spine_fx_submodel_packer.py)
- **定位**：通用透明帧序列 PNG → Spine 3.8 Submodel 打包引擎。
- **核心原理**：
  - 接收一组 `AnimSequenceSpec`（每段动画可同时包含 `normal` 常规混合层与 `add` 加法混合层帧目录）。
  - 对每一帧执行 **Tight-Bounds 紧裁切**（`_tight_crop_frame`，自动裁除四周纯透明留白并记录相对画布中心偏移）与 **RGBA SHA-256 逐帧去重**（`_sha256_rgba`），静止帧/空帧零重复占图。
  - 使用 **Skyline 二维装箱算法**（`_pack_skyline`）将去重裁切块紧密排入 `<= 4096×4096` 图集，写入 `lossless=True, exact=True` `.webp`（`_save_exact_webp`），生成单槽位逐帧 `attachment` 切换时间轴的 Spine 3.8 `.skel.json`、`.atlas.txt` 及 `.config.json`。
- **工作流程**：加载帧列表 → 并行紧裁切与哈希去重 → Skyline 装箱生成图集 → 写出 `.webp` + `.atlas.txt` + `.skel.json` + `.config.json`。
- **注意事项**：
  - **EX Submodel `scale_factor` 独立**：`pack_fx_submodel` 必须显式传入与主模型一致的 `scale_factor`，切勿保持默认 `1.0`（否则 EX 中粒子会相对人物放大近 9~10 倍）。
  - 为 `add` 通道自动写入 `"blend": "additive"` 槽位属性，搭配 EX 默认 PMA 着色器时输入 PNG 必须是严格黑底无预乘过曝的纯净 Additive 帧。

---

## 阶段 1：Live2D 与 Spine 基础包构建

### 1.1 [`core_pipeline/batch_live2d_builder.py`](../core_pipeline/batch_live2d_builder.py)
- **状态**：主力构建器（Live2D 全库 182 套）。
- **CLI 参数**：`--char <子串>`、`--model <模型名>`、`--skip-existing`、`--dry-run`。
- **核心原理**：
  - 扫描全部 Live2D AssetBundle（`scan_live2d_bundles`），关联 Lua 配置表（`CfgSoulTable` / `CfgDressTable` / `CfgSoulActionTable` / `CfgSoulActionGroupTable`），为每个角色皮肤分配唯一输出目录。
  - **严格皮肤语音隔离**：区分原皮与换装语音池，避免 `MoodActionID` 与通用基线语音串入专属换装触摸组；将 `1401..1404` 归入 `TouchSpecial`。
  - **防干扰控制器与静默菜单**：关闭会覆盖原版烘焙动画的 `EyeBlink`、`AutoBreath`、`ExtraMotion`，保留 `MouseTracking` 与 `LipSync`；生成零曲线 `menu_silent.motion3.json` 供 `Tap` 与分级语音菜单使用，杜绝打开/翻页菜单时人物抽搐打断动作。
  - **实证 `.moc3` 热区**：优先绑定原厂 `DREFTouchBox*` / `HitArea*` ArtMesh，避免将不可点击的 Cubism Part ID 误写入 `HitAreas`。
- **工作流程**：索引备份定位参数 → 加载 Lua 元数据表 → 扫描 Live2D AB → 逐套提取 `.moc3`/贴图/物理/表情/动作/语音 → 组装 `.model3.json`（后续由 `build_i18n_and_ogg_fleet.py` 扩展三语并转 `.ogg`）。
- **注意事项**：
  - 全量跑完后还需衔接 `build_i18n_and_ogg_fleet.py`、`apply_l2d_model_switch.py`、`set_l2d_idle_standby1.py`、`add_l2d_idle_switch.py` 与 `fix_all_key_triggers.py` 才能获得最终全功能成品。

### 1.2 [`core_pipeline/batch_spine_builder.py`](../core_pipeline/batch_spine_builder.py)
- **状态**：主力构建器（换装 Spine 基础包 + 底层场景/二进制工具库）。
- **CLI 参数**：`--char`、`--ctrl`、`--limit`、`--resume`、`--workers`。
- **核心原理**：
  - 解析全部换装 Spine 控制项，提取主角色 Spine 3.8 二进制骨架与图集、全部官方配音与 BGM，同时提供一套可复用的底层工具函数：
    - `parse_spine38_binary` / `eval_bone_world_positions`：解析骨骼层级与世界包围盒，用于热区初算与居中校准；
    - `strip_embedded_bg_slots_binary` / `shift_binary_root_xy` / `patch_binary_root_transform`：无损修补二进制骨架根骨骼平移、缩放与旋转；
    - `_render_nine_slice`：忠实还原 Unity UGUI `Image.m_Type == 1 (Sliced)` 九宫格拉伸（按 `Sprite.m_Border` 保护四角与边框不畸变）；
    - `_extract_unity_scene_layers` & `_build_scene_submodels_exact`：早期 v1 场景分层提取与静态/动态子模型构建（v2 阶段已被 `rebuild_all_scenes_and_fx_v2.py` 继承升级）。
- **工作流程**：按角色/皮肤解包主 Spine 与音频 → 渲染背景静态层与 `bj_*` 子 Spine → 挂载 FX Submodel → 写出基础 `.config.json` 与触摸动作映射。
- **注意事项**：
  - 早期 `batch_spine_builder.py` 的单层静态背景与多子模型拼接在复杂皮肤上可能触发 EX `<= 6` 子模型上限；**现行标准管线会在本脚本建出主骨架与语音后，交由阶段 3 的 `rebuild_all_scenes_and_fx_v2.py` 统一接管场景与 FX 重建**。

### 1.3 [`core_pipeline/batch_orig_spine_builder.py`](../core_pipeline/batch_orig_spine_builder.py)
- **状态**：主力构建器（54 套原皮 BattleHead Spine）。
- **CLI 参数**：`--char <子串>`。
- **核心原理**：从战斗头像/半身 Spine 资产（`BattleHead`）提取全部 54 位角色的原皮 Spine，直接复用对应角色已校验通过的 Live2D `原皮` 语音、字幕与触摸组结构；**全部触摸动作组强制设为 `"file": ""` 纯语音触发**，避免摸后强切动作导致原皮循环待机卡顿跳帧。
- **工作流程**：索引 `BattleHead` 资源 → 匹配 Live2D 原皮语音与台词 → 选定 `idle`/`greet` 动画 → 写出 `spine/<角色>/原皮/` 包。
- **注意事项**：依赖对应角色的 Live2D `原皮` 包已预先构建完成；运行后需配合 `fix_all_touch_triggers.py`、`build_i18n_and_ogg_fleet.py` 及原皮背景挂载脚本。

### 1.4 [`scripts/build_missing_battle_spines.py`](../scripts/build_missing_battle_spines.py)
- **状态**：主力补齐脚本（11 套无换装 `dressspine` 的纯战斗皮肤）。
- **CLI 参数**：`--only "<角色>/<皮肤>"`、`--force`。
- **核心原理**：针对游戏内无全屏 `dressspine`、仅有 `23_spine/battle/character/` 战斗骨骼的 11 套早期皮肤（如星见亚砂夏樱 S2~S5、阿卡赛特黑鲨信号等），自动提取战斗 Spine，直接串联调用 `spine_etc2_clean_v3` 执行 V4.4 ETC2 净化并转为无损 `exact=True` `.webp`，复用同皮肤三语 Live2D `.ogg` 语音与台词，额外注入 `战斗与动作` 独立展示分组，并内置经 `Spine3_8` 世界包围盒逐套视觉复核的精确手部/身体 `hit_areas`。
- **工作流程**：筛选目标皮肤 → 解包战斗骨架与图集 → V4.4 净化并转 WebP → 关联三语 Live2D 语音 → 写入方案 A 三语配置。
- **注意事项**：默认跳过已存在目录，覆盖重跑须显式加 `--force`；不会触碰任何已有原皮或换装皮肤。

### 1.5 [`scripts/build_netsuki_s3_spine.py`](../scripts/build_netsuki_s3_spine.py)
- **状态**：主力专项全功能 v2 补建脚本（第 110 套换装 `梦咲音月/此情无垢`）。
- **CLI 参数**：`--front-only`（仅快速重建前景 `scene_front`）。
- **核心原理**：
  - 针对官方后续版本追加的 `802_Netsuki_S3`，完整串联 `art_prefabs.ab` 场景解析、v2 复合组装、原生 60 FPS 粒子、零交叉淡化 GPU 频段、V4.4 ETC2 净化、13 句官配 `.ogg` 真实时长 `text_duration` 对齐及视觉校准 `CALIBRATED_HIT_AREAS`。
  - **亮点创新（`_inject_native_shu_branches`）**：原版前景桃枝使用 `FX_qqc/raodong_alphablended` UV 扰动 Shader，在低帧率录制或高振幅下易抽搐撕裂且贴图达 `8.52 MB`；本脚本将 4 支桃枝重构为 **原生 Spine 3.8 双骨软体权重网格（Skinned Mesh）无限帧率微风摆动动画**，彻底消除鬼畜抽搐并将 `scene_front` 贴图降至 `1.09 MB`。
- **工作流程**：解包 `_batch16.ab` 主/背景骨架 → 净化转 WebP → 组装 `scene_back` / `bj_01` / `scene_front`（含原生桃枝） / `fx_802_netsuki_s3_touch` → 写入三语配置与背景开关。
- **注意事项**：修改桃枝曲线或前景粒子时使用 `--front-only` 即可秒级重编前景，无需重跑音频与主图集。

### 1.6 [`core_pipeline/build_i18n_and_ogg_fleet.py`](../core_pipeline/build_i18n_and_ogg_fleet.py)
- **状态**：主力三语配置与音频转码脚本。
- **CLI 参数**：`--workers <N>`、`--batch-size <N>`、`--skip-ogg`（仅重生三语 JSON）。
- **核心原理**：
  - **低内存流式 I18N 提取**：逐个分片流式提取所需约 10,500 条中/英/日文本 ID（常驻内存 `< 150 MB`），避免一次性载入全部多语言分片导致内存飙升。
  - **去重批量 WAV → OGG**：将全库约 29,275 份重复 `.wav` 按内容去重后，调用多进程 FFmpeg `libvorbis` 批量转为高质量 `.ogg`（验证 `OggS` 魔数头），彻底规避 `libsndfile` 处理 Vorbis 时的崩溃问题。
  - 同步生成方案 A 三语配置（Live2D：`.model3.json` / `model_en.model3.json` / `model_ja.model3.json`；Spine：`.config.json` / `config_en.config.json` / `config_ja.config.json`）。
- **工作流程**：流式构建三语映射表 → 去重并转码全部 `.wav` 为 `.ogg`（若未设 `--skip-ogg`）→ 同步生成并回写全库三语配置文件。
- **注意事项**：
  - **严禁转码为 `.opus`**：Live2DViewerEX 未捆绑 `bassopus.dll`，`.opus` 会导致客户端完全无声，必须使用标准 Vorbis `.ogg`。
  - 仅修改台词翻译或菜单文案时，直接传入 `--skip-ogg` 可在数秒内完成全库更新。

### 1.7 [`core_pipeline/aurora_s4_live2d_builder.py`](../core_pipeline/aurora_s4_live2d_builder.py)、[`aurora_s4_spine_builder.py`](../core_pipeline/aurora_s4_spine_builder.py) 与 [`verify_aurora_s4_packages.py`](../core_pipeline/verify_aurora_s4_packages.py)
- **状态**：早期单皮肤试点参考实现（`欧若拉/童话心绘`）。
- **核心原理与流程**：作为全库批量化之前的首个端到端样板工程，完整验证了 `ui_to_spine_rect` 坐标换算、Submodel `scale_factor` 对齐、Live2D 控制器禁用与语音分组协议；后续批量引擎（`batch_live2d_builder.py`、`batch_spine_builder.py`、`verify_batch_*`）均以此架构泛化而来。
- **注意事项**：日常全库维护请使用 `batch_*` 与 `rebuild_all_scenes_and_fx_v2.py`；此 3 个脚本适合作为阅读最小可运行单皮肤流程的教学入口。

---

## 阶段 2：视觉预览、触控热区校准、语音路由与布局审计

### 2.1 Live2D 触控盒审计、渲染与修复（[`audit_live2d_touch.py`](../core_pipeline/audit_live2d_touch.py)、[`render_live2d_touch_previews.py`](../core_pipeline/render_live2d_touch_previews.py)、[`fix_live2d_touch_audit.py`](../core_pipeline/fix_live2d_touch_audit.py)）
- **核心原理**：
  - 直接通过 `ctypes` 调用 Live2D 官方原生 `Live2DCubismCore.dll`（`csmGetDrawableIds`、`csmGetDrawableVertexPositions`、`csmGetDrawableRenderOrders`），在模型真实画布坐标系下提取每个 ArtMesh Drawable 的精准顶点包围盒与渲染层级。
  - 检测并纠偏 3 类常见缺陷：误绑不可点击的 `Body` Part ID、隐藏 `Body2` 网格遮蔽真实热区、遗漏非标准命名的 `HitArea*` 网格。
- **工作流程**：`audit_live2d_touch.py` 全库扫描标出异常 → `render_live2d_touch_previews.py --all-flagged` 输出带彩色热区框与网格标签的纹理叠加预览图 → 视觉确认后由 `fix_live2d_touch_audit.py` / `fix_all_touch_triggers.py` 落盘修复。
- **注意事项**：依赖本机可访问的 64 位 `Live2DCubismCore.dll`（Live2DViewerEX 安装目录内自带）。

### 2.2 Spine 离屏合成与热区渲染引擎（[`render_spine_composite_previews.py`](../core_pipeline/render_spine_composite_previews.py) + [`_spine38_composite_renderer.cs`](../core_pipeline/_spine38_composite_renderer.cs)；[`render_spine_touch_previews.py`](../core_pipeline/render_spine_touch_previews.py) + [`_spine38_preview_renderer.cs`](../core_pipeline/_spine38_preview_renderer.cs)）
- **核心原理**：
  - Python 包装脚本自动检测 SHA-256 并按需调用 Windows `csc.exe` 编译配套 C# 离屏光栅化器，直接链接 Live2DViewerEX 同源 `lw_Data\Managed\Assembly-CSharp.dll` 中的 `Spine3_8` 运行时。
  - 按精确 `Skeleton.DrawOrder` 渲染所有 `RegionAttachment` 与 `MeshAttachment`：
    - **合成预览器**（`render_spine_composite_previews.py`）：完整叠加负层背景（`-3/-2/-1`）、主人物（`0`）、正层前景/粒子（`+1/+2`），支持 `--with-hits` 叠加 `bg_static` 青色边界框、坐标网格与彩色热区框（超出背景自动标红 `[OUT!]`），并支持 `--emit-meta` 输出每个候选骨骼的实时世界坐标 `.meta.json`。
    - **单人偶热区预览器**（`render_spine_touch_previews.py`）：专注 `idle` 第 0 帧人物蒙皮与 `hit_areas` 核验。
- **常用 CLI 参数**：`--only "<角色>/<皮肤>"`、`--all`、`--with-hits`、`--emit-meta`、`--skip-fx`、`--tag <后缀>`、`--no-manifest`。
- **注意事项**：
  - 需本机存在 Live2DViewerEX 的 `Assembly-CSharp.dll` 与 `.NET Framework 4.x` `csc.exe`。
  - 日常抽检务必使用 `--only`，避免全库重渲耗时。

### 2.3 全库触控热区校准器（[`fix_all_touch_triggers.py`](../core_pipeline/fix_all_touch_triggers.py)）与单模型热区更新器（[`update_spine_hit_areas.py`](../core_pipeline/update_spine_hit_areas.py)、[`doll_audit_helper.py`](../core_pipeline/doll_audit_helper.py)）
- **核心原理**：
  - `fix_all_touch_triggers.py`：全库端到端校准器。Live2D 侧以 `CubismCore` 实时验证 ArtMesh；Spine 侧结合骨骼几何包围盒、人体解剖位置约束（防左右手镜像标反、防误绑裙摆/背景/漂浮发丝）与原皮纯语音规则统一求解并同步三语配置。
  - `update_spine_hit_areas.py`：单个 Spine 皮肤热区合规写入器，强制断言：**① 骨骼 ID 真实存在于骨架中且非 `root`、无重复；② 触发 `motion` 存在；③ 换装热区完整矩形严禁越出 `bg_static` 背景边界**，通过后三语同步写入并自动重渲预览图。
  - `doll_audit_helper.py`：单角色隔离式三合一工作流 CLI（`--doll <名> --prepare` 渲图 / `--update-l2d` 改 Live2D 热区 / `--verify` 跑单人偶定向验收），保证多角色校对互不越界。
- **注意事项**：修改任何热区时，**严禁手工只改中文 `.config.json`**，务必通过上述脚本保证中/英/日三语完全一致，否则打包多语言 `.lpk` 时校验器会报错。

### 2.4 全库语音路由审计与修复（[`fix_spine_voice_routing.py`](../core_pipeline/fix_spine_voice_routing.py)）
- **CLI 参数**：默认 Dry-run 仅审计；加 `--apply` 落盘写入。
- **核心原理（三信号融合判定）**：针对全库 182 Live2D + 163+ Spine 排查摸胸播牵手、摸腿播摸头、皮肤串播邻皮台词及官方表 `drees` 拼写笔误等问题：
  1. **信号 1**：反查官方 `CfgSoulActionGroupTable` 精确资源词干索引；
  2. **信号 2**：解析音频文件名身体部位后缀标记（`detect_sound_tag` / `infer_dress_suffix_part`）；
  3. **信号 3**：分析中/英/日字幕语义关键词并过滤中性台词（`detect_semantic_parts` / `is_neutral_text`）。
- **工作流程**：先无参执行 Dry-run 审查冲突清单 → 确认无误后带 `--apply` 同步修订三语配置（严格保留原皮 Spine `file == ""` 纯语音触发）。
- **注意事项**：务必先 Dry-run 再 `--apply`，避免未审先覆写手工特调语音项。

### 2.5 背景布局审计与早期布局修复（[`audit_spine_bg_layout.py`](../core_pipeline/audit_spine_bg_layout.py)、[`fix_all_spine_bg_layouts.py`](../core_pipeline/fix_all_spine_bg_layouts.py)、[`scripts/fix_spine_bg_layer_order.py`](../scripts/fix_spine_bg_layer_order.py)、[`scripts/fix_spine_layers_and_positions.py`](../scripts/fix_spine_layers_and_positions.py)、[`scripts/fix_spine_static_pma_and_scenes.py`](../scripts/fix_spine_static_pma_and_scenes.py)）
- **定位说明**：
  - `audit_spine_bg_layout.py` 为全库背景/前景布局与 Unity `RectTransform` 数学真值比对审计器（用于定位偏移、镜像、非均匀缩放与层序违例）。
  - `fix_all_spine_bg_layouts.py`（`--only` / `--all`）、`fix_spine_bg_layer_order.py`、`fix_spine_layers_and_positions.py` 及 `fix_spine_static_pma_and_scenes.py` 为 v1 阶段演进过程中的专项修复脚本（分别解决了非均匀缩放/负缩放翻转、5 套层级倒置、MeshRenderer 同 `sortingOrder` 下 `-wz` 深度倒置与静态图 Straight Alpha → PMA 转换）；**其核心算法已全部沉淀并被阶段 3 的 `rebuild_all_scenes_and_fx_v2.py` 统一取代**，保留供定向排障与回溯参考。

### 2.6 原皮 Spine 背景解包与挂载（[`scripts/unpack_orig_spine_bgs.py`](../scripts/unpack_orig_spine_bgs.py)、[`mount_orig_spine_bgs.py`](../scripts/mount_orig_spine_bgs.py)、[`fix_orig_bg_3dolls.py`](../scripts/fix_orig_bg_3dolls.py)）
- **核心原理与流程**：
  1. `unpack_orig_spine_bgs.py`：从离线包中提取全 54 位角色的原皮完整立绘（`Battle01`，优先无和谐源）及祈愿纯人物立绘，区分天然可直挂背景与人物烘焙在一起的立绘；
  2. `mount_orig_spine_bgs.py`：将 7 位零修补官方背景（含克洛托 4 层动态 `BJ_01..04` 及多套独立静态远景）直接挂载至对应原皮 Spine 并三语同步；
  3. `fix_orig_bg_3dolls.py`：视觉复核后对 3 套特例原皮（如 `克洛托/原皮` 升级完整轮椅+人偶 `Clotho_DefaultDress` 并 V4.4 净化、`越一弥心/原皮` 移除误挂横幅）做定向精修。
- **注意事项**：仅面向 `spine/<角色>/原皮/`，不会影响任何换装皮肤。

---

## 阶段 3：Unity 粒子导出/录制与 v2 统一复合单骨架组装

这是本工具链技术密度最高的核心子系统，采用 **「60 FPS 原生 Spine 骨骼粒子（71.3%）+ Unity 2021 零交叉淡化 GPU 频段（28.7%）+ 单骨架统一插层合并」** 双轨混合架构。

### 3.1 [`core_pipeline/batch_fx_exporter.py`](../core_pipeline/batch_fx_exporter.py)
- **状态**：主力粒子 Spec 提取与 Unity Batchmode 驱动器。
- **CLI 参数**：`--char`、`--skins`、`--ctrl`、`--limit`、`--resume`、`--export-only`、`--manifest-out`、`--workers`、`--unity-workers`（默认 2 路隔离 Unity 工程并发）。
- **核心原理**：
  - **低内存 `AssetIndexer` + `_LazyCabObjMap`（16 包 LRU 驱逐）**：解决全包常驻引发 `17+ GB` 内存飙升问题，将峰值内存稳定压在 `~1.35 GB`。
  - **官方运行时真值解析**：严格以 **`art_prefabs.ab` + `SoulAction` 动态挂载节点** 解析背景 `BgPrefab`（而非已过期的 `ui.ab` 编辑器快照），完整导出 Unity `ParticleSystem` 全部模块 DTO（`InitialModule` 含 `rotation3D` 与 `gravityModifier`、`Emission` 含 `rateOverTime mode=2/3`、`Shape` 含旋转、`Velocity`、`Force`、`Noise`、`Color/Size/RotationBySpeed`、`UVModule` 帧动画、`SubEmitters`、材质 Shader 参数、`tex_wrap_modes` `Clamp/Repeat` 与 `Custom1XYZW`）。
  - **自动剔除干扰项与缩放纠偏**：识别屏蔽云雾（`_is_censor_cloud`）；仅在根节点 `max(|sx|,|sy|) > 1.05` 时清除 Unity UI 父级逆缩放，完整保留 `< 1.0` 的合法缩小比例。
  - **并发安全**：多线程读取 `UnityPy` 全程加 `asset_lock`；调用多路 Unity 批录时通过 `--unity-workers` 复制物理隔离的工程副本，彻底规避 Unity 工程锁冲突。
- **工作流程**：构建皮肤清单 → 提取全部粒子 Spec + 导出材质贴图/网格/缠绕模式 → 写入 `fx_manifest.json` →（若未设 `--export-only`）启动隔离 Unity 2021.3.34f1 批录。
- **注意事项**：**调用 Unity Batchmode 时绝对禁止传入 `-nographics`**，否则无 GPU 渲染上下文会导致录屏全黑或空帧！

### 3.2 [`unity_fx_recorder/`](../unity_fx_recorder/)（Unity 2021.3.34f1 离线粒子引擎）

| 文件 | 角色与核心原理 | 关键注意事项 |
| :--- | :--- | :--- |
| [`Assets/Editor/SoulTideSpineParticleExporter.cs`](../unity_fx_recorder/Assets/Editor/SoulTideSpineParticleExporter.cs) | **原生粒子轨迹导出器**：在 Unity 真实模拟每个 `ParticleSystem`，逐帧调用 `ParticleSystem.GetParticles` 采集每个粒子的位置、旋转、缩放、颜色与生命周期，连同 UV 滚屏片参数一并导出为 JSON，供 Python 原生骨骼粒子引擎消费。 | 依赖与游戏一致的 Unity `2021.3.34f1` 版本以确保随机种子与曲线采样一致。 |
| [`Assets/Editor/SoulTideBatchFxRecorder.cs`](../unity_fx_recorder/Assets/Editor/SoulTideBatchFxRecorder.cs) | **v2 零交叉淡化 GPU 批录器**：针对含拖尾、溶解/扭曲 Shader、3D 网格旋转或 `CustomData` 的复杂节点，通过 `-fxManifest` 单进程批量重建粒子系统，按双通道（Normal RGBA32 + Additive 黑底）离线捕获 PNG。废除会产生“半程发暗重影”的交叉淡化，采用**精确整数 tick $K$-分身叠加、$C^1$ 双相流与单粒子周期对齐/常驻保活**实现无缝循环，并依据 `tex_wrap_modes` 还原 `Clamp` 贴图防边缘色条。 | `JsonUtility` 反序列化 JSON `null` 子对象会变成默认全 0 实例，脚本已用显式布尔门控与 `HasCurveData` 规避，扩展 DTO 时切勿直接判 `!= null`。 |
| [`Assets/Shaders/SoulTideParticleAdd.shader`](../unity_fx_recorder/Assets/Shaders/SoulTideParticleAdd.shader) & [`SoulTideParticleAlpha.shader`](../unity_fx_recorder/Assets/Shaders/SoulTideParticleAlpha.shader) | **双通道 PMA 兼容粒子 Shader**：原生支持主贴图/双遮罩独立 `_MainClamp` / `_MaskClamp` / `_Mask2Clamp` 环绕控制、UV 滚动、溶解与 `TEXCOORD1`（`Custom1XYZW`），确保录出的帧与 Live2DViewerEX `DefaultPMAShader` 叠加时不爆白球、无边缘拉丝。 | 不可用 Unity 内置标准 Mobile Particle Shader 替代，否则会丢失 `Clamp` 保护与 `Custom1XYZW` 通道。 |
| [`core_pipeline/SoulTideFxRecorder.cs`](../core_pipeline/SoulTideFxRecorder.cs) | 早期单皮肤交互式 Unity Editor 窗口录制器（`ShowWindow`/`OnGUI`），用于单场景手工调试验证。 | 批量生产统一使用 `SoulTideBatchFxRecorder.cs`。 |

### 3.3 [`core_pipeline/build_gpu_bands_manifest.py`](../core_pipeline/build_gpu_bands_manifest.py) 与 [`run_full_unity_v2_batch.py`](../core_pipeline/run_full_unity_v2_batch.py)
- **核心原理与工作流程**：
  1. `build_gpu_bands_manifest.py`（支持 `--skins`）：在 `SubEmitter` 树粒度拆分每个皮肤的待机粒子：凡纯原生可表达的子树彻底从 GPU 录屏队列剔除（交给 60 FPS 原生引擎），仅保留确实包含拖尾/溶解/扭曲/3D 网格/CustomData 的子树，并为其计算最优无缝整数周期（`_pick_clean_gpu_period`），输出精简后的 GPU 频段清单；
  2. `run_full_unity_v2_batch.py`：可断点续跑的批调度器，先跑 `SoulTideSpineParticleExporter` 导出全库轨迹 JSON，再跑 `SoulTideBatchFxRecorder` 录制剩余需要 GPU 通道的皮肤。
- **注意事项**：两步全部跑完并生成轨迹与 GPU 帧序列后，才进入下一步 `rebuild_all_scenes_and_fx_v2.py`。

### 3.4 [`scripts/convert_fx_to_native_spine.py`](../scripts/convert_fx_to_native_spine.py)
- **状态**：主力 60 FPS 原生 Spine 骨骼粒子引擎（同时作为库供 `rebuild_all_scenes_and_fx_v2.py` 调用）。
- **CLI 参数**：`--skins`、`--force`。
- **核心原理**：
  - 节点拦截判定（`node_blockers` / `compute_gpu_blocked_node_indices`）：自动过滤无法纯 2D 骨骼还原的节点（拖尾、自定义 Shader、3D 网格、CustomData、子发射器），其余 **562 / 788（71.3%）** 粒子全部转为真 60 FPS 骨骼关键帧。
  - **多骨环形相位中继（Multi-Bone Torus Phase-Relay，`_slice_track_torus_laps`）**：解决粒子跨越循环周期接缝时的跳变问题，无缝拼接多圈生命周期。
  - **注水式骨骼预算分配（`water_fill_budgets`）**：在多节点复杂皮肤（如 `4401_Dora_S2`）中按节点需求公平分配骨骼配额，防止单节点爆骨或其它节点坍塌。
  - 支持旋转/对角 `uv_quads`、解析生灭端点平滑淡入淡出（`_apply_smooth_fade`）、关键帧曲线抽稀（`decimate_1d/2d/rgba`）及自动注入 `fx_root` 画布中心偏移骨。
- **注意事项**：独立调用时仅重建可独立原生化的 `fx_*` 目录；**v2 全功能管线推荐直接通过 `rebuild_all_scenes_and_fx_v2.py` 自动调用其 `emit_native_fx_nodes_into_skeleton` API 合入复合骨架**。

### 3.5 [`scripts/rebuild_spine_scenes_from_art_prefabs.py`](../scripts/rebuild_spine_scenes_from_art_prefabs.py) 与 [`scripts/rebuild_all_scenes_and_fx_v2.py`](../scripts/rebuild_all_scenes_and_fx_v2.py)
- **状态**：`rebuild_all_scenes_and_fx_v2.py` 为**当前最高主力 v2 组装器**；`rebuild_spine_scenes_from_art_prefabs.py` 为其底层 `FastSceneRepos` / `art_prefabs.ab` 场景解析库（早期 v1 入口）。
- **v2 CLI 参数**：`--all`、`--skins <逗号分隔 skin_key>`、`--frame-workers <N>`（多线程 GPU 帧裁切与无损 WebP 编码）、`--skip-bg-toggle`、`--skip-v2-done`。
- **核心原理**：
  1. **严格全局全序渲染键**：对同一皮肤内全部 UGUI `Image`、9-Slice、`SpriteRenderer`（实体内按 `-wz` 深度分流）、`bj_*` 子 Spine、原生骨骼粒子与 GPU 粒子频段统一按 **`(SortedComponentOrder.Order 优先于 Canvas.m_SortingOrder, -wz, global_dfs)`** 排序，并以主人物为界精确拆分前后侧（`scene_back*` 负层与 `scene_front*` 正层）。
  2. **突破 EX 6 子模型上限**：槽位充裕时保留原生二进制 `bj_*` 减少 JSON 体积；一旦超限自动调用 `spine38_binary_to_json.py` 无损解码合并入复合骨架，同时自动检测并拆槽规避嵌套 `ClippingAttachment`（保证 `nested_clips=0`、全库单皮肤恒 `<= 5` 子模型）。
  3. **独立纯触摸子模型分离**：将 67 套触摸特效抽离为独立纯触摸子模型（含 4 套位于角色后方 `-1` 槽位的 `fx_*_touch_back`），并统一修正触发命令为 `start_mtn <id> main:<anim>` 防止漏匹配。
  4. **坐标归零对齐**：主模型与所有子模型均归一化到统一主骨架坐标系并归零居中，避免 EX 桌面缩放时背景偏移。
- **工作流程**：加载 `art_prefabs.ab` 与粒子轨迹/GPU 帧 → 计算全局 `draw_key` 分侧 → 合成静态分带 PMA 贴图 + 注入原生粒子 + 打包紧裁切 GPU 频段 + 合并超限 `bj_*` → 拆出独立纯触摸子模型 → 同步回写三语配置并调用 `add_spine_bg_toggle.py`。
- **注意事项**：
  - 每次重跑 v2 组装后，若改动涉及 `1802_SakuyaMako_S3`、`2502_Alisa_S3`、`604_Asuna_S9`、`1102_NicoletteLamel_S3` 或 4 套 `BoneFollower` 皮肤，**必须紧接着重跑 `patch_hidden_bg_anims_and_bone_fx.py`** 以恢复隐藏背景动画与骨骼跟随粒子！

---

## 阶段 4：隐藏背景动画、Live2D 变身/待机菜单、背景开关与热键修复

### 4.1 [`scripts/patch_hidden_bg_anims_and_bone_fx.py`](../scripts/patch_hidden_bg_anims_and_bone_fx.py)
- **状态**：主力 v2 后处理脚本（幂等可重跑，末尾自动同步 `add_spine_bg_toggle.py`）。
- **核心原理**：解析官方 Unity `AnimationClip` 曲线（`_read_legacy_clip` / `_eval_unity_curve`），按静态分带精准原地剥离重复静图（`_strip_static_paths_and_rerender_st00`，彻底防止移走后残留重影），并在 v2 复合骨架内无缝注入：
  - `1802_SakuyaMako_S3`：24.5s 列车进站、精准右锚滑门、站台灯及 `st_s05` 站台立柱前后拆分；
  - `2502_Alisa_S3`：6.1s 小狗头滑入弹跳淡出（`st_s03` 原地剥离防重影）；
  - `604_Asuna_S9`：54.0s 摩天轮以真实世界轴心 `(797, 371.5)` 旋转，全部 20 个车厢设 `noRotationOrReflection` 始终保持水平不倒立；
  - `1102_NicoletteLamel_S3`：将官方卡顿且存在重复/漏帧的 12 FPS 60 帧窗外路灯重制为 **`0.13 px` RMS 精度的 3D 针孔透视数学模型 + 3 路灯接力原生 Spine 骨骼无限帧率动画**（贴图从 `548.5 KB` 降至 `22.1 KB`）；
  - 同步补齐 `1503_Dreizehn_S4`、`2201_Andrea_S2`、`2901_EtsukazuMiko_S2`、`3001_TsukinoMiyo_S2` 4 套 `BoneFollower` 骨骼跟随常驻粒子。
- **注意事项**：必须运行在 `rebuild_all_scenes_and_fx_v2.py` 之后；脚本本身幂等，重复运行安全。

### 4.2 [`scripts/apply_l2d_model_switch.py`](../scripts/apply_l2d_model_switch.py)
- **状态**：主力 Live2D 变身与主形态互切脚本（幂等可重跑）。
- **核心原理**：面向 4 位带官方变身/黑化形态的人偶（10 套 Live2D 皮肤，三语同步）同时实现两套能力：
  1. **动作触发无断音临时变身**：为`梦咲音月`（3 套）解包黑化红发贴图并注入 `replace_tex` + `PostCommand`；为`伊汐尔`（2 套）、`越一弥心`（3 套）、`露比·罗斯`（2 套）按方案 A 生成自包含 `submodels/henshin/sub_henshin.model3.json` 子模型包，实现动作播完自动还原且语音不断流；
  2. **常驻主形态一键互切**：在各皮肤根目录生成三语常驻主形态配置（`model_red*.model3.json` / `model_henshin*.model3.json`），在 `Tap` 与 `语音菜单` 顶层注入 `Form_Switch_Main`，采用**零 `../` 同级相对路径 `change_model`** 实现主形态互切（确保打入 `.lpk` 后跨语言重启不丢模型）。
- **注意事项**：必须在 `add_l2d_idle_switch.py` **之前**运行，这样后者能自动发现根目录下的 10 组变身常驻主形态并同步为其注入待机切换菜单与继承原 `Command`。

### 4.3 [`scripts/set_l2d_idle_standby1.py`](../scripts/set_l2d_idle_standby1.py) 与 [`scripts/add_l2d_idle_switch.py`](../scripts/add_l2d_idle_switch.py)
- **状态**：主力 Live2D 待机配置与持久化切换菜单脚本（三语同步、幂等可重跑；`add_l2d_idle_switch.py` 支持 `--only`）。
- **核心原理**：
  - `set_l2d_idle_standby1.py`：先将全库 Live2D 默认 `Idle` 统一锚定 `standby1`（无精确同名时回退 `standby1_*` 变体）并设 `FadeIn: 0`，避免切换眨眼/突变。
  - `add_l2d_idle_switch.py`：利用 Live2DViewerEX 原生写盘持久化变量 `CharData.varFloats["idle_mode"]`：
    - 未初始化时默认值为 `0`，自然命中 `standby1`（零破坏旧用户存档）；
    - 为 `Idle` 组内全部 `standby*` + 🔀 随机轮播（`equal 99`）+ 情绪 `*_loop` 动画严格配置 `Type: 1 (equal <k>)` 互斥条件；
    - 在 `Tap` 与 `语音菜单` 注入「🔄 切换待机动作」分页子菜单，末端项 `IdleSet_*` 直指目标动画并附带 `Type: 2 (assign <k>)`，实现即时平滑过渡且重启 EX 永久记忆。
- **注意事项**：
  - 变身主形态（如黑化音月）的每条 `Idle` 必须完整保留原始 `Command`（如 `replace_tex`），否则切换待机动作会导致变身贴图退回原皮——本脚本已自动继承保护。
  - 跳过无任何待机动画的纯剧情包（如 `露比·罗斯/原皮_艾妮斯剧情`）。

### 4.4 [`scripts/clean_spine_non_oath_menus.py`](../scripts/clean_spine_non_oath_menus.py)
- **状态**：主力 Spine 菜单净化脚本（三语同步、幂等可重跑）。
- **核心原理**：调用 `spine38_binary_to_json` 读取每个 Spine 骨架真实存在的动画列表，精准保留含 `*_marry` / `*_oath` 动画的 **26 套真婚皮**，移除全部 **84 套非婚换装皮肤** 中无效的 `誓约模式全动作` 菜单分组与 `VK_M (77)` 键位绑定。
- **注意事项**：无破坏性，可随时重跑；校验器 `verify_batch_spine.py` 会对此执行防回流断言。

### 4.5 [`scripts/add_spine_bg_toggle.py`](../scripts/add_spine_bg_toggle.py)
- **状态**：主力 Spine 背景与主骨架家具物件开关脚本（三语同步、幂等可重跑；支持 `--only`）。
- **核心原理**：
  - 自动跳过 65 套无背景子模型的原皮与纯战斗皮肤，对其余换装皮肤按子模型类型分流（v2 纯触摸架构下：42 套纯背景 + 68 套独立纯触摸，0 共用），写入三语 `背景开关` / `背景菜单`、`F3 (114)` / `H (72)` 热键以及严格**先 `remove_submodel` 后 `add_submodel` 且零过期路径**的 `reload_bg`。
  - **主骨架附带物件 `slot_opacities` 三选一机制**：内置经双面板离屏渲染逐套实测的 **38 套换装皮肤 `EXTRA_HIDE_PROP_SLOTS` 槽位映射**（仅隐藏椅子/桌台/床榻/护栏/景物/独立摆件，绝不误伤服装、头发与钢琴/脚镣/武器等互动道具）：
    - 隐藏背景及物件：`slot_opacities lock <csv> 0 0`（在 `BeforeMeshUpdate` 逐帧覆写 `slot.A=0`，带透明度关键帧的动态槽位也不闪烁回显）；
    - 恢复物件：`slot_opacities set <csv> 1 0`（**严禁仅用 `unlock`**，因为无透明度曲线的静态槽位在 `unlock` 后会永远停留在 `0f` 变不回来；`set ... 1 0` 会先置 `1f` 再自动移出锁定表，动静槽位均完美恢复）。
- **注意事项**：重跑 `rebuild_all_scenes_and_fx_v2.py` 或 `patch_hidden_bg_anims_and_bone_fx.py` 后会自动触发本脚本；若手工调整了子模型清单，需重新运行本脚本刷新 `reload_bg`。

### 4.6 [`scripts/fix_all_key_triggers.py`](../scripts/fix_all_key_triggers.py)
- **状态**：主力全库热键与菜单引用修复脚本（三语同步、幂等可重跑）。
- **核心原理（基于 EX 运行时字节码实证）**：
  1. **Windows 虚拟键码映射**：`lwtray.exe` 轮询的是 Win32 `GetAsyncKeyState(VK_*)` 而非小写 ASCII 或 Unity `KeyCode`；批量将全部 Spine 键码从错误小写/Unity 码重映射为标准 `VK_*`（`A..G=65..71, H=72, M=77, N=78, R=82, F3=114`）。
  2. **Live2D 誓约戒指静默切换**：EX `CKeyTrigger` 不支持无动作直跑命令，且前置 `Command` 会被 `LastExpression()` 覆写；为全库 27 套誓约戒指皮肤注入 `"誓约戒指切换"` 静默动作（`MotionDuration: 50` + `PostCommand: "next_exp"`），将 `VK_R (82)` 绑定至 `DownMtn`。
  3. 同步调用 `add_spine_bg_toggle` 确保 `背景菜单` 使用精确 `背景开关:hide_bg` / `:show_bg`（禁止写 `:0`/`:1` 下标引用）。
- **注意事项**：修改任意 `key_trigger` 或新增皮肤后务必复跑一次本脚本。

---

## 阶段 5：Spine ETC2 边缘净化与全库无损存储优化

### 5.1 [`scripts/spine_etc2_clean_v3.py`](../scripts/spine_etc2_clean_v3.py)（配套 [`export_spine_blend_masks.cs`](../scripts/export_spine_blend_masks.cs)、[`render_spine_compare.cs`](../scripts/render_spine_compare.cs)）
- **状态**：V4.4 主力 Spine ETC2 4×4 边缘去噪生产工具。
- **CLI 参数**：`--root`、`--doll`、`--backup-dir`、`--from-backup`、`--mask-dir`、`--no-submodels`、`--workers`、`--dry-run`、`--report`。
- **核心原理**：
  - 手游包 ETC2 4×4 分离压缩 RGB/Alpha 通道，导致 Spine PMA 图集透明区出现 `A=0 & RGB>0` 幽灵点（Additive 叠加发光）、`RGB > A` 违例及 4×4 跨透明边界的灰紫虚线。
  - **自动分流保护**：`detect_pma_etc2_atlas` 自动跳过干净无损图集与 Straight Alpha 静态背景层，绝不误处理。
  - **V4.4 双通道隔离锚点 + 轮廓守护**：清除悬浮微噪与硬/半混合 4×4 边块污染，利用 Straight 亮度防黑洞门控避免白羽/亮丝/白扇被暗色邻域打黑洞；内置核心墨线真轮廓判别、1px 彩色镶边保护与跨色相保护，完整守住 1px 连续描边、金边与樱花水彩薄纱。
  - **配套 C# 工具**：`export_spine_blend_masks.cs` 导出 `Additive`/`Screen` 槽位 UV 保护掩码传给 `--mask-dir`；`render_spine_compare.cs` 提供 Bilinear PMA 1:1 裁剪离屏渲染，供修图前后 3×/6× 放大目视对比。
- **工作流程**：先 `--dry-run` 预检 → 可选运行 `export_spine_blend_masks.exe` 导出特殊混合槽掩码 → 运行 `--from-backup --workers 8` 始终从原始未压缩备份一手重修（避免多代有损叠加）。
- **注意事项**：**始终优先使用 `--from-backup`** 从一手原始图集重算，避免对已净化图集反复执行造成边缘衰减。

### 5.2 [`scripts/optimize_l2d_spine_storage.py`](../scripts/optimize_l2d_spine_storage.py)
- **状态**：主力全库逐比特无损存储优化器（8 线程并行、幂等可重跑）。
- **CLI 参数**：`--workers <N>`。
- **核心原理与流程**：
  1. 清理经确认的未引用孤儿 PNG；
  2. 将全库 Live2D 与 Spine `.png` 纹理转为 `lossless=True, exact=True, quality=100` 无损 `.webp`，并**逐张回读解码断言 `np.array_equal` 零像素差异**后才删除原 PNG；
  3. 同步改写 `.model3.json`、`replace_tex` 命令、`.atlas.txt`、`.config.json`（并确保 Spine 设置 `tex_type: 1` / Live2D 对应格式标识）；
  4. 对全库 `.motion3.json`、`.physics3.json`、`.model3.json`、`.config.json` 与 `fx_*.json` 执行无损去空白紧凑压缩（人声 `.ogg` 零重编码）。
- **注意事项**：切勿去掉 `exact=True` 或放宽 `np.array_equal` 断言；运行期间请关闭占用纹理文件的 Live2DViewerEX 进程。

---

## 阶段 6：原生多语言 `.lpk` 角色合集打包与自动化验收

### 6.1 [`core_pipeline/verify_batch_live2d.py`](../core_pipeline/verify_batch_live2d.py) 与 [`core_pipeline/verify_batch_spine.py`](../core_pipeline/verify_batch_spine.py)
- **状态**：全库与增量定向核心验收器。
- **CLI 参数**：`--only "<角色>/<皮肤>,..."`（强烈推荐用于增量改动）、`--char`（Live2D）、`--workers`（Spine）。
- **核心校验项**：
  - **Live2D**：`.moc3` `CubismCore` 校验、全部 `HitAreas` 为合法 ArtMesh、控制器关闭项、`Idle` `VarFloats["idle_mode"]` 条件互斥、零曲线 `menu_silent`、标准 `VK_*` 热键、三语对称、`OggS` 音频头与零残留 `.wav`/`.png`。
  - **Spine**：骨架（二进制/JSON）可解析性、图集区域与无损 `.webp` 存在性、全部 `start_mtn` 含 `main:` 前缀且目标动画存在、子模型数 `<= 6`、无嵌套裁切、非婚皮无无效誓约菜单、`slot_opacities` 所列槽位全部真实存在于主骨架、`VK_*` 热键与 `reload_bg` 顺序正确、三语完全一致。
- **注意事项**：定向 `--only` 模式下自动跳过覆写全库汇总报告，速度仅需 1~3 秒。

### 6.2 [`scripts/build_and_pack_workshop_lpks.py`](../scripts/build_and_pack_workshop_lpks.py) 与 [`scripts/pack_all_dolls_mega_lpk.py`](../scripts/pack_all_dolls_mega_lpk.py)
- **状态**：主力原生多语言 `STD2_0` `.lpk` 打包脚本。
- **CLI 参数**：
  - `build_and_pack_workshop_lpks.py`：`--dolls <角色1> <角色2>`（省略则全量 55 位）、`--workers <N>`；
  - `pack_all_dolls_mega_lpk.py`：`--workers <N>`（默认单趟同时产出 55 单人偶包 + 1 份全 55 人偶总集包）、`--mega-only`（仅产总集包）。
- **核心原理**：
  - **EX 原生四语融合（`merge_multilang_motions`）**：Live2DViewerEX 筛选动作时，若当前语言的 `langPool` 非空则会完全丢弃无语言标签的 `defaultPool`（严禁同组混排！）。因此脚本自动把中/英/日三套独立配置融合为单一主配置：英文省略 `Language`（`""` 全局兜底），并严格对称写入 `"zhs"`、`"zht"`（简繁映射）与 `"ja"` 组，同时融合誓约戒指双语表情名并归一化 `Form_Switch_Main` 指向同一 `.bin3`。
  - **模型内置四语跨引擎切装菜单（`_inject_workshop_costume_menus`）**：针对创意工坊分页仅默认加载 `cosList[0]` 的限制，打包期自动为所有多服装角色（`>= 2` 套）的主模型与变身主形态配置注入四语对称的 `Menu_WS_Skins` 分页菜单（`<= 6` 套直接列表、`> 6` 套自动按 `★ Live2D 服装` / `✦ Spine 服装` 分类分页，全用通用 BMP 符号，零污染散装源目录），叶节点通过 `change_model <target_zip_cfg>` 实现 Live2D ↔ Live2D ↔ Spine 跨引擎原地无缝互切；依托 EX 原生 `CharData.configFile` 自动落盘实现重启记忆与无 Spine DLC 时自动自愈；同时在 Live2D `Tap`/`语音菜单` 顶部、Spine 原生 `"tap"` 空白点击回退组、`背景菜单` 以及零冲突 Windows 热键 **`F2 (113)` / `S (83)`** 挂载直达入口。
  - **跨皮肤+跨引擎零重编码音频去重**：对同一角色（或总集包跨全部 55 角色）下所有 Live2D 与 Spine 的 `.ogg` 按 **SHA-256** 内容哈希归入共享 `audio/` 与 `bgm/`，再结合 `STD2_0` 协议的 `MD5(路径)` 条目映射与 Deflate-6 压缩，将源目录 `4,077.68 MiB` 无损压至 `2,239.22 MiB`（`54.91%`）。
  - 自动生成 `< 1 MB` 渐变背景预览图（单人偶封面与 11×5 全角色拼图封面）及角色头像，并采用 Zip64 兼容超 2 GiB 总集包。
- **注意事项**：
  - 打包前务必确认目标角色的 Live2D 与 Spine 已通过 `verify_batch_*` 校验；
  - 暂存目录利用 NTFS 硬链接减少磁盘双倍占用，需确保暂存盘与源目录位于同一 NTFS 分区（跨分区会自动降级为复制）。

### 6.3 [`scripts/verify_workshop_lpks.py`](../scripts/verify_workshop_lpks.py)
- **状态**：主力 `.lpk` 端到端完整性校验脚本（支持 `--only <角色...>` 定向与 `--exclude-mega`）。
- **核心原理与校验项**：逐包递归解析 ZIP 与 `STD2_0` 清单 `config.mlve`（`1d862f7d02e6008f4550188a31ca654f`）和头像（`4a301072dec6b6a49050e5b294cd7983`），逐套核查全部 357 套服装及子模型/变身/隐藏背景引用、四语言 `{"", "zhs", "zht", "ja"}` 严格对等（`check_multilang_group`）、多服装主模型与变身形态的 **`Menu_WS_Skins` / `WS_Skin_*` 全服装覆盖 / `F2(113)` & `S(83)` 热键 / Live2D `Tap` & `语音菜单` 与 Spine `"tap"` & `背景菜单` 入口**、多 `Idle` `VarFloats["idle_mode"]` 互斥、Spine `atlases[].tex_names` 与 `.atlas.txt` 页名对齐、`.ogg` 魔数头与零重复条目，以及 `< 1 MB` 封面限制。
- **注意事项**：任何打包完成后都应运行本脚本确认 `0` 失败后再导入 Live2DViewerEX。

---

## 阶段 7：研发与逆向归档专题（`research_archive/01~05`）

本目录收纳在攻克上述工程难题过程中沉淀的 **199 个专项诊断、普查、逆向探针与算法原型脚本**（日常批量构建无需运行，适合二次开发、算法复现或底层原理排查时参考）：

| 目录 | 脚本数 | 涵盖原理与典型工具 | 注意事项 |
| :--- | :---: | :--- | :--- |
| [`01_heling_and_particle_fx/`](../research_archive/01_heling_and_particle_fx/) | `87` | `和铃/古锦新韵` 方案一原生 Spine 粒子原型（`build_heling_s2_scheme1.py`）、Unity 粒子早期工程资源（`unity_fx_proj_assets/`）、全库 101+ 皮肤粒子/Shader/3D 旋转/拖尾/相机/遮挡普查脚本（`audit_*`、`inspect_*`、`verify_exact_2d_coords.py`）。 | 多数为只读普查与早期原型，正式粒子流水线请以 `core_pipeline/batch_fx_exporter.py`、`unity_fx_recorder/` 与 `scripts/convert_fx_to_native_spine.py` 为准。 |
| [`02_texture_degauze_rebake/`](../research_archive/02_texture_degauze_rebake/) | `20` | 针对特定皮肤胸前纱布去除的跨工具链实验：干净部件导包、AI 重绘图按 Spine 蒙皮 UV 精确反烘焙（`export_idle0_bake_meta.cs`、`bake_gen_to_83_1.py`）、Lab 色彩空间对齐、SDF 抗锯齿去白边与细节精修（`fix_v3_fringe_and_belly.py`）。 | 面向单套特定纹理拓扑（Slot/UV 索引硬编码），迁移至其他皮肤前须重测目标 UV 映射。 |
| [`03_etc2_edge_denoise_rd/`](../research_archive/03_etc2_edge_denoise_rd/) | `11` | ETC2 4×4 压缩块污染机理研究工具：C# UV 渗色与像素级探针（`check_uv_bleed.cs`、`diagnose_render.cs`、`probe_lines.cs`）及 V1 / V2 / V3.2 / V3.3 算法迭代原型。 | 生产环境请统一使用已解决黑洞与描边保护问题的 [`scripts/spine_etc2_clean_v3.py`](../scripts/spine_etc2_clean_v3.py)（V4.4）。 |
| [`04_ex_engine_reverse_lpk/`](../research_archive/04_ex_engine_reverse_lpk/) | `41` | 面向 Live2DViewerEX（`lw.exe` / `exstudio.exe`）的 C# 反射与 IL 逆向探针：验证 `STD2_0` `.lpk` 哈希去重、`libwebp` 解码、Spine PMA 渲染、Submodel 缩放与 `slot_opacities`/动作指令解析（`inspect_lpk*.cs`、`inspect_commands.cs`、`inspect_webp*.cs`、`ex_spine38*.cs`）。 | 需链接本地正版 Live2DViewerEX 的 `Assembly-CSharp.dll` 编译运行，仅作兼容性分析研究。 |
| [`05_hitarea_align_audit/`](../research_archive/05_hitarea_align_audit/) | `40` | Live2D `.moc3` 顶点旋转/变形与触控盒分析（`inspect_moc3_and_boxes.py`、`debug_moc3_rot_warp.py`）、Spine 按骨骼逐顶点蒙皮提取（`extract_spine38_per_bone_verts.py`）、原皮与换装挂载点/缩放/音频全库诊断脚本。 | 多为一次性分析诊断脚本，正式热区与布局校准请使用 `core_pipeline/` 下的标准工具。 |

---

## 延伸阅读

- 如遇具体画面穿帮、粒子黑屏、热键失灵或 `.lpk` 切换语言异常，请对照 **[Live2D & Spine 制作问题排查与避坑手册（46 项实证排障）](./troubleshooting_manual.md)**。
- 查看基于本工具链产出的全量 55 位人偶成品索引，请参阅 **[Steam 创意工坊 55 人偶发布索引](./workshop_55_dolls_index.md)**。
