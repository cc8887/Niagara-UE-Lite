# UE 5.8.1 双平台验收记录

验收日期：2026-10-29。引擎：UE 5.8.1，CL 56057345。
完整 CLI 包已经构建、封包、重新解压，并从最终解压目录重新执行原生创建、
Cook、Pak 和渲染。这里区分编辑资产验证、实际模拟/图像验证和运行环境隔离。

## 包体

| 包 | 压缩字节数 | 压缩大小 | 解压有效载荷 | 清单记录数 |
| --- | ---: | ---: | ---: | ---: |
| Windows x86_64 / D3D12 SM6 | 1,801,901,805 | 1.678 GiB | 3,633,982,253 字节 / 3.384 GiB | 68,079 |
| Linux x86_64 / Vulkan SM6 | 1,593,948,187 | 1.484 GiB | 3,708,003,399 字节 / 3.453 GiB | 68,415 |

GiB = 2^30 字节。有效载荷是清单内文件之和，不含清单自身和文件系统分配开销；
实际文件数比记录数多 1。包含编辑后端、原生编译/Cook 工具、Python、Niagara
模板及模块、预览运行端和预热 DDC。使用者仍需要匹配的系统库与图形驱动。

最终压缩包 SHA256：

```text
34718a9a8f16b3ebba49c01e4d8258b8b4ccf8cefe57641ccdef23a2302d8999  Niagara-UE-Lite-Standalone-UE5.8.1-Windows-x86_64.zip
c6859c4884acc5e3e96b52374e2634583ff0cf9906cb1e2ca21de388d4193d77  Niagara-UE-Lite-Standalone-UE5.8.1-Linux-x86_64.tar.gz
```

独立 Cooked 预览目录另行计量，橙色喷泉示例：

| 平台 | 字节数 | 大小 | 文件数 |
| --- | ---: | ---: | ---: |
| Windows | 242,527,577 | 231.29 MiB | 19 |
| Linux | 228,982,333 | 218.37 MiB | 9 |

这是解压有效载荷，不是压缩包大小；不包含原生编辑资产或编辑/Cook 后端。
包体随系统、贴图、材质和 ShaderMap 增长。当前 Cook 收集工作区 Content，
不是任意项目都固定在这个大小，也还没有对每种发射器做依赖裁剪。

## 原生创建、编辑、保存

两平台分别通过 10 项进程级验收：创建、读取、编辑、重新加载、保存、编译、
拒绝重复创建、拒绝无效编辑、拒绝后重新读取、拒绝越界资产路径。

验证内容包括：

- 创建实际 `UNiagaraSystem` 和 Fountain 发射器，并保存原生 `.uasset`。
- `SpawnRate` 从 90 改为 240；粒子颜色、尺寸修改后在新进程中读回。
- 原生保存前生成备份；包含无效操作的编辑请求不改变主资产文件 SHA256。
- Snapshot 中的输入值包含动态结构类型与数据，不再是空对象。

两平台另各通过 6 项贴图链路验收：PNG 导入、未 Cook 的 Texture2D `.uasset`
导入、材质创建、系统创建、渲染器材质绑定、保存后重新加载。
这是首版历史验证记录；preview.7 已删除材质创建入口，改为加载和绑定外部已有材质。
实际渲染使用导入贴图，不只检查静态引用。

可用操作还包含添加/删除发射器、模块和 Sprite 渲染器，以及启用状态和属性编辑；
这不意味着所有模块和属性组合均已验收。`ue-niagara-recipe/1` 是受支持操作的
输入协议，`ue-niagara-snapshot/1` 是原生状态导出。任意 Niagara 图的无损 JSON
往返不在当前承诺范围，原生 `.uasset` 保留完整编辑信息。

## 模拟和图像

Windows：Windows 11 24H2，AMD Radeon Graphics，D3D12/SM6。
Linux：WSL Ubuntu 24.04，Mesa 26.1.6，llvmpipe / LLVM 19.1.7，Vulkan/SM6。
Linux 使用 `--cpu-vulkan`；驱动来自验收环境，不封装进本工具包。

