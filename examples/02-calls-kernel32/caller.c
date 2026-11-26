#include <stdio.h>

__declspec(dllimport) int __stdcall MyStrLen(const char* s);

int main(void)
{
    int n = MyStrLen("hello world");   /* fused code calls kernel32!lstrlenA */
    printf("MyStrLen(\"hello world\") = %d  (expected 11)\n", n);
    return n == 11 ? 0 : 1;
}
