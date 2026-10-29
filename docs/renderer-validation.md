# GPU Sprite、Ribbon 与 Mesh 渲染验收

2026-10-29，UE 5.8.1 / CL 56057345，`v0.1.0-preview.2`。
两端均通过独立包创建原生资产、保存后由新进程读取、Cook、运行 Shipping 预览。
最终矩阵各有 6 例：三种效果分别模拟 30 / 60 帧，再冻结仿真、预热 16 帧，
输出 512×512 PNG。12 例均正常退出、图像非黑，并逐图检查实际形状。

## 设备与结果

| 平台 | RHI / 设备 | GPU Sprite | Ribbon | Mesh |
| --- | --- | --- | --- | --- |
| Windows | D3D12 / NVIDIA GeForce RTX 5080 | GPUComputeSim | CPUSim | CPUSim |
| Linux | Vulkan / Mesa 26.1.6，llvmpipe LLVM 19.1.7 | GPUComputeSim，由软件 Vulkan 执行 | CPUSim | CPUSim |

Linux 未验证物理 GPU。`GPUComputeSim` 指 Niagara 的计算着色器仿真路径，
不表示 llvmpipe 是物理 GPU，也没有回退成 Niagara CPUSim。
GPU Ribbon、GPU Mesh、Fluids 和依赖外部场景的数据接口未纳入本轮验收。

下表各对数值按 30 / 60 帧排列。粒子数来自实际数据，GPU 数量在保存截图后
异步读回原生 GPU 缓冲；CPU 数量来自 Niagara 数据集。

| 平台 | 效果 | 精确粒子数 | maxRGB | nonZeroPixels |
| --- | --- | ---: | ---: | ---: |
| Windows | GPU Sprite | 116 / 236 | 255 / 255 | 16,075 / 28,074 |
| Windows | Ribbon | 100 / 100 | 240 / 240 | 7,203 / 7,219 |
| Windows | Mesh | 19 / 39 | 241 / 241 | 5,644 / 12,232 |
| Linux | GPU Sprite | 116 / 236 | 255 / 255 | 15,513 / 27,109 |
| Linux | Ribbon | 100 / 100 | 240 / 240 | 6,871 / 6,883 |
| Linux | Mesh | 19 / 39 | 241 / 241 | 5,443 / 11,912 |

GPU Sprite 为蓝色喷泉，Ribbon 为完整的青色曲线，Mesh 为可辨识的金色立体
轴标网格喷泉。GPU Sprite 与 Mesh 在两个时间点的图片指纹不同。跨 RHI 的
像素并不完全相同，本次没有声称 Windows 与 Linux 逐像素一致。

所有运行均满足：

- 进程退出码 0；原生组件、仿真和 SceneProxy 有效；PNG 实际写出。
- `withEditor`、`unrealEdLoaded`、`niagaraEditorLoaded` 均为 false。
- 仿真年龄约为 0.5 / 1.0 秒；实际投影水平 FOV 为 45°。
- 正确的原生 Renderer 类、材质与仿真目标；CPU 位置数据无 NaN / Inf。
- GPU 读回完成、数量精确；读回发生在截图保存之后，不参与修复或替换图像。
- 捕获时组件就绪、没有自身待完成的 PSO，已完成 16 个连续就绪的预热帧。

## 发现的问题与修复

1. **两端模板目录不同。** Windows 安装中存在的 `StaticBeam`、`UpwardMeshBurst`
   不在本次 Linux 引擎内容目录中。配方改用两端共有的 `DynamicBeam` 和
   `Fountain`，并通过原生编辑 API 删除和重新创建 Ribbon / Mesh Renderer。
2. **Ribbon 切线数值语义错误。** 模板的非绝对切线会再乘以 Beam 长度；原先的
   大数值产生了过大的曲线。改为 1.4 / -1.1 的相对切线分量，使用原生 Vector3f
   输入。没有把它们误当作世界坐标长度或强制归一化方向。
3. **方形输出的实际 FOV 小于配置值。** 相机默认 16:9 与 `MaintainYFOV`
   组合，使 512×512 输出的实际水平 FOV 从配置的 45°变成 26.231283°，裁切了
   Ribbon。相机现使用输出宽高比。同一 Linux EXE、Pak、60 帧及完全相同的
   100 个 CPU 粒子位置的 A/B 对照，确认实际 FOV 恢复 45°后完整显示曲线。
4. **截图可能早于渲染代理就绪。** 首次 Windows Ribbon 失败时有 100 个有效
   粒子，但 `sceneProxyExists=false`，截图全黑。现暂停在目标仿真帧，以非阻塞
   方式等待组件自身的代理和 PSO 就绪，再计数预热帧。总等待及预热限时 60 秒，
   超时写出明确诊断。Windows 保留 PSO 预缓存；全局 PSO 队列只记录、不阻塞截图。
   暖缓存下开关 PSO 的复跑都成功，因此没有断言首次缺失代理一定由 PSO 导致。
5. **Mesh 示例太小。** 调大原生 `S_Gnomon` 渲染比例，使网格轮廓可辨识；没有
   使用 Sprite 冒充 Mesh。

最终矩阵的组件在开始等待时已经就绪，`waitFrames=0`、
`psoPendingObserved=false`。这证明就绪检查未破坏两端正常渲染，但不等于
复现并覆盖了每一种延迟创建代理或 PSO 超时分支。额外 Windows 运行在全局仍有
3,855 项预缓存请求时也正常出图，符合“只等待当前组件”的设计。

## 复现与证据

解压对应平台独立包，Windows 将下列 `./niagara-cli` 换成 `niagara-cli.exe`。
Linux 软件 Vulkan 运行时在各个 `demo` 后增加 `--cpu-vulkan`；物理 GPU 不加。

```sh
./niagara-cli --workspace ./work demo --effect gpu --frames 60 --out outputs/gpu.png
./niagara-cli --workspace ./work demo --effect ribbon --frames 60 --out outputs/ribbon.png
./niagara-cli --workspace ./work demo --effect mesh --frames 60 --out outputs/mesh.png
```

源码中的 `tools/acceptance_renderers.py` 可重做创建、重新加载、Cook 和六例渲染：

```sh
python tools/acceptance_renderers.py --root <extracted-kit> --workspace ./qa-work --out ./qa-results
```

Linux 软件设备再加 `--cpu-vulkan`。测试器只记录自动检查，人工图像检查单独
记录，避免把一个非黑像素等同于正确的粒子效果。

Release 中的 `Niagara-UE-Lite-RendererValidation.zip` 提供两端原始 PNG、运行
元数据、相机 A/B 图像、验证报告和离线 HTML 图集。独立包及校验文件只放在
Release；源码仓库不包含二进制、Cooked 资产或本机路径。包体大小和 SHA256
以该 Release 附带的包元数据及 `SHA256SUMS.txt` 为准。

本轮没有重新验证首版全部贴图和任意编辑操作；历史资产读写、纹理及首版包体
证据仍见 [validation.md](validation.md)。完整编辑包含无界面编辑/Cook 后端；
“Runtime 不加载编辑器”不应解释成整个独立包不包含 UnrealEd。
