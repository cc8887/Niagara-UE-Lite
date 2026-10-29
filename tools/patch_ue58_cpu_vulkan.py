"""Check or apply the UE 5.8.1/5.9.0 CPU Vulkan and Bloom compatibility fixes.

The engine source is deliberately modified only with --apply. Set
NIAGARA_BUILD_ENGINE to the matching Engine directory.
5.8.1 and 5.9.0 share the memory-property and bindless stage anchors; in 5.9
the acceleration-structure layout moved to descriptor-heap mappings without a
stageFlags field, so that replacement only applies to 5.8.1.
"""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="patch the engine source")
    args = parser.parse_args()
    engine = Path(os.environ["NIAGARA_BUILD_ENGINE"])
    version = json.loads((engine / "Build/Build.version").read_text(encoding="utf-8"))
    supported = {(5, 8, 1), (5, 9, 0)}
    actual = (version["MajorVersion"], version["MinorVersion"], version["PatchVersion"])
    if actual not in supported:
        raise SystemExit(f"This patch supports UE 5.8.1/5.9.0, found {actual}")
    base = engine / "Source/Runtime/VulkanRHI/Private"
    memory = base / "VulkanMemory.cpp"
    descriptors = base / "VulkanBindlessDescriptorManager.cpp"
    profile_gate = base / "VulkanRHI.cpp"
    gaussian = engine / "Source/Runtime/Renderer/Private/PostProcess/PostProcessWeightedSampleSum.cpp"
    originals = {path: path.read_bytes() for path in (memory, descriptors, profile_gate, gaussian)}
    changes = dict(originals)
    missing = []

    def replace_once(path, old, new, label, version_scoped=None):
        if version_scoped is not None and actual != version_scoped:
            return
        data = changes[path]
        # Some replacements (e.g. the profile gate) have `new` starting with
        # the full `old` text, so `old` remains present after applying.
        # Treat a single existing `new` occurrence as "already applied".
        if data.count(new) == 1:
            return
        if data.count(old) != 1 or data.count(new) != 0:
            raise SystemExit(f"Unexpected {path.name}: cannot safely apply {label}")
        missing.append(label)
        changes[path] = data.replace(old, new, 1)

    replace_once(memory,
        b"if (MemoryProperties.memoryTypes[Index].propertyFlags == Properties)",
        b"if ((MemoryProperties.memoryTypes[Index].propertyFlags & Properties) == Properties)",
        "memory-property subset check")

    # A tiny Gaussian tail can underflow to zero, including the unpaired last
    # tap. Its bilinear offset must not evaluate 0/0: lavapipe propagates the
    # resulting NaN through Bloom into Tonemap and blacks out the entire view.
    # A zero-weight tap contributes nothing; a finite offset preserves the
    # original kernel, Bloom quality and temporal anti-aliasing settings.
    replace_once(gaussian,
        b"OutOffsetAndWeight[SampleCount].X = SampleIndex + (Weight1 / TotalWeight);",
        b"OutOffsetAndWeight[SampleCount].X = SampleIndex + (TotalWeight > 0.0f ? Weight1 / TotalWeight : 0.0f);",
        "finite zero-weight Gaussian tap")

    data = changes[descriptors]
    newline = b"\r\n" if b"\r\n" in data else b"\n"
    anchor = b"static inline VkMemoryPropertyFlags GetDescriptorBufferMemoryType(FVulkanDevice& Device)"
    marker = b"static VkShaderStageFlags MaterialRenderBindlessStages(FVulkanDevice& Device)"
    if data.count(marker) == 0 and data.count(anchor) == 1:
        helper = """// Older software Vulkan drivers can mishandle the reserved bits in ALL.
// Preserve every stage actually enabled on a CPU device used by this CLI.
static VkShaderStageFlags MaterialRenderBindlessStages(FVulkanDevice& Device)
{
#if PLATFORM_LINUX
    if (FParse::Param(FCommandLine::Get(), TEXT("MaterialRenderCpuVulkan")) &&
        Device.GetDeviceProperties().deviceType == VK_PHYSICAL_DEVICE_TYPE_CPU)
    {
        VkShaderStageFlags Stages = VK_SHADER_STAGE_ALL_GRAPHICS | VK_SHADER_STAGE_COMPUTE_BIT;
        const FOptionalVulkanDeviceExtensions& Extensions = Device.GetOptionalExtensions();
        if (Extensions.HasEXTMeshShader)
            Stages |= VK_SHADER_STAGE_TASK_BIT_EXT | VK_SHADER_STAGE_MESH_BIT_EXT;
        if (Extensions.HasRaytracingExtensions())
            Stages |= VK_SHADER_STAGE_RAYGEN_BIT_KHR | VK_SHADER_STAGE_ANY_HIT_BIT_KHR |
                VK_SHADER_STAGE_CLOSEST_HIT_BIT_KHR | VK_SHADER_STAGE_MISS_BIT_KHR |
                VK_SHADER_STAGE_INTERSECTION_BIT_KHR | VK_SHADER_STAGE_CALLABLE_BIT_KHR;
        return Stages;
    }
#endif
    return VK_SHADER_STAGE_ALL;
}

""".encode("utf-8").replace(b"\n", newline)
        changes[descriptors] = data.replace(anchor, helper + anchor, 1)
        missing.append("CPU bindless stage helper")
    elif data.count(marker) != 1 or data.count(anchor) != 1:
        raise SystemExit("Unexpected VulkanBindlessDescriptorManager.cpp helper state")

    replace_once(descriptors,
        b"\t\t.stageFlags = VK_SHADER_STAGE_ALL," + newline + b"\t\t.pImmutableSamplers = nullptr",
        b"\t\t.stageFlags = MaterialRenderBindlessStages(Device)," + newline + b"\t\t.pImmutableSamplers = nullptr",
        "acceleration-structure descriptor stages", version_scoped=(5, 8, 1))
    replace_once(descriptors,
        b"\t\t\t\t.stageFlags = VK_SHADER_STAGE_ALL,",
        b"\t\t\t\t.stageFlags = MaterialRenderBindlessStages(DeviceRef),",
        "bindless descriptor stages")
    replace_once(descriptors,
        b"DescriptorSetLayoutBindings[BindingIndex].stageFlags = VK_SHADER_STAGE_ALL;",
        b"DescriptorSetLayoutBindings[BindingIndex].stageFlags = MaterialRenderBindlessStages(Device);",
        "uniform-buffer descriptor stages")

    # UE 5.9 added mandatory Vulkan profile validation to IsSupported(SM6);
    # lavapipe/llvmpipe fails vpGetInstanceProfileSupport, so the RHI init
    # aborts before rendering. When this CLI runs on a CPU device, trust its
    # own capabilities and skip the profile gate entirely.
    newline_gate = b"\r\n" if b"\r\n" in changes[profile_gate] else b"\n"
    replace_once(profile_gate,
        b"static bool CheckVulkanProfile(ERHIFeatureLevel::Type FeatureLevel, bool bRaytracing)" + newline_gate + b"{" + newline_gate,
        b"static bool CheckVulkanProfile(ERHIFeatureLevel::Type FeatureLevel, bool bRaytracing)" + newline_gate + b"{" + newline_gate +
        b"#if PLATFORM_LINUX" + newline_gate +
        b"\tif (FParse::Param(FCommandLine::Get(), TEXT(\"AllowCPUDevices\")) && FParse::Param(FCommandLine::Get(), TEXT(\"MaterialRenderCpuVulkan\")))" + newline_gate +
        b"\t{" + newline_gate +
        b"\t\tUE_LOGF(LogVulkanRHI, Log, \"Skipping Vulkan Profile check for MaterialRender CPU Vulkan mode.\");" + newline_gate +
        b"\t\treturn true;" + newline_gate +
        b"\t}" + newline_gate +
        b"#endif" + newline_gate,
        "CPU Vulkan profile gate bypass", version_scoped=(5, 9, 0))

    if missing and not args.apply:
        raise SystemExit("UE CPU Vulkan fixes missing: " + ", ".join(missing) + "; run this script with --apply")
    if missing:
        for path, content in changes.items():
            if content != originals[path]:
                path.write_bytes(content)
        print("Applied UE CPU Vulkan fixes: " + ", ".join(missing))
    else:
        print("UE CPU Vulkan fixes already applied")


if __name__ == "__main__":
    main()
