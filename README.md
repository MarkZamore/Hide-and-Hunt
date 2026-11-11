# Hide and Hunt для LANMinecraft

Карточка `minecraft-11`, папка `Hide and Hunt`. Авторская бета-версия
`1.0.0-beta.2` от ItzMaceTekk, Minecraft 26.3, Fabric Loader 0.20.1, Java 25.
Точные исходные файлы и лицензии закреплены в
[`tools/upstream-lock.json`](tools/upstream-lock.json) и
[`notices/THIRD-PARTY.txt`](notices/THIRD-PARTY.txt).

Стандартный вход через Steam остаётся в меню сетевой игры Minecraft.
В авторском меню при создании мира можно включить «Через e4mc», чтобы вручную
передать друзьям выданный адрес. У нового мира флажок снят.

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

Авторский архив закреплён целиком. Подготовка исправляет сигнатуру одного
обработчика отрисовки Minecraft 26.3 и конфликт перехватов бан-команд
между e4mc и e4steam. У e4mc отключены собственное исключение для входа
владельца и экспериментальные обработчики Dialtone. Штатные проверки
входа, общий Steam-транспорт и обычное реле e4mc с выдачей адреса сохраняются.
Производный архив содержит уведомление об изменениях. Отдельный Fabric-мод в
[`bridge`](bridge/README.md) включает e4mc по явному выбору и убирает
запасной вызов UPnP. Эти операции описывает
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
с SHA256 подготовленных JAR. Библиотеки Fabric API ведут на общий официальный
проект Fabric API. Служебный `hideandhunt_bundle` ведёт на официальный Hide
and Hunt. У пакета bridge своя ссылка на эти исходники.

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
Запись каталога появляется после проверки публичных файлов и после выпуска
лаунчера с возможностью `steam-native-publication-metadata-v1`.

Для отдельной проверки чистой установки с публичного источника используйте
[`tools/qa/install`](tools/qa/install). Передайте фактический
`LANMinecraft.dll` через свойство `LauncherAssemblyPath` при сборке probe,
затем укажите тот же DLL, новую папку установки внутри
`artifacts/agent-runs` и проверенный манифест при запуске.

Общий мод e4steam и клиент Minecraft предоставляет лаунчер. Политика
сетевых журналов принадлежит сборке и управляет ровно `config/log4j2.xml`.
Игровые миры, настройки и ручные серверы принадлежат игроку.
