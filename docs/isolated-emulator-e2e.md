# Isolated Emulator E2E Runbook

Use this runbook when running Android E2E locally. Do not run E2E against the
default/shared emulator unless you are certain nothing else is using it.

## Why

This repo's E2E drives the emulator UI with `uiautomator` and coordinate taps.
If another app is foreground on the same emulator, the test can interact with
that app instead. This already happened with PocketShell on `emulator-5554`.

The rule is: run this repo's E2E on a dedicated emulator serial.

## Start A Dedicated Emulator

Use a separate emulator console port. Port `5564` gives serial
`emulator-5564`. If the default AVD is already running, create a separate AVD
for this repo instead of trying to start a second writable instance of the same
AVD.

```sh
export ANDROID_HOME="$HOME/Android/Sdk"
export EMULATOR="$ANDROID_HOME/emulator/emulator"
export ADB="$ANDROID_HOME/platform-tools/adb"

"$EMULATOR" -avd test \
  -port 5564 \
  -no-window \
  -no-audio \
  -no-boot-anim \
  -gpu swiftshader_indirect \
  -no-snapshot-save &
```

If `test` is already running, create and use a repo-specific AVD:

```sh
"$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager" create avd \
  -n phoneaws-e2e \
  -k 'system-images;android-35;default;x86_64' \
  --device pixel_6

"$EMULATOR" -avd phoneaws-e2e \
  -port 5564 \
  -no-window \
  -no-audio \
  -no-boot-anim \
  -gpu swiftshader_indirect \
  -no-snapshot-save &
```

Then target only that emulator:

```sh
export ANDROID_SERIAL=emulator-5564

"$ADB" wait-for-device
"$ADB" shell 'while [ "$(getprop sys.boot_completed | tr -d "\r")" != 1 ]; do sleep 1; done'
"$ADB" shell input keyevent KEYCODE_WAKEUP
"$ADB" shell wm dismiss-keyguard
```

Verify:

```sh
adb devices
adb -s "$ANDROID_SERIAL" shell getprop ro.boot.qemu.avd_name
adb -s "$ANDROID_SERIAL" shell 'toybox nc -z -w 3 10.0.2.2 18000; echo nc_rc=$?'
```

Run the port check after this repo's local stack is up. It must print
`nc_rc=0`; otherwise the app cannot reach DynamoDB Local from the emulator.

## Run The E2E

Keep `ANDROID_SERIAL` exported for the whole command:

```sh
ANDROID_SERIAL=emulator-5564 make e2e
```

The script installs the APK, clears only
`com.alexeygrigorev.phoneawsauth`, starts Docker fixtures, drives the app UI,
and removes its own Docker containers.

## Clean Up

Stop only the dedicated emulator when done:

```sh
adb -s emulator-5564 emu kill
```

Clean this repo's Docker fixtures if a run was interrupted:

```sh
docker rm -f aws-gate-e2e-server-a aws-gate-e2e-server-b 2>/dev/null || true
docker compose -p phone-aws-auth-e2e -f docker/docker-compose.yml down || true
```

## Safety Rules

- Do not use naked `adb` for E2E when multiple devices are attached.
- Do not use naked `docker compose down` from this repo. Use the
  `phone-aws-auth-e2e` project name so Compose cleanup stays scoped to this
  repo's containers.
- Do not `pm clear`, `am force-stop`, or tap on `emulator-5554` if it is used
  by another project.
- Do not force-stop unrelated packages to make this repo's E2E pass.
- Always set `ANDROID_SERIAL` or use `adb -s <serial>`.
- If UI assertions show another package name, stop the run and switch to an
  isolated emulator.
