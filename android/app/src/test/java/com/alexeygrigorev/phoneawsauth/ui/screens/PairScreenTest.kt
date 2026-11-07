package com.alexeygrigorev.phoneawsauth.ui.screens

import com.alexeygrigorev.phoneawsauth.settings.PairedConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class PairScreenTest {
    @Test
    fun parseAcceptsFullPairingPayload() {
        val config = parse(
            """
            {
              "region": "eu-west-1",
              "name": "hetzner",
              "table": "phone-aws-gate",
              "rowKey": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
              "accessKeyId": "AKIATEST",
              "secretAccessKey": "secret"
            }
            """.trimIndent(),
        )

        assertNull(config.gcp)
        assertEquals("hetzner", config.name)
        assertEquals("eu-west-1", config.region)
        assertEquals("phone-aws-gate", config.table)
        assertEquals("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", config.rowKey)
        assertEquals("AKIATEST", config.accessKeyId)
        assertEquals("secret", config.secretAccessKey)
    }

    @Test
    fun parseUsesDefaultsForOptionalRegionAndTable() {
        val config = parse(
            """
            {
              "rowKey": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
              "accessKeyId": "AKIATEST",
              "secretAccessKey": "secret"
            }
            """.trimIndent(),
        )

        assertEquals(PairedConfig.DEFAULT_REGION, config.region)
        assertEquals(PairedConfig.DEFAULT_TABLE, config.table)
        assertEquals("Host", config.name)
    }

    @Test
    fun parseRejectsInvalidJson() {
        val error = assertThrows(IllegalArgumentException::class.java) {
            parse("not json")
        }

        assertEquals(true, error.message?.startsWith("Not valid JSON"))
    }

    @Test
    fun parseRejectsMissingSecret() {
        val error = assertThrows(IllegalArgumentException::class.java) {
            parse(
                """
                {
                  "rowKey": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                  "accessKeyId": "AKIATEST"
                }
                """.trimIndent(),
            )
        }

        assertEquals("Missing field: secretAccessKey", error.message)
    }

    @Test
    fun parseRejectsBadRowKey() {
        val error = assertThrows(IllegalArgumentException::class.java) {
            parse(
                """
                {
                  "rowKey": "not-a-sha",
                  "accessKeyId": "AKIATEST",
                  "secretAccessKey": "secret"
                }
                """.trimIndent(),
            )
        }

        assertEquals("rowKey must be 64 hex chars (sha256)", error.message)
    }

    @Test
    fun parseAcceptsGoogleCloudPairing() {
        val config = parse(cloudPayload("https://gate.example/", "a".repeat(64)))
        assertEquals("https://gate.example", config.gcp?.url)
        assertEquals("a".repeat(64), config.gcp?.controllerToken)
    }

    @Test
    fun parseRejectsPartialOrInsecureGoogleCloudPairing() {
        assertThrows(IllegalArgumentException::class.java) {
            parse(cloudPayload("https://gate.example", ""))
        }
        assertThrows(IllegalArgumentException::class.java) {
            parse(cloudPayload("http://gate.example", "a".repeat(64)))
        }
        assertThrows(IllegalArgumentException::class.java) {
            parse(cloudPayload("https://attacker.example@gate.example", "a".repeat(64)))
        }
    }

    private fun cloudPayload(url: String, token: String): String = """
        {
          "rowKey": "${"0".repeat(64)}",
          "accessKeyId": "AKIATEST",
          "secretAccessKey": "secret",
          "gcpUrl": "$url",
          "gcpControllerToken": "$token"
        }
    """.trimIndent()
}
