package com.alexeygrigorev.phoneawsauth.ui.screens

import com.alexeygrigorev.phoneawsauth.settings.PairedConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class PairScreenTest {
    @Test
    fun parseAcceptsFullPairingPayload() {
        val config = parse(
            """
            {
              "region": "eu-west-1",
              "table": "phone-aws-gate",
              "rowKey": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
              "accessKeyId": "AKIATEST",
              "secretAccessKey": "secret"
            }
            """.trimIndent(),
        )

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
}
