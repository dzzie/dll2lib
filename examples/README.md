# dll2lib examples

Three self-contained demos, each building a DLL, converting it to a static
`.lib` with `dll2lib`, linking a caller, then **deleting the DLL** and running
the program to prove the code is fused in.

| Folder | Shows |
|---|---|
| [`01-hello-export`](01-hello-export/) | the basics: one `__stdcall` export + a relocated global |
| [`02-calls-kernel32`](02-calls-kernel32/) | **import rebuild** — a DLL that calls `kernel32!lstrlenA` |
| [`03-cpp-crt`](03-cpp-crt/) | **the bootstrap** — a real `/MT` C++ DLL with a global ctor + `DllMain` |

## Running

Open an **"x86 Native Tools Command Prompt for VS"** (so `cl` / `link` / `lib`
are on PATH and target 32-bit), make sure `python` is on PATH, then in a demo
folder:

```
build.cmd
```

Each `build.cmd` prints the steps and ends by running `demo.exe`. Exit code 0
means success. The `.dll` is deleted before the run, so a successful run proves
there is no runtime dependency on it.

> These produce 32-bit (i386) output — dll2lib v1 is PE32/i386 only.
