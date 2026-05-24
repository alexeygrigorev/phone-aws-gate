package com.alexeygrigorev.phoneawsauth.updates

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

data class ReleaseInfo(
    val tagName: String,
    val htmlUrl: String,
    val apkUrl: String,
)

class ReleaseChecker {
    suspend fun check(currentVersion: String): ReleaseInfo? = withContext(Dispatchers.IO) {
        try {
            val conn = URL(API_URL).openConnection() as HttpURLConnection
            conn.connectTimeout = 10_000
            conn.readTimeout = 10_000
            conn.setRequestProperty("Accept", "application/vnd.github+json")
            conn.setRequestProperty("User-Agent", "phone-aws-auth")

            if (conn.responseCode != 200) return@withContext null

            val json = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
            val tagName = json.getString("tag_name")
            if (!isNewerVersion(currentVersion, tagName)) return@withContext null

            val assets = json.optJSONArray("assets") ?: return@withContext null
            var apkUrl = ""
            for (i in 0 until assets.length()) {
                val asset = assets.getJSONObject(i)
                val name = asset.getString("name")
                if (name.endsWith("-debug.apk")) {
                    apkUrl = asset.getString("browser_download_url")
                    break
                }
            }
            if (apkUrl.isBlank()) return@withContext null

            ReleaseInfo(
                tagName = tagName,
                htmlUrl = json.getString("html_url"),
                apkUrl = apkUrl,
            )
        } catch (_: Exception) {
            null
        }
    }

    private companion object {
        const val API_URL = "https://api.github.com/repos/alexeygrigorev/phone-aws-gate/releases/latest"
    }
}

internal fun isNewerVersion(current: String, remote: String): Boolean {
    val currentNums = versionParts(current)
    val remoteNums = versionParts(remote)

    for (i in 0 until maxOf(currentNums.size, remoteNums.size)) {
        val c = currentNums.getOrElse(i) { 0 }
        val r = remoteNums.getOrElse(i) { 0 }
        if (r > c) return true
        if (r < c) return false
    }
    return false
}

private fun versionParts(version: String): List<Int> {
    return version
        .substringBefore("-")
        .removePrefix("v")
        .split(".")
        .mapNotNull { it.toIntOrNull() }
}
