# Niagara-UE-Lite

UE 5.8.1 原生 Niagara standalone CLI：创建、读取、编辑、编译、保存原生
`.uasset`，离线 Cook 后通过 UE 原生 Niagara 仿真和渲染输出 PNG。

独立包内置无界面 `UnrealEd` / `NiagaraEditor`、Python 和编译/Cook 后端，
使用者无需另装 UE、Python 或 C++ SDK。生成的纯 Runtime 预览目录不包含编辑器。
Windows 使用 D3D12/SM6；Linux 使用 Vulkan/SM6。

这是编辑功能的 CLI，不包含 Niagara 图形编辑窗口。不是完全去除 UnrealEd 的
引擎重构；模块边界见 [architecture.md](docs/architecture.md)。

在解压目录运行（Windows 用 `niagara-cli.exe`，Linux 用 `./niagara-cli`）：

```sh
./niagara-cli capabilities
./niagara-cli --workspace ./work init
./niagara-cli --workspace ./work create --asset /Game/Demo/NS_Fountain --recipe examples/fountain.json
./niagara-cli --workspace ./work read --asset /Game/Demo/NS_Fountain --out fountain.json
./niagara-cli --workspace ./work edit --asset /Game/Demo/NS_Fountain --recipe examples/fountain-orange.json
./niagara-cli --workspace ./work save --asset /Game/Demo/NS_Fountain
./niagara-cli --workspace ./work build --asset /Game/Demo/NS_Fountain --out outputs/fountain.png
```

`build` 执行 Cook、Pak 和渲染。也可以分开运行：

```sh
./niagara-cli --workspace ./work cook --asset /Game/Demo/NS_Fountain --package outputs/runtime
./niagara-cli render --package outputs/runtime --asset /Game/Demo/NS_Fountain --frames 60 --out outputs/frame.png
./niagara-cli --workspace ./work demo --out outputs/demo.png
```

Linux 无 GPU 时，加 `--cpu-vulkan`，需要满足 UE Vulkan SM6 的 Mesa lavapipe
驱动。CPU 粒子仿真和 CPU Vulkan 渲染是两个独立概念；`--cpu-vulkan` 会检测并
选择 CPU Vulkan 设备，不会用其他绘图库生成替代图像。

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
- `ue-niagara-recipe/1`：通过原生模板、模块与编辑操作创建或修改资产。

Snapshot 不是通用粒子解释器格式，也不承诺任意 Niagara 图可由 JSON 无损重建。
完整编辑资产保留在 `.uasset`。纯 Runtime 消费 Cook 后的字节码和 ShaderMap。

构建与封包见 [build.md](docs/build.md)。可执行文件、SDK、缓存和压缩包不进入 Git。
包含 Epic Engine Tools 的完整包保留 Epic 分发条款，沿用私有交付方式。

双平台实际包体、原生资产读写和渲染验收见 [validation.md](docs/validation.md)。
