/* A DLL that IMPORTS from another DLL (kernel32!lstrlenA) and re-exports it.
 * When dll2lib fuses this, it rebuilds the import table so the host exe pulls
 * kernel32!lstrlenA itself -- the DLL's dependency becomes the host's. */
__declspec(dllimport) int __stdcall lstrlenA(const char* s);

int __stdcall MyStrLen(const char* s) { return lstrlenA(s); }
