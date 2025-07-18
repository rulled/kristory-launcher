<#
.SYNOPSIS
    Скрипт для полной сборки приложения KRISTORY с изолированными окружениями Python.
.DESCRIPTION
    Этот скрипт автоматизирует весь процесс сборки релиза. Для каждого Python-компонента
    (бэкенд, установщик) создается отдельное, чистое виртуальное окружение, что гарантирует
    отсутствие конфликтов зависимостей.
.PARAMETER Version
    Обязательный параметр. Указывает версию для сборки (например, "1.0.0").
.EXAMPLE
    .\build.ps1 -Version "1.2.3"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version
)

# --- Блок конфигурации ---
$ReleaseDir = "release"
$BuildDir = "release/build"
$DistDir = "release/dist"
$PyWorkDir = "build_py_temp"
$VenvsDir = "build/venvs"

$SystemPython = "python"

$BackendAppName = "KRISTORYBackend"
$OnlineSetupName = "KRISTORY_Online_Setup_v$($Version)"

# --- Утилитарные функции ---

function Run-Command {
    param(
        [string]$Command,
        [array]$Arguments,
        [string]$ErrorMessage,
        [string]$WorkingDirectory = $PSScriptRoot
    )
    Write-Host "Выполняю в '$WorkingDirectory': $Command $($Arguments -join ' ')"
    $process = Start-Process -FilePath $Command -ArgumentList $Arguments -Wait -NoNewWindow -PassThru -WorkingDirectory $WorkingDirectory
    if ($process.ExitCode -ne 0) {
        throw "ОШИБКА: $ErrorMessage. Код выхода: $($process.ExitCode)"
    }
}

function Setup-PythonEnvironment {
    param(
        [string]$VenvName,
        [string]$RequirementsPath
    )
    # Корректный способ собрать путь: сначала до папки venvs, потом до конкретного venv
    $venvPath = Join-Path -Path (Join-Path -Path $PSScriptRoot -ChildPath $VenvsDir) -ChildPath $VenvName
    Write-Host "`n--- Настройка Python окружения '$VenvName' ---" -ForegroundColor Yellow

    if (-not (Test-Path $venvPath)) {
        Write-Host "Создаю виртуальное окружение в '$venvPath'..."
        Run-Command -Command $SystemPython -Arguments @("-m", "venv", $venvPath) -ErrorMessage "Не удалось создать venv для '$VenvName'"
    } else {
        Write-Host "Виртуальное окружение '$VenvName' уже существует."
    }

    $pythonInVenv = Join-Path -Path $venvPath -ChildPath "Scripts/python.exe"

    Write-Host "Устанавливаю зависимости из '$RequirementsPath'..."
    Run-Command -Command $pythonInVenv -Arguments @("-m", "pip", "install", "-r", $RequirementsPath) -ErrorMessage "Не удалось установить зависимости для '$VenvName'"

    return $pythonInVenv
}


