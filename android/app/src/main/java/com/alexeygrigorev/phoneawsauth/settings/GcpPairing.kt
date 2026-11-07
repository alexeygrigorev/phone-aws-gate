package com.alexeygrigorev.phoneawsauth.settings

import java.net.URI
import org.json.JSONObject

data class GcpPairing(val url: String, val controllerToken: String) {
    init {
        val endpoint = runCatching { URI(url) }.getOrNull()
        require(
            endpoint != null && endpoint.scheme == "https" && endpoint.host != null &&
                endpoint.userInfo == null && endpoint.query == null && endpoint.fragment == null &&
                (endpoint.path.isEmpty() || endpoint.path == "/"),
        ) { "Google Cloud pairing needs an HTTPS service URL" }
        require(controllerToken.matches(Regex("[0-9a-f]{64}"))) {
            "Google Cloud pairing needs a valid controller token"
        }
    }

    override fun toString(): String = "GcpPairing(url=$url)"

    companion object {
        fun fromJson(obj: JSONObject): GcpPairing? {
            val url = obj.optString("gcpUrl")
            val token = obj.optString("gcpControllerToken")
            if (url.isEmpty() && token.isEmpty()) return null
            return GcpPairing(url.trimEnd('/'), token)
        }
    }
}
