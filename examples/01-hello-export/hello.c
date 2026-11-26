/* A tiny __stdcall DLL with one export.
 * g_bias is volatile so the optimizer keeps the memory load -- that gives us a
 * real base relocation (code -> data) for dll2lib to convert. */
static volatile int g_bias = 100;

int __stdcall AddNumbers(int a, int b) { return a + b + g_bias; }
