@echo off
echo Building CubePet...
pip install pyinstaller pypresence winotify win10toast
pyinstaller --clean --noconfirm CubePet.spec
echo.
echo Build complete. Check the 'dist' folder.
echo If the 'dist' folder is empty or the exe is missing, your Antivirus might have deleted it.
echo Please check your Antivirus quarantine or exclusion settings.
pause
