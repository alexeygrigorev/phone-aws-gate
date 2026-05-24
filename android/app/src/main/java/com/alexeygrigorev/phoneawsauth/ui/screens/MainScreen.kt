package com.alexeygrigorev.phoneawsauth.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.fragment.app.FragmentActivity
import com.alexeygrigorev.phoneawsauth.BuildConfig
import com.alexeygrigorev.phoneawsauth.auth.BiometricResult
import com.alexeygrigorev.phoneawsauth.auth.findFragmentActivity
import com.alexeygrigorev.phoneawsauth.auth.requireBiometric
import com.alexeygrigorev.phoneawsauth.net.GateClient
import com.alexeygrigorev.phoneawsauth.net.LocalDev
import com.alexeygrigorev.phoneawsauth.settings.PairedConfig
import com.alexeygrigorev.phoneawsauth.settings.PairedSettings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private sealed class UiState {
    data object Loading : UiState()
    data class Idle(val result: GateClient.Result) : UiState()
    data class Busy(val previous: GateClient.Result?) : UiState()
}

@Composable
fun MainScreen(onPair: () -> Unit, pairVersion: Int) {
    val context = LocalContext.current
    val settings = remember { PairedSettings(context) }
    val activity = remember(context) { context.findFragmentActivity() }

    // remember(pairVersion) re-reads settings after the Pair screen pops.
    var paired by remember(pairVersion) { mutableStateOf(settings.load()) }
    var hosts by remember(pairVersion) { mutableStateOf(settings.hosts()) }
    var devOverride by remember(pairVersion) { mutableStateOf(false) }

    val client: GateClient? = when {
        paired != null -> buildClient(paired!!)
        devOverride -> LocalDev.client()
        else -> null
    }

    if (client == null) {
        NotPairedScreen(
            onPair = onPair,
            onUseDevStack = { devOverride = true },
        )
        return
    }

    // Biometric is required for paired (real-AWS) operations, skipped for
    // local-dev (DDB Local can't escape the emulator anyway).
    val debugSkipBiometric = BuildConfig.DEBUG &&
        context.getSharedPreferences("phone-aws-debug", 0).getBoolean("skip_biometric", false)
    val requireBio = paired != null && !debugSkipBiometric

    GateControl(
        client = client,
        modeLabel = paired?.name ?: "local-dev",
        hosts = hosts,
        selectedRowKey = paired?.rowKey,
        requireBiometric = requireBio,
        activity = activity,
        onUnpair = {
            paired?.let { settings.remove(it.rowKey) } ?: settings.clear()
            hosts = settings.hosts()
            paired = settings.load()
            devOverride = false
        },
        onSelectHost = { host ->
            settings.select(host.rowKey)
            paired = host
        },
        onPair = onPair,
    )
}

@Composable
private fun NotPairedScreen(onPair: () -> Unit, onUseDevStack: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("AWS Gate", style = MaterialTheme.typography.titleLarge)
        Text(
            "Not paired. Pair this device with a deployed stack to control its gate.",
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(8.dp))
        Button(modifier = Modifier.fillMaxWidth(), onClick = onPair) {
            Text("Pair")
        }
        OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = onUseDevStack) {
            Text("Use local-dev stack (emulator)")
        }
    }
}

