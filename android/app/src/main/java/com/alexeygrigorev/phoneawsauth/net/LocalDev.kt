package com.alexeygrigorev.phoneawsauth.net

/**
 * Hardcoded values for the local dev loop (DDB Local in docker-compose).
 * These match docker/docker-compose.yml. Replace with paired secrets once
 * the pair flow is implemented.
 */
object LocalDev {
    // 10.0.2.2 is the Android emulator's loopback alias for the host machine.
    const val DDB_ENDPOINT = "http://10.0.2.2:18000"

    // sha256("local-bearer-token-not-secret") — matches the value baked into
    // the vendor container's SERVER_TOKEN_HASH env var.
    const val ROW_KEY = "4b3e9fadaac93f5d99f34f024bdfdcd8921b80d56b554d930d93f32471b534b6"

    // DDB Local accepts anything; the SDK still requires non-empty values.
    const val FAKE_ACCESS_KEY = "local"
    const val FAKE_SECRET_KEY = "local"

    fun client(): GateClient = GateClient(
        rowKey = ROW_KEY,
        accessKeyId = FAKE_ACCESS_KEY,
        secretAccessKey = FAKE_SECRET_KEY,
        ddbEndpoint = DDB_ENDPOINT,
    )
}
