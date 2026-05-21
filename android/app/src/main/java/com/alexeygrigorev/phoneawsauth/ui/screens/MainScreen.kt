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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
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
        if (requireBiometric && activity != null) {
            when (val auth = requireBiometric(activity, title, "phone-aws-auth")) {
                BiometricResult.Authenticated -> op()
                BiometricResult.UserCancelled -> GateClient.Result.Error("Cancelled", "Biometric cancelled")
                BiometricResult.NotAvailable -> GateClient.Result.Error("NoBiometric", "No biometric enrolled")
                is BiometricResult.Failed -> GateClient.Result.Error("Biometric", auth.reason)
            }
        } else {
            op()
        }
    }

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

        val busy = state is UiState.Busy
        Button(
            modifier = Modifier.fillMaxWidth(),
            enabled = !busy,
            onClick = { runStart(scope, gateOp, client, "sandbox") { state = it } },
        ) { Text("Start sandbox (60 min)") }

        Button(
            modifier = Modifier.fillMaxWidth(),
            enabled = !busy,
            onClick = { runStart(scope, gateOp, client, "prod") { state = it } },
        ) { Text("Start prod (60 min)") }

        Button(
            modifier = Modifier.fillMaxWidth(),
            enabled = !busy,
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
    val text = when (state) {
        UiState.Loading -> "Checking gate…"
        is UiState.Busy -> "Working…"
        is UiState.Idle -> when (val r = state.result) {
            is GateClient.Result.Closed -> "Gate: CLOSED"
            is GateClient.Result.Open -> "Gate: OPEN (${r.mode})\nuntil ${formatEpoch(r.expiresAt)}"
            is GateClient.Result.Error -> "ERROR: ${r.type}\n${r.message}"
        }
    }
    Text(
        text = text,
        textAlign = TextAlign.Center,
        style = MaterialTheme.typography.bodyLarge,
    )
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
    onState: (UiState) -> Unit,
) {
    onState(UiState.Busy(null))
    scope.launch {
        val r = gateOp("Open AWS gate ($mode)") {
            withContext(Dispatchers.IO) { client.start(mode, durationMinutes = 60) }
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
