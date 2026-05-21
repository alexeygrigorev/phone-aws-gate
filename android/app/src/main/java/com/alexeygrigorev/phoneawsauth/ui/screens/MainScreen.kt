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
    val requireBio = paired != null

    GateControl(
        client = client,
        modeLabel = if (paired != null) "paired" else "local-dev",
        requireBiometric = requireBio,
        activity = activity,
        onUnpair = {
            settings.clear()
            paired = null
            devOverride = false
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
        Text("phone-aws-auth", style = MaterialTheme.typography.titleLarge)
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
    requireBiometric: Boolean,
    activity: FragmentActivity?,
    onUnpair: () -> Unit,
    onPair: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var state by remember(client) { mutableStateOf<UiState>(UiState.Loading) }

    LaunchedEffect(client) {
        state = UiState.Idle(client.status())
    }

    val gateOp: suspend (String, suspend () -> GateClient.Result) -> GateClient.Result = { title, op ->
        val biometricActivity = activity
        if (!requireBiometric) {
            op()
        } else if (biometricActivity == null) {
            GateClient.Result.Error("Biometric", "Biometric prompt is unavailable")
        } else {
            when (val auth = requireBiometric(biometricActivity, title, "phone-aws-auth")) {
                BiometricResult.Authenticated -> op()
                BiometricResult.UserCancelled -> GateClient.Result.Error("Cancelled", "Biometric cancelled")
                BiometricResult.NotAvailable -> GateClient.Result.Error("NoBiometric", "No biometric enrolled")
                is BiometricResult.Failed -> GateClient.Result.Error("Biometric", auth.reason)
            }
        }
    }

    // Duration picker. Values map to start(durationMinutes).
    val durationOptions = listOf(15, 60, 240, 480)
    var durationIdx by remember { mutableIntStateOf(1) }
    val durationMinutes = durationOptions[durationIdx]
    val durationLabel = if (durationMinutes < 60) "${durationMinutes}m" else "${durationMinutes / 60}h"

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            "phone-aws-auth",
            style = MaterialTheme.typography.titleLarge,
        )
        Text("[$modeLabel]", style = MaterialTheme.typography.bodySmall)
        StatusBlock(state)

        Spacer(Modifier.height(8.dp))
        HorizontalDivider()
        Spacer(Modifier.height(8.dp))

        Text("Auto-close TTL: $durationLabel", style = MaterialTheme.typography.labelMedium)
        SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
            durationOptions.forEachIndexed { i, mins ->
                SegmentedButton(
                    shape = SegmentedButtonDefaults.itemShape(i, durationOptions.size),
                    onClick = { durationIdx = i },
                    selected = i == durationIdx,
                ) {
                    Text(if (mins < 60) "${mins}m" else "${mins / 60}h")
                }
            }
        }

        val busy = state is UiState.Busy
        val gateActionsEnabled = canRunGateAction(
            result = (state as? UiState.Idle)?.result,
            busy = busy,
        )
        Button(
            modifier = Modifier.fillMaxWidth(),
            enabled = gateActionsEnabled,
            onClick = { runStart(scope, gateOp, client, "sandbox", durationMinutes) { state = it } },
        ) { Text("Start sandbox ($durationLabel)") }

        Button(
            modifier = Modifier.fillMaxWidth(),
            enabled = gateActionsEnabled,
            onClick = { runStop(scope, gateOp, client) { state = it } },
        ) { Text("Stop") }

        Spacer(Modifier.height(8.dp))

        OutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            onClick = { runRefresh(scope, client) { state = it } },
            enabled = !busy,
        ) { Text("Refresh") }

        OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = onPair) {
            Text("Re-pair")
        }

        OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = onUnpair) {
            Text("Unpair / use other deployment")
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
    // Paired config implies real AWS — no DDB Local endpoint.
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
    onState: (UiState) -> Unit,
) {
    onState(UiState.Busy(null))
    scope.launch {
        val r = gateOp("Open AWS gate ($mode)") {
            withContext(Dispatchers.IO) { client.start(mode, durationMinutes) }
        }
        onState(UiState.Idle(r))
    }
}

private fun runStop(
    scope: CoroutineScope,
    gateOp: suspend (String, suspend () -> GateClient.Result) -> GateClient.Result,
    client: GateClient,
    onState: (UiState) -> Unit,
) {
    onState(UiState.Busy(null))
    scope.launch {
        val r = gateOp("Close AWS gate") {
            withContext(Dispatchers.IO) {
                client.stop()
                client.status()
            }
        }
        onState(UiState.Idle(r))
    }
}

private fun runRefresh(scope: CoroutineScope, client: GateClient, onState: (UiState) -> Unit) {
    onState(UiState.Busy(null))
    scope.launch(Dispatchers.IO) {
        onState(UiState.Idle(client.status()))
    }
}

internal fun canRunGateAction(result: GateClient.Result?, busy: Boolean): Boolean {
    return !busy && result != null && result !is GateClient.Result.Error
}
