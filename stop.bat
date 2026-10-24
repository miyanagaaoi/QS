@echo off
chcp 936 >nul
setlocal enabledelayedexpansion

rem ===========================================================================
rem  采购与项目管理平台 - 停止本机服务
rem ---------------------------------------------------------------------------
rem  用法：
rem    stop.bat            按端口结束 start.bat 启动的后端(8000)与前端(5173)
rem    stop.bat --check    只列出占用端口的进程 PID，不结束（排障用）
rem  说明：只结束监听这两个端口的进程，不会误杀其它程序。
rem ===========================================================================

echo ============================================
echo   采购与项目管理平台 - 停止本机服务
echo ============================================
echo.

set CHECK=0
if /i "%~1"=="--check" set CHECK=1

set KILLED=0
for %%P in (8000 5173) do (
  set FOUND=0
  for /f "tokens=*" %%L in ('netstat -ano ^| findstr /r /c:":%%P .*LISTENING"') do (
    for /f "tokens=5" %%I in ("%%L") do (
      if not "%%I"=="0" (
        set FOUND=1
        set KILLED=1
        if "%CHECK%"=="1" (
          echo [检查模式] 端口 %%P 的监听进程 PID=%%I ^(未结束^)
        ) else (
          echo 结束端口 %%P 的进程 PID=%%I
          taskkill /F /PID %%I >nul 2>nul
        )
      )
    )
  )
  if !FOUND!==0 echo 端口 %%P：无监听进程
)

echo.
if "%CHECK%"=="1" (
  echo [检查模式] 以上仅为检测结果，未结束任何进程。
) else (
  if %KILLED%==1 (
    echo 已结束相关进程。
  ) else (
    echo 没有需要结束的进程。
  )
)
echo.
if not "%CHECK%"=="1" pause
exit /b 0
