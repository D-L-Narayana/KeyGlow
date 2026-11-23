@echo off
rem Builds KeyGlow.exe into the repository folder from the source in src\
cd /d "%~dp0.."
python -m PyInstaller --noconfirm --clean --distpath . --workpath build\work build\KeyGlow.spec
