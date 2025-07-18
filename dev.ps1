# --- НАСТРОЙКА ОКНА POWERSHELL ДЛЯ УДОБНОГО ЛОГИРОВАНИЯ ---
# Увеличиваем размер буфера и окна, чтобы логи не "убегали"
$Host.UI.RawUI.BufferSize = New-Object System.Management.Automation.Host.Size(500, 9999)
$Host.UI.RawUI.WindowSize = New-Object System.Management.Automation.Host.Size(150, 50)


# --- ФУНКЦИЯ ДЛЯ ПРОВЕРКИ И УСТАНОВКИ PYTHON ЗАВИСИМОСТЕЙ ---
function Ensure-PythonDependencies {
    # 1. Проверяем, существует ли папка виртуального окружения
    if (-not (Test-Path -Path ".venv")) {
        Write-Host "Виртуальное окружение Python не найдено. Создаю..." -ForegroundColor Yellow
        
        # 2. Пытаемся найти python.exe или python3.exe
        $pythonExecutable = Get-Command python, python3 -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $pythonExecutable) {
            Write-Host "ОШИБКА: Python не найден в системе. Пожалуйста, установите Python 3.8+ и убедитесь, что он добавлен в PATH." -ForegroundColor Red
            throw "Python не найден"
        }
        
        Write-Host "Используется Python: $($pythonExecutable.Source)"
        
        # 3. Создаем виртуальное окружение
        & $pythonExecutable.Source -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ОШИБКА: Не удалось создать виртуальное окружение." -ForegroundColor Red
            throw "Ошибка создания venv"
        }
        Write-Host "Виртуальное окружение создано." -ForegroundColor Green
    }
    
    # 4. Активируем окружение и устанавливаем зависимости
    Write-Host "Активация окружения и установка зависимостей из backend/requirements.txt..."
    # Путь к pip в venv
    $pipPath = Join-Path -Path ".venv" -ChildPath "Scripts\pip.exe"
    & $pipPath install -r (Join-Path -Path "backend" -ChildPath "requirements.txt")
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ОШИБКА: Не удалось установить зависимости Python." -ForegroundColor Red
        throw "Ошибка pip install"
    }
    
    Write-Host "Зависимости Python успешно установлены." -ForegroundColor Green
}


# --- ФУНКЦИЯ ДЛЯ ПРОВЕРКИ И УСТАНОВКИ NODE.JS ЗАВИСИМОСТЕЙ ---
function Ensure-NodeDependencies {
    if (-not (Test-Path -Path "node_modules")) {
        Write-Host "Папка node_modules не найдена. Устанавливаю зависимости..." -ForegroundColor Yellow
        npm install
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ОШИБКА: Не удалось установить зависимости Node.js." -ForegroundColor Red
            throw "Ошибка npm install"
        }
        Write-Host "Зависимости Node.js успешно установлены." -ForegroundColor Green
    } else {
        Write-Host "Зависимости Node.js уже установлены." -ForegroundColor Cyan
    }
}


# --- ГЛАВНЫЙ БЛОК СКРИПТА ---

# 1. Проверяем и настраиваем всё необходимое
try {
    Write-Host "--- Этап 1: Проверка зависимостей Python ---" -ForegroundColor Magenta
    Ensure-PythonDependencies
    Write-Host ""
    Write-Host "--- Этап 2: Проверка зависимостей Node.js ---" -ForegroundColor Magenta
    Ensure-NodeDependencies
    Write-Host ""
} catch {
    Write-Host "Произошла критическая ошибка при настройке окружения. Пожалуйста, проверьте сообщения выше." -ForegroundColor Red
    # Выходим из скрипта, если что-то пошло не так
    exit 1
}


# 2. Предлагаем пользователю выбор
Write-Host "--- Режим Запуска ---" -ForegroundColor Magenta
Write-Host "1. Запустить только бэкенд (Python)"
Write-Host "2. Запустить только фронтенд (Next.js)"
Write-Host "[Enter] Запустить всё (Бэкенд в новом окне, Фронтенд в текущем)" -ForegroundColor Yellow

$choice = Read-Host "Выберите действие (1, 2 или нажмите Enter)"

# 3. Запускаем выбранный режим
switch ($choice) {
    "1" {
        # Запустить только бэкенд
        Write-Host "Запускаю только бэкенд..."
        & ".\.venv\Scripts\python.exe" -m backend
    }
    "2" {
        # Запустить только фронтенд
        Write-Host "Запускаю только фронтенд..."
        npm run dev
    }
    default {
        # Запустить всё (по умолчанию)
        Write-Host "Запускаю бэкенд в новом окне и фронтенд в этом..."
        
        # Запускаем бэкенд в новом окне PowerShell
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "& '.\.venv\Scripts\python.exe' -m backend"
        
        # Запускаем фронтенд в текущем окне
        npm run dev
    }
}
