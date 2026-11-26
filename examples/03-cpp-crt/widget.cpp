// A normal C++ DLL built with the static CRT (/MT): a C++ global constructor
// and a DllMain. Neither runs unless the DLL's CRT entry (DllMainCRTStartup)
// is invoked -- which is exactly what dll2lib's _widget_StaticInit bootstrap
// does for a fused build.
#include <windows.h>

static int g_value;                                   // 0 until initialized

struct Init { Init() { g_value = 40; } };             // runs during CRT init (_initterm)
static Init g_init;

extern "C" __declspec(dllexport) int __stdcall GetWidget(void) { return g_value; }

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID p)
{
    if (reason == DLL_PROCESS_ATTACH) g_value += 2;   // 40 + 2 = 42
    return TRUE;
}
