package com.alexeygrigorev.phoneawsauth.ui.screens

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.alexeygrigorev.phoneawsauth.settings.PairedConfig
import com.alexeygrigorev.phoneawsauth.settings.PairedSettings
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import org.json.JSONObject

@Composable
fun PairScreen(onDone: () -> Unit) {
    val context = LocalContext.current
    val settings = remember { PairedSettings(context) }

    var payload by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }

    fun applyPayload(text: String) {
        runCatching { parse(text) }
            .onSuccess {
                settings.save(it)
                onDone()
            }
            .onFailure { error = it.message ?: "Could not parse payload" }
    }

    val scanLauncher = rememberLauncherForActivityResult(ScanContract()) { result ->
        val contents = result.contents
        if (contents.isNullOrBlank()) {
            // user cancelled; ignore
        } else {
            payload = contents
            applyPayload(contents)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Register host", style = MaterialTheme.typography.titleLarge)
        Text(
            "Scan the QR shown by ./pair-qr.sh on the host, or paste the JSON it printed " +
                "(useful in the emulator without a working camera).",
            style = MaterialTheme.typography.bodySmall,
        )

        Button(
            modifier = Modifier.fillMaxWidth(),
            onClick = {
                error = null
                scanLauncher.launch(
                    ScanOptions()
                        .setBeepEnabled(false)
                        .setOrientationLocked(true)
                        .setPrompt("Point the camera at the host QR")
                        .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                )
            },
        ) { Text("Scan QR") }

        Spacer(Modifier.height(8.dp))

        OutlinedTextField(
            value = payload,
            onValueChange = { payload = it; error = null },
            label = { Text("…or paste pairing JSON") },
            modifier = Modifier
                .fillMaxWidth()
                .height(220.dp),
            isError = error != null,
        )

        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }

        OutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            onClick = { applyPayload(payload) },
            enabled = payload.isNotBlank(),
        ) { Text("Register host (from pasted JSON)") }

        Spacer(Modifier.height(8.dp))

        if (settings.isPaired()) {
            OutlinedButton(
                modifier = Modifier.fillMaxWidth(),
                onClick = { settings.clear(); error = "Cleared paired config." },
            ) { Text("Forget current pairing") }
        }

        OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = onDone) {
            Text("Cancel")
        }
    }
}

internal fun parse(payload: String): PairedConfig {
    val obj = try {
        JSONObject(payload.trim())
    } catch (e: Exception) {
        throw IllegalArgumentException("Not valid JSON: ${e.message}")
    }

    val rowKey = obj.optString("rowKey").ifBlank {
        throw IllegalArgumentException("Missing field: rowKey")
    }
    val accessKeyId = obj.optString("accessKeyId").ifBlank {
        throw IllegalArgumentException("Missing field: accessKeyId")
    }
    val secretAccessKey = obj.optString("secretAccessKey").ifBlank {
        throw IllegalArgumentException("Missing field: secretAccessKey")
    }

    if (!rowKey.matches(Regex("^[0-9a-f]{64}$"))) {
        throw IllegalArgumentException("rowKey must be 64 hex chars (sha256)")
    }

    return PairedConfig(
        name = obj.optString("name").ifBlank { "Host" },
        region = obj.optString("region").ifBlank { PairedConfig.DEFAULT_REGION },
        table = obj.optString("table").ifBlank { PairedConfig.DEFAULT_TABLE },
        rowKey = rowKey,
        accessKeyId = accessKeyId,
        secretAccessKey = secretAccessKey,
    )
}
