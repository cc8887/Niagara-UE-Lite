# Niagara-UE-Lite

UE 5.8.1 原生 Niagara standalone CLI：创建、读取、编辑、编译、保存原生
`.uasset`，离线 Cook 后通过 UE 原生 Niagara 仿真和渲染输出 PNG。

独立包内置无界面 `UnrealEd` / `NiagaraEditor`、Python 和编译/Cook 后端，
使用者无需另装 UE、Python 或 C++ SDK。生成的纯 Runtime 预览目录不包含编辑器。
Windows 使用 D3D12/SM6；Linux 使用 Vulkan/SM6。

preview.6 以通用原生编辑操作为入口：AI 可以从空 System 或独立 Emitter
开始，检索已有模块、动态输入和资源，查询 Schema，再添加、配置、保存和 Cook。
创建不要求模板，默认封包也不再携带发射器模板或预置效果。
接口和实际覆盖边界见
[template-free-authoring.md](docs/template-free-authoring.md)。

新增 JSON 对象文档的 `export` / `import`，恢复内部图、Scratch Pad、
继承依赖和编辑器数据，并支持显式属性修改与资源附件。格式保留每个对象的
原生序列化扩展，要求匹配引擎构建；使用方法与验收边界见
[json-round-trip.md](docs/json-round-trip.md)。

