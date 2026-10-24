@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ===========================================================================
rem  采购与项目管理平台 - Windows 一键启动
rem ---------------------------------------------------------------------------
rem  用法：
rem    双击 start.bat              -> 检查环境并启动（后端 8000 + 前端 5173，自动开浏览器）
rem    start.bat --check           -> 只检查环境，不启动（CI/排障用）
rem  停止：运行 stop.bat，或直接关闭弹出的两个命令行窗口
rem
rem  说明：
rem    - 首次运行会自动创建 backend\.venv 并安装依赖、安装前端 node_modules，耗时较长；
rem    - 脚本只读取/创建本地依赖目录，不改动代码；
rem    - 若 8000/5173 已被占用，会提示并跳过重复启动。
rem ===========================================================================

echo ============================================
echo   采购与项目管理平台 - 一键启动
echo ============================================
echo.

set CHECK=0
if /i "%~1"=="--check" set CHECK=1

rem --------------------------------------------------------------- 1/4 Python
if exist "backend\.venv\Scripts\python.exe" (
  echo [1/4] 后端虚拟环境：已存在
) else (
  echo [1/4] 后端虚拟环境：未找到，正在创建（首次较慢）...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv backend\.venv
  ) else (
    python -m venv backend\.venv
  )
  if not exist "backend\.venv\Scripts\python.exe" (
    echo   [错误] 创建虚拟环境失败：请先安装 Python 3.11+ 并加入 PATH
    goto :fail
  )
  echo   安装后端依赖...
  backend\.venv\Scripts\python.exe -m pip install -q --upgrade pip
  backend\.venv\Scripts\python.exe -m pip install -q -r backend\requirements.txt
  if errorlevel 1 (
    echo   [错误] 后端依赖安装失败，请检查网络；可手动执行：
    echo     backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
    goto :fail
  )
)

rem --------------------------------------------------------------- 2/4 Node
where node >nul 2>nul
if errorlevel 1 (
  echo [2/4] 前端依赖：[跳过] 未检测到 Node.js —— 仅用后端托管模式时无需前端
  set HAS_NODE=0
) else (
  set HAS_NODE=1
  if exist "frontend\node_modules" (
    echo [2/4] 前端依赖：已存在
  ) else (
    echo [2/4] 前端依赖：未找到，正在安装（首次较慢）...
    pushd frontend
    call npm install --no-audit --no-fund
    popd
    if not exist "frontend\node_modules" (
      echo   [错误] 前端依赖安装失败，请手动执行：cd frontend ^&^& npm install
      goto :fail
    )
  )
)

rem --------------------------------------------------------------- 3/4 配置
if not exist "backend\.env" (
  if exist "backend\.env.example" (
    copy /y "backend\.env.example" "backend\.env" >nul
    echo [3/4] 配置：已从 .env.example 生成 backend\.env（生产请修改 XUNJIA_SECRET_KEY）
  ) else (
    echo [3/4] 配置：未找到 backend\.env，将使用默认配置（内网演示可用）
  )
) else (
  echo [3/4] 配置：backend\.env 已存在
)

rem --------------------------------------------------------------- 4/4 端口
set PORT8000=0
set PORT5173=0
for /f "tokens=*" %%L in ('netstat -ano ^| findstr /r /c:":8000 .*LISTENING"') do set PORT8000=1
for /f "tokens=*" %%L in ('netstat -ano ^| findstr /r /c:":5173 .*LISTENING"') do set PORT5173=1
echo [4/4] 端口：8000=%PORT8000% 5173=%PORT5173% （1=已被占用）

echo.
if %CHECK%==1 (
  echo [检查模式] 环境检查完成，未启动任何服务。
  goto :done
)

rem --------------------------------------------------------------- 启动
if %PORT8000%==1 (
  echo [跳过] 8000 已有服务在运行，不再重复启动后端。
) else (
  echo 启动后端： http://127.0.0.1:8000  ^(API 文档 /docs^)
  start "XJ-后端 8000" /D "%~dp0backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
)

if %HAS_NODE%==0 (
  echo.
  echo 未安装 Node.js：只启动后端。前端页面可直接访问 http://127.0.0.1:8000/
  echo ^(后端已托管 frontend\dist；如需前端热更新请安装 Node.js 后重跑本脚本^)
  start "" http://127.0.0.1:8000/
  goto :done
)

if %PORT5173%==1 (
  echo [跳过] 5173 已有服务在运行，不再重复启动前端。
) else (
  echo 启动前端： http://127.0.0.1:5173  ^(热更新开发服务器^)
  start "XJ-前端 5173" /D "%~dp0frontend" cmd /k "npm run dev"
)

echo.
echo 等待服务就绪（约 8 秒）后自动打开浏览器...
timeout /t 8 /nobreak >nul
start "" http://127.0.0.1:5173

:done
echo.
echo 常用账号：admin / Admin@2026  -  wangcaigou / buyer123  -  hengxin_wenju / supplier123
echo 停止服务：运行 stop.bat，或关闭弹出的命令行窗口。
echo.
rem 检查模式供脚本/CI 调用，不阻塞等待按键
if not "%CHECK%"=="1" pause
exit /b 0

:fail
echo.
echo 启动失败，请按上面的提示处理后重试。
pause
exit /b 1
