package com.alexeygrigorev.phoneawsauth

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.alexeygrigorev.phoneawsauth.ui.screens.MainScreen
import com.alexeygrigorev.phoneawsauth.ui.screens.PairScreen
import com.alexeygrigorev.phoneawsauth.ui.theme.PhoneAwsAuthTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            PhoneAwsAuthTheme {
                App()
            }
        }
    }
}

@Composable
private fun App() {
    val navController = rememberNavController()
    Scaffold(modifier = Modifier.fillMaxSize()) { padding ->
        NavHost(
            navController = navController,
            startDestination = Routes.Main,
            modifier = Modifier.padding(padding),
        ) {
            composable(Routes.Main) {
                MainScreen(onPair = { navController.navigate(Routes.Pair) })
            }
            composable(Routes.Pair) {
                PairScreen(onDone = { navController.popBackStack() })
            }
        }
    }
}

private object Routes {
    const val Main = "main"
    const val Pair = "pair"
}
