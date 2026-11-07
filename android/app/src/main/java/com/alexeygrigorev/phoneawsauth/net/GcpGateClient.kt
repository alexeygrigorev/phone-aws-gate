package com.alexeygrigorev.phoneawsauth.net

import com.alexeygrigorev.phoneawsauth.settings.GcpPairing
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URI
import org.json.JSONException
import org.json.JSONObject

internal class GcpGateClient(rowKey: String, private val config: GcpPairing) {
    init {
        require(rowKey.matches(Regex("[0-9a-f]{64}"))) { "Invalid host key" }
    }

    private val url = URI("${config.url.trimEnd('/')}/hosts/$rowKey/grant").toURL()

    sealed interface Result {
        data class Grant(val expiresAt: Long) : Result
        data class Error(val message: String) : Result
    }

    fun status(): Result = request("GET")

    fun start(durationMinutes: Int): Result = request(
        "PUT",
        JSONObject().put("duration_minutes", durationMinutes).toString(),
    )

    fun stop(): Result = request("DELETE")

    private fun request(method: String, body: String? = null): Result {
        val connection = try {
            url.openConnection() as HttpURLConnection
        } catch (_: IOException) {
            return Result.Error("Connection failed")
        }
        try {
            connection.requestMethod = method
            connection.instanceFollowRedirects = false
            connection.useCaches = false
            connection.connectTimeout = 5_000
            connection.readTimeout = 7_000
            connection.setRequestProperty("Authorization", "Bearer ${config.controllerToken}")
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val status = connection.responseCode
            if (status != 200) return Result.Error("HTTP $status")
            val response = connection.inputStream.bufferedReader(Charsets.UTF_8).use { reader ->
                val body = StringBuilder()
                val buffer = CharArray(256)
                while (true) {
                    val count = reader.read(buffer)
                    if (count == -1) break
                    if (body.length + count > 1024) return Result.Error("Invalid grant status")
                    body.append(buffer, 0, count)
                }
                body.toString()
            }
            val expiresAt = JSONObject(response).getLong("expires_at")
            return if (expiresAt >= 0) Result.Grant(expiresAt) else Result.Error("Invalid grant status")
        } catch (_: IOException) {
            return Result.Error("Connection failed")
        } catch (_: JSONException) {
            return Result.Error("Invalid grant status")
        } finally {
            connection.disconnect()
        }
    }
}

