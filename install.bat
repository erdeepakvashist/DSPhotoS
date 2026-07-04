@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==============================================
echo   DS PhotoS - Installer
echo ==============================================
echo.

rem --- Step 1: make sure every dependency this installer needs is present ---
rem Locate a usable Python (prefer 3.12); if none is found, install one
rem automatically so this works on a bare machine with no intervention.
call :find_python
if not defined PYEXE (
    echo Python was not found - installing it automatically...
    echo.
    call :install_python
    call :find_python
)

if not defined PYEXE (
    echo.
    echo Automatic Python install did not succeed.
    echo Please install Python 3.12 from https://www.python.org/downloads/
    echo ^(check "Add python.exe to PATH" during setup^), then run install.bat again.
    echo.
    pause
    exit /b 1
)

echo Using Python: %PYEXE%
echo.

rem Best-effort: the Visual C++ runtime some wheels (onnxruntime/torch) need
rem is preinstalled on nearly all Windows 10/11 machines; only try to add it
rem if winget is available, and never fail the install if this step fails.
where winget >nul 2>&1
if !errorlevel! equ 0 (
    winget install -e --id Microsoft.VCRedist.2015+.x64 --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
)

goto :after_python_setup

:find_python
set "PYEXE="
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    exit /b 0
)
py -3.12 -c "" >nul 2>&1
if !errorlevel! equ 0 (
    set "PYEXE=py -3.12"
    exit /b 0
)
py -3 -c "" >nul 2>&1
if !errorlevel! equ 0 (
    set "PYEXE=py -3"
    exit /b 0
)
where python >nul 2>&1
if !errorlevel! equ 0 (
    set "PYEXE=python"
    exit /b 0
)
exit /b 1

:install_python
rem Prefer winget (built into Windows 10 2004+ / Windows 11) for a trusted,
rem fully silent install; fall back to downloading the official installer.
where winget >nul 2>&1
if !errorlevel! equ 0 (
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if !errorlevel! equ 0 exit /b 0
)

echo winget install unavailable or failed, downloading Python directly...
set "PY_INSTALLER=%TEMP%\python-3.12-installer.exe"
curl -fsSL -o "%PY_INSTALLER%" "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
if not exist "%PY_INSTALLER%" (
    echo Download failed.
    exit /b 1
)
start /wait "" "%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
del "%PY_INSTALLER%" >nul 2>&1
exit /b 0

:after_python_setup

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
