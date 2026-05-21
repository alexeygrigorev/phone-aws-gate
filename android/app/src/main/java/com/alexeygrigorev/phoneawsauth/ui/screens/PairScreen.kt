package com.alexeygrigorev.phoneawsauth.ui.screens

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
import org.json.JSONObject

@Composable
fun PairScreen(onDone: () -> Unit) {
    val context = LocalContext.current
    val settings = remember { PairedSettings(context) }

    var payload by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Pair with a deployment", style = MaterialTheme.typography.titleLarge)
        Text(
            "Paste the JSON printed by deploy.sh (the QR scanner comes later). " +
                "Expected fields: rowKey, accessKeyId, secretAccessKey. " +
                "region and table are optional (default eu-west-1 / phone-aws-gate).",
            style = MaterialTheme.typography.bodySmall,
        )

        OutlinedTextField(
            value = payload,
            onValueChange = { payload = it; error = null },
            label = { Text("Pairing JSON") },
            modifier = Modifier
                .fillMaxWidth()
                .height(220.dp),
            supportingText = { Text("Tap and paste") },
            isError = error != null,
        )

        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }

        Button(
            modifier = Modifier.fillMaxWidth(),
            onClick = {
                runCatching { parse(payload) }
                    .onSuccess {
                        settings.save(it)
                        onDone()
                    }
                    .onFailure { error = it.message ?: "Could not parse payload" }
            },
            enabled = payload.isNotBlank(),
        ) { Text("Save & pair") }

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
        region = obj.optString("region").ifBlank { PairedConfig.DEFAULT_REGION },
        table = obj.optString("table").ifBlank { PairedConfig.DEFAULT_TABLE },
        rowKey = rowKey,
        accessKeyId = accessKeyId,
        secretAccessKey = secretAccessKey,
    )
}
