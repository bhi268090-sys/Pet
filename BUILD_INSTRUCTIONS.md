# CubePet Build Instructions

## Automated Build
Double-click `build.bat` to build the executable.

## Manual Build
Run the following command in your terminal:
```powershell
pyinstaller CubePet.spec
```

## Troubleshooting: "File Not Found" or Missing Executable
If the build completes but `dist\CubePet.exe` is missing, or if you see a `FileNotFoundError` during the build process:

Your antivirus (e.g., Windows Defender) may quarantine unsigned PyInstaller executables.

This can be a false positive, but it can also be a real signal of suspicious behavior. Treat it as a prompt to review what the program does and rebuild from trusted source.

Recommended steps:
1. Verify you're building from the current source (not old artifacts in `build/` or `dist/`).
2. Rebuild and test on an isolated machine/VM.
3. If you distribute it, consider code signing and publishing hashes/releases so users can verify integrity.
