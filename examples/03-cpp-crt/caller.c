#include <stdio.h>

__declspec(dllimport) int __stdcall GetWidget(void);

/* dll2lib emits this bootstrap. Call it ONCE before using any export: it runs
 * the fused DLL's CRT startup (C++ global ctors) and DllMain(DLL_PROCESS_ATTACH). */
extern void __cdecl widget_StaticInit(void);

int main(void)
{
    printf("before StaticInit: GetWidget() = %d  (expected 0)\n", GetWidget());

    widget_StaticInit();   /* <-- runs the C++ ctor (g=40) and DllMain (+2) */

    int v = GetWidget();
    printf("after  StaticInit: GetWidget() = %d  (expected 42)\n", v);
    return v == 42 ? 0 : 1;
}
