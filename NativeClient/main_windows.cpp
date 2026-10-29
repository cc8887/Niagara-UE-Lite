#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string>
#include <vector>
#include <cstdio>

static std::wstring Quote(const std::wstring& text)
{
    std::wstring out=L"\"";size_t slashes=0;
    for(wchar_t c:text)
    {
        if(c==L'\\'){++slashes;continue;}
        if(c==L'\"'){out.append(slashes*2+1,L'\\');out+=c;slashes=0;continue;}
        out.append(slashes,L'\\');slashes=0;out+=c;
    }
    out.append(slashes*2,L'\\');return out+L"\"";
}
int wmain(int argc,wchar_t** argv)
{
    std::vector<wchar_t> path(32768);DWORD count=GetModuleFileNameW(nullptr,path.data(),DWORD(path.size()));
    if(!count||count==path.size())return 2;
    std::wstring root(path.data(),count);root.resize(root.find_last_of(L"\\/"));
    const std::wstring home=root+L"\\backend\\Engine\\Binaries\\ThirdParty\\Python3\\Win64";
    const std::wstring exe=home+L"\\python.exe";
    SetEnvironmentVariableW(L"PYTHONHOME",home.c_str());SetEnvironmentVariableW(L"PYTHONNOUSERSITE",L"1");
    std::wstring command=Quote(exe)+L" "+Quote(root+L"\\scripts\\niagara_cli.py");
    for(int i=1;i<argc;++i)command+=L" "+Quote(argv[i]);
    STARTUPINFOW start{};start.cb=sizeof(start);PROCESS_INFORMATION proc{};
    start.dwFlags=STARTF_USESTDHANDLES;
    start.hStdInput=GetStdHandle(STD_INPUT_HANDLE);
    start.hStdOutput=GetStdHandle(STD_OUTPUT_HANDLE);
    start.hStdError=GetStdHandle(STD_ERROR_HANDLE);
    if(!CreateProcessW(exe.c_str(),command.data(),nullptr,nullptr,TRUE,CREATE_NO_WINDOW,nullptr,nullptr,&start,&proc))
    {std::fprintf(stderr,"Unable to start bundled Python (Windows error %lu)\n",GetLastError());return 2;}
    WaitForSingleObject(proc.hProcess,INFINITE);DWORD code=1;GetExitCodeProcess(proc.hProcess,&code);
    CloseHandle(proc.hThread);CloseHandle(proc.hProcess);return int(code);
}