@Composable
private fun GateControl(
    client: GateClient,
    modeLabel: String,
    hosts: List<PairedConfig>,
    selectedRowKey: String?,
    requireBiometric: Boolean,
    activity: FragmentActivity?,
    onUnpair: () -> Unit,
    onSelectHost: (PairedConfig) -> Unit,
    onPair: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var state by remember(client) { mutableStateOf<UiState>(UiState.Loading) }

    LaunchedEffect(client) {
        state = UiState.Idle(withContext(Dispatchers.IO) { client.status() })
    }

    val gateOp: suspend (String, suspend () -> GateClient.Result) -> GateClient.Result = { title, op ->
        val biometricActivity = activity
        if (!requireBiometric) {
            op()
        } else if (biometricActivity == null) {
            GateClient.Result.Error("Biometric", "Biometric prompt is unavailable")
        } else {
            when (val auth = requireBiometric(biometricActivity, title, "AWS Gate")) {
                BiometricResult.Authenticated -> op()
                BiometricResult.UserCancelled -> GateClient.Result.Error("Cancelled", "Biometric cancelled")
                BiometricResult.NotAvailable -> GateClient.Result.Error("NoBiometric", "No biometric enrolled")
                is BiometricResult.Failed -> GateClient.Result.Error("Biometric", auth.reason)
            }
        }
    }

    // Duration picker. Values map to start(durationMinutes).
    val durationOptions = listOf(15, 60, 240, 480)
    val uiPrefs = remember(context) { context.getSharedPreferences("phone-aws-ui", 0) }
    var durationIdx by remember {
        mutableIntStateOf(durationIndexFor(durationOptions, uiPrefs.getInt(KEY_DEFAULT_DURATION_MINUTES, 60)))
    }
    val durationMinutes = durationOptions[durationIdx]
    val durationLabel = if (durationMinutes < 60) "${durationMinutes}m" else "${durationMinutes / 60}h"

    val rawResult = (state as? UiState.Idle)?.result
    // Tick once per second whenever we have an Open result so the UI can flip
    // to CLOSED at expiry instead of showing "0:00 remaining" forever.
    var nowSec by remember { mutableLongStateOf(System.currentTimeMillis() / 1000) }
    LaunchedEffect(rawResult) {
        if (rawResult is GateClient.Result.Open) {
            while (true) {
                nowSec = System.currentTimeMillis() / 1000
                delay(1000)
            }
        }
    }
    val displayResult = effectiveResult(rawResult, nowSec)
    val displayState: UiState = when (state) {
        is UiState.Idle -> displayResult?.let { UiState.Idle(it) } ?: state
        else -> state
    }
    val busy = state is UiState.Busy
    val gateActionsEnabled = canRunGateAction(result = displayResult, busy = busy)
    val isOpen = displayResult is GateClient.Result.Open

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            "AWS Gate",
            style = MaterialTheme.typography.titleLarge,
        )
        Text("[$modeLabel]", style = MaterialTheme.typography.bodySmall)
        if (hosts.size > 1) {
            hosts.forEach { host ->
                OutlinedButton(
                    modifier = Modifier.fillMaxWidth(),
                    enabled = host.rowKey != selectedRowKey,
                    onClick = { onSelectHost(host) },
                ) { Text(if (host.rowKey == selectedRowKey) "Selected: ${host.name}" else "Use ${host.name}") }
            }
        }
        StatusBlock(displayState)

        Spacer(Modifier.height(8.dp))
        HorizontalDivider()
        Spacer(Modifier.height(8.dp))

        Text("Auto-close TTL: $durationLabel", style = MaterialTheme.typography.labelMedium)
        SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
            durationOptions.forEachIndexed { i, mins ->
                SegmentedButton(
                    shape = SegmentedButtonDefaults.itemShape(i, durationOptions.size),
                    onClick = {
                        durationIdx = i
                        uiPrefs.edit().putInt(KEY_DEFAULT_DURATION_MINUTES, mins).apply()
                    },
                    selected = i == durationIdx,
                ) {
                    Text(if (mins < 60) "${mins}m" else "${mins / 60}h")
                }
            }
        }

        Button(
            modifier = Modifier.fillMaxWidth(),
            enabled = gateActionsEnabled,
            onClick = {
                runStart(scope, gateOp, client, "sandbox", durationMinutes, isExtend = isOpen) {
                    state = it
                }
            },
        ) { Text(if (isOpen) "Extend ($durationLabel)" else "Start ($durationLabel)") }

        Button(
            modifier = Modifier.fillMaxWidth(),
            enabled = gateActionsEnabled,
            onClick = { runStop(scope, client) { state = it } },
        ) { Text("Stop") }

        Spacer(Modifier.height(8.dp))

        OutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            onClick = { runRefresh(scope, client) { state = it } },
            enabled = !busy,
        ) { Text("Refresh") }

        OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = onPair) {
            Text("Register another host")
        }

        OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = onUnpair) {
            Text("Forget this host")
        }
    }
}

