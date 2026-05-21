package com.alexeygrigorev.phoneawsauth.settings

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * The values that come out of pairing — written once when the operator scans
 * (or pastes) the QR from deploy.sh, read on every gate operation.
 */
data class PairedConfig(
    val region: String,
    val table: String,
    val rowKey: String,
    val accessKeyId: String,
    val secretAccessKey: String,
) {
    companion object {
        // Hardcoded names per the deploy contract; user-facing pairing payloads
        // can omit them.
        const val DEFAULT_REGION = "eu-west-1"
        const val DEFAULT_TABLE = "phone-aws-gate"
    }
}

/**
 * EncryptedSharedPreferences-backed store for the paired config.
 *
 * The master key lives in the Android Keystore (AES256_GCM scheme); the
 * values are AES-GCM encrypted at rest. Biometric gating is layered on
 * later — see task #18.
 */
class PairedSettings(context: Context) {

    private val prefs = run {
        val masterKey = MasterKey.Builder(context, "phone-aws-master-key")
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            "phone-aws-paired",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    fun isPaired(): Boolean = prefs.contains(KEY_ROW_KEY)

    fun load(): PairedConfig? {
        if (!isPaired()) return null
        return PairedConfig(
            region = prefs.getString(KEY_REGION, PairedConfig.DEFAULT_REGION)!!,
            table = prefs.getString(KEY_TABLE, PairedConfig.DEFAULT_TABLE)!!,
            rowKey = prefs.getString(KEY_ROW_KEY, "")!!,
            accessKeyId = prefs.getString(KEY_ACCESS_KEY_ID, "")!!,
            secretAccessKey = prefs.getString(KEY_SECRET_ACCESS_KEY, "")!!,
        )
    }

    fun save(config: PairedConfig) {
        prefs.edit()
            .putString(KEY_REGION, config.region)
            .putString(KEY_TABLE, config.table)
            .putString(KEY_ROW_KEY, config.rowKey)
            .putString(KEY_ACCESS_KEY_ID, config.accessKeyId)
            .putString(KEY_SECRET_ACCESS_KEY, config.secretAccessKey)
            .apply()
    }

    fun clear() {
        prefs.edit().clear().apply()
    }

    private companion object {
        const val KEY_REGION = "region"
        const val KEY_TABLE = "table"
        const val KEY_ROW_KEY = "row_key"
        const val KEY_ACCESS_KEY_ID = "access_key_id"
        const val KEY_SECRET_ACCESS_KEY = "secret_access_key"
    }
}