所有示例使用原生 CPU-sim Sprite 发射器、固定种子 1337、1/60 秒步长、60 个
模拟帧、16 个时序 AA 预热帧、512×512 输出，保持 TSR（method 4）。

| 场景 | 平台 | 原生粒子数 | maxRGB | nonZeroPixels | Runtime 退出码 |
| --- | --- | ---: | ---: | ---: | ---: |
| 白色喷泉，最终压缩包解压后 demo | Windows | 88 | 246 | 26,901 | 0 |
| 白色喷泉，最终压缩包解压后 demo | Linux | 88 | 247 | 25,461 | 0 |
| 修改后的橙色喷泉 | Windows | 236 | 255 | 86,882 | 0 |
| 修改后的橙色喷泉 | Linux | 236 | 255 | 85,795 | 0 |
| 导入贴图后的蓝色粒子 | Windows | 88 | 238 | 13,913 | 0 |
| 导入贴图后的蓝色粒子 | Linux | 88 | 238 | 13,389 | 0 |

六份图像均已实际查看，具有对应的粒子形态、颜色与贴图变化。
元数据同时确认 `systemValid=true`、`systemReady=true`、`sceneProxyExists=true`、
`withEditor=false`、`niagaraEditorLoaded=false`、`unrealEdLoaded=false`。

相同场景在 D3D12 与 Vulkan 上的 RGB 平均绝对差分别为白色 0.2963、橙色
0.2240、贴图 0.0431（每通道范围 0–255）。这是两条原生 RHI 路径的图像证据，
不表示跨 RHI 逐像素一致，也不是与完整 Niagara 图形编辑器视口的对照验收。

## 独立性和最终压缩包

Linux 在专用 mount/network namespace 中隐藏原 UE 引擎、C++ SDK、项目源码
和构建目录，并断开网络，以普通用户完成上述 10+6 项资产操作及两次 Cook/渲染。
随后进一步隐藏包内 `backend`，直接运行已 Cook 的 Shipping 程序，仍得到
236 粒子、maxRGB 255 的橙色喷泉，进程退出码 0。

Windows 使用包内 Python 和编辑后端；检查的 191 次 UE 模块加载路径全部位于
独立包或工作区，没有原安装引擎路径，也跳过了 SDK 探测。Windows 没有物理隐藏
已安装 UE，所以此项隔离证据弱于 Linux 的 namespace 验证。

最终两份压缩包重新解压后，每个清单文件的大小、SHA256 均匹配；Linux 执行权限
也通过检查。之后从两个最终解压目录分别执行 `demo`，重新创建资产、Cook 并出图。
打包过程冻结文件清单，测试工作区、日志、源资产、调试符号和 C++ SDK 不混入交付包。

完整 CLI 包内置 `UnrealEd` / `NiagaraEditor`。无界面不等于完全删除这些模块。
Cooked Shipping 预览不包含编辑器，也不在运行时编译新的 Niagara 图或材质。

## 复现入口和范围

解压后运行；Windows PowerShell：

```powershell
.\niagara-cli.exe --workspace .\work demo --out .\outputs\demo.png
```

Linux，已具备满足 UE SM6 要求的 CPU Vulkan 驱动：

```sh
./niagara-cli --workspace ./work demo --cpu-vulkan --out ./outputs/demo.png
```

两者均生成 PNG、运行元数据、资产快照和 `demo-runtime` 目录。
编辑流程及贴图命令见主 README。源码工具 `tools/verify_archive.py` 用于核对
解压清单；`acceptance_authoring.py` / `acceptance_textures.py` 可重复验收资产链路。

首版验收范围是 CPU-sim Sprite。GPU-sim、Ribbon/Mesh Renderer、Niagara Fluids、
自定义插件、场景碰撞和依赖外部世界的 Data Interface 尚未完成专门验收。
没有提供 Niagara 图形编辑窗口；当前 standalone 是面向命令行的原生编辑后端。
