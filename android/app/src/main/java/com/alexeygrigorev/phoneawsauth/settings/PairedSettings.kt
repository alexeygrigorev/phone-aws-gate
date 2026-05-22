package com.alexeygrigorev.phoneawsauth.settings

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONArray
import org.json.JSONObject

/**
 * The values that come out of pairing — written once when the operator scans
 * (or pastes) the QR from deploy.sh, read on every gate operation.
 */
data class PairedConfig(
    val name: String,
    val region: String,
    val table: String,
    val rowKey: String,
    val accessKeyId: String,
    val secretAccessKey: String,
    val ddbEndpoint: String? = null,
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

    fun isPaired(): Boolean = hosts().isNotEmpty()

    fun hosts(): List<PairedConfig> {
        val raw = prefs.getString(KEY_HOSTS, null)
        if (!raw.isNullOrBlank()) {
            val arr = JSONArray(raw)
            return (0 until arr.length()).map { idx ->
                val obj = arr.getJSONObject(idx)
                PairedConfig(
                    name = obj.optString("name").ifBlank { "Host" },
                    region = obj.optString("region").ifBlank { PairedConfig.DEFAULT_REGION },
                    table = obj.optString("table").ifBlank { PairedConfig.DEFAULT_TABLE },
                    rowKey = obj.getString("rowKey"),
                    accessKeyId = obj.getString("accessKeyId"),
                    secretAccessKey = obj.getString("secretAccessKey"),
                    ddbEndpoint = obj.optString("ddbEndpoint").ifBlank { null },
                )
            }
        }

        val legacy = loadLegacy() ?: return emptyList()
        writeHosts(listOf(legacy), legacy.rowKey)
        return listOf(legacy)
    }

    fun load(): PairedConfig? {
        val list = hosts()
        if (list.isEmpty()) return null
        val selected = prefs.getString(KEY_SELECTED_ROW_KEY, null)
        return list.firstOrNull { it.rowKey == selected } ?: list.first()
    }

    private fun loadLegacy(): PairedConfig? {
        if (!prefs.contains(KEY_ROW_KEY)) return null
        return PairedConfig(
            name = prefs.getString(KEY_NAME, "Host")!!,
            region = prefs.getString(KEY_REGION, PairedConfig.DEFAULT_REGION)!!,
            table = prefs.getString(KEY_TABLE, PairedConfig.DEFAULT_TABLE)!!,
            rowKey = prefs.getString(KEY_ROW_KEY, "")!!,
            accessKeyId = prefs.getString(KEY_ACCESS_KEY_ID, "")!!,
            secretAccessKey = prefs.getString(KEY_SECRET_ACCESS_KEY, "")!!,
            ddbEndpoint = null,
        )
    }

    fun save(config: PairedConfig) {
        val updated = hosts()
            .filterNot { it.rowKey == config.rowKey }
            .plus(config)
            .sortedBy { it.name.lowercase() }
        writeHosts(updated, config.rowKey)
    }

    fun saveAll(configs: List<PairedConfig>) {
        if (configs.isEmpty()) return
        val byRowKey = linkedMapOf<String, PairedConfig>()
        hosts().forEach { byRowKey[it.rowKey] = it }
        configs.forEach { byRowKey[it.rowKey] = it }
        val updated = byRowKey.values.sortedBy { it.name.lowercase() }
        writeHosts(updated, configs.last().rowKey)
    }

    fun select(rowKey: String) {
        prefs.edit()
            .putString(KEY_SELECTED_ROW_KEY, rowKey)
            .commit()
    }

    fun remove(rowKey: String) {
        val updated = hosts().filterNot { it.rowKey == rowKey }
        val arr = JSONArray()
        updated.forEach { host ->
            arr.put(JSONObject()
                .put("name", host.name)
                .put("region", host.region)
                .put("table", host.table)
                .put("rowKey", host.rowKey)
                .put("accessKeyId", host.accessKeyId)
                .put("secretAccessKey", host.secretAccessKey)
                .put("ddbEndpoint", host.ddbEndpoint))
        }
        val edit = prefs.edit()
            .putString(KEY_HOSTS, arr.toString())
        val selected = updated.firstOrNull()?.rowKey
        if (selected == null) {
            edit.remove(KEY_SELECTED_ROW_KEY)
        } else {
            edit.putString(KEY_SELECTED_ROW_KEY, selected)
        }
        edit
            .commit()
    }

    private fun writeHosts(hosts: List<PairedConfig>, selectedRowKey: String) {
        val arr = JSONArray()
        hosts.forEach { host ->
            arr.put(JSONObject()
                .put("name", host.name)
                .put("region", host.region)
                .put("table", host.table)
                .put("rowKey", host.rowKey)
                .put("accessKeyId", host.accessKeyId)
                .put("secretAccessKey", host.secretAccessKey)
                .put("ddbEndpoint", host.ddbEndpoint))
        }
        prefs.edit()
            .putString(KEY_HOSTS, arr.toString())
            .putString(KEY_SELECTED_ROW_KEY, selectedRowKey)
            .remove(KEY_NAME)
            .remove(KEY_REGION)
            .remove(KEY_TABLE)
            .remove(KEY_ROW_KEY)
            .remove(KEY_ACCESS_KEY_ID)
            .remove(KEY_SECRET_ACCESS_KEY)
            .commit()
    }

    @Deprecated("Use save(config), kept only as documentation of legacy keys.")
    private fun saveLegacy(config: PairedConfig) {
        prefs.edit()
            .putString(KEY_NAME, config.name)
            .putString(KEY_REGION, config.region)
            .putString(KEY_TABLE, config.table)
            .putString(KEY_ROW_KEY, config.rowKey)
            .putString(KEY_ACCESS_KEY_ID, config.accessKeyId)
            .putString(KEY_SECRET_ACCESS_KEY, config.secretAccessKey)
            .apply()
    }

    fun clear() {
        prefs.edit().clear().commit()
    }

    private companion object {
        const val KEY_HOSTS = "hosts_json"
        const val KEY_SELECTED_ROW_KEY = "selected_row_key"
        const val KEY_NAME = "name"
        const val KEY_REGION = "region"
        const val KEY_TABLE = "table"
        const val KEY_ROW_KEY = "row_key"
        const val KEY_ACCESS_KEY_ID = "access_key_id"
        const val KEY_SECRET_ACCESS_KEY = "secret_access_key"
    }
}
