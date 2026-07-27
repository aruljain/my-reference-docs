@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  Removes "misc docs/projects.zip" from ALL git history
REM  and force-pushes the cleaned history back to origin.
REM
REM  Run this from the ROOT of your local git repo
REM  (the folder that contains the .git folder).
REM ============================================================

echo.
echo === Checking this is a git repository ===
if not exist ".git" (
    echo ERROR: No .git folder found here.
    echo Please run this .bat file from inside your repo folder.
    pause
    exit /b 1
)

echo.
echo === Checking for git-filter-repo python module ===
python -m git_filter_repo --version >nul 2>nul
if errorlevel 1 (
    echo git_filter_repo module not found. Installing via pip...
    pip install git-filter-repo
    if errorlevel 1 (
        echo ERROR: Failed to install git-filter-repo.
        pause
        exit /b 1
    )
)

echo.
echo === Saving current remote URL ===
for /f "delims=" %%i in ('git remote get-url origin') do set REMOTE_URL=%%i
echo Remote is: %REMOTE_URL%

echo.
echo === Removing "misc docs/projects.zip" from history ===
python -m git_filter_repo --path "misc docs/projects.zip" --invert-paths --force
if errorlevel 1 (
    echo ERROR: git-filter-repo failed. Aborting before push.
    pause
    exit /b 1
)

echo.
echo === Re-adding origin remote if needed ===
git remote get-url origin >nul 2>nul
if errorlevel 1 (
    git remote add origin "%REMOTE_URL%"
) else (
    git remote set-url origin "%REMOTE_URL%"
)

echo.
echo === Adding .gitignore entry so it doesn't come back (if not already there) ===
findstr /c:"misc docs/projects.zip" .gitignore >nul 2>nul
if errorlevel 1 (
    echo misc docs/projects.zip>> .gitignore
    git add .gitignore
    git commit -m "Ignore projects.zip"
)

echo.
echo === Force-pushing cleaned history to GitHub ===
git push origin --force --all
git push origin --force --tags

echo.
echo ============================================================
echo  DONE. History has been rewritten and pushed.
echo  Anyone else who cloned this repo must re-clone it, or run:
echo     git fetch origin
echo     git reset --hard origin/main
echo ============================================================
pause