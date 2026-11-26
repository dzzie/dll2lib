#include <stdio.h>

/* Declared dllimport, but we link the STATIC lib -- dll2lib provides both the
 * direct symbol and the __imp__ slot, so this resolves with no hello.dll. */
__declspec(dllimport) int __stdcall AddNumbers(int a, int b);

int main(void)
{
    int r = AddNumbers(20, 22);   /* 20 + 22 + 100 = 142 */
    printf("AddNumbers(20, 22) = %d  (expected 142)\n", r);
    return r == 142 ? 0 : 1;
}