@Composable
private fun StatusBlock(state: UiState) {
    when (state) {
        UiState.Loading -> Text("Checking gate…", textAlign = TextAlign.Center)
        is UiState.Busy -> Text("Working…", textAlign = TextAlign.Center)
        is UiState.Idle -> when (val r = state.result) {
            is GateClient.Result.Closed ->
                Text("Gate: CLOSED", textAlign = TextAlign.Center, style = MaterialTheme.typography.bodyLarge)
            is GateClient.Result.Open -> OpenStatus(r)
            is GateClient.Result.Error ->
                Text("ERROR: ${r.type}\n${r.message}",
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.error)
        }
    }
}

@Composable
private fun OpenStatus(r: GateClient.Result.Open) {
    var now by remember { mutableLongStateOf(System.currentTimeMillis() / 1000) }
    LaunchedEffect(r.expiresAt) {
        while (true) {
            now = System.currentTimeMillis() / 1000
            delay(1000)
        }
    }
    val remaining = (r.expiresAt - now).coerceAtLeast(0L)
    Text(
        text = "Gate: OPEN (${r.mode})\n${formatRemaining(remaining)} remaining · until ${formatEpoch(r.expiresAt)}",
        textAlign = TextAlign.Center,
        style = MaterialTheme.typography.bodyLarge,
    )
}

private fun formatRemaining(seconds: Long): String {
    val h = seconds / 3600
    val m = (seconds % 3600) / 60
    val s = seconds % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
}

private fun buildClient(c: PairedConfig): GateClient = GateClient(
    rowKey = c.rowKey,
    table = c.table,
    awsRegion = c.region,
    accessKeyId = c.accessKeyId,
    secretAccessKey = c.secretAccessKey,
    ddbEndpoint = c.ddbEndpoint,
)

private fun formatEpoch(epochSeconds: Long): String {
    val fmt = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
    return fmt.format(Date(epochSeconds * 1000))
}

private fun runStart(
    scope: CoroutineScope,
    gateOp: suspend (String, suspend () -> GateClient.Result) -> GateClient.Result,
    client: GateClient,
    mode: String,
    durationMinutes: Int,
    isExtend: Boolean = false,
    onState: (UiState) -> Unit,
) {
    onState(UiState.Busy(null))
    scope.launch {
        val title = if (isExtend) "Extend AWS gate ($mode)" else "Open AWS gate ($mode)"
        val r = gateOp(title) {
            withContext(Dispatchers.IO) { client.start(mode, durationMinutes) }
        }
        onState(UiState.Idle(r))
    }
}

private fun runStop(
    scope: CoroutineScope,
    client: GateClient,
    onState: (UiState) -> Unit,
) {
    onState(UiState.Busy(null))
    scope.launch {
        val r = withContext(Dispatchers.IO) {
            client.stop()
            client.status()
        }
        onState(UiState.Idle(r))
    }
}

private fun runRefresh(scope: CoroutineScope, client: GateClient, onState: (UiState) -> Unit) {
    onState(UiState.Busy(null))
    scope.launch {
        val result = withContext(Dispatchers.IO) { client.status() }
        onState(UiState.Idle(result))
    }
}

internal fun canRunGateAction(result: GateClient.Result?, busy: Boolean): Boolean {
    return !busy && result != null && result !is GateClient.Result.Error
}

internal fun effectiveResult(raw: GateClient.Result?, nowSec: Long): GateClient.Result? {
    return if (raw is GateClient.Result.Open && raw.expiresAt <= nowSec) {
        GateClient.Result.Closed
    } else {
        raw
    }
}

internal fun durationIndexFor(options: List<Int>, savedMinutes: Int): Int {
    val exact = options.indexOf(savedMinutes)
    return if (exact >= 0) exact else options.indexOf(60).takeIf { it >= 0 } ?: 0
}

private const val KEY_DEFAULT_DURATION_MINUTES = "default_duration_minutes"
