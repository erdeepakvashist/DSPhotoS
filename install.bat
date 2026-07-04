@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==============================================
echo   DS PhotoS - Installer
echo ==============================================
echo.

rem --- Locate a usable Python (prefer 3.12) ---
set "PYEXE="

if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)

if not defined PYEXE (
    py -3.12 -c "" >nul 2>&1
    if !errorlevel! equ 0 set "PYEXE=py -3.12"
)

if not defined PYEXE (
    py -3 -c "" >nul 2>&1
    if !errorlevel! equ 0 set "PYEXE=py -3"
)

if not defined PYEXE (
    where python >nul 2>&1
    if !errorlevel! equ 0 set "PYEXE=python"
)

if not defined PYEXE (
    echo Python was not found on this machine.
    echo.
    echo Please install Python 3.12 from https://www.python.org/downloads/
    echo ^(check "Add python.exe to PATH" during setup^), then run install.bat again.
    echo.
    pause
    exit /b 1
)

echo Using Python: %PYEXE%
echo.

rem --- Guarantee a clean, empty photo database on every new install ---
rem A fresh git clone never has a data\ folder (it's gitignored), so if one
rem shows up here on a first-ever install, this copy was zipped/copied from
rem a machine that had already scanned photos. Reset it so nobody else's
rem photos, faces, or thumbnails ship with the install. AI models are kept
rem to avoid a ~650 MB re-download.
if not exist .venv (
    if exist data\photos.db (
        echo A photo database already exists in this folder:
        echo   %cd%\data\photos.db
        echo.
        echo A new install must start with no photos, faces, or thumbnails
        echo from a previous setup.
        set /p RESET_DATA="Clear it for a clean install? [Y/n] "
        if /i not "!RESET_DATA!"=="n" (
            echo Clearing existing photo data...
            del /q data\photos.db data\photos.db-shm data\photos.db-wal >nul 2>&1
            if exist data\thumbs rmdir /s /q data\thumbs >nul 2>&1
            echo Done.
        )
        echo.
    )
)

rem --- Create the virtual environment ---
if not exist .venv (
    echo Creating virtual environment...
    %PYEXE% -m venv .venv
    if not exist .venv\Scripts\python.exe (
        echo Failed to create the virtual environment.
        pause
        exit /b 1
    )
) else (
    echo Virtual environment already exists, skipping creation.
)

echo.
echo Installing dependencies ^(this may take a few minutes^)...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Dependency installation failed. See the error above.
    pause
    exit /b 1
)

rem --- Create a desktop shortcut for one-click launches ---
echo.
echo Creating desktop shortcut...
set "SHORTCUT_VBS=%TEMP%\dsphotos_shortcut_%RANDOM%.vbs"
> "%SHORTCUT_VBS%" echo Set oWS = WScript.CreateObject("WScript.Shell")
>> "%SHORTCUT_VBS%" echo sLinkFile = oWS.SpecialFolders("Desktop") ^& "\DS PhotoS.lnk"
>> "%SHORTCUT_VBS%" echo Set oLink = oWS.CreateShortcut(sLinkFile)
>> "%SHORTCUT_VBS%" echo oLink.TargetPath = "%~dp0run.bat"
>> "%SHORTCUT_VBS%" echo oLink.WorkingDirectory = "%~dp0"
>> "%SHORTCUT_VBS%" echo oLink.WindowStyle = 7
>> "%SHORTCUT_VBS%" echo oLink.IconLocation = "shell32.dll,220"
>> "%SHORTCUT_VBS%" echo oLink.Description = "DS PhotoS - local photo search"
>> "%SHORTCUT_VBS%" echo oLink.Save
cscript //nologo "%SHORTCUT_VBS%" >nul 2>&1
del "%SHORTCUT_VBS%" >nul 2>&1

echo.
echo ==============================================
echo   Install complete!
echo ==============================================
echo   A "DS PhotoS" shortcut was added to your Desktop.
echo   Double-click it any time to launch the app
echo   ^(first launch also downloads the AI models, ~650 MB^).
echo ==============================================
echo.

set /p LAUNCH_NOW="Launch DS PhotoS now? [Y/n] "
if /i "%LAUNCH_NOW%"=="n" goto :end
call run.bat

:end
endlocal
