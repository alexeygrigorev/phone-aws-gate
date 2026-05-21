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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.alexeygrigorev.phoneawsauth.net.GateClient
import com.alexeygrigorev.phoneawsauth.net.LocalDev
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private sealed class UiState {
    data object Loading : UiState()
    data class Idle(val result: GateClient.Result) : UiState()
    data class Busy(val previous: GateClient.Result?) : UiState()
}

@Composable
fun MainScreen(onPair: () -> Unit) {
    val scope = rememberCoroutineScope()
    val client = remember { LocalDev.client() }
    var state by remember { mutableStateOf<UiState>(UiState.Loading) }

    LaunchedEffect(Unit) {
        state = UiState.Idle(client.status())
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
        StatusBlock(state)

        Spacer(Modifier.height(8.dp))
        HorizontalDivider()
        Spacer(Modifier.height(8.dp))

        val busy = state is UiState.Busy
        Button(
            modifier = Modifier.fillMaxWidth(),
            enabled = !busy,
            onClick = { runStart(scope, client, "sandbox") { state = it } },
        ) { Text("Start sandbox (60 min)") }

        Button(
            modifier = Modifier.fillMaxWidth(),
            enabled = !busy,
            onClick = { runStart(scope, client, "prod") { state = it } },
        ) { Text("Start prod (60 min)") }

        Button(
            modifier = Modifier.fillMaxWidth(),
            enabled = !busy,
            onClick = { runStop(scope, client) { state = it } },
        ) { Text("Stop") }

        Spacer(Modifier.height(8.dp))

        OutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            onClick = { runRefresh(scope, client) { state = it } },
            enabled = !busy,
        ) { Text("Refresh") }

        OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = onPair) {
            Text("Pair")
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

private fun formatEpoch(epochSeconds: Long): String {
    val fmt = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
    return fmt.format(Date(epochSeconds * 1000))
}

private fun runStart(
    scope: CoroutineScope,
    client: GateClient,
    mode: String,
    onState: (UiState) -> Unit,
) {
    onState(UiState.Busy(null))
    scope.launch(Dispatchers.IO) {
        val r = client.start(mode, durationMinutes = 60)
        onState(UiState.Idle(r))
    }
}

private fun runStop(scope: CoroutineScope, client: GateClient, onState: (UiState) -> Unit) {
    onState(UiState.Busy(null))
    scope.launch(Dispatchers.IO) {
        client.stop()
        // Read back the actual state so the UI shows whatever DDB now says.
        onState(UiState.Idle(client.status()))
    }
}

private fun runRefresh(scope: CoroutineScope, client: GateClient, onState: (UiState) -> Unit) {
    onState(UiState.Busy(null))
    scope.launch(Dispatchers.IO) {
        onState(UiState.Idle(client.status()))
    }
}
