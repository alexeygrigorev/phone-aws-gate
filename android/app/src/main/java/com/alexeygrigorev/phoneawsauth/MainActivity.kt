package com.alexeygrigorev.phoneawsauth

import android.os.Bundle
import android.util.Log
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.fragment.app.FragmentActivity
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.alexeygrigorev.phoneawsauth.settings.PairedSettings
import com.alexeygrigorev.phoneawsauth.ui.screens.MainScreen
import com.alexeygrigorev.phoneawsauth.ui.screens.PairScreen
import com.alexeygrigorev.phoneawsauth.ui.screens.parse
import com.alexeygrigorev.phoneawsauth.ui.theme.PhoneAwsAuthTheme
import org.json.JSONArray
import java.util.Base64

class MainActivity : FragmentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (BuildConfig.DEBUG) {
            if (intent.getBooleanExtra("skip_biometric", false)) {
                getSharedPreferences("phone-aws-debug", MODE_PRIVATE)
                    .edit()
                    .putBoolean("skip_biometric", true)
                    .apply()
            }
            debugPairingPayloads().takeIf { it.isNotEmpty() }?.let { payloads ->
                runCatching {
                    PairedSettings(this).saveAll(payloads.map { payload -> parse(payload) })
                    Log.i("AwsGateDebug", "Saved ${payloads.size} debug host(s)")
                }.onFailure {
                    Log.e("AwsGateDebug", "Debug pairing failed", it)
                }
            }
        }
        enableEdgeToEdge()
        setContent {
            PhoneAwsAuthTheme {
                App()
            }
        }
    }

    private fun debugPairingPayloads(): List<String> {
        intent.getStringExtra("pairing_jsons_b64")?.let { encoded ->
            val raw = String(Base64.getDecoder().decode(encoded), Charsets.UTF_8)
            val arr = JSONArray(raw)
            return (0 until arr.length()).map { idx -> arr.getJSONObject(idx).toString() }
        }
        intent.getStringExtra("pairing_json")?.let { return listOf(it) }
        return intent.getStringExtra("pairing_json_b64")?.let {
            listOf(String(Base64.getDecoder().decode(it), Charsets.UTF_8))
        } ?: emptyList()
    }
}

@Composable
private fun App() {
    val navController = rememberNavController()
    // Bumped after a successful pair so MainScreen re-reads settings.
    var pairVersion by remember { mutableIntStateOf(0) }

    Scaffold(modifier = Modifier.fillMaxSize()) { padding ->
        NavHost(
            navController = navController,
            startDestination = Routes.Main,
            modifier = Modifier.padding(padding),
        ) {
            composable(Routes.Main) {
                MainScreen(
                    onPair = { navController.navigate(Routes.Pair) },
                    pairVersion = pairVersion,
                )
            }
            composable(Routes.Pair) {
                PairScreen(onDone = {
                    pairVersion++
                    navController.popBackStack()
                })
            }
        }
    }
}

private object Routes {
    const val Main = "main"
    const val Pair = "pair"
}
