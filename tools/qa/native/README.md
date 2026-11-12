# Native Hide and Hunt acceptance

Run on Windows x64 with Python 3.12 and JDK 25. Use the LANMinecraft checkout as
the workspace. The fixture reuses hash-verified Minecraft assets and libraries,
has its own config and saves, and includes only a synthetic local player.
Choose one fixture directory and use a different evidence label for each run.

```powershell
python -B tools/workspace_storage.py --check
$qa = 'LocalSources/Hide-and-Hunt/tools/qa/native/run_native.py'
$run = Join-Path (Get-Location) 'artifacts/agent-runs/hide-and-hunt/runtime'
python -B $qa --workspace (Get-Location) --fixture $run --jdk $env:JAVA_HOME --label baseline
python -B $qa --workspace (Get-Location) --fixture $run --jdk $env:JAVA_HOME --label candidate `
  --content '<verified derived JAR>' --bridge '<verified bridge JAR>' `
  --adapter-args '<JSON array of fresh production adapter JVM flags>'
```

Wait for the actual Minecraft title screen before opening **Hide and Hunt**.
Create a technical world and check that the form has name and port controls
without a relay toggle. Start a minigame with bots, save and reopen the world.
Open a previous QA world with `"upnp": true` and check that it uses the same
Steam publication path and that the saved flag remains unchanged. Verify the
manual address list and native Multiplayer menu. The observer records actual
Fabric IDs, versions and selected JAR origins without adding a mod to the
inventory. Check that e4mc and its dependencies are absent from that inventory.

The candidate uses the pack logging profile and refuses native Steam API
initialization through the QA-only agent. A synthetic skin registry and
loopback PNG are enabled when production adapter options are present.
Record the nickname in game, the skin download and any visual evidence
separately from the Java preflight. Mark real Steam sessions as `NOT RUN`.

Exit Minecraft through its menu. Keep the compact verification report and
approved preview, then remove owned fixture files and rerun the workspace
storage check.
