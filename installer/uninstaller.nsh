!include "MUI2.nsh"
!include "LogicLib.nsh"

; Указываем NSIS, что плагины могут лежать в корневой папке проекта
!addplugindir "."

!macro customUnInstall
    ; ЗАГРУЖАЕМ JSON ИЗ ФАЙЛА
    ; nsJSON сам обработает файл и найдет нужные данные
    nsJSON::Set /file "$APPDATA\KRISTORY\launcher_config.json"

    ; Если произошла ошибка (файл не найден, это не JSON), переходим к концу
    IfErrors EndGameDirDelete

    ; ПОЛУЧАЕМ ЗНАЧЕНИЕ ПО КЛЮЧЮ "game_directory"
    ; nsJSON::Get извлекает чистый путь в переменную $R4
    nsJSON::Get "game_directory" $R4

    ; Если ключ не найден или его значение пустое, переходим к концу
    IfErrors EndGameDirDelete

    ; ПРОВЕРЯЕМ, ЧТО ПУТЬ НЕ ПУСТОЙ И УДАЛЯЕМ ПАПКУ
    ${If} $R4 != ""
        DetailPrint "Обнаружена папка с игрой для удаления: $R4"
        ; RMDir /r надежно удалит указанную папку
        RMDir /r "$R4"
    ${EndIf}

EndGameDirDelete:
    ; Очистка стека плагина (обязательно)
    nsJSON::Clear

    DetailPrint "Удаление папок лаунчера..."
    RMDir /r "$APPDATA\KRISTORY"
    RMDir /r "$APPDATA\.kristory"

!macroend