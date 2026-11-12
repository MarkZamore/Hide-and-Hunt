# Hide and Hunt для LANMinecraft

Карточка `minecraft-11`, папка `Hide and Hunt`. Авторская бета-версия
`1.0.0-beta.2` от ItzMaceTekk, Minecraft 26.3, Fabric Loader 0.20.1, Java 25.
Точные исходные файлы и лицензии закреплены в
[`tools/upstream-lock.json`](tools/upstream-lock.json) и
[`notices/THIRD-PARTY.txt`](notices/THIRD-PARTY.txt).

Миры для друзей из Steam открываются в меню «Сетевая игра» Minecraft.
В авторском меню можно создать и запустить свой мир или открыть сохранённый
вручную адрес. В лобби нажмите ПКМ по предмету «Играть» и задайте число ботов
и их силу перед стартом раунда. Статистика привязана к UUID игрока и хранится
в файле `hideandhunt/statistik.json` мира у хоста.

## Подготовка выпуска

Храните скачанный авторский архив, официальный клиент Minecraft и сборочные
результаты в рабочем стенде. Для выпуска нужны Python 3.12, фактический JDK 25,
оригинал [`FaWrAGlY`](https://modrinth.com/plugin/hide-and-hunt/version/FaWrAGlY)
и официальный клиент 26.3. Используйте тот же SHA проверенных входов, что и
в приёмке.

```powershell
python -B tools/prepare_26_3.py --upstream $author --out $rendererCandidate
python -B bridge/build.py --client-jar $client --upstream $author --out $bridge
```

Подготовка извлекает компонент 26.3, сохраняет MIT-лицензию автора и Fabric
API, исправляет сигнатуру обработчика отрисовки и исключает вложенный e4mc
вместе с его точками запуска. Отдельный Fabric-мод в
[`bridge`](bridge/README.md) убирает переключатель и открытие порта через
UPnP из авторского меню. Публикация мира вызывает штатный Minecraft API,
который уже поддерживает e4steam в выпущенном лаунчере. Эти операции описаны в
[`tools/overlay.json`](tools/overlay.json).

После запуска подготовленной сборки получить фактический реестр Fabric
как JSON-объект `{ "modId": "exactVersion" }`, включая платформенные и
общие управляемые ID. Сохраните журнал приёмки и хеши использованных JAR.

```powershell
python -B tools/generate_manifest.py inventory --upstream $author --bridge $bridge --observations $versions
python -B tools/generate_manifest.py review --upstream $author --bridge $bridge
python -B tools/generate_manifest.py record-lock --upstream $author --bridge $bridge --reviewed $reviewedDistributionSha256
python -B -m unittest discover -s tools -p test_generate_manifest.py
```

Для `record-lock` используйте `reviewedDistributionSha256` из `review`
после проверки точных байтов и источников автоматических сетевых записей.
Файл `library/loaded-mods.json` связывает только моды, выбранные загрузчиком,
с SHA256 подготовленных JAR. Модули Fabric API ведут на общий официальный
проект Fabric API. У пакета bridge своя ссылка на эти исходники.

`stage` и `verify` проверяют обязательные locks, receipt Log4j, правила
автоматического списка и факт загрузки точного состава. Перед отправкой
выпуска подготовьте данные из точного Git HEAD.

```powershell
python -B tools/generate_manifest.py stage --upstream $author --bridge $bridge --out $stage
python -B tools/generate_manifest.py --verify-only --upstream $author --out $stage
```

Публикуйте immutable-ассеты в `pack-latest`, затем `pack-manifest.json`.
Проверьте фактически скачанные файлы тем же `--verify-only`. Скачанные
ассеты должны находиться в `assets/`, манифест рядом с этим каталогом.
Существующая запись каталога читает этот источник. Требуемая возможность
`steam-native-publication-metadata-v1` уже есть в выпущенном лаунчере.

## При обновлении авторской версии

Возьмите новый авторский JAR как вход для `prepare_26_3.py`. Изменение SHA
останавливает подготовку. Сверьте состав компонента для 26.3, сохраните
исключение e4mc и связанных точек запуска, затем проверьте привязки bridge к
новым классам создания, открытия и списка миров. Упаковщик проверяет все
вложенные JAR, включая отсутствующие в декларации загрузчика. Он отклоняет
возвращение e4mc или оболочки для нескольких версий.

До обновления lock проверьте запуск, открытие старого мира со включённым
ранее флажком, создание нового мира, ручной список адресов и публикацию
через штатный Steam-адаптер. При смене имён файлов добавьте проверенные
SHA256 и размеры прошлых поставок в
[`tools/retired-files.json`](tools/retired-files.json), чтобы прежние JAR
не оставались активными после обновления. Обновляйте inventory и lock
после этой приёмки.

Для отдельной проверки чистой установки с публичного источника используйте
[`tools/qa/install`](tools/qa/install). Передайте фактический
`LANMinecraft.dll` через свойство `LauncherAssemblyPath` при сборке probe,
затем укажите тот же DLL, новую папку установки внутри
`artifacts/agent-runs` и проверенный манифест при запуске.
Для проверки перехода со старой версии укажите её тестовую установку,
манифест из подготовленного `stage` и флаг `--verify-update`. Probe проверит
удаление старых файлов и сохранность настроек, ручного списка и статистики.

Общий мод e4steam и клиент Minecraft предоставляет лаунчер. Политика
сетевых журналов принадлежит сборке и управляет ровно `config/log4j2.xml`.
Игровые миры, настройки и ручные серверы принадлежат игроку.