双平台独立包及校验文件发布在
[preview.6 Release](https://github.com/cc8887/Niagara-UE-Lite/releases/tag/v0.1.0-preview.6)。
仓库保持私有；可执行文件、缓存和压缩包通过 Release 附件分发。

基础包按程序白名单和原生资产引用清单裁剪；预热 DDC 为可选下载。未安装缓存
时仍能创建、编辑、保存和 Cook，首次编译会更慢。缓存安装位置与资源边界见
[curation.md](docs/curation.md)。

命令行服务配置进一步解除 MainFrame、Persona 的运行依赖，并按平台保留 Cook
目标及着色器格式。贴图操作使用原生资产服务，预览地图由原生命令行后端创建和
保存；Sequencer、GraphEditor 及必要的编辑、编译服务继续保留。实现和验证边界见
[editor-backend-profile.md](docs/editor-backend-profile.md)。

精简发行包移除 CEF、可选图形调试层和外置符号/静态库，剥离 Linux ELF 中的
非必要符号并对相同库去重。Linux 的 WebBrowser / CEF3Utils 从匹配源码重新
编译为 `WITH_CEF3=0`，解除对 Chromium 的硬依赖。Cook 导出的运行目录会补齐
共享 DLL，保持独立可用。构建边界与验收方式见 [slimming.md](docs/slimming.md)。

这是编辑功能的 CLI，不包含 Niagara 图形编辑窗口。不是完全去除 UnrealEd 的
引擎重构；模块边界见 [architecture.md](docs/architecture.md)。

在解压目录运行（Windows 用 `niagara-cli.exe`，Linux 用 `./niagara-cli`）：

```sh
./niagara-cli capabilities
./niagara-cli api
./niagara-cli --workspace ./work init
./niagara-cli --workspace ./work create --asset /Game/Demo/MySystem
./niagara-cli --workspace ./work catalog --kind modules --search Spawn
./niagara-cli --workspace ./work edit --asset /Game/Demo/MySystem --recipe operations.json
./niagara-cli --workspace ./work read --asset /Game/Demo/MySystem --out snapshot.json
./niagara-cli --workspace ./work save --asset /Game/Demo/MySystem
./niagara-cli --workspace ./work build --asset /Game/Demo/MySystem --out outputs/frame.png
```

`build` 执行 Cook、Pak 和渲染。也可以分开运行：

```sh
./niagara-cli --workspace ./work cook --asset /Game/Demo/MySystem --package outputs/runtime
./niagara-cli render --package outputs/runtime --asset /Game/Demo/MySystem --frames 60 --out outputs/frame.png
```

Linux 无 GPU 时，加 `--cpu-vulkan`，需要满足 UE Vulkan SM6 的 Mesa lavapipe
驱动。CPU 粒子仿真和 CPU Vulkan 渲染是两个独立概念；`--cpu-vulkan` 会检测并
选择 CPU Vulkan 设备，不会用其他绘图库生成替代图像。

<details>
<summary>历史 preview.5 模板演示（当前无模板封包不携带这些配方）</summary>

旧版演示入口包括 GPU Sprite、CPU Ribbon 和 CPU Mesh Renderer。Windows：

```powershell
.\niagara-cli.exe --workspace .\work demo --effect gpu --out .\outputs\gpu.png
.\niagara-cli.exe --workspace .\work demo --effect ribbon --out .\outputs\ribbon.png
.\niagara-cli.exe --workspace .\work demo --effect mesh --out .\outputs\mesh.png
```

Linux 使用同样的 `--effect` 选项；软件 Vulkan 示例：

```sh
./niagara-cli --workspace ./work demo --effect gpu --cpu-vulkan --out outputs/gpu.png
./niagara-cli --workspace ./work demo --effect ribbon --cpu-vulkan --out outputs/ribbon.png
./niagara-cli --workspace ./work demo --effect mesh --cpu-vulkan --out outputs/mesh.png
```

`gpu` 配方将 Niagara 仿真目标设为 `GPUComputeSim`。若 Vulkan 设备是 llvmpipe，
计算着色器由软件设备执行；不能将其称为物理 GPU 验证。`ribbon` 与 `mesh` 配方
仍使用 `CPUSim`，分别检验原生 Ribbon 和 Mesh Renderer，不表示两者的 GPU 仿真
组合也已完成验收。具体平台、图像与测量结果见
[renderer-validation.md](docs/renderer-validation.md)。

配方使用两端都具备的原生 `Fountain` 和 `DynamicBeam` 模板。同为 UE 5.8.1 的
安装也可能有不同内容目录；配方不再依赖仅在部分安装中提供的 `StaticBeam` 或
`UpwardMeshBurst`。Mesh 示例使用 `S_Gnomon`；Ribbon 与 Mesh 材质均为原生 Unlit
材质，因此不要求演示场景额外放置灯光。

</details>

运行元数据区分 `simTarget`、Renderer 类和 RHI 设备。CPU 粒子数直接读取数据集；
GPU 粒子数在截图保存后从原生 GPU 缓冲读回，并报告 `particleCountSource`、
`particleCountExact` 和 `gpuReadbackCompleted`。读回不参与已经保存的图像生成，
也不会把 CPU 侧估计值当作精确 GPU 数量。

资产与源图保存在工作区 `Content` / `SourceArt`；编辑旧资产前自动备份至
`Saved/NiagaraStandalone/Backups`。创建时拒绝覆盖，操作失败不保存主资产。
每个命令使用独立后端进程；首轮无缓存 Cook 可能需要数分钟。

贴图与原生材质：

```sh
./niagara-cli --workspace ./work import-texture --file texture.png --asset /Game/Demo/T_Particle
./niagara-cli --workspace ./work create-material --texture /Game/Demo/T_Particle --asset /Game/Demo/M_Particle
```

然后用 `renderer-properties` 的 `Material` 字段把材质对象路径绑定到发射器
Renderer。支持 PNG/JPEG/TGA/BMP/EXR/HDR 的 UE TextureFactory 导入，也支持
匹配 UE 5.8.1、未 Cook 的标准 Texture2D `.uasset` 和同名 `.uexp` / `.ubulk`。
原生资产导入需要保留文件名；额外插件、外部虚拟化数据不在此导入范围内。

文本接口有两种明确用途：

- `ue-niagara-snapshot/1`：读取原生拓扑、参数值、动态值类型、渲染器和编译状态。
- `ue-niagara-recipe/1`：通过通用原生编辑操作创建或修改资产，可选择复用已有资产。

Renderer 可通过 `add-renderer` 指定原生类；也保留 `add-sprite-renderer`、
`add-ribbon-renderer`、`add-mesh-renderer` 便捷操作。通过 `renderer-properties`
设置原生材质、网格、朝向等属性，通过 `remove-renderer` 删除指定索引。

Snapshot 不是通用粒子解释器格式，也不承诺任意 Niagara 图可由 JSON 无损重建。
完整编辑资产保留在 `.uasset`。纯 Runtime 消费 Cook 后的字节码和 ShaderMap。

构建与封包见 [build.md](docs/build.md)。可执行文件、SDK、缓存和压缩包不进入 Git。
包含 Epic Engine Tools 的完整包保留 Epic 分发条款，沿用私有交付方式。

首版双平台包体、原生资产读写和 Sprite 渲染验收保留在
[validation.md](docs/validation.md)；GPU、Ribbon、Mesh 的扩展验收单独记录于
[renderer-validation.md](docs/renderer-validation.md)。
