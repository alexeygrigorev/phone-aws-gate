package com.alexeygrigorev.phoneawsauth.net

import aws.sdk.kotlin.services.dynamodb.model.AttributeValue
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class GateClientTest {
    @Test
    fun missingItemMapsToClosed() {
        assertEquals(GateClient.Result.Closed, resultFromItem(null, now = 100))
    }

    @Test
    fun inactiveItemMapsToClosed() {
        val item = openItem(active = false, expiresAt = 200)

        assertEquals(GateClient.Result.Closed, resultFromItem(item, now = 100))
    }

    @Test
    fun expiredItemMapsToClosed() {
        val item = openItem(expiresAt = 100)

        assertEquals(GateClient.Result.Closed, resultFromItem(item, now = 100))
        assertEquals(GateClient.Result.Closed, resultFromItem(item, now = 101))
    }

    @Test
    fun unexpiredActiveItemMapsToOpen() {
        val result = resultFromItem(openItem(expiresAt = 200), now = 100)

        assertTrue(result is GateClient.Result.Open)
        val open = result as GateClient.Result.Open
        assertEquals("sandbox", open.mode)
        assertEquals(50, open.startedAt)
        assertEquals(200, open.expiresAt)
        assertEquals("hello", open.note)
    }

    @Test
    fun malformedNumericFieldsMapToClosedOrZero() {
        val item = openItem(expiresAt = 200) + mapOf(
            "started_at" to AttributeValue.N("not-a-number"),
        )

        val result = resultFromItem(item, now = 100)

        assertTrue(result is GateClient.Result.Open)
        assertEquals(0, (result as GateClient.Result.Open).startedAt)
    }

    private fun openItem(
        active: Boolean = true,
        expiresAt: Long,
    ): Map<String, AttributeValue> = mapOf(
        "active" to AttributeValue.Bool(active),
        "mode" to AttributeValue.S("sandbox"),
        "started_at" to AttributeValue.N("50"),
        "expires_at" to AttributeValue.N(expiresAt.toString()),
        "note" to AttributeValue.S("hello"),
    )
}
