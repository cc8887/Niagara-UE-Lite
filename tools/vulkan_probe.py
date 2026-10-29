"""Minimal Vulkan CPU-adapter discovery using the loader shipped with UE."""
import ctypes as c
from pathlib import Path

def cpu_adapter(package):
    paths=list(Path(package).glob('**/Vulkan/Linux/libvulkan.so.1'))
    vk=c.CDLL(str(paths[0]) if paths else 'libvulkan.so.1')
    class App(c.Structure):
        _fields_=[('sType',c.c_uint32),('pNext',c.c_void_p),('name',c.c_char_p),('version',c.c_uint32),
                  ('engine',c.c_char_p),('engineVersion',c.c_uint32),('apiVersion',c.c_uint32)]
    class Create(c.Structure):
        _fields_=[('sType',c.c_uint32),('pNext',c.c_void_p),('flags',c.c_uint32),('app',c.POINTER(App)),
                  ('layerCount',c.c_uint32),('layers',c.c_void_p),('extensionCount',c.c_uint32),('extensions',c.c_void_p)]
    class Extension(c.Structure):
        _fields_=[('name',c.c_char*256),('version',c.c_uint32)]
    vk.vkCreateInstance.argtypes=[c.POINTER(Create),c.c_void_p,c.POINTER(c.c_void_p)]
    vk.vkDestroyInstance.argtypes=[c.c_void_p,c.c_void_p]
    vk.vkEnumeratePhysicalDevices.argtypes=[c.c_void_p,c.POINTER(c.c_uint32),c.POINTER(c.c_void_p)]
    vk.vkGetPhysicalDeviceProperties.argtypes=[c.c_void_p,c.c_void_p]
    vk.vkEnumerateDeviceExtensionProperties.argtypes=[c.c_void_p,c.c_char_p,c.POINTER(c.c_uint32),c.POINTER(Extension)]
    app=App(0,None,b'Niagara-UE-Lite',1,b'UE',1,(1<<22)|(3<<12));info=Create(1,None,0,c.pointer(app),0,None,0,None)
    instance=c.c_void_p()
    if vk.vkCreateInstance(c.byref(info),None,c.byref(instance))!=0:raise RuntimeError('Unable to create Vulkan 1.3 probe instance')
    try:
        count=c.c_uint32()
        if vk.vkEnumeratePhysicalDevices(instance,c.byref(count),None)!=0:raise RuntimeError('Vulkan enumeration failed')
        devices=(c.c_void_p*count.value)()
        if vk.vkEnumeratePhysicalDevices(instance,c.byref(count),devices)!=0:raise RuntimeError('Vulkan enumeration failed')
        for index,device in enumerate(devices):
            properties=c.create_string_buffer(4096);vk.vkGetPhysicalDeviceProperties(device,properties)
            if int.from_bytes(properties.raw[16:20],'little')!=4:continue # VK_PHYSICAL_DEVICE_TYPE_CPU
            name=properties.raw[20:276].split(b'\0',1)[0].decode('utf-8')
            n=c.c_uint32();vk.vkEnumerateDeviceExtensionProperties(device,None,c.byref(n),None)
            extensions=(Extension*n.value)();vk.vkEnumerateDeviceExtensionProperties(device,None,c.byref(n),extensions)
            names={bytes(x.name).decode('ascii') for x in extensions}
            if 'VK_EXT_shader_image_atomic_int64' not in names:
                raise RuntimeError('CPU Vulkan driver lacks VK_EXT_shader_image_atomic_int64 required by UE SM6')
            return {'index':index,'name':name,'deviceType':'CPU','shaderImageAtomicInt64Extension':True}
        raise RuntimeError('No CPU Vulkan adapter found; install a suitable Mesa lavapipe driver')
    finally:vk.vkDestroyInstance(instance,None)
