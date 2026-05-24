plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.alexeygrigorev.phoneawsauth"
    compileSdk = 35

    signingConfigs {
        create("stableDebug") {
            storeFile = file("../debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    defaultConfig {
        applicationId = "com.alexeygrigorev.phoneawsauth"
        minSdk = 28
        targetSdk = 35
        versionCode = 6
        versionName = "0.2.4"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("stableDebug")
        }
        debug {
            signingConfig = signingConfigs.getByName("stableDebug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.fragment.ktx)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.aws.sdk.dynamodb)
    implementation(libs.androidx.security.crypto)
    implementation(libs.androidx.biometric)
    implementation(libs.zxing.android.embedded)
    debugImplementation(libs.androidx.ui.tooling)
    testImplementation(libs.junit)
    testImplementation(libs.json)
}
