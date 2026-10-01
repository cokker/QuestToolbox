#define UNICODE
#define _UNICODE
#include <windows.h>
#include <wchar.h>
#include <stdio.h>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command, int show) {
    wchar_t directory[32768], python[32768], script[32768], args[65536];
    DWORD length = GetModuleFileNameW(NULL, directory, 32768);
    if (!length || length >= 32768) return 1;
    wchar_t *slash = wcsrchr(directory, L'\\');
    if (!slash) return 1;
    *slash = 0;
    if (swprintf(python, 32768, L"%ls\\runtime\\pythonw.exe", directory) < 0 ||
        swprintf(script, 32768, L"%ls\\main.py", directory) < 0) return 1;
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES || GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"Extract the entire ZIP before launching QuestToolbox.exe. Keep the runtime and quest_toolbox folders beside it.", L"Quest Toolbox", MB_OK | MB_ICONERROR);
        return 1;
    }
    swprintf(args, 65536, L"\"%ls\" \"%ls\"", python, script);
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");
    if (!CreateProcessW(python, args, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, directory, &startup, &process)) {
        MessageBoxW(NULL, L"Could not start the bundled runtime. Re-extract the archive and check antivirus quarantine.", L"Quest Toolbox", MB_OK | MB_ICONERROR);
        return 1;
    }
    CloseHandle(process.hThread);
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD result = 1;
    GetExitCodeProcess(process.hProcess, &result);
    CloseHandle(process.hProcess);
    return (int)result;
}
