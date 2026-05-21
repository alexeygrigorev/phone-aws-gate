package com.alexeygrigorev.phoneawsauth.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun MainScreen(onPair: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("phone-aws-auth")
        Text("(not paired)")

        Spacer(Modifier.height(8.dp))

        Button(modifier = Modifier.fillMaxWidth(), enabled = false, onClick = {}) {
            Text("Start sandbox")
        }
        Button(modifier = Modifier.fillMaxWidth(), enabled = false, onClick = {}) {
            Text("Start prod")
        }
        Button(modifier = Modifier.fillMaxWidth(), enabled = false, onClick = {}) {
            Text("Stop")
        }

        Spacer(Modifier.height(24.dp))

        OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = onPair) {
            Text("Pair")
        }
    }
}