# --- Основной процесс сборки ---
try {
    # --- ШАГ 0: Очистка и проверка окружения ---
    Write-Host "--- ШАГ 0: Очистка и проверка ---" -ForegroundColor Cyan
    # Удаляем только временные директории и результаты предыдущих сборок
    @( $ReleaseDir, "out", $PyWorkDir, "build" ) | ForEach-Object {
        if (Test-Path $_) {
            Write-Host "Удаляю старую директорию: $_"
            Remove-Item -Recurse -Force $_
        }
    }
    # Создаем необходимые директории заново
    New-Item -ItemType Directory -Force $BuildDir | Out-Null
    New-Item -ItemType Directory -Force $VenvsDir | Out-Null


    # Проверка и установка зависимостей Node.js
    Write-Host "--- Проверка и установка зависимостей Node.js ---" -ForegroundColor Cyan
    Run-Command -Command "npm.cmd" -Arguments @("install") -ErrorMessage "Не удалось установить зависимости Node.js"

    # --- ШАГ 1: Сборка фронтенда (Next.js) ---
    Write-Host "`n--- ШАГ 1: Сборка фронтенда (Next.js) ---" -ForegroundColor Cyan
    Run-Command -Command "npm.cmd" -Arguments @("run", "build:ui") -ErrorMessage "Сборка фронтенда провалена."

    # --- ШАГ 1.5: Оптимизация node_modules (npm prune + modclean) ---
    Write-Host "`n--- ШАГ 1.5: Оптимизация node_modules (npm prune + modclean) ---" -ForegroundColor Cyan
    if (Test-Path "node_modules") {
        # Удаляем dev-зависимости
        Write-Host "Удаляем dev-зависимости..." -ForegroundColor Yellow
        Run-Command -Command "npm.cmd" -Arguments @("prune", "--production") -ErrorMessage "Ошибка при удалении dev-зависимостей."
        
        # Очищаем мусорные файлы через modclean (если установлен)
        Write-Host "Очищаем мусорные файлы..." -ForegroundColor Yellow
        try {
            Run-Command -Command "npx.cmd" -Arguments @("modclean", "--run", "--patterns=default:safe") -ErrorMessage "Ошибка при очистке modclean."
            Write-Host "Modclean выполнен успешно!" -ForegroundColor Green
        } catch {
            Write-Host "Modclean не установлен или произошла ошибка. Продолжаем без него." -ForegroundColor Yellow
        }
    } else {
        Write-Host "Папка node_modules не найдена. Пропускаем оптимизацию." -ForegroundColor Yellow
    }

    # --- ШАГ 2: Сборка бэкенда (Python) ---
    $backendPythonExe = Setup-PythonEnvironment -VenvName "backend" -RequirementsPath "backend/requirements.txt"
    Write-Host "`n--- ШАГ 2: Сборка бэкенда (Python) ---" -ForegroundColor Cyan
    Run-Command `
        -Command $backendPythonExe `
        -Arguments @("-m", "PyInstaller", "KRISTORYBackend.spec", "--distpath", $BuildDir, "--workpath", $PyWorkDir) `
        -ErrorMessage "Сборка бэкенда провалена."

    # --- ШАГ 3: Сборка Electron-приложения и установщиков ---
    Write-Host "`n--- ШАГ 3: Сборка Electron-приложения и установщиков ---" -ForegroundColor Cyan
    try {
        $packageJsonPath = Join-Path -Path $PSScriptRoot -ChildPath "package.json"
        $packageJson = Get-Content -Raw -Path $packageJsonPath | ConvertFrom-Json
        $packageJson.version = $Version
        $packageJson | ConvertTo-Json -Depth 100 | Set-Content -Path $packageJsonPath -Encoding UTF8
        Write-Host "Версия в package.json обновлена на $Version"
    }
    catch {
        throw "Не удалось обновить версию в package.json. Ошибка: $_"
    }
    Run-Command -Command "npx.cmd" -Arguments @("electron-builder", "--win", "--x64") -ErrorMessage "Сборка Electron-приложения провалена."
    Write-Host "Полный установщик и портативная версия созданы в $DistDir"

    # --- ШАГ 4: Сборка онлайн-установщика ---
    $installerPythonExe = Setup-PythonEnvironment -VenvName "installer" -RequirementsPath "installer/requirements.txt"
    Write-Host "`n--- ШАГ 4: Сборка онлайн-установщика ---" -ForegroundColor Cyan
    Run-Command `
        -Command $installerPythonExe `
        -Arguments @("-m", "PyInstaller", `
                    "--name", $OnlineSetupName, `
                    "--onefile", `
                    "--windowed", `
                    "--distpath", $DistDir, `
                    "--workpath", $PyWorkDir, `
                    "--icon", "public/icon.ico", `
                    "--add-data", "public;public", `
                    "--manifest", "installer/manifest.xml", `
                    "installer/bootstrapper.py") `
        -ErrorMessage "Сборка онлайн-установщика провалена."


    Write-Host -ForegroundColor Green "`n--- СБОРКА УСПЕШНО ЗАВЕРШЕНА ---"
    Write-Host "Все готовые файлы находятся в папке '$DistDir':"
    Get-ChildItem -Path $DistDir | ForEach-Object { Write-Host " - $($_.Name)" }
}
catch {
    Write-Host -ForegroundColor Red "`n--- ОШИБКА: $($_.Exception.Message) ---"
    exit 1
}
finally {
    # Очистка временной папки сборки python
    if (Test-Path $PyWorkDir) {
        Remove-Item -Recurse -Force $PyWorkDir
    }
    # Очистка spec файла, если он создается автоматически
    Get-ChildItem -Path $PSScriptRoot -Filter "*.spec" | ForEach-Object {
        if ($_.Name -ne "KRISTORYBackend.spec") {
            Remove-Item $_.FullName
        }
    }
}
